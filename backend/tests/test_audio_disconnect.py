"""An absent playback bridge freezes the room; all HTTP speech is simulated."""
from __future__ import annotations

import asyncio

import httpx
import pytest

from backend import main
from backend.services.audience import MockOrchestrator
from backend.services.voice_higgs import HiggsVoice
from backend.session_records import SessionRecords
from backend.tests.conftest import make_session, seg
from backend.tests.test_room_voice_integration import (
    real_room as real_room,
)
from backend.tests.test_room_voice_integration import (
    receive_event,
    speech_turn,
    submit_turn,
    wait_for_state,
)


def test_audio_socket_loss_pauses_held_capture_and_requires_explicit_resume(real_room):
    client, room, clock, requests = real_room
    session_id = room.session.session_id
    with client.websocket_connect(f"/ws/sessions/{session_id}") as events:
        with client.websocket_connect(f"/ws/voice/{session_id}") as audio:
            audio.receive_json()
            events.send_json({"type": "presentation_started"})
            receive_event(events, "audio_status")
            clock["ms"] = 35_000
            events.send_json({"type": "presenter_turn_started", "turn_id": "held"})
            wait_for_state(client, lambda: room.session.presenter_turn_id == "held")
        wait_for_state(client, lambda: room.session.phase == "paused")
        assert room.session.presenter_turn_id is None
        assert room.session.paused_at_ms == 35_000
        clock["ms"] = 95_000
        assert client.portal is not None
        client.portal.call(room.run, room._tick())
        assert client.get(f"/api/sessions/{session_id}").json()["elapsed_ms"] == 35_000
        assert requests == [] and not room.session.questions

        with client.websocket_connect(f"/ws/voice/{session_id}") as replacement:
            assert replacement.receive_json()["type"] == "ready"
            assert room.session.phase == "paused"  # attachment alone never resumes
            response = client.post(f"/api/sessions/{session_id}/control",
                                   json={"action": "resume"})
            assert response.json()["phase"] == "presenting"
            clock["ms"] = 96_000
            submit_turn(events, "claim", "We have 2,000 paying users.", 95_000, 95_500)
            receive_event(events, "transcript_segment")
            clock["ms"] = 97_000
            tick = client.portal.start_task_soon(room.run, room._tick())
            play_id = speech_turn(replacement)
            replacement.send_json({"type": "played", "play_id": play_id})
            tick.result(timeout=2)
            assert len(requests) == 1
            assert not any(event.type == "error" for event in room.session.events)


def test_detached_end_pauses_qna_but_finish_early_still_works(real_room):
    client, room, clock, requests = real_room
    session_id = room.session.session_id
    room.session.config.qna_questions = 1
    with client.websocket_connect(f"/ws/sessions/{session_id}") as events:
        with client.websocket_connect(f"/ws/voice/{session_id}") as audio:
            audio.receive_json()
            events.send_json({"type": "presentation_started"})
            receive_event(events, "audio_status")
        wait_for_state(client, lambda: room.session.phase == "paused")
        clock["ms"] = 10_000
        assert client.post(f"/api/sessions/{session_id}/control",
                           json={"action": "end"}).json()["phase"] == "qna"
        assert client.portal is not None
        client.portal.call(room.run, room._tick())
        assert room.session.phase == "paused" and room.session.paused_phase == "qna"
        assert requests == []
        assert client.post(f"/api/sessions/{session_id}/control",
                           json={"action": "end"}).json()["phase"] == "report"
        before = list(room.session.events)
        client.portal.call(room.run, room._tick())
        assert room.session.events == before
        assert not any(event.type == "error" for event in before)


def test_audio_socket_loss_cancels_unacknowledged_speech_without_new_errors(real_room):
    client, room, clock, requests = real_room
    session_id = room.session.session_id
    with client.websocket_connect(f"/ws/sessions/{session_id}") as events:
        with client.websocket_connect(f"/ws/voice/{session_id}") as audio:
            audio.receive_json()
            events.send_json({"type": "presentation_started"})
            receive_event(events, "audio_status")
            clock["ms"] = 35_000
            submit_turn(events, "claim", "We have 2,000 paying users.", 32_000, 34_000)
            receive_event(events, "transcript_segment")
            clock["ms"] = 36_000
            assert client.portal is not None
            tick = client.portal.start_task_soon(room.run, room._tick())
            speech_turn(audio)  # disconnect without a playback acknowledgment
            assert room.session.voice.speaking
        tick.result(timeout=2)
        wait_for_state(client, lambda: room.session.phase == "paused")
        assert not room.session.voice.speaking and len(requests) == 1
        assert not any(event.type == "error" for event in room.session.events)
        assert len([event for event in room.session.events
                    if event.type == "ai_speech_ended"]) == 1


def test_report_audio_close_and_completed_qna_are_terminal_without_errors(real_room):
    client, room, _, requests = real_room
    session_id = room.session.session_id
    with client.websocket_connect(f"/ws/sessions/{session_id}") as events:
        with client.websocket_connect(f"/ws/voice/{session_id}") as audio:
            audio.receive_json()
            events.send_json({"type": "presentation_started"})
            receive_event(events, "audio_status")
            assert client.post(f"/api/sessions/{session_id}/control",
                               json={"action": "end"}).json()["phase"] == "report"
            before = list(room.session.events)
        wait_for_state(client, lambda: not room.session.voice.attached)
        assert room.session.events == before and requests == []
        assert not any(event.type == "error" for event in before)


async def test_loss_invalidates_pending_model_and_freezes_at_receipt_before_lock(
    monkeypatch, tmp_path,
):
    clock = {"now": 0}
    monkeypatch.setattr(main, "wall_ms", lambda: clock["now"])
    monkeypatch.setattr(main, "SESSION_RECORDS", SessionRecords(tmp_path))
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(200, content=b"\x00\x00")

    voice = HiggsVoice(httpx.AsyncClient(base_url="https://voice.invalid/v1",
                                        transport=httpx.MockTransport(respond)))
    session = make_session()
    session.voice = voice
    room = main.Room(session)
    room.t0 = 0

    async def sink(_):
        pass

    owner = voice.attach(sink, room.now_ms)
    await room.run(session.start(0))
    await room.run(session.presenter_transcript(32_000, seg(30, "We have 2,000 paying users.")))
    entered, release = asyncio.Event(), asyncio.Event()

    class WaitingDecision(MockOrchestrator):
        async def decide(self, ctx):
            entered.set()
            await release.wait()
            return await super().decide(ctx)

    session.orchestrator = WaitingDecision()
    clock["now"] = 36_000
    decision = asyncio.create_task(room.run(session.tick(clock["now"])))
    await asyncio.wait_for(entered.wait(), 1)
    clock["now"] = 37_000
    loss = asyncio.create_task(room.audio_disconnected(voice, owner))
    await asyncio.sleep(0)
    assert not voice.attached and not loss.done()
    clock["now"] = 45_000
    assert main.session_snapshot(room)["elapsed_ms"] == 37_000
    await room.prepare_control("pause")
    duplicate = asyncio.create_task(room.run(room.apply_control("pause", 45_000)))
    release.set()
    await asyncio.wait_for(asyncio.gather(decision, loss, duplicate), 1)
    assert session.phase == "paused" and session.paused_at_ms == 37_000
    assert not session.questions and requests == []
    assert not any(event.type in ("error", "ai_speech_started") for event in session.events)
    # A duplicated frontend Pause cannot move the original loss-time freeze forward.
    await room.prepare_control("pause")
    await room.run(room.apply_control("pause", 45_000))
    assert session.paused_at_ms == 37_000
    await voice.stop_voice_session()


@pytest.mark.parametrize("new_control", [False, True])
async def test_old_loss_cannot_pause_replacement_or_clear_a_new_control(new_control):
    session = make_session()
    voice = HiggsVoice(httpx.AsyncClient(transport=httpx.MockTransport(
        lambda _: httpx.Response(200, content=b"\x00\x00"))))
    session.voice = voice
    room = main.Room(session)

    async def sink(_):
        pass

    owner = voice.attach(sink, room.now_ms)
    await session.start(0)
    async with room.lock:
        loss = asyncio.create_task(room.audio_disconnected(voice, owner))
        await asyncio.sleep(0)
        replacement = voice.attach(sink, room.now_ms)
        assert replacement != owner
        if new_control:
            await room.prepare_control("end")
    await asyncio.wait_for(loss, 1)
    assert voice.attached and session.phase == "presenting"
    assert session._audience_action_allowed(1) is not new_control
    # A truly delayed old socket finally must not detach the replacement either.
    await room.audio_disconnected(voice, owner)
    assert voice.attached and session.phase == "presenting"
    if new_control:
        await room.run(room.apply_control("end", 1))
        assert session.phase == "qna" and session._audience_action_allowed(1)
    await voice.stop_voice_session()


async def test_audio_loss_after_completed_qna_finishes_instead_of_pausing(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "SESSION_RECORDS", SessionRecords(tmp_path))
    session = make_session(qna_questions=1)
    voice = HiggsVoice(httpx.AsyncClient(transport=httpx.MockTransport(
        lambda _: httpx.Response(200, content=b"\x00\x00"))))
    session.voice = voice
    room = main.Room(session)

    async def sink(_):
        pass

    owner = voice.attach(sink, room.now_ms)
    await session.start(0)
    session.in_qna = True
    session.qna_asked = 1
    session._set_phase("qna", 1)
    await room.audio_disconnected(voice, owner)
    assert session.phase == "report" and session.report is not None
    assert not any(event.type in ("paused", "error") for event in session.events)
