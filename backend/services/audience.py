"""The audience brain: one call decides what the panel does next (CLAUDE.md §9).

Owner: Person C. Tests: test_e2e_mock.py, test_claude_orchestrator.py.

Why: a real panel is one conversation, not separate question / follow-up / small-talk
systems. Every time the presenter finishes a sentence (or goes quiet) the brain sees the
whole conversation and returns one `PanelTurn`: wait, or one panelist says one thing.
`MockOrchestrator` is deterministic (tests, offline work); `ClaudeOrchestrator` is real.
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
    PanelTurn,
    Persona,
    RecoveryAssessment,
    TranscriptSegment,
)

from .curveballs import CATALOG

T = TypeVar("T")


Trigger = Literal["joined", "spoke", "silence", "qna"]


@dataclass
class Line:
    speaker: str  # "presenter" or a persona id / "moderator"
    text: str
    at_ms: int


@dataclass
class OrchestratorContext:
    preset_id: str
    difficulty: str
    personas: list[Persona]
    slide_number: int
    slide_text: str
    conversation: list[Line]  # presenter and panel, oldest first
    trigger: Trigger = "spoke"
    elapsed_s: int = 0
    seconds_since_panel_spoke: int | None = None
    open_question: Line | None = None  # a panel question the presenter is answering
    follow_ups_used: int = 0
    questions_asked: int = 0
    question_budget: int = 2
    eligible_kinds: list[CurveballKind] = field(default_factory=list)
    curveball_budget_remaining: int = 0
    qna_left: int = 0


class Orchestrator(Protocol):
    async def turn(self, ctx: OrchestratorContext) -> PanelTurn: ...
    async def assess_recovery(
        self, kind: CurveballKind, line: str, after: list[TranscriptSegment],
        resume_after_ms: int | None,
    ) -> RecoveryAssessment: ...
    async def expand_persona(self, description: str, index: int) -> Persona: ...


WAIT = PanelTurn(action="wait", reason="nothing to say")


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

    async def turn(self, ctx: OrchestratorContext) -> PanelTurn:
        ids = [p.id for p in ctx.personas]
        last = next((ln for ln in reversed(ctx.conversation) if ln.speaker == "presenter"), None)
        if ctx.trigger == "joined":
            return PanelTurn(action="speak", persona_id=ids[0], mood="warm", reason="greeting",
                             line="Hi, we can see and hear you. Whenever you're ready.")
        if ctx.trigger == "qna":
            segs = [TranscriptSegment(start_ms=ln.at_ms, text=ln.text)
                    for ln in ctx.conversation if ln.speaker == "presenter"]
            claim = find_claim(segs, set())
            return PanelTurn(action="speak", persona_id=ids[-1], is_question=True,
                             reason="closing question", cited_transcript_excerpt=claim,
                             line="Before we wrap up: what's the one number you'd stake this on?")
        if last is None:
            return WAIT
        if last.text.rstrip().endswith("?"):
            return PanelTurn(action="speak", persona_id=ids[0], reason="asked directly",
                             line="Honestly, I'd rather hear your take first.")
        if ctx.open_question is not None:
            if ctx.follow_ups_used == 0 and len(last.text.split()) < SUBSTANTIVE_WORDS:
                return PanelTurn(action="speak", persona_id=ctx.open_question.speaker,
                                 is_question=True, mood="pressing", reason="thin answer",
                                 line="Can you put a number on that?")
            return WAIT
        quiet_long_enough = (ctx.seconds_since_panel_spoke is None
                             or ctx.seconds_since_panel_spoke >= 25)
        if quiet_long_enough and ctx.questions_asked < ctx.question_budget:
            claim = find_claim([TranscriptSegment(start_ms=last.at_ms, text=last.text)], set())
            if claim:
                persona = max(ctx.personas, key=lambda p: p.skepticism)
                return PanelTurn(
                    action="speak", persona_id=persona.id, is_question=True, mood="pressing",
                    line=f'You said "{claim[:70].rstrip(".")}" — what evidence supports that?',
                    reason="unsupported claim", cited_transcript_excerpt=claim)
        if quiet_long_enough and ctx.eligible_kinds:
            kind = ctx.eligible_kinds[0]
            spec = CATALOG[kind]
            players = [p for p in ctx.personas if kind in p.plays] or ctx.personas
            return PanelTurn(action="curveball", curveball_kind=kind, reason="curveball due",
                             persona_id=players[0].id if spec.speaker == "persona" else None,
                             line=spec.default_line or None)
        return WAIT

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

TURN_PROMPT = """You run a panel of two or three fictional people on a live video call, listening
to someone rehearse a presentation. Each time the presenter finishes a sentence, or goes quiet,
you decide what the panel does next, the way real people on a call would.

Choose exactly one action:
- "wait": nobody speaks. Usually right while the presenter is mid-flow and not talking to you;
  a real audience mostly listens.
- "speak": one panelist says one thing, one or two short spoken sentences.
- "curveball": only a kind from the eligible list, delivered by a fitting panelist (persona_id
  null for moderator kinds), grounded in what was actually said.

When to speak:
- The presenter talks to the panel (greets you, asks if you can hear them, asks a question,
  invites questions, asks what you think, small talk): someone always answers, like a person
  would, and nudges back to the pitch when it fits.
- The presenter has just answered an open panel question: the asker reacts as that person
  really would. A follow-up if the answer dodged it (at most one per question), a brief
  genuine reaction, or "wait" to let them carry on.
- The presenter makes a strong unsupported claim, uses confusing jargon or skips the evidence,
  and the panel has been quiet a while: interrupt with one sharp question of at most 20 words
  that quotes or paraphrases what they said. Set is_question and copy the quoted words
  verbatim into cited_transcript_excerpt.
- "joined": the presenter just joined the call; one panelist greets them briefly.
- "qna": the talk is over; ask the one question the talk left most open (is_question).
- Pacing: unless the presenter addressed you, don't interrupt more than about every 25
  seconds, and stay within the question budget unless they invite questions.

Who speaks: whoever this moment fits best given their role and focus — the student when
something is confusing, the professor on method and evidence, the VC on money and market.
Share the talking: favour someone who hasn't spoken lately; one person must not answer
everything. Small talk can come from anyone.

Voice: each panelist stays in character (role, focus, skepticism, style). Natural spoken
English with contractions; no lists, markdown or stage directions; no stock filler such as
"great question", "thanks, go on" or "fair enough". Never repeat what the panel already said.
Challenge ideas, never the person. Never invent facts about the presenter's company.
Set mood to how the line should sound. persona_id must be one of the listed ids exactly."""

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
    latency is controlled with output_config.effort: "low" for the live turn, "high" for
    assess_recovery. JSON comes back through structured outputs
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
        # Live-measured 23 Oct: a low-effort call 2.1–2.6 s; assess_recovery 6.4 s (high).
        self.timeout_s = float(os.environ.get("ORCHESTRATOR_TIMEOUT_S", "12"))
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
        names = {p.id: p.name for p in ctx.personas}
        personas = "\n".join(
            f"- {p.id} ({p.name}): {p.role}; focus: {', '.join(p.focus)}; "
            f"skepticism {p.skepticism:.2f}" + (f"; style {p.style_hint}" if p.style_hint else "")
            + (f"; may voice: {', '.join(p.plays)}" if p.plays else "")
            for p in ctx.personas
        )
        convo = "\n".join(
            f"[{ln.at_ms / 1000:.0f}s] "
            f"{'PRESENTER' if ln.speaker == 'presenter' else names.get(ln.speaker, ln.speaker)}"
            f": {ln.text}" for ln in ctx.conversation) or "(nothing yet)"
        since = ("never" if ctx.seconds_since_panel_spoke is None
                 else f"{ctx.seconds_since_panel_spoke}s ago")
        open_q = (f"{names.get(ctx.open_question.speaker, ctx.open_question.speaker)} asked "
                  f"{ctx.open_question.text!r} (follow-ups used: {ctx.follow_ups_used} of 1)"
                  if ctx.open_question else "(none)")
        return (
            f"preset: {ctx.preset_id}; difficulty: {ctx.difficulty}\n"
            f"panel (fictional):\n{personas}\n\n"
            f"slide {ctx.slide_number}: {ctx.slide_text[:1200] or '(no deck)'}\n\n"
            f"conversation so far:\n{convo}\n\n"
            f"trigger: {ctx.trigger}"
            + (" (the presenter has gone quiet)" if ctx.trigger == "silence" else "") + "\n"
            f"talk time: {ctx.elapsed_s}s; panel last spoke: {since}\n"
            f"open question: {open_q}\n"
            f"questions asked: {ctx.questions_asked} of a budget of {ctx.question_budget}\n"
            f"eligible curveballs now: {', '.join(ctx.eligible_kinds) or '(none)'} "
            f"(budget left {ctx.curveball_budget_remaining})"
            + (f"\nclosing Q&A questions left: {ctx.qna_left}" if ctx.trigger == "qna" else "")
        )

    async def turn(self, ctx: OrchestratorContext) -> PanelTurn:
        out = await self._parse(TURN_PROMPT, self.format_context(ctx), PanelTurn, "low")
        if out is None or out.action == "wait" or not (out.line or "").strip():
            return WAIT
        ids = {p.id for p in ctx.personas}
        if out.action == "curveball":
            if out.curveball_kind not in ctx.eligible_kinds:
                return WAIT
            if CATALOG[out.curveball_kind].speaker != "persona":
                out.persona_id = None
            elif out.persona_id not in ids:
                players = [p for p in ctx.personas if out.curveball_kind in p.plays]
                out.persona_id = (players or ctx.personas)[0].id
            return out
        if out.persona_id not in ids:
            return WAIT
        presenter = [TranscriptSegment(start_ms=ln.at_ms, text=ln.text)
                     for ln in ctx.conversation if ln.speaker == "presenter"]
        if not self.verbatim(out.cited_transcript_excerpt, presenter):
            out.cited_transcript_excerpt = None  # a quote must be the presenter's own words
        return out

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
