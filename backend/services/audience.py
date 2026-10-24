"""The audience brain: one orchestrator, three prompts (CLAUDE.md §9).

Owner: Person C (P0-5, P0-6, P0-3b custom personas). Tests: test_e2e_mock.py.

Why: one decision-maker, never agents racing to speak. `MockOrchestrator` must be
deterministic (tests, offline frontend work); `ClaudeOrchestrator` is the real one.
The prompts and the Claude call shape are settled; the bodies are skeletons.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Literal, Protocol

from spec.contracts import (
    CurveballKind,
    FollowUpVerdict,
    OrchestratorDecision,
    Persona,
    RecoveryAssessment,
    TranscriptSegment,
)


@dataclass
class OrchestratorContext:
    preset_id: str
    difficulty: str
    personas: list[Persona]
    slide_number: int
    slide_text: str
    recent_transcript: list[TranscriptSegment]
    prior_qa: list[dict] = field(default_factory=list)
    question_allowed: bool = False
    eligible_kinds: list[CurveballKind] = field(default_factory=list)
    curveball_budget_remaining: int = 0
    seconds_since_last_event: int | None = None


class Orchestrator(Protocol):
    async def decide(self, ctx: OrchestratorContext) -> OrchestratorDecision: ...
    async def follow_up(
        self, question: str, answer: str, persona: Persona, used: int
    ) -> FollowUpVerdict: ...
    async def assess_recovery(
        self, kind: CurveballKind, line: str, after: list[TranscriptSegment],
        resume_after_ms: int | None,
    ) -> RecoveryAssessment: ...
    async def expand_persona(self, description: str, index: int) -> Persona: ...


# ---------------------------------------------------------------------------------
# Mock: deterministic, no network. The e2e tests define its behaviour.
# ---------------------------------------------------------------------------------


class MockOrchestrator:
    async def decide(self, ctx: OrchestratorContext) -> OrchestratorDecision:
        # TODO(C): if question_allowed and the recent transcript contains a claim (a number,
        # "%", "customers", "users", "always", "never"...), return a question from the most
        # skeptical persona that quotes the claim in cited_transcript_excerpt. Else if
        # eligible_kinds, return a curveball of the first kind (persona = one whose `plays`
        # includes it). Else "none".
        return OrchestratorDecision(action="none", reason="not implemented")

    async def follow_up(
        self, question: str, answer: str, persona: Persona, used: int
    ) -> FollowUpVerdict:
        # TODO(C): used ≥ 1 or a substantive answer → satisfied ("Fair enough, go on.");
        # a thin answer → one follow-up asking for the missing detail.
        return FollowUpVerdict(verdict="satisfied", line="Go on.")

    async def assess_recovery(
        self, kind: CurveballKind, line: str, after: list[TranscriptSegment],
        resume_after_ms: int | None,
    ) -> RecoveryAssessment:
        # TODO(C): deterministic rubric stand-in: quote after[0].text as evidence; score from
        # resume_after_ms; 0 with a clear observation when `after` is empty.
        raise NotImplementedError

    async def expand_persona(self, description: str, index: int) -> Persona:
        # TODO(C): a Persona with id f"custom_{index}", custom=True, role=description.
        raise NotImplementedError


# ---------------------------------------------------------------------------------
# Claude: the real orchestrator. Structured outputs, adaptive thinking, low effort live.
# ---------------------------------------------------------------------------------

SYSTEM_PROMPT = """You are the moderator of a simulated presentation audience.
You decide ONE action for the room: "none", a "question" from the most relevant persona
(one short, specific, natural question of at most 20 words that quotes or paraphrases
something the presenter actually said), or a "curveball" from the eligible kinds only,
with a line for the assigned speaker grounded in the current talk.
Rules: prefer unsupported claims, confusing terms and missing evidence. Never invent facts
about the slides or the presenter's company. No duplicates. Heckler and fact_check lines
challenge the idea, never the person. Bait is plausible, adjacent, and beyond what was
covered. Personas are fictional. Be brief."""

FOLLOW_UP_PROMPT = """Does the presenter's answer address the actual question? If yes,
acknowledge in at most 6 words (for example "Fair enough, go on.") and hand back. If no,
ask one concise follow-up targeting the missing detail. Never rude; never the same wording
twice."""

RECOVERY_PROMPT = """Score the presenter's recovery from a curveball, 0-100, on the rubric
for its kind: time_crunch - core message and a clear close within the limit; slides_down -
kept structure and resumed promptly without slides; heckler - addressed the challenge
directly, composed wording, returned to the talk; latecomer - recap under 30 s covering
problem, solution, ask; bait - admitted uncertainty or scoped the answer rather than
inventing specifics; distraction - resumed the thought without restarting; vip_arrives -
stated the ask and the why-now within 30 s. Quote the transcript as evidence. If timing is
null, say so in the observation."""

PERSONA_PROMPT = """Turn a free-text description of an audience member into a fictional
persona for a presentation rehearsal. Keep the name generic (never a real person), give two
to four focus areas, a skepticism from 0 to 1, a one-word style_hint (impatient, confused,
thoughtful or neutral), and which curveball kinds this persona could voice."""


class ClaudeOrchestrator:
    """Official `anthropic` SDK only (no raw HTTP, no OpenAI-compatible shim).

    Model `claude-opus-5-5`. Thinking stays adaptive (it cannot be disabled on this model);
    latency is controlled with output_config.effort: "low" for decide/follow_up (they run in a
    ~4 s window), "high" for assess_recovery. JSON comes back through structured outputs
    (`client.messages.parse(..., output_format=<pydantic model>)`), never prefill. Keep the
    system prompt byte-identical across calls so the prefix caches; everything that varies
    goes in the user turn. A `stop_reason == "refusal"` returns None and the caller skips.
    """

    def __init__(self) -> None:
        import anthropic

        self.client = anthropic.AsyncAnthropic()
        self.model = os.environ.get("ORCHESTRATOR_MODEL", "claude-opus-5-5")

    async def _parse(self, system: str, user: str, schema: type,
                     effort: Literal["low", "high"]):
        response = await self.client.messages.parse(
            model=self.model,
            max_tokens=2048,
            system=system,
            output_config={"effort": effort},
            messages=[{"role": "user", "content": user}],
            output_format=schema,
        )
        if response.stop_reason == "refusal":
            return None
        return response.parsed_output

    async def decide(self, ctx: OrchestratorContext) -> OrchestratorDecision:
        # TODO(C): format ctx into the user turn (personas, slide text ≤1500 chars, last ~30 s
        # of transcript with timestamps, prior Q&A, question_allowed, eligible kinds, budget,
        # seconds since last event) → self._parse(SYSTEM_PROMPT, user, OrchestratorDecision, "low")
        raise NotImplementedError

    async def follow_up(
        self, question: str, answer: str, persona: Persona, used: int
    ) -> FollowUpVerdict:
        # TODO(C): used ≥ 1 → satisfied without a call; else _parse(FOLLOW_UP_PROMPT, ..., "low")
        raise NotImplementedError

    async def assess_recovery(
        self, kind: CurveballKind, line: str, after: list[TranscriptSegment],
        resume_after_ms: int | None,
    ) -> RecoveryAssessment:
        # TODO(C): _parse(RECOVERY_PROMPT, ..., RecoveryAssessment, "high")
        raise NotImplementedError

    async def expand_persona(self, description: str, index: int) -> Persona:
        # TODO(C): _parse(PERSONA_PROMPT, ..., Persona, "low");
        #          set id=f"custom_{index}", custom=True
        raise NotImplementedError
