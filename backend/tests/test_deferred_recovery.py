"""A captured turn can finish after its curveball closes, without moving that deadline."""
from __future__ import annotations

import asyncio

import pytest

from backend.engine import TRANSCRIPTION_WAIT_MS
from backend.services.audience import MockOrchestrator
from backend.services.curveballs import CATALOG
from backend.tests.conftest import make_session
from spec.contracts import RecoveryAssessment, TranscriptSegment

TRIGGER = 204_897
DEADLINE = 264_897
RESOLVED = 265_358
RELEASED = 266_194
ARRIVED = 269_397
CLOSING = TranscriptSegment(
    start_ms=215_438, end_ms=RELEASED,
    text="Our closing request is a pilot with three schools, measured against weekly retention.",
)


class Grader(MockOrchestrator):
    def __init__(self, *, wait: bool = False, fail: bool = False) -> None:
        self.calls: list[tuple[str, list[TranscriptSegment], int | None]] = []
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.wait, self.fail = wait, fail

    async def assess_recovery(self, kind, line, after, resume_after_ms):
        if not after:
            return await super().assess_recovery(kind, line, after, resume_after_ms)
        self.calls.append((line, list(after), resume_after_ms))
        self.entered.set()
        if self.wait:
            await self.release.wait()
        if self.fail:
            raise RuntimeError("offline grader unavailable")
        return RecoveryAssessment(score=78, evidence=after[0].text,
                                  observation="A clear close with a small overrun.",
                                  suggestion="Finish the request before the countdown ends.")


async def closed_crunch(*, held: bool = True, pending: bool = False, grader=None):
    session = make_session(qna_questions=1)
    session.orchestrator = grader or Grader()
    await session.start(0)
    await session.force_curveball("time_crunch", TRIGGER)
    assert session.time_crunch_deadline_ms == DEADLINE
    if held:
        session.presenter_turn_started(CLOSING.start_ms, "closing")
        if pending:
            session.presenter_turn_ended(DEADLINE - 100, "closing")
    await session.tick(RESOLVED)
    rec = session.curveballs.records[0]
    assert rec.resolution == "timed_out" and rec.resolved_at_ms == RESOLVED
    assert session.phase == "qna" and session.time_crunch_deadline_ms is None
    return session, rec


async def deliver_closing(session, *, segment=CLOSING, turn_id="closing", now_ms=ARRIVED):
    session.presenter_turn_ended(RELEASED, turn_id)
    await session.presenter_transcript(now_ms, segment, turn_id)


async def test_final_straddling_countdown_is_graded_once_without_reopening_the_effect():
    grader = Grader()
    session, rec = await closed_crunch(grader=grader)
    resolved_event = next(e for e in session.events if e.type == "curveball_resolved")
    assert rec.recovery is not None and rec.recovery.score is None
    await session.tick(RESOLVED + 100)
    session.presenter_turn_ended(RELEASED, "closing")
    await session.tick(RELEASED + 100)
    assert not session.questions and session.presenter_floor_blocked(RELEASED + 100)
    before = [(e.type, e.timestamp_ms) for e in session.events]

    await session.presenter_transcript(ARRIVED, CLOSING, "closing")
    assert len(grader.calls) == 1 and grader.calls[0][1] == [CLOSING]
    context = grader.calls[0][0]
    for value in (f"deadline_ms={DEADLINE}", f"resolved_at_ms={RESOLVED}",
                  f"start_ms={CLOSING.start_ms}", f"end_ms={RELEASED}",
                  f"received_at_ms={ARRIVED}", "do not assume every word"):
        assert value in context
    assert rec.recovery is not None and rec.recovery.score == 78
    assert rec.recovery.evidence == CLOSING.text and rec.recovery.resume_after_ms is None
    assert rec.recovery.notes == (
        "Closing turn began during the countdown and ended 1.3 seconds after zero. "
        "Individual word timing is unavailable.")
    assert resolved_event.payload["recovery"] == rec.recovery.model_dump()
    assert rec.resolved_at_ms == resolved_event.timestamp_ms == RESOLVED
    assert rec.resolution == "timed_out" and session.phase == "qna"
    assert [(e.type, e.timestamp_ms) for e in session.events] == before + [
        ("transcript_segment", ARRIVED)]
    await session.presenter_transcript(ARRIVED + 1, CLOSING, "closing")
    assert len(grader.calls) == 1
    await session.finish(ARRIVED + 2)
    assert session.report is not None
    assert session.report.curveballs[0].recovery == rec.recovery
    assert session.report.dimensions["recovery"] == 78


async def test_release_before_resolution_keeps_the_matching_final_eligible():
    grader = Grader()
    session, rec = await closed_crunch(pending=True, grader=grader)
    segment = CLOSING.model_copy(update={"end_ms": DEADLINE - 100})
    await session.presenter_transcript(ARRIVED, segment, "closing")
    assert len(grader.calls) == 1 and rec.recovery is not None
    assert rec.recovery.score == 78 and "after zero" not in (rec.recovery.notes or "")


async def test_other_turn_history_does_not_consume_or_contaminate_the_pending_recovery():
    grader = Grader()
    session, rec = await closed_crunch(grader=grader)
    other = CLOSING.model_copy(update={"text": "An unrelated delayed transcript."})
    await session.presenter_transcript(ARRIVED - 100, other, "other")
    assert not grader.calls and session.presenter_floor_blocked(ARRIVED - 100)
    await deliver_closing(session)
    assert grader.calls[0][1] == [CLOSING] and other in session.transcript
    assert rec.recovery is not None and rec.recovery.evidence == CLOSING.text


@pytest.mark.parametrize("start_ms", [TRIGGER, DEADLINE + 1, RESOLVED + 1])
async def test_final_outside_the_closed_effect_window_cannot_grade_recovery(start_ms):
    grader = Grader()
    session, rec = await closed_crunch(grader=grader)
    await deliver_closing(session, segment=CLOSING.model_copy(update={"start_ms": start_ms}))
    await session.presenter_transcript(ARRIVED + 1, CLOSING, "closing")
    assert not grader.calls and rec.recovery is not None and rec.recovery.score is None


@pytest.mark.parametrize("change", ["cancel", "new_turn", "pause", "skip", "end", "expired"])
async def test_cancellation_or_expiry_never_regrades_a_later_transcript(change):
    grader = Grader()
    session, rec = await closed_crunch(grader=grader)
    if change == "cancel":
        session.presenter_turn_cancelled("closing")
    elif change == "new_turn":
        session.presenter_turn_started(RESOLVED + 1, "qna-answer")
    elif change == "expired":
        session.presenter_turn_ended(RELEASED, "closing")
    else:
        session.prepare_control(change)
        await session.control(change, RESOLVED + 1)
    received = RELEASED + TRANSCRIPTION_WAIT_MS if change == "expired" else ARRIVED
    await session.presenter_transcript(received, CLOSING, "closing")
    assert not grader.calls and rec.recovery is not None and rec.recovery.score is None


async def test_silence_and_a_later_qna_turn_remain_unmeasured():
    grader = Grader()
    session, rec = await closed_crunch(held=False, grader=grader)
    session.presenter_turn_started(RESOLVED + 1, "qna")
    await session.presenter_transcript(ARRIVED, CLOSING, "qna")
    assert not grader.calls and rec.recovery is not None and rec.recovery.score is None


async def test_a_skipped_effect_or_already_graded_record_is_never_regraded():
    grader = Grader()
    session = make_session()
    session.orchestrator = grader
    await session.start(0)
    await session.force_curveball("slides_down", 60_000)
    session.presenter_turn_started(62_000, "closing")
    await session.control("skip", 63_000)
    await session.presenter_transcript(65_000, CLOSING.model_copy(
        update={"start_ms": 62_000, "end_ms": 64_000}), "closing")
    assert session.curveballs.records[0].recovery is None and not grader.calls
    session, rec = await closed_crunch(grader=grader)
    assert rec.recovery is not None
    rec.recovery.score = 91
    await deliver_closing(session)
    assert rec.recovery.score == 91 and not grader.calls


async def test_grader_failure_keeps_actual_evidence_but_never_retries_or_invents_a_score():
    grader = Grader(fail=True)
    session, rec = await closed_crunch(grader=grader)
    await deliver_closing(session)
    await session.presenter_transcript(ARRIVED + 1, CLOSING, "closing")
    assert len(grader.calls) == 1 and rec.recovery is not None
    assert rec.recovery.score is None and rec.recovery.evidence == CLOSING.text
    assert "1.3 seconds after zero" in (rec.recovery.notes or "")
    assert len([e for e in session.events if e.type == "error"]) == 1


@pytest.mark.parametrize("action", ["pause", "end", "cancel_task"])
async def test_inflight_grading_cannot_mutate_after_pause_finish_or_task_cancellation(action):
    grader = Grader(wait=True)
    session, rec = await closed_crunch(grader=grader)
    resolved = next(e for e in session.events if e.type == "curveball_resolved")
    original = dict(resolved.payload)
    task = asyncio.create_task(deliver_closing(session))
    await asyncio.wait_for(grader.entered.wait(), 1)
    if action == "cancel_task":
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        session.prepare_control(action)
        await session.control(action, ARRIVED + 1)
        grader.release.set()
        await task
    assert rec.recovery is not None and rec.recovery.score is None
    assert resolved.payload == original
    assert len(grader.calls) == 1
    assert not any(e.type == "error" for e in session.events)
    if action == "end":
        assert session.report is not None and session.report.curveballs[0].recovery is not None
        assert session.report.curveballs[0].recovery.score is None


async def test_time_crunch_speech_always_matches_the_fixed_sixty_second_timer():
    session = make_session()
    await session.start(0)
    await session._fire_curveball("time_crunch", TRIGGER,
                                 "We only have five minutes left.", None)
    rec = session.curveballs.records[0]
    canonical = CATALOG["time_crunch"].default_line
    assert rec.line == canonical
    speech = next(e for e in session.events if e.type == "ai_speech_started")
    assert speech.payload["line"] == canonical
    assert session.time_crunch_deadline_ms == DEADLINE
