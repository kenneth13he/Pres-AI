"""The real orchestrator, without a key or network: prompt formatting, fallbacks, guards."""

import json
from dataclasses import dataclass, field
from typing import Any, Literal, TypeVar

import pytest
from pydantic import TypeAdapter

from backend import presets
from backend.services.audience import (
    FOLLOW_UP_PROMPT,
    RECOVERY_PROMPT,
    SYSTEM_PROMPT,
    ClaudeOrchestrator,
    MockOrchestrator,
    OrchestratorContext,
    StructuredOrchestrator,
)
from backend.tests.conftest import seg
from spec.contracts import FollowUpVerdict, OrchestratorDecision, Persona, RecoveryAssessment

T = TypeVar("T")


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
                                reason="unsupported",
                                cited_transcript_excerpt="100,000 customers in six months",
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
                            plays=["bait", "time_crunch", "elevator"])
    orch = ClaudeOrchestrator(client=FakeClient(model_persona))
    got = await orch.expand_persona("my thesis committee chair who hates jargon", 1)
    assert got.id == "custom_1" and got.custom is True and got.role == "Thesis committee chair"
    assert got.plays == ["bait"]
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
    status = orch.diagnostics()
    assert status["operations"]["decide"] == {
        "attempts": 1, "successes": 0, "failures": 1, "fallbacks": 0,
        "rejections": 0, "skipped": 0,
    }
    assert status["last_error"] == {
        "operation": "decide", "kind": "timeout", "error_class": "TimeoutError",
        "status_code": None,
    }
    fallback = await orch.expand_persona("someone", 1)
    assert fallback.custom
    assert orch.diagnostics()["operations"]["expand_persona"]["fallbacks"] == 1


# ---- through the real SDK (no network: httpx MockTransport) ------------------------------


def sdk_client(body: dict, status: int = 200):

    import anthropic
    import httpx2  # the SDK's own HTTP stack (not `httpx`)

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(status, json=body, request=request)

    return anthropic.AsyncAnthropic(
        api_key="sk-test", max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
    )


def message(text: str, stop_reason: str = "end_turn") -> dict:
    return {
        "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
        "content": [{"type": "text", "text": text}], "stop_reason": stop_reason,
        "stop_sequence": None, "usage": {"input_tokens": 10, "output_tokens": 10},
    }


async def test_refusal_with_text_through_the_real_sdk_is_a_none_not_a_crash():
    orch = ClaudeOrchestrator(client=sdk_client(message("I can't help with that.", "refusal")))
    got = await orch.decide(ctx())
    assert got.action == "none"


async def test_truncated_and_invalid_replies_through_the_real_sdk_fall_back():
    orch = ClaudeOrchestrator(client=sdk_client(message('{"action": "quest', "max_tokens")))
    assert (await orch.decide(ctx())).action == "none"
    bad = json.dumps({"score": 250, "evidence": "x", "observation": "o", "suggestion": "s"})
    orch = ClaudeOrchestrator(client=sdk_client(message(bad)))
    got = await orch.assess_recovery("slides_down", "l", [seg(1, "a b c d")], 100)
    assert got.score is None


async def test_api_error_through_the_real_sdk_never_breaks_persona_expansion():
    orch = ClaudeOrchestrator(client=sdk_client(
        {"type": "error", "error": {"type": "authentication_error", "message": "bad key"}}, 401))
    got = await orch.expand_persona("someone sceptical", 3)
    assert got.id == "custom_3" and got.custom is True
    assert (await orch.decide(ctx())).action == "none"


async def test_valid_reply_through_the_real_sdk_parses_and_is_grounded():
    good = json.dumps({
        "action": "question", "persona_id": "vc",
        "line": "What backs “100,000 customers in six months”?", "reason": "unsupported",
        "cited_transcript_excerpt": "“100,000 customers in six months”", "slide_number": 99,
    })
    orch = ClaudeOrchestrator(client=sdk_client(message(good)))
    got = await orch.decide(ctx())
    assert got.action == "question" and got.persona_id == "vc"
    assert got.slide_number == 3  # the slide actually shown, not the model's guess


async def test_question_with_an_invented_quote_is_not_asked():
    orch = ClaudeOrchestrator(client=FakeClient(OrchestratorDecision(
        action="question", persona_id="vc", line="q", reason="r",
        cited_transcript_excerpt="we are profitable already", slide_number=3)))
    got = await orch.decide(ctx())
    assert got.action == "none" and "verbatim" in got.reason
    orch = ClaudeOrchestrator(client=FakeClient(OrchestratorDecision(
        action="question", persona_id="Skeptical VC", line="q", reason="r",
        cited_transcript_excerpt="100,000 customers in six months", slide_number=3)))
    assert (await orch.decide(ctx())).action == "none"  # off-roster persona id


def test_verbatim_check_is_forgiving_about_quotes_case_and_segment_boundaries():
    segs = [seg(1, "So, the problem again"), seg(4, "is onboarding, honestly.")]
    assert ClaudeOrchestrator.verbatim("“the PROBLEM again is onboarding”", segs)
    assert not ClaudeOrchestrator.verbatim(" ", segs)
    assert not ClaudeOrchestrator.verbatim("is onboarding", segs)  # < 3 words
    assert not ClaudeOrchestrator.verbatim("the problem is churn", segs)


async def test_qna_round_accepts_a_question_grounded_in_the_slides():
    client = FakeClient(OrchestratorDecision(
        action="question", persona_id="student", line="What happens after the pilot?",
        reason="left open", cited_transcript_excerpt=None, slide_number=3))
    orch = ClaudeOrchestrator(client=client)
    assert (await orch.decide(ctx())).action == "none"  # mid-talk: needs a verbatim quote
    got = await orch.decide(ctx(qna=True))
    assert got.action == "question" and got.cited_transcript_excerpt is None
    assert "closing Q&A" in client.messages.calls[-1]["messages"][0]["content"]


async def test_diagnostics_record_real_sdk_success_and_tokens_as_independent_snapshots():
    orch = ClaudeOrchestrator(client=sdk_client(message(json.dumps({
        "action": "none", "reason": "Let the presenter finish.",
    }))), model="configured-model")
    assert (await orch.decide(ctx())).action == "none"
    status = orch.diagnostics()
    assert status["adapter"] == "claude" and status["model"] == "configured-model"
    assert status["last_response_model"] == "claude-opus-5-5"
    assert status["operations"]["decide"] == {
        "attempts": 1, "successes": 1, "failures": 0, "fallbacks": 0,
        "rejections": 0, "skipped": 0,
    }
    assert status["usage"] == {"input_tokens": 10, "output_tokens": 10}
    assert status["last_error"] is None and status["totals"]["successes"] == 1
    status["operations"]["decide"]["successes"] = 999
    status["usage"]["input_tokens"] = 999
    assert orch.diagnostics()["totals"]["successes"] == 1
    assert orch.diagnostics()["usage"]["input_tokens"] == 10


async def test_diagnostics_api_401_is_a_failure_and_never_exposes_vendor_text():
    private_marker = "PRIVATE_VENDOR_BODY_CREDENTIAL_123"
    orch = ClaudeOrchestrator(client=sdk_client({
        "type": "error", "error": {"type": "authentication_error", "message": private_marker},
    }, 401))
    assert (await orch.decide(ctx())).action == "none"
    assert (await orch.expand_persona("private persona description", 2)).custom
    status = orch.diagnostics()
    assert status["totals"]["attempts"] == 2 and status["totals"]["successes"] == 0
    assert status["totals"]["failures"] == status["totals"]["fallbacks"] == 2
    assert status["last_error"] == {
        "operation": "expand_persona", "kind": "api_error",
        "error_class": "AuthenticationError", "status_code": 401,
    }
    serialized = json.dumps(status)
    for private in (private_marker, "private persona description", "sk-test", "100,000 customers"):
        assert private not in serialized
    status["last_error"]["kind"] = "mutated"
    assert orch.diagnostics()["last_error"]["kind"] == "api_error"


async def test_diagnostics_no_call_guards_are_skips_and_mock_is_explicit():
    client = FakeClient(None)
    orch = ClaudeOrchestrator(client=client)
    await orch.decide(ctx(question_allowed=False, eligible_kinds=[]))
    await orch.follow_up("q", "a", presets.personas()["vc"], used=1)
    await orch.assess_recovery("slides_down", "line", [], None)
    status = orch.diagnostics()
    assert status["totals"]["skipped"] == 3 and status["totals"]["attempts"] == 0
    assert status["totals"]["fallbacks"] == 0 and client.messages.calls == []
    mock = MockOrchestrator().diagnostics()
    assert mock["adapter"] == "mock" and mock["model"] is None
    assert mock["totals"]["attempts"] == mock["totals"]["successes"] == 0


async def test_diagnostics_grounding_rejection_is_separate_from_api_success():
    orch = ClaudeOrchestrator(client=FakeClient(OrchestratorDecision(
        action="question", persona_id="vc", line="q", reason="r",
        cited_transcript_excerpt="the model invented this quote")))
    assert (await orch.decide(ctx())).action == "none"
    counts = orch.diagnostics()["operations"]["decide"]
    assert counts["successes"] == counts["rejections"] == counts["fallbacks"] == 1
    assert counts["failures"] == 0
    assert orch.diagnostics()["last_error"]["kind"] == "ungrounded_question"


@pytest.mark.parametrize("stop_reason,kind", [
    ("refusal", "refusal"), ("max_tokens", "truncated_response"),
])
async def test_diagnostics_identify_exposed_stop_reasons(stop_reason, kind):
    orch = ClaudeOrchestrator(client=FakeClient(FakeResponse(None, stop_reason=stop_reason)))
    await orch.decide(ctx())
    status = orch.diagnostics()
    assert status["totals"]["failures"] == status["totals"]["fallbacks"] == 1
    assert status["last_error"]["kind"] == kind


async def test_sdk_validation_failure_is_honest_when_stop_reason_is_unavailable():
    # messages.parse validates JSON before exposing stop_reason; do not guess from text.
    orch = ClaudeOrchestrator(client=sdk_client(message("refusal body is private", "refusal")))
    await orch.decide(ctx())
    status = orch.diagnostics()
    assert status["last_error"]["kind"] == "invalid_structured_response"
    assert status["last_error"]["error_class"] == "ValidationError"
    assert status["totals"]["successes"] == 0 and status["totals"]["fallbacks"] == 1
    assert "refusal body is private" not in json.dumps(status)


class BosonStub(StructuredOrchestrator):
    """Only the provider transport changes; all semantic behavior comes from the core."""

    def __init__(self, reply: dict[str, Any]) -> None:
        super().__init__(model="higgs-realtime", adapter="boson")
        self.reply = reply

    async def _parse(self, system: str, user: str, schema: type[T],
                     effort: Literal["low", "high"], max_tokens: int = 2048,
                     timeout_s: float | None = None) -> T | None:
        operation = self._operation(schema)
        self._reasoning_counts[operation]["attempts"] += 1
        output = TypeAdapter(schema).validate_python(self.reply)
        self._reasoning_counts[operation]["successes"] += 1
        return output


@pytest.mark.parametrize("missing", ["persona_id", "line"])
async def test_provider_neutral_core_rejects_missing_action_required_optional_fields(missing):
    reply = {
        "action": "question", "persona_id": "vc", "line": "What evidence supports that?",
        "reason": "unsupported", "cited_transcript_excerpt": "100,000 customers in six months",
    }
    del reply[missing]
    # The contract accepts these omitted optional fields; a speaking decision must not.
    assert OrchestratorDecision.model_validate(reply).action == "question"
    orch = BosonStub(reply)
    assert (await orch.decide(ctx())).action == "none"
    status = orch.diagnostics()
    assert status["adapter"] == "boson" and status["model"] == "higgs-realtime"
    assert status["totals"]["rejections"] == status["totals"]["fallbacks"] == 1
    assert status["last_error"]["kind"] == "invalid_question"


async def test_provider_neutral_core_preserves_grounding_and_deliberate_no_call_guards():
    orch = BosonStub({
        "action": "question", "persona_id": "vc", "line": "What evidence supports that?",
        "reason": "unsupported", "cited_transcript_excerpt": "100,000 customers in six months",
        "slide_number": 99,
    })
    decision = await orch.decide(ctx())
    assert decision.action == "question" and decision.slide_number == 3
    satisfied = await orch.follow_up("q", "a", presets.personas()["vc"], used=1)
    recovery = await orch.assess_recovery("slides_down", "line", [], None)
    assert satisfied.verdict == "satisfied" and recovery.score is None
    assert orch.diagnostics()["totals"]["attempts"] == 1
    assert orch.diagnostics()["totals"]["skipped"] == 2
    assert orch.diagnostics()["totals"]["fallbacks"] == 0
