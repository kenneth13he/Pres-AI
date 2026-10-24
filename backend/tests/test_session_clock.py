"""Finished durations freeze; the full session clock and pause accounting stay separate."""
from pathlib import Path

from backend import main
from backend.services.voice_mock import MockVoice
from backend.session_records import SessionRecords
from backend.tests.conftest import make_session


async def test_finished_elapsed_freezes_at_the_session_ended_timestamp():
    session = make_session()
    await session.start(0)
    await session.finish(333_000)
    ended = next(event for event in session.events if event.type == "session_ended")
    assert ended.timestamp_ms == 333_000
    assert session.elapsed_ms(403_000) == ended.timestamp_ms
    await session.finish(503_000)
    assert session.elapsed_ms(603_000) == 333_000
    assert len([event for event in session.events if event.type == "session_ended"]) == 1


async def test_finishing_paused_qna_excludes_both_closed_and_current_pause():
    session = make_session()
    await session.start(0)
    await session.control("pause", 10_000)
    await session.control("resume", 30_000)
    await session.control("end", 40_000)
    assert session.phase == "qna"
    await session.control("pause", 45_000)
    await session.control("end", 95_000)
    assert session.phase == "report"
    assert session.elapsed_ms(200_000) == 25_000
    assert session.paused_at_ms is None
    assert session.pauses == [(10_000, 30_000), (45_000, 95_000)]
    assert len([event for event in session.events if event.type == "resumed"]) == 1


async def test_early_finish_from_paused_presentation_does_not_count_the_pause():
    session = make_session(qna_questions=0)
    await session.start(0)
    await session.control("pause", 10_000)
    await session.control("end", 100_000)
    assert session.phase == "report"
    assert session.elapsed_ms(200_000) == 10_000


async def test_snapshot_and_saved_report_keep_duration_when_the_room_clock_advances(
    monkeypatch, tmp_path: Path,
):
    clock = {"now": 10_000}
    monkeypatch.setattr(main, "wall_ms", lambda: clock["now"])
    monkeypatch.setattr(main, "SESSION_RECORDS", SessionRecords(tmp_path))
    session = make_session()
    room = main.Room(session)
    room.t0 = 10_000
    monkeypatch.setattr(main, "ROOMS", {session.session_id: room})
    await room.run(session.start(0))
    clock["now"] = 343_000
    await room.run(session.finish(333_000))
    first = main.get_session(session.session_id)
    clock["now"] = 413_000
    later = main.get_session(session.session_id)
    assert first["elapsed_ms"] == later["elapsed_ms"] == 333_000
    assert first["session_clock_ms"] == 333_000
    assert later["session_clock_ms"] == 403_000
    assert later["timer_remaining_ms"] is None
    main.ROOMS.pop(session.session_id)
    assert main.get_session(session.session_id)["elapsed_ms"] == 333_000
    assert main.get_report(session.session_id)["session_id"] == session.session_id


async def test_slide_navigation_remains_available_before_start_and_while_paused():
    session = make_session()
    await session.slide_changed(0, 2)
    assert session.phase == "setup" and session.slide_number == 2
    await session.start(0)
    await session.control("pause", 10_000)
    await session.slide_changed(15_000, 3)
    assert session.phase == "paused" and session.slide_number == 3
    assert [event.payload["slide_number"] for event in session.events
            if event.type == "slide_changed"] == [2, 3]


async def test_finished_session_ignores_late_slide_input_without_events_or_voice_context(
    monkeypatch, tmp_path: Path,
):
    monkeypatch.setattr(main, "SESSION_RECORDS", SessionRecords(tmp_path))
    session = make_session()
    room = main.Room(session)
    await session.start(0)
    await session.slide_changed(5_000, 2)
    await session.finish(10_000)
    before = main.session_snapshot(room)
    assert isinstance(session.voice, MockVoice)
    voice_calls = list(session.voice.calls)
    changed_at = session.slide_changed_at_ms
    # This is the actual path for an old socket's queued slide message.
    await main._handle_client_message(room, {"type": "slide_changed", "slide_number": 99})
    assert main.session_snapshot(room) == before
    assert session.slide_number == 2 and session.slide_changed_at_ms == changed_at
    assert session.voice.calls == voice_calls
