"""The real orchestrator, without a key or network: prompt formatting, fallbacks, guards."""

from dataclasses import dataclass, field
from typing import Any

import pytest

from backend import presets
from backend.services.audience import (
    FOLLOW_UP_PROMPT,
    RECOVERY_PROMPT,
    SYSTEM_PROMPT,
    ClaudeOrchestrator,
    OrchestratorContext,
)
from backend.tests.conftest import seg
from spec.contracts import FollowUpVerdict, OrchestratorDecision, Persona, RecoveryAssessment


@dataclass
class FakeResponse:
    parsed_output: Any
    stop_reason: str = "end_turn"


@dataclass
class FakeMessages:
    reply: Any
    calls: list[dict] = field(default_factory=list)

    async def parse(self, **kwargs):
        self.calls.append(kwargs)
        return self.reply if isinstance(self.reply, FakeResponse) else FakeResponse(self.reply)


class FakeClient:
    def __init__(self, reply):
        self.messages = FakeMessages(reply)


def ctx(**overrides: Any) -> OrchestratorContext:
    roster = presets.personas()
    base: dict[str, Any] = dict(
        preset_id="startup_pitch", difficulty="normal",
        personas=[roster["vc"], roster["student"], roster["professor"]],
        slide_number=3, slide_text="Traction\n100,000 customers in six months",
        recent_transcript=[seg(33, "We can get 100,000 customers in six months.")],
        prior_qa=[{"persona_id": "vc", "q": "Evidence?", "cited": "x", "a": None}],
        question_allowed=True, eligible_kinds=["slides_down"], curveball_budget_remaining=1,
        seconds_since_last_event=42,
    )
    base.update(overrides)
    return OrchestratorContext(**base)


async def test_decide_formats_the_context_and_returns_the_parsed_decision():
    want = OrchestratorDecision(action="question", persona_id="vc",
                                line="What evidence supports 100,000 customers?",
                                reason="unsupported", cited_transcript_excerpt="100,000 customers",
                                slide_number=3)
    client = FakeClient(want)
    orch = ClaudeOrchestrator(client=client, model="claude-opus-5-5")
    got = await orch.decide(ctx())
    assert got == want
    call = client.messages.calls[0]
    assert call["model"] == "claude-opus-5-5" and call["output_format"] is OrchestratorDecision
    assert call["system"] == SYSTEM_PROMPT and call["output_config"] == {"effort": "low"}
    user = call["messages"][0]["content"]
    for needle in ("vc: Skeptical VC", "[33.0s] We can get 100,000 customers",
                   "slide 3 text:", "eligible curveball kinds: slides_down",
                   "vc asked: 'Evidence?'", "seconds since the last audience event: 42",
                   "actions allowed right now: question, curveball, none"):
        assert needle in user, needle


async def test_decide_skips_the_call_when_nothing_is_allowed():
    client = FakeClient(OrchestratorDecision(action="question", reason="x"))
    orch = ClaudeOrchestrator(client=client)
    got = await orch.decide(ctx(question_allowed=False, eligible_kinds=[]))
    assert got.action == "none" and client.messages.calls == []


async def test_decide_guards_disallowed_answers_and_refusals():
    orch = ClaudeOrchestrator(client=FakeClient(
        OrchestratorDecision(action="curveball", curveball_kind="heckler", reason="x")))
    assert (await orch.decide(ctx(eligible_kinds=["slides_down"]))).action == "none"
    orch = ClaudeOrchestrator(client=FakeClient(
        OrchestratorDecision(action="question", persona_id="vc", line="q", reason="x")))
    assert (await orch.decide(ctx(question_allowed=False))).action == "none"
    orch = ClaudeOrchestrator(client=FakeClient(FakeResponse(None, stop_reason="refusal")))
    got = await orch.decide(ctx())
    assert got.action == "none" and "declined" in got.reason


async def test_follow_up_uses_the_prompt_once_then_hands_back():
    client = FakeClient(FollowUpVerdict(verdict="follow_up", line="What data?",
                                        missing_detail="data"))
    orch = ClaudeOrchestrator(client=client)
    persona = presets.personas()["vc"]
    first = await orch.follow_up("Evidence?", "We plan to grow.", persona, used=0)
    assert first.verdict == "follow_up"
    assert client.messages.calls[0]["system"] == FOLLOW_UP_PROMPT
    second = await orch.follow_up("Evidence?", "We plan to grow.", persona, used=1)
    assert second.verdict == "satisfied" and len(client.messages.calls) == 1  # no second call


async def test_recovery_is_null_without_speech_and_evidence_must_be_verbatim():
    client = FakeClient(RecoveryAssessment(score=80, evidence="made-up quote",
                                           observation="ok", suggestion="s"))
    orch = ClaudeOrchestrator(client=client)
    none = await orch.assess_recovery("slides_down", "line", [], None)
    assert none.score is None and none.evidence is None and client.messages.calls == []
    after = [seg(128.4, "So, the problem again is onboarding.")]
    got = await orch.assess_recovery("slides_down", "line", after, 3400)
    assert got.score == 80 and got.evidence == after[0].text  # non-verbatim evidence replaced
    assert client.messages.calls[0]["system"] == RECOVERY_PROMPT
    assert client.messages.calls[0]["output_config"] == {"effort": "high"}
    assert "3.4 s" in client.messages.calls[0]["messages"][0]["content"]


async def test_expand_persona_sets_id_and_custom_and_falls_back_on_refusal():
    model_persona = Persona(id="whatever", name="The Chair", role="Thesis committee chair",
                            focus=["jargon", "method"], skepticism=0.7, style_hint="thoughtful",
                            plays=["bait"])
    orch = ClaudeOrchestrator(client=FakeClient(model_persona))
    got = await orch.expand_persona("my thesis committee chair who hates jargon", 1)
    assert got.id == "custom_1" and got.custom is True and got.role == "Thesis committee chair"
    orch = ClaudeOrchestrator(client=FakeClient(FakeResponse(None, stop_reason="refusal")))
    fallback = await orch.expand_persona("someone", 2)
    assert fallback.id == "custom_2" and fallback.custom is True


async def test_timeout_surfaces_as_an_exception_the_engine_turns_into_an_error_event():
    import asyncio

    class SlowMessages:
        async def parse(self, **kwargs):
            await asyncio.sleep(1)

    class SlowClient:
        messages = SlowMessages()

    orch = ClaudeOrchestrator(client=SlowClient())
    orch.timeout_s = 0.01
    with pytest.raises(asyncio.TimeoutError):
        await orch.decide(ctx())
