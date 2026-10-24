"""Decides whether the room may do something right now: nothing, a question, or a curveball.

Owner: Person C (P0-8). Spec: CLAUDE.md §8 "Scheduler rules".
Tests: backend/tests/test_scheduler.py.

Why: exactly one audience event at a time, with cooldowns and caps, is what keeps the
room from feeling like a pile-on. The scheduler is a pure function of a snapshot so it is
deterministic and testable without audio.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from spec.contracts import CurveballKind, CurveballMode, Difficulty, InterruptionFrequency

# (persona questions, curveballs) per session — CLAUDE.md §6.3
BUDGETS: dict[Difficulty, tuple[int, int]] = {
    "friendly": (2, 0),
    "normal": (2, 1),
    "brutal": (3, 2),
}
COOLDOWN_MS: dict[InterruptionFrequency, int] = {"rare": 60_000, "normal": 40_000, "often": 25_000}
FIRST_QUESTION_MS = 30_000
FIRST_CURVEBALL_MS = 45_000
PAUSE_SILENCE_MS = 1_500  # no presenter speech for this long counts as a natural pause
SLIDE_TRANSITION_MS = 1_500


@dataclass
class SchedulerSnapshot:
    """Everything the scheduler is allowed to know about the session."""

    phase: str
    elapsed_ms: int
    questions_asked: int
    curveballs_fired: int
    fired_kinds: list[CurveballKind]
    last_event_end_ms: int | None
    last_presenter_speech_ms: int | None
    slide_number: int
    slide_changed_at_ms: int | None
    duration_target_s: int
    now_ms: int

    @property
    def at_pause(self) -> bool:
        # TODO(C): True when the presenter has been silent for PAUSE_SILENCE_MS.
        raise NotImplementedError

    @property
    def in_slide_transition(self) -> bool:
        # TODO(C): True for SLIDE_TRANSITION_MS after a slide change.
        raise NotImplementedError


@dataclass
class Eligibility:
    question: bool = False
    curveball_kinds: list[CurveballKind] = field(default_factory=list)

    @property
    def anything(self) -> bool:
        return self.question or bool(self.curveball_kinds)


class Scheduler:
    def __init__(
        self,
        difficulty: Difficulty,
        frequency: InterruptionFrequency,
        curveball_mode: CurveballMode,
        allowed_kinds: list[CurveballKind],
        curveballs_enabled: bool = True,
    ) -> None:
        self.question_budget, self.curveball_budget = BUDGETS[difficulty]
        self.cooldown_ms = COOLDOWN_MS[frequency]
        # TODO(C): resolve the allowed kinds from the mode:
        #   off / disabled → [] ; choose → intersection with allowed_kinds ;
        #   surprise → allowed_kinds
        self.allowed_kinds: list[CurveballKind] = []

    def eligible(self, s: SchedulerSnapshot) -> Eligibility:
        """Rules (CLAUDE.md §8, §6.2):
        - only in phase "presenting", never during a slide transition
        - nothing within cooldown_ms of last_event_end_ms
        - question: elapsed ≥ FIRST_QUESTION_MS and questions_asked < question_budget
        - curveballs: elapsed ≥ FIRST_CURVEBALL_MS, curveballs_fired < curveball_budget,
          kinds from curveballs.eligible_kinds(...)
        """
        # TODO(C)
        raise NotImplementedError
