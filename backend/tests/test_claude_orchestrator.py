"""The real orchestrator, without a key or network: prompt formatting, fallbacks, guards."""

import json
from dataclasses import dataclass, field
from typing import Any

import pytest

from backend import presets
from backend.services.audience import (
    RECOVERY_PROMPT,
    TURN_PROMPT,
    ClaudeOrchestrator,
    Line,
    OrchestratorContext,
)
from backend.tests.conftest import seg
from spec.contracts import PanelTurn, Persona, RecoveryAssessment


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
        conversation=[Line("presenter", "We can get 100,000 customers in six months.", 33_000),
                      Line("vc", "Based on what?", 37_000)],
        trigger="spoke", elapsed_s=60, seconds_since_panel_spoke=42,
        open_question=Line("vc", "Based on what?", 37_000),
        eligible_kinds=["slides_down"], curveball_budget_remaining=1,
    )
    base.update(overrides)
    return OrchestratorContext(**base)


QUESTION = PanelTurn(action="speak", persona_id="vc", is_question=True, reason="unsupported",
                     line="What backs 100,000 customers?",
                     cited_transcript_excerpt="100,000 customers in six months")


async def test_turn_formats_the_whole_conversation_and_returns_the_parsed_turn():
    client = FakeClient(QUESTION)
    orch = ClaudeOrchestrator(client=client, model="claude-opus-5-5")
    assert await orch.turn(ctx()) == QUESTION
    call = client.messages.calls[0]
    assert call["model"] == "claude-opus-5-5" and call["output_format"] is PanelTurn
    assert call["system"] == TURN_PROMPT and call["output_config"] == {"effort": "low"}
    user = call["messages"][0]["content"]
    for needle in ("vc (", "[33s] PRESENTER: We can get 100,000 customers",
                   "Based on what?", "slide 3:", "trigger: spoke", "panel last spoke: 42s ago",
                   "open question:", "eligible curveballs now: slides_down"):
        assert needle in user, needle


async def test_turn_guards_wrong_speakers_and_ineligible_curveballs():
    orch = ClaudeOrchestrator(client=FakeClient(PanelTurn(
        action="curveball", curveball_kind="heckler", line="x", reason="x")))
    assert (await orch.turn(ctx())).action == "wait"
    orch = ClaudeOrchestrator(client=FakeClient(PanelTurn(
        action="speak", persona_id="Skeptical VC", line="hi", reason="x")))
    assert (await orch.turn(ctx())).action == "wait"  # off-roster persona id
    orch = ClaudeOrchestrator(client=FakeClient(PanelTurn(
        action="speak", persona_id="vc", line="  ", reason="x")))
    assert (await orch.turn(ctx())).action == "wait"
    orch = ClaudeOrchestrator(client=FakeClient(FakeResponse(None, stop_reason="refusal")))
    assert (await orch.turn(ctx())).action == "wait"


async def test_a_moderator_curveball_has_no_persona_and_a_persona_one_gets_a_player():
    orch = ClaudeOrchestrator(client=FakeClient(PanelTurn(
        action="curveball", curveball_kind="slides_down", persona_id="vc", line="x",
        reason="x")))
    assert (await orch.turn(ctx())).persona_id is None
    orch = ClaudeOrchestrator(client=FakeClient(PanelTurn(
        action="curveball", curveball_kind="heckler", persona_id="nobody", line="x",
        reason="x")))
    got = await orch.turn(ctx(eligible_kinds=["heckler"]))
    assert got.action == "curveball" and got.persona_id in {"vc", "student", "professor"}


async def test_an_invented_quote_is_dropped_but_the_line_is_still_said():
    orch = ClaudeOrchestrator(client=FakeClient(QUESTION.model_copy(
        update={"cited_transcript_excerpt": "we are profitable already"})))
    got = await orch.turn(ctx())
    assert got.action == "speak" and got.cited_transcript_excerpt is None


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
        await orch.turn(ctx())


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
    got = await orch.turn(ctx())
    assert got.action == "wait"


async def test_truncated_and_invalid_replies_through_the_real_sdk_fall_back():
    orch = ClaudeOrchestrator(client=sdk_client(message('{"action": "quest', "max_tokens")))
    assert (await orch.turn(ctx())).action == "wait"
    bad = json.dumps({"score": 250, "evidence": "x", "observation": "o", "suggestion": "s"})
    orch = ClaudeOrchestrator(client=sdk_client(message(bad)))
    got = await orch.assess_recovery("slides_down", "l", [seg(1, "a b c d")], 100)
    assert got.score is None


async def test_api_error_through_the_real_sdk_never_breaks_persona_expansion():
    orch = ClaudeOrchestrator(client=sdk_client(
        {"type": "error", "error": {"type": "authentication_error", "message": "bad key"}}, 401))
    got = await orch.expand_persona("someone sceptical", 3)
    assert got.id == "custom_3" and got.custom is True
    assert (await orch.turn(ctx())).action == "wait"


async def test_valid_reply_through_the_real_sdk_parses_and_is_grounded():
    good = json.dumps({
        "action": "speak", "persona_id": "vc", "is_question": True,
        "line": "What backs “100,000 customers in six months”?", "reason": "unsupported",
        "cited_transcript_excerpt": "“100,000 customers in six months”", "mood": "pressing",
    })
    orch = ClaudeOrchestrator(client=sdk_client(message(good)))
    got = await orch.turn(ctx())
    assert got.action == "speak" and got.persona_id == "vc" and got.is_question
    assert got.cited_transcript_excerpt is not None


def test_verbatim_check_is_forgiving_about_quotes_case_and_segment_boundaries():
    segs = [seg(1, "So, the problem again"), seg(4, "is onboarding, honestly.")]
    assert ClaudeOrchestrator.verbatim("“the PROBLEM again is onboarding”", segs)
    assert not ClaudeOrchestrator.verbatim(" ", segs)
    assert not ClaudeOrchestrator.verbatim("is onboarding", segs)  # < 3 words
    assert not ClaudeOrchestrator.verbatim("the problem is churn", segs)
