"""Decision attempts are bounded without weakening presenter-floor/control guards."""

from __future__ import annotations

import asyncio

import pytest

from backend.engine import DECISION_INTERVAL_MS
from backend.services.audience import MockOrchestrator
from backend.tests.conftest import make_session, s, seg
from spec.contracts import OrchestratorDecision


class CountingNone(MockOrchestrator):
    def __init__(self) -> None:
        self.calls = []

    async def decide(self, ctx):
        self.calls.append(ctx)
        return OrchestratorDecision(action="none", reason="offline check")


async def prepared(model, **config):
    session = make_session(curveballs={"mode": "off"}, **config)
    session.orchestrator = model
    await session.start(0)
    await session.presenter_transcript(s(32), seg(32, "We have 2,000 paying users."))
    return session


async def test_none_attempt_backs_off_then_a_later_eligible_question_works():
    class ThenAsk(CountingNone):
        async def decide(self, ctx):
            self.calls.append(ctx)
            if len(self.calls) == 1:
                return OrchestratorDecision(action="none", reason="wait")
            return await MockOrchestrator.decide(self, ctx)

    model = ThenAsk()
    session = await prepared(model)
    await session.tick(s(36))
    for now_ms in (s(37), s(38), s(40), s(41) - 1):
        await session.tick(now_ms)
    assert len(model.calls) == 1 and not session.questions
    await session.tick(s(36) + DECISION_INTERVAL_MS)
    assert len(model.calls) == 2 and session.phase == "answering"
    assert "2,000 paying users" in session.questions[0]["cited_excerpt"]


async def test_failed_attempt_also_backs_off_instead_of_flooding_each_tick():
    class Failing(CountingNone):
        async def decide(self, ctx):
            self.calls.append(ctx)
            if len(self.calls) == 1:
                raise RuntimeError("offline model failure")
            return OrchestratorDecision(action="none", reason="recovered")

    model = Failing()
    session = await prepared(model)
    await session.tick(s(36))
    await session.tick(s(37))
    assert len(model.calls) == 1
    errors = [event for event in session.events if event.type == "error"]
    assert len(errors) == 1 and errors[0].payload["where"] == "orchestrator.decide"
    await session.tick(s(41))
    assert len(model.calls) == 2 and session.phase == "presenting"


async def test_absent_or_expired_transcripts_do_not_spend_a_question_decision():
    model = CountingNone()
    session = make_session(curveballs={"mode": "off"})
    session.orchestrator = model
    await session.start(0)
    await session.tick(s(36))
    await session.presenter_transcript(s(1), seg(1, "An old opening statement."))
    await session.tick(s(37))
    assert not model.calls and session._last_decision_attempt_ms is None
    await session.presenter_transcript(s(38), seg(38, "A fresh presentation statement."))
    await session.tick(s(39))
    assert len(model.calls) == 1


async def test_a_due_curveball_can_be_decided_without_a_recent_transcript():
    model = CountingNone()
    session = make_session(curveballs={"mode": "choose", "kinds": ["slides_down"]})
    session.orchestrator = model
    await session.start(0)
    await session.slide_changed(s(1), 2)
    await session.presenter_transcript(s(2), seg(2, "An opening thought."))
    await session.tick(s(61))
    assert len(model.calls) == 1
    assert model.calls[0].eligible_kinds == ["slides_down"]
    assert model.calls[0].question_allowed is False
    assert model.calls[0].recent_transcript == []


async def test_held_capture_and_pending_final_still_block_before_consuming_an_attempt():
    model = CountingNone()
    session = await prepared(model)
    session.presenter_turn_started(s(35), "held")
    await session.tick(s(36))
    session.presenter_turn_ended(s(38), "held")
    await session.tick(s(40))
    assert not model.calls and session._last_decision_attempt_ms is None
    await session.presenter_transcript(
        s(41), seg(35, "We have 3,000 paying users."), turn_id="held")
    await session.tick(s(43))
    assert len(model.calls) == 1


async def test_pause_freezes_the_remaining_decision_interval():
    model = CountingNone()
    session = await prepared(model)
    await session.tick(s(36))
    await session.control("pause", s(38))
    await session.control("resume", s(100))
    await session.presenter_transcript(s(100), seg(100, "A fresh thought after resuming."))
    await session.tick(s(100))
    await session.tick(s(102))
    assert len(model.calls) == 1
    await session.tick(s(103))
    assert len(model.calls) == 2


@pytest.mark.parametrize("closing_qna", [False, True])
async def test_stale_decisions_are_discarded_and_share_the_attempt_interval(closing_qna):
    class Waiting(CountingNone):
        def __init__(self):
            super().__init__()
            self.entered, self.release = asyncio.Event(), asyncio.Event()

        async def decide(self, ctx):
            self.calls.append(ctx)
            if len(self.calls) == 1:
                self.entered.set()
                await self.release.wait()
            return await MockOrchestrator.decide(self, ctx)

    model = Waiting()
    session = await prepared(model)
    if closing_qna:
        await session.control("end", s(35))
    task = asyncio.create_task(session.tick(s(36)))
    await asyncio.wait_for(model.entered.wait(), 1)
    session.presenter_turn_started(s(37), "new-input")
    model.release.set()
    await task
    assert not session.questions
    session.presenter_turn_cancelled("new-input")
    await session.tick(s(39))
    assert len(model.calls) == 1
    await session.tick(s(41))
    assert len(model.calls) == 2 and session.phase == "answering"


async def test_qna_none_finishes_once_without_periodic_retries():
    model = CountingNone()
    session = await prepared(model)
    await session.control("end", s(35))
    await session.tick(s(36))
    assert session.ended and len(model.calls) == 1
    await session.tick(s(40))
    assert len(model.calls) == 1
