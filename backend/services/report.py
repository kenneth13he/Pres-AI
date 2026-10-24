"""Build the report card from the session's own record (CLAUDE.md §10).

Owner: Person C (P0-12, P1-4).
Test: test_e2e_mock.py::test_slides_down_then_resume_records_recovery.

Why: every line is a verbatim quote or a measured number; anything unmeasured is None
with a caveat in `metric_caveats`, never a made-up value.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from spec.contracts import Report

if TYPE_CHECKING:
    from ..engine import Session

FILLERS = re.compile(r"\b(um+|uh+|erm|like|you know|basically|actually|literally)\b", re.I)


def build_report(session: Session) -> Report:
    """
    dimensions: clarity/evidence/structure/question_handling → None until the rubric pass
                (P0-12) runs; recovery → mean of curveball recovery scores, None if no curveball.
    metrics:    filler_words (regex over presenter segments, with caveat), words_per_minute
                (only if every segment has end_ms, else None + caveat), unanswered_questions,
                curveballs_faced, skipped.
    curveballs: one CurveballReport per record, recovery as recorded.
    key_moments: from events — question_queued, curveball_triggered, curveball_resolved
                 (with "resumed after X s" when measured).
    improvements: one per question that cited an excerpt (observation, evidence quote, suggestion).
    persona_feedback: one line per persona.
    """
    # TODO(C)
    raise NotImplementedError
