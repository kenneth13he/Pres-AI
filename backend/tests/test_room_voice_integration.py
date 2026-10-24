"""The presentation room owns the microphone floor and speaks through the real adapter.

Vendor HTTP is simulated; WebSocket events, binary audio, playback acknowledgements and
the session engine are real. No test contacts Boson or records microphone audio.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from fastapi.testclient import TestClient

from backend import main
from backend.services.audience import MockOrchestrator
from backend.services.voice_higgs import HiggsVoice, SpendCounter
from backend.session_records import SessionRecords
from backend.tests.conftest import make_config, make_session, s, seg


async def test_held_floor_and_pending_final_block_all_audience_interruptions():
    session = make_session()
    await session.start(0)
    await session.presenter_transcript(s(32), seg(32, "We have 2,000 paying users."))
    session.presenter_turn_started(s(34), "held")
    await session.tick(s(36))
    await session.force_curveball("heckler", s(37))
    assert session.phase == "presenting" and not session.questions
    session.presenter_turn_ended(s(38), "held")
    await session.tick(s(40))
    assert session.presenter_floor_blocked(s(40)) and not session.questions

    await session.presenter_transcript(s(41), seg(33, "A late earlier fragment."), "old")
    assert session.presenter_floor_blocked(s(41))
    await session.presenter_transcript(
        s(42), seg(34, "We have 3,000 paying users across our pilot schools."), "held")
    assert not session.presenter_floor_blocked(s(42))
    await session.tick(s(44))
    assert session.phase == "answering"
    assert "3,000" in session.questions[0]["cited_excerpt"]


def test_abandoned_capture_and_missing_final_have_bounded_floor_timeouts():
    session = make_session()
    session.phase = "presenting"
    session.presenter_turn_started(s(1), "first")
    assert session.presenter_floor_blocked(s(65))
    assert not session.presenter_floor_blocked(s(66))
    session.presenter_turn_started(s(70), "second")
    session.presenter_turn_ended(s(72), "second")
    assert session.presenter_floor_blocked(s(101))
    assert not session.presenter_floor_blocked(s(102))
    session.presenter_turn_started(s(110), "new")
    session.presenter_turn_cancelled("old")
    assert session.presenter_floor_blocked(s(111))
    session.presenter_turn_cancelled("new")
    assert not session.presenter_floor_blocked(s(111))


class WaitingDecision(MockOrchestrator):
    def __init__(self):
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def decide(self, ctx):
        self.entered.set()
        await self.release.wait()
        return await super().decide(ctx)


async def test_capture_start_invalidates_a_decision_already_in_flight():
    session = make_session()
    await session.start(0)
    await session.presenter_transcript(s(32), seg(32, "We have 2,000 paying users."))
    model = WaitingDecision()
    session.orchestrator = model
    task = asyncio.create_task(session.tick(s(36)))
    await asyncio.wait_for(model.entered.wait(), 1)
    session.presenter_turn_started(s(37), "new")
    model.release.set()
    await task
    assert session.phase == "presenting" and not session.questions


async def test_qna_waits_for_a_held_turn_and_its_final_transcript():
    session = make_session()
    await session.start(0)
    await session.presenter_transcript(s(32), seg(32, "We have 2,000 paying users."))
    await session.control("end", s(35))
    session.presenter_turn_started(s(36), "closing")
    await session.tick(s(37))
    assert session.phase == "qna" and not session.questions
    session.presenter_turn_ended(s(38), "closing")
    await session.tick(s(39))
    assert not session.questions
    await session.presenter_transcript(
        s(40), seg(36, "Our next pilot will serve 3,000 paying users."), "closing")
    await session.tick(s(41))
    assert session.phase == "answering" and len(session.questions) == 1


@pytest.mark.parametrize("action", ["pause", "skip", "end"])
async def test_control_received_during_decision_prevents_new_speech(action):
    session = make_session(qna_questions=0)
    await session.start(0)
    await session.presenter_transcript(s(32), seg(32, "We have 2,000 paying users."))
    model = WaitingDecision()
    session.orchestrator = model
    task = asyncio.create_task(session.tick(s(36)))
    await asyncio.wait_for(model.entered.wait(), 1)
    session.prepare_control(action)
    model.release.set()
    await task
    await session.control(action, s(38))
    assert not session.questions
    assert not any(event.type == "ai_speech_started" for event in session.events)
    assert session.phase == {"pause": "paused", "skip": "presenting", "end": "report"}[action]


@pytest.mark.parametrize("action", ["pause", "skip", "end"])
async def test_control_received_during_follow_up_prevents_a_late_reply(action):
    session = make_session(qna_questions=0)
    await session.start(0)
    await session.presenter_transcript(s(32), seg(32, "We have 2,000 paying users."))
    await session.tick(s(36))
    initial_speech = len([event for event in session.events if event.type == "ai_speech_started"])
    entered, release = asyncio.Event(), asyncio.Event()

    class WaitingFollowUp(MockOrchestrator):
        async def follow_up(self, question, answer, persona, used):
            entered.set()
            await release.wait()
            return await super().follow_up(question, answer, persona, used)

    session.orchestrator = WaitingFollowUp()
    task = asyncio.create_task(session.presenter_transcript(s(42), seg(40, "Through schools.")))
    await asyncio.wait_for(entered.wait(), 1)
    session.prepare_control(action)
    release.set()
    await task
    await session.control(action, s(44))
    assert len([event for event in session.events
                if event.type == "ai_speech_started"]) == initial_speech


@pytest.fixture
def real_room(monkeypatch, tmp_path):
    clock = {"ms": 0}
    monkeypatch.setattr(main, "wall_ms", lambda: clock["ms"])
    monkeypatch.setattr(main, "TICK_S", 3600)
    monkeypatch.setattr(main, "ROOMS", {})
    monkeypatch.setattr(main, "SESSION_RECORDS", SessionRecords(tmp_path / "sessions"))
    monkeypatch.setattr(main, "make_orchestrator", MockOrchestrator)
    monkeypatch.setattr(SpendCounter, "tts_chars", 0)
    monkeypatch.setattr(SpendCounter, "realtime_ms", 0)
    monkeypatch.setenv("SPEND_SOFT_CAP_USD", "60")
    monkeypatch.setenv("DEBUG_CURVEBALL_ENDPOINT", "true")
    requests = []

    def make_voice():
        def respond(request):
            requests.append(request)
            return httpx.Response(200, content=b"\x00\x00\x01\x00",
                                  headers={"content-type": "audio/pcm"})
        return HiggsVoice(httpx.AsyncClient(base_url="https://voice.invalid/v1",
                                            transport=httpx.MockTransport(respond)))

    monkeypatch.setattr(main, "make_voice", make_voice)
    with TestClient(main.app) as client:
        config = make_config(qna_questions=0).model_dump(exclude={"input_mode"})
        response = client.post("/api/sessions", json={"config": config})
        assert response.status_code == 200, response.text
        session_id = response.json()["session_id"]
        assert response.json()["config"]["input_mode"] == "push_to_talk"
        yield client, main.ROOMS[session_id], clock, requests


def wait_for_state(client, predicate):
    async def wait():
        async with asyncio.timeout(2):
            while not predicate():
                await asyncio.sleep(0)
    assert client.portal is not None
    client.portal.call(wait)


def receive_event(socket, kind, predicate=lambda _: True):
    for _ in range(100):
        event = socket.receive_json()
        if event["type"] == kind and predicate(event):
            return event
    raise AssertionError(f"No {kind} event received")


def speech_turn(socket):
    first = socket.receive_json()
    assert first["type"] == "speech_started"
    assert socket.receive_bytes() == b"\x00\x00\x01\x00"
    complete = socket.receive_json()
    assert complete["type"] == "speech_complete"
    assert complete["play_id"] == first["play_id"]
    return complete["play_id"]


def submit_turn(socket, turn_id, text, start_ms, end_ms):
    socket.send_json({"type": "presenter_turn_started", "turn_id": turn_id})
    socket.send_json({"type": "presenter_turn_ended", "turn_id": turn_id})
    socket.send_json({"type": "transcript_segment", "turn_id": turn_id,
                      "segment": {"start_ms": start_ms, "end_ms": end_ms, "text": text}})


def test_actual_room_binary_question_answer_follow_up_and_end(real_room):
    client, room, clock, requests = real_room
    session_id = room.session.session_id
    with client.websocket_connect(f"/ws/voice/{session_id}") as audio:
        assert audio.receive_json()["type"] == "ready"
        with client.websocket_connect(f"/ws/sessions/{session_id}") as events:
            events.send_json({"type": "presentation_started"})
            receive_event(events, "audio_status")
            clock["ms"] = 35_000
            submit_turn(events, "claim", "We have 2,000 paying users.", 32_000, 34_000)
            receive_event(events, "transcript_segment")
            clock["ms"] = 36_000
            assert client.portal is not None
            tick = client.portal.start_task_soon(room.run, room.session.tick(36_000))
            first_id = speech_turn(audio)
            question = receive_event(events, "question_queued")
            assert "2,000 paying users" in question["payload"]["cited_excerpt"]
            assert not tick.done() and room.session.phase == "interruption"
            audio.send_json({"type": "played", "play_id": first_id})
            tick.result(timeout=2)
            receive_event(events, "phase_changed", lambda e: e["payload"]["to"] == "answering")

            clock["ms"] = 43_000
            submit_turn(events, "answer", "Through schools.", 40_000, 42_000)
            follow_id = speech_turn(audio)
            follow = receive_event(events, "question_queued")
            assert follow["payload"]["follow_up_of"] == question["payload"]["question_id"]
            audio.send_json({"type": "played", "play_id": follow_id})
            wait_for_state(client, lambda: room.session.pending_question is not None
                           and room.session.pending_question["follow_up_of"] is not None)

            clock["ms"] = 51_000
            submit_turn(events, "detail", "We signed three pilot schools with two thousand "
                        "paid weekly users in total.", 48_000, 50_000)
            ack_id = speech_turn(audio)
            audio.send_json({"type": "played", "play_id": ack_id})
            receive_event(events, "phase_changed", lambda e: e["payload"]["to"] == "presenting")
            assert len(requests) == 3 and room.session.pending_question is None
            assert not any(event.type == "error" for event in room.session.events)
            assert client.post(f"/api/sessions/{session_id}/control",
                               json={"action": "pause"}).json()["phase"] == "paused"
            assert client.post(f"/api/sessions/{session_id}/control",
                               json={"action": "end"}).json()["phase"] == "report"
            report = client.get(f"/api/sessions/{session_id}/report").json()
            assert report["metrics"]["unanswered_questions"] == 0
            assert any("2,000" in moment["summary"] for moment in report["key_moments"])
            assert not room.session.voice.speaking


def test_rest_skip_cancels_unacknowledged_room_speech(real_room):
    client, room, clock, _ = real_room
    session_id = room.session.session_id
    with client.websocket_connect(f"/ws/voice/{session_id}") as audio:
        audio.receive_json()
        with client.websocket_connect(f"/ws/sessions/{session_id}") as events:
            events.send_json({"type": "presentation_started"})
            receive_event(events, "audio_status")
            clock["ms"] = 70_000
            with ThreadPoolExecutor(max_workers=1) as worker:
                forcing = worker.submit(client.post, f"/api/sessions/{session_id}/curveball",
                                        json={"kind": "heckler"})
                wait_for_state(client, lambda: forcing.done() or room.session.voice.speaking)
                if forcing.done():
                    # A disabled debug route must fail before any blocking audio read.
                    early = forcing.result(timeout=2)
                    assert early.status_code == 200, early.text
                    pytest.fail("Curveball request finished before unacknowledged speech.")
                speech_turn(audio)
                result = client.post(f"/api/sessions/{session_id}/control",
                                     json={"action": "skip"})
                assert result.status_code == 200 and result.json()["phase"] == "presenting"
                assert forcing.result(timeout=2).status_code == 200
            assert room.session.pending_question is None
            assert room.session.curveballs.records[0].resolution == "skipped"
            assert not room.session.voice.speaking


def test_same_socket_can_claim_floor_while_its_previous_answer_awaits_follow_up(real_room):
    client, room, clock, requests = real_room
    session_id = room.session.session_id
    entered, release = asyncio.Event(), asyncio.Event()

    class SlowFollowUp(MockOrchestrator):
        async def follow_up(self, question, answer, persona, used):
            entered.set()
            await release.wait()
            return await super().follow_up(question, answer, persona, used)

    room.session.orchestrator = SlowFollowUp()
    with client.websocket_connect(f"/ws/voice/{session_id}") as audio:
        audio.receive_json()
        with client.websocket_connect(f"/ws/sessions/{session_id}") as events:
            events.send_json({"type": "presentation_started"})
            receive_event(events, "audio_status")
            clock["ms"] = 35_000
            submit_turn(events, "claim", "We have 2,000 paying users.", 32_000, 34_000)
            receive_event(events, "transcript_segment")
            clock["ms"] = 36_000
            assert client.portal is not None
            tick = client.portal.start_task_soon(room.run, room.session.tick(36_000))
            audio.send_json({"type": "played", "play_id": speech_turn(audio)})
            tick.result(timeout=2)

            clock["ms"] = 43_000
            submit_turn(events, "answer", "Through schools.", 40_000, 42_000)
            wait_for_state(client, entered.is_set)
            clock["ms"] = 45_000
            events.send_json({"type": "presenter_turn_started", "turn_id": "continuation"})
            # This is the same socket that submitted the answer. Its reader must remain
            # responsive while the ordered worker awaits that answer's audience model.
            wait_for_state(client, lambda: room.session.presenter_turn_id == "continuation")
            client.portal.call(release.set)
            wait_for_state(client, lambda: room.active_task is None)
            assert len(requests) == 1  # only the original question; no interruption while held
            assert room.session.presenter_floor_blocked(46_000)

            clock["ms"] = 51_000
            events.send_json({"type": "presenter_turn_ended", "turn_id": "continuation"})
            events.send_json({"type": "transcript_segment", "turn_id": "continuation",
                              "segment": {"start_ms": 45_000, "end_ms": 50_000,
                                          "text": "We signed three pilot schools with two "
                                          "thousand paid weekly users in total."}})
            audio.send_json({"type": "played", "play_id": speech_turn(audio)})
            wait_for_state(client, lambda: room.session.phase == "presenting")
            assert len(requests) == 2 and room.session.pending_question is None
        wait_for_state(client, lambda: not room.workers)


def test_only_the_socket_owning_a_capture_releases_its_floor_on_disconnect(real_room):
    client, room, _, _ = real_room
    path = f"/ws/sessions/{room.session.session_id}"
    with client.websocket_connect(path) as presenter:
        presenter.send_json({"type": "presentation_started"})
        receive_event(presenter, "audio_status")
        presenter.send_json({"type": "presenter_turn_started", "turn_id": "owned"})
        wait_for_state(client, lambda: room.session.presenter_turn_id == "owned")
        with client.websocket_connect(path):
            pass
        assert room.session.presenter_turn_id == "owned"
    assert room.session.presenter_turn_id is None


def test_snapshot_countdown_freezes_while_paused_and_live_mode_remains_supported(real_room):
    client, room, clock, _ = real_room
    room.t0 = 0
    room.session.start_ms = 0
    room.session.phase = "presenting"
    room.session.time_crunch_deadline_ms = 60_000
    clock["ms"] = 30_000
    path = f"/api/sessions/{room.session.session_id}"
    assert client.get(path).json()["timer_remaining_ms"] == 30_000
    client.post(path + "/control", json={"action": "pause"})
    clock["ms"] = 50_000
    assert client.get(path).json()["timer_remaining_ms"] == 30_000
    assert client.get(path).json()["elapsed_ms"] == 30_000
    client.post(path + "/control", json={"action": "resume"})
    assert client.get(path).json()["timer_remaining_ms"] == 30_000
    assert client.get(path).json()["elapsed_ms"] == 30_000
    room.session.time_crunch_deadline_ms = None
    assert client.get(path).json()["timer_remaining_ms"] is None
    config = make_config(input_mode="live").model_dump()
    assert client.post("/api/sessions", json={"config": config}).json()["config"]["input_mode"] \
        == "live"
