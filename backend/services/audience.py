"""The audience brain: one orchestrator, three prompts (CLAUDE.md §9).

Owner: Person C (P0-5, P0-6, P0-3b custom personas). Tests: test_e2e_mock.py.

Why: one decision-maker, never agents racing to speak. `MockOrchestrator` must be
deterministic (tests, offline frontend work); `ClaudeOrchestrator` is the real one.
The prompts and the Claude call shape are settled; the bodies are skeletons.
"""

from __future__ import annotations

import asyncio
import os
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, TypeVar

import anthropic
from pydantic import ValidationError

from spec.contracts import (
    CurveballKind,
    FollowUpVerdict,
    OrchestratorDecision,
    Persona,
    RecoveryAssessment,
    TranscriptSegment,
)

from .curveballs import CATALOG

T = TypeVar("T")


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


# A sentence that makes a checkable claim: a quantity (digits, %, million…) or a strong
# absolute about the product/market. Greetings and ordinals ("first", "only") don't count.
SENTENCE_RE = re.compile(r"[^.!?]+[.!?]?")
CLAIM_RE = re.compile(
    r"\b(\d[\d,.]*\s*(%|percent|million|thousand|k|x)?|customers|users|revenue|churn|"
    r"nobody|always|never|best|fastest|cheapest|biggest)\b",
    re.IGNORECASE,
)
MIN_CLAIM_WORDS = 4
SUBSTANTIVE_WORDS = 12  # an answer this long is taken as having given the detail


def find_claim(segments: list[TranscriptSegment], already_cited: set[str]) -> str | None:
    """The most recent presenter sentence that states a checkable claim, verbatim, that has
    not been cited by an earlier question."""
    for seg in reversed(segments):
        if seg.speaker != "presenter":
            continue
        for m in reversed(list(SENTENCE_RE.finditer(seg.text))):
            sentence = m.group(0).strip()
            if len(sentence.split()) < MIN_CLAIM_WORDS or not CLAIM_RE.search(sentence):
                continue
            if sentence in already_cited:
                continue
            return sentence
    return None


class MockOrchestrator:
    """Deterministic stand-in: grounds a question in a detected claim, asks one follow-up
    when the answer is thin, scores recovery from timing. No network."""

    async def decide(self, ctx: OrchestratorContext) -> OrchestratorDecision:
        if ctx.question_allowed:
            cited: set[str] = {str(q["cited"]) for q in ctx.prior_qa if q.get("cited")}
            claim = find_claim(ctx.recent_transcript, cited)
            if claim:
                # The most skeptical persona who has asked the least, so the room shares the work.
                asked = {p.id: 0 for p in ctx.personas}
                for q in ctx.prior_qa:
                    asked[q.get("persona_id", "")] = asked.get(q.get("persona_id", ""), 0) + 1
                persona = max(ctx.personas, key=lambda p: (-asked[p.id], p.skepticism))
                return OrchestratorDecision(
                    action="question",
                    persona_id=persona.id,
                    line=f'You said "{claim[:70].rstrip(".")}" — what evidence supports that?',
                    reason="unsupported claim in transcript",
                    cited_transcript_excerpt=claim,
                    slide_number=ctx.slide_number,
                )
        if ctx.eligible_kinds:
            kind = ctx.eligible_kinds[0]
            spec = CATALOG[kind]
            persona_id = None
            if spec.speaker == "persona":
                players = [p for p in ctx.personas if kind in p.plays] or ctx.personas
                persona_id = players[0].id
            return OrchestratorDecision(
                action="curveball",
                curveball_kind=kind,
                persona_id=persona_id,
                line=spec.default_line or None,
                reason="curveball budget available and kind eligible",
                slide_number=ctx.slide_number,
            )
        return OrchestratorDecision(action="none", reason="nothing worth interrupting for")

    async def follow_up(
        self, question: str, answer: str, persona: Persona, used: int
    ) -> FollowUpVerdict:
        if used >= 1 or len(answer.split()) >= SUBSTANTIVE_WORDS:
            return FollowUpVerdict(verdict="satisfied", line="Fair enough, go on.")
        # Never the same wording twice (§9): vary by persona and by the question asked.
        variants = [
            "That's the plan — what early data do you have for it?",
            f"{persona.name} again — can you put a number on that?",
            "Understood. What have you actually measured so far?",
            "And the evidence for that is…?",
        ]
        line = variants[sum(map(ord, question)) % len(variants)]
        return FollowUpVerdict(verdict="follow_up", line=line,
                               missing_detail="evidence for the stated approach")

    async def assess_recovery(
        self, kind: CurveballKind, line: str, after: list[TranscriptSegment],
        resume_after_ms: int | None,
    ) -> RecoveryAssessment:
        if not after:
            # Unmeasured is null, never 0 (§6, §10).
            return RecoveryAssessment(
                score=None, evidence=None,
                observation="No presenter speech was recorded after the event; not assessed.",
                suggestion="Keep a three-point outline in your head so you can restart anywhere.",
            )
        if kind == "time_crunch":
            # Judged on the close, not a resume gap: did they keep talking and stop in time?
            score, observation = 70, "Kept going under the countdown."
        elif resume_after_ms is None:
            score, observation = 50, "Resumed; timing could not be measured."
        elif resume_after_ms < 5_000:
            score, observation = 85, "Resumed promptly and kept the thread."
        else:
            score, observation = 60, "Slow to resume."
        return RecoveryAssessment(
            score=score, evidence=after[0].text, observation=observation,
            suggestion="Name what happened in one sentence, then continue from your outline.",
        )

    async def expand_persona(self, description: str, index: int) -> Persona:
        words = description.strip().split()
        return Persona(
            id=f"custom_{index}",
            name=" ".join(words[:3]).title() or f"Custom {index}",
            role=description.strip()[:60] or "Custom audience member",
            focus=["what this person cares about", "clarity"],
            skepticism=0.6,
            style_hint="neutral",
            plays=["heckler", "bait"],
            custom=True,
        )


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
covered. Personas are fictional. Be brief.
Output rules: persona_id must be one of the listed persona ids exactly; cited_transcript_excerpt
must be copied verbatim from the transcript (or null); slide_number is the slide shown now."""

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
    (`client.messages.parse(..., output_format=<pydantic model>)`), never prefill. The system
    prompts are byte-identical across calls so the prefix caches; everything that varies goes
    in the user turn. A `stop_reason == "refusal"` returns None and the caller falls back to
    a safe default — the session never breaks on the brain (§8).

    `client` is injectable so the formatting and fallbacks are tested without a key.
    """

    def __init__(self, client: Any | None = None, model: str | None = None) -> None:
        if client is None:
            # One retry only: the 8 s window below is the real budget, not the SDK's 600 s.
            client = anthropic.AsyncAnthropic(max_retries=1)
        self.client = client
        self.model = model or os.environ.get("ORCHESTRATOR_MODEL", "claude-opus-5-5")
        # Live-measured 23 Oct: decide 2.2–2.6 s, follow_up 2.1 s (effort low);
        # assess_recovery 6.4 s (effort high) — hence two budgets.
        self.timeout_s = float(os.environ.get("ORCHESTRATOR_TIMEOUT_S", "8"))
        self.slow_timeout_s = float(os.environ.get("ORCHESTRATOR_SLOW_TIMEOUT_S", "15"))

    async def _parse(self, system: str, user: str, schema: type[T],
                     effort: Literal["low", "high"], max_tokens: int = 2048,
                     timeout_s: float | None = None) -> T | None:
        """None means "no usable answer": a refusal, a truncated or schema-violating reply,
        or an API error. The SDK validates the JSON before we see stop_reason, so a refusal
        that carries text surfaces as ValidationError — caught here. A timeout propagates:
        the engine turns it into an `error` event."""
        try:
            response = await asyncio.wait_for(
                self.client.messages.parse(
                    model=self.model,
                    max_tokens=max_tokens,
                    system=system,
                    output_config={"effort": effort},
                    messages=[{"role": "user", "content": user}],
                    output_format=schema,
                ),
                timeout=timeout_s or self.timeout_s,
            )
        except (ValidationError, anthropic.APIError):
            return None
        if response.stop_reason in ("refusal", "max_tokens"):
            return None
        return response.parsed_output

    @staticmethod
    def _norm(text: str) -> str:
        text = unicodedata.normalize("NFKC", text).casefold()
        text = re.sub(r"[\"'\u2018\u2019\u201c\u201d\u2026]", " ", text)
        return " ".join(text.split())

    @classmethod
    def verbatim(cls, quote: str | None, segments: list[TranscriptSegment]) -> bool:
        """A quote counts only if it is at least three words and appears (quotes, case and
        whitespace aside) in the given transcript (§13 Grounding)."""
        if not quote:
            return False
        q = cls._norm(quote)
        if len(q.split()) < 3:
            return False
        return q in cls._norm(" ".join(s.text for s in segments))

    # ---- formatting (pure, tested) --------------------------------------------------

    @staticmethod
    def format_transcript(segments: list[TranscriptSegment]) -> str:
        if not segments:
            return "(silence)"
        return "\n".join(f"[{s.start_ms / 1000:.1f}s] {s.text}" for s in segments)

    @staticmethod
    def format_context(ctx: OrchestratorContext) -> str:
        personas = "\n".join(
            f"- {p.id}: {p.role}; focus: {', '.join(p.focus)}; skepticism {p.skepticism:.2f}"
            + (f"; style {p.style_hint}" if p.style_hint else "")
            + (f"; may voice: {', '.join(p.plays)}" if p.plays else "")
            for p in ctx.personas
        )
        prior = "\n".join(
            f"- {q['persona_id']} asked: {q['q']!r}"
            + (f" (citing {q['cited']!r})" if q.get("cited") else "")
            + (f" → answered: {q['a']!r}" if q.get("a") else " → not answered")
            for q in ctx.prior_qa
        ) or "(none)"
        allowed = []
        if ctx.question_allowed:
            allowed.append("question")
        if ctx.eligible_kinds:
            allowed.append("curveball")
        allowed.append("none")
        return (
            f"preset: {ctx.preset_id}\ndifficulty: {ctx.difficulty}\n"
            f"personas (fictional):\n{personas}\n\n"
            f"slide {ctx.slide_number} text:\n{ctx.slide_text[:1500] or '(no deck)'}\n\n"
            f"recent presenter transcript (last ~30 s):\n"
            f"{ClaudeOrchestrator.format_transcript(ctx.recent_transcript)}\n\n"
            f"prior questions this session:\n{prior}\n\n"
            f"actions allowed right now: {', '.join(allowed)}\n"
            f"eligible curveball kinds: {', '.join(ctx.eligible_kinds) or '(none)'}\n"
            f"curveball budget remaining: {ctx.curveball_budget_remaining}\n"
            f"seconds since the last audience event: "
            f"{ctx.seconds_since_last_event if ctx.seconds_since_last_event is not None else 'n/a'}"
        )

    # ---- the three prompts + persona expansion ----------------------------------------

    async def decide(self, ctx: OrchestratorContext) -> OrchestratorDecision:
        none = OrchestratorDecision(action="none", reason="no decision")
        if not ctx.question_allowed and not ctx.eligible_kinds:
            return none
        out = await self._parse(SYSTEM_PROMPT, self.format_context(ctx),
                                OrchestratorDecision, "low")
        if out is None:
            return OrchestratorDecision(action="none", reason="model declined; skipped")
        # Enforce what the engine will check anyway, so a bad answer is a "none", not an error.
        ids = {p.id for p in ctx.personas}
        if out.action == "question":
            if not ctx.question_allowed or out.persona_id not in ids or not out.line:
                return none
            if not self.verbatim(out.cited_transcript_excerpt, ctx.recent_transcript):
                return OrchestratorDecision(action="none",
                                            reason="question had no verbatim excerpt; skipped")
            out.slide_number = ctx.slide_number
        elif out.action == "curveball":
            if out.curveball_kind not in ctx.eligible_kinds:
                return none
            if out.persona_id is not None and out.persona_id not in ids:
                out.persona_id = None  # the engine assigns a roster persona
            out.slide_number = ctx.slide_number
        return out

    async def follow_up(
        self, question: str, answer: str, persona: Persona, used: int
    ) -> FollowUpVerdict:
        if used >= 1:
            return FollowUpVerdict(verdict="satisfied", line="Thanks — go on.")
        user = (f"persona: {persona.role} ({persona.name}); style: {persona.style_hint}\n"
                f"question: {question}\nanswer: {answer}")
        out = await self._parse(FOLLOW_UP_PROMPT, user, FollowUpVerdict, "low")
        return out or FollowUpVerdict(verdict="satisfied", line="Fair enough, go on.")

    async def assess_recovery(
        self, kind: CurveballKind, line: str, after: list[TranscriptSegment],
        resume_after_ms: int | None,
    ) -> RecoveryAssessment:
        if not after:
            return RecoveryAssessment(
                score=None, evidence=None,
                observation="No presenter speech was recorded after the event; not assessed.",
                suggestion="Keep a three-point outline in your head so you can restart anywhere.",
            )
        timing = "null" if resume_after_ms is None else f"{resume_after_ms / 1000:.1f} s"
        user = (f"kind: {kind}\nline delivered: {line}\n"
                f"measured time until the presenter resumed: {timing}\n"
                f"next 60 s of presenter transcript:\n{self.format_transcript(after)}")
        out = await self._parse(RECOVERY_PROMPT, user, RecoveryAssessment, "high",
                                max_tokens=8192, timeout_s=self.slow_timeout_s)
        if out is None:
            return RecoveryAssessment(
                score=None, evidence=None,
                observation="The model declined to assess this recovery.",
                suggestion="Name what happened in one sentence, then continue from your outline.",
            )
        if not self.verbatim(out.evidence, after):
            out.evidence = after[0].text  # evidence must be verbatim (§10)
        return out

    async def expand_persona(self, description: str, index: int) -> Persona:
        """Never raises: session creation must not fail on the brain (§8)."""
        try:
            out = await self._parse(PERSONA_PROMPT, f"description: {description.strip()}",
                                    Persona, "low")
        except Exception:
            out = None
        if out is None:
            return await MockOrchestrator().expand_persona(description, index)
        return out.model_copy(update={
            "id": f"custom_{index}", "custom": True,
            "voice_id": None, "avatar_url": None,  # Person B maps voices; the model never does
            "skepticism": min(1.0, max(0.0, out.skepticism)),
            # Only kinds a persona actually voices; the live model also listed moderator kinds.
            "plays": [k for k in out.plays if CATALOG[k].speaker == "persona"],
        })
