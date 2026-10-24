"""Build the report card from the session's own record (CLAUDE.md §10).

Owner: Person C (P0-12, P1-4).
Test: test_e2e_mock.py::test_slides_down_then_resume_records_recovery, test_report.py.

Why: every line is a verbatim quote or a measured number; anything unmeasured is None
with a caveat in `metric_caveats`, never a made-up value.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from spec.contracts import (
    CurveballReport,
    Improvement,
    KeyMoment,
    PersonaFeedback,
    Report,
)

if TYPE_CHECKING:
    from ..engine import Session

FILLERS = re.compile(r"\b(um+|uh+|erm|like|you know|basically|actually|literally)\b", re.I)


def build_report(session: Session) -> Report:
    presenter = [s for s in session.transcript if s.speaker == "presenter"]
    caveats: list[str] = []

    filler_words: int | None = None
    wpm: int | None = None
    if presenter:
        filler_words = sum(len(FILLERS.findall(s.text)) for s in presenter)
        caveats.append("Filler count depends on recognition accuracy; treat as approximate.")
        if all(s.end_ms is not None for s in presenter):
            spoken_ms = sum(s.end_ms - s.start_ms for s in presenter if s.end_ms is not None)
            words = sum(len(s.text.split()) for s in presenter)
            wpm = round(words / (spoken_ms / 60_000)) if spoken_ms > 0 else None
        if wpm is None:
            caveats.append("Words per minute not measured: transcript segments lack end times.")
    else:
        caveats.append("No presenter transcript was captured; speech metrics are unavailable.")

    records = session.curveballs.records
    scored = [r.recovery.score for r in records if r.recovery and r.recovery.score is not None]
    recovery_dim = round(sum(scored) / len(scored)) if scored else None
    if not records:
        caveats.append("Recovery is null: no curveball fired in this session.")
    caveats.append("Content dimensions are scored by the orchestrator's rubric pass (P0-12); "
                   "null until it runs.")

    improvements = [
        Improvement(
            observation=f"{q['persona_id']} questioned a claim"
                        + (f" on slide {q['slide_number']}" if q.get("slide_number") else ""),
            evidence=q["cited_excerpt"],
            suggestion="Back the claim with a number and its source before you say it.",
        )
        for q in session.questions
        if q.get("cited_excerpt")
    ]
    # Skipped is never penalised (§2): a skipped or cut-off question is neither unanswered
    # nor scored; curveball pseudo-questions carry their own resolution.
    unanswered = sum(1 for q in session.questions
                     if q.get("answer") is None and not q.get("skipped")
                     and not q["curveball_id"])
    skipped = (sum(1 for q in session.questions if q.get("skipped") and not q["curveball_id"])
               + sum(1 for r in records if r.resolution == "skipped"))

    return Report(
        session_id=session.session_id,
        overall_score=None,
        dimensions={
            "clarity": None, "evidence": None, "structure": None,
            "question_handling": None, "recovery": recovery_dim,
        },
        metrics={
            "filler_words": filler_words,
            "words_per_minute": wpm,
            "unanswered_questions": unanswered,
            "curveballs_faced": len(records),
            "skipped": skipped,
        },
        metric_caveats=caveats,
        strengths=[],
        improvements=improvements,
        curveballs=[
            CurveballReport(kind=r.kind, at_ms=r.at_ms, resolution=r.resolution or "timed_out",
                            recovery=r.recovery)
            for r in records
        ],
        key_moments=_key_moments(session),
        persona_feedback=[
            PersonaFeedback(persona_id=p.id, score=None, comment=_persona_comment(p.id, session))
            for p in session.config.personas
        ],
    )


def _key_moments(session: Session) -> list[KeyMoment]:
    out: list[KeyMoment] = []
    for ev in session.events:
        p = ev.payload
        if ev.type == "question_queued" and not p.get("curveball_id"):
            out.append(KeyMoment(at_ms=ev.timestamp_ms, type="question",
                                 persona_id=p.get("persona_id"), summary=p.get("question", "")))
        elif ev.type == "curveball_triggered":
            out.append(KeyMoment(at_ms=ev.timestamp_ms, type="curveball", kind=p.get("kind"),
                                 persona_id=p.get("persona_id"),
                                 summary=p.get("line") or str(p.get("kind", ""))))
        elif ev.type == "curveball_resolved":
            recovery = p.get("recovery") or {}
            ms = recovery.get("resume_after_ms")
            if ms is not None:
                out.append(KeyMoment(at_ms=ev.timestamp_ms, type="curveball", kind=p.get("kind"),
                                     summary=f"resumed after {ms / 1000:.1f} s"))
    return out


def _persona_comment(persona_id: str, session: Session) -> str:
    asked = [q for q in session.questions
             if q["persona_id"] == persona_id and not q["follow_up_of"]]
    if not asked:
        return "Listened; had no question this time."
    q = asked[-1]
    if q.get("cut_off"):
        return "We ran out of time for my question — no penalty."
    if q.get("skipped"):
        return "You skipped my question — no penalty, but I'm still curious."
    if q.get("answer") is None and not q["curveball_id"]:
        return f"Never got an answer to: {q['question']}"
    return f"Asked about: {q['cited_excerpt'] or q['question']}"
