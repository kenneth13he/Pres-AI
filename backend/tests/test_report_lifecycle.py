"""Ending closes voice immediately; only completed feedback is exposed or persisted."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, cast

import httpx
import pytest

from backend import engine, main
from backend.services.audience import MockOrchestrator
from backend.services.voice_mock import MockVoice
from backend.session_records import SessionRecords
from backend.tests.conftest import make_session, seg
from spec.contracts import RecoveryAssessment, Report


class RecordingRecords(SessionRecords):
    def __init__(self, root: Path):
        super().__init__(root)
        self.reports: list[dict[str, Any]] = []

    def save(self, snapshot: dict[str, Any], report: dict[str, Any]) -> None:
        self.reports.append(report)
        super().save(snapshot, report)


class EventSink:
    def __init__(self):
        self.events: list[dict[str, Any]] = []

    async def send_text(self, data: str) -> None:
        self.events.append(json.loads(data))


@pytest.fixture
def room(monkeypatch, tmp_path: Path):
    clock = {"ms": 0}
    monkeypatch.setattr(main, "wall_ms", lambda: clock["ms"])
    store = RecordingRecords(tmp_path)
    monkeypatch.setattr(main, "SESSION_RECORDS", store)
    session = make_session()
    room = main.Room(session)
    room.t0 = 0
    monkeypatch.setattr(main, "ROOMS", {session.session_id: room})
    return room, clock, store


async def test_terminal_events_stop_capture_before_grading_and_only_final_report_is_saved(
    room, monkeypatch,
):
    room, clock, store = room
    session = room.session
    sink = EventSink()
    room.sockets.add(cast(Any, sink))
    entered, release = asyncio.Event(), asyncio.Event()

    async def assess(session, baseline):
        assert session.phase == "report" and session.report is None
        assert session.presenter_turn_id is None
        assert isinstance(session.voice, MockVoice)
        assert session.voice.calls[-1][0] == "stop"
        assert any(event["type"] == "session_ended" for event in sink.events)
        assert store.reports == []
        entered.set()
        await release.wait()
        return baseline.model_copy(update={"overall_score": 81})

    monkeypatch.setattr(engine, "assess_report", assess)
    await room.run(session.start(0))
    session.presenter_turn_started(330_000, "last-turn")
    clock["ms"] = 333_000
    finishing = asyncio.create_task(room.run(session.finish(333_000)))
    await asyncio.wait_for(entered.wait(), 1)
    clock["ms"] = 403_000
    assert main.get_session(session.session_id)["elapsed_ms"] == 333_000
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),
                                 base_url="http://testserver") as client:
        response = await client.get(f"/api/sessions/{session.session_id}/report")
        assert response.status_code == 409
        assert response.json()["detail"] == {
            "code": "report_preparing", "message": "Your session has ended. Preparing feedback.",
        }
    release.set()
    await finishing
    assert session.report is not None and session.report.overall_score == 81
    assert len(store.reports) == 1 and store.reports[0]["overall_score"] == 81
    assert store.load(session.session_id)["snapshot"]["elapsed_ms"] == 333_000
    assert len([e for e in sink.events if e["type"] == "session_ended"]) == 1
    assert next(e for e in sink.events if e["type"] == "session_ended")["timestamp_ms"] == 333_000
    await room.flush()
    assert len(store.reports) == 1


async def test_unfinished_report_keeps_the_existing_nonretryable_conflict(room):
    room, _, _ = room
    with pytest.raises(main.HTTPException) as error:
        main.get_report(room.session.session_id)
    assert error.value.status_code == 409 and error.value.detail == "session not finished"


async def test_duplicate_end_and_finish_cannot_reopen_or_assess_twice(room, monkeypatch):
    room, _, _ = room
    session = room.session
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def assess(session, baseline):
        calls.append(session.session_id)
        entered.set()
        await release.wait()
        return baseline

    monkeypatch.setattr(engine, "assess_report", assess)
    await session.start(0)
    session.in_qna = True
    finishing = asyncio.create_task(room.run(session.finish(30_000)))
    await asyncio.wait_for(entered.wait(), 1)
    await session.control("end", 40_000)
    await session.finish(50_000)
    await session.control("resume", 60_000)
    assert session.phase == "report" and session.report is None
    assert session.elapsed_ms(70_000) == 30_000 and len(calls) == 1
    release.set()
    await finishing
    assert isinstance(session.voice, MockVoice)
    assert len([call for call in session.voice.calls if call[0] == "stop"]) == 1
    assert len([e for e in session.events if e.type == "session_ended"]) == 1


@pytest.mark.parametrize("hook", ["raise", "timeout"])
async def test_notification_failure_is_bounded_and_does_not_prevent_final_feedback(
    room, monkeypatch, hook,
):
    room, _, store = room
    session = room.session
    monkeypatch.setattr(engine, "REPORT_NOTIFICATION_TIMEOUT_S", .01)

    async def notify():
        if hook == "raise":
            raise RuntimeError("PRIVATE_NOTIFICATION_ERROR")
        await asyncio.Future()

    async def assess(session, baseline):
        return baseline.model_copy(update={"overall_score": 81})

    session.on_report_pending = notify
    monkeypatch.setattr(engine, "assess_report", assess)
    await room.run(session.finish(30_000))
    assert session.report is not None and session.report.overall_score == 81
    assert "completion notification was delayed" in " ".join(session.report.metric_caveats)
    assert "PRIVATE_NOTIFICATION_ERROR" not in session.report.model_dump_json()
    assert len(store.reports) == 1


@pytest.mark.parametrize("failure", ["raise", "invalid", "timeout"])
async def test_unexpected_report_failure_keeps_measured_report_and_safe_caveat(
    room, monkeypatch, failure,
):
    room, _, store = room
    session = room.session
    monkeypatch.setattr(engine, "REPORT_PREPARATION_TIMEOUT_S", .01)

    async def assess(session, baseline):
        if failure == "raise":
            raise RuntimeError("PRIVATE_GRADER_ERROR")
        if failure == "timeout":
            await asyncio.Future()
        return None

    monkeypatch.setattr(engine, "assess_report", assess)
    await session.start(0)
    await session.presenter_transcript(5_000, seg(2, "We have two thousand paying customers."))
    await room.run(session.finish(30_000))
    assert session.report is not None and session.report.overall_score is None
    assert session.report.metrics["words_per_minute"] is not None
    assert "Optional feedback could not finish" in " ".join(session.report.metric_caveats)
    assert "PRIVATE_GRADER_ERROR" not in session.report.model_dump_json()
    assert len(store.reports) == 1


async def test_one_post_stop_budget_also_bounds_leftover_recovery_grading(room, monkeypatch):
    room, _, store = room
    session = room.session
    monkeypatch.setattr(engine, "REPORT_PREPARATION_TIMEOUT_S", .01)
    entered = asyncio.Event()

    class SlowRecovery(MockOrchestrator):
        async def assess_recovery(self, kind, line, after, resume_after_ms) -> RecoveryAssessment:
            assert session.phase == "report" and session.report is None
            assert isinstance(session.voice, MockVoice)
            assert session.voice.calls[-1][0] == "stop"
            entered.set()
            await asyncio.Future()
            raise AssertionError("Unreachable: the recovery wait must time out.")

    async def forbidden(*args):
        pytest.fail("Report grading must share the exhausted recovery preparation budget.")

    monkeypatch.setattr(engine, "assess_report", forbidden)
    session.orchestrator = SlowRecovery()
    await session.start(0)
    await session.force_curveball("slides_down", 60_000)
    await session.presenter_transcript(65_000, seg(61, "We can continue from the outline."))
    await room.run(session.finish(66_000))
    assert entered.is_set() and session.phase == "report"
    assert session.report is not None and session.curveballs.active is None
    assert "could not finish" in " ".join(session.report.metric_caveats)
    assert len(store.reports) == 1


@pytest.mark.parametrize("during", ["notification", "assessment"])
async def test_cancellation_propagates_after_persisting_a_valid_measured_fallback(
    room, monkeypatch, during,
):
    room, _, store = room
    session = room.session
    entered, canceled = asyncio.Event(), asyncio.Event()

    async def wait_forever(*args):
        entered.set()
        try:
            await asyncio.Future()
        finally:
            canceled.set()

    if during == "notification":
        session.on_report_pending = wait_forever
    else:
        monkeypatch.setattr(engine, "assess_report", wait_forever)
    await session.start(0)
    await session.force_curveball("slides_down", 60_000)
    if during == "assessment":
        await session.control("skip", 65_000)
    finishing = asyncio.create_task(room.run(session.finish(66_000)))
    await asyncio.wait_for(entered.wait(), 1)
    finishing.cancel()
    with pytest.raises(asyncio.CancelledError):
        await finishing
    assert canceled.is_set() and room.active_task is None
    assert session.phase == "report" and session.report is not None
    assert session.curveballs.active is None and session.presenter_turn_id is None
    assert len(store.reports) == 1
    saved = store.load(session.session_id)
    assert saved is not None
    assert Report.model_validate(saved["report"]).session_id == session.session_id
    assert "was interrupted" in " ".join(saved["report"]["metric_caveats"])
    assert saved["snapshot"]["elapsed_ms"] == 66_000


async def test_mock_finish_keeps_the_immediate_unscored_report_path(room):
    room, _, store = room
    await room.run(room.session.finish(0))
    assert room.session.report is not None and room.session.report.overall_score is None
    assert len(store.reports) == 1
