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

from . import curveballs

# (persona questions, curveballs) per session — CLAUDE.md §6.3
BUDGETS: dict[Difficulty, tuple[int, int]] = {
    "friendly": (2, 0),
    "normal": (2, 1),
    "brutal": (3, 2),
}
# Within the 30–45 s band CLAUDE.md §8 states; frequency moves the cooldown inside that band.
COOLDOWN_MS: dict[InterruptionFrequency, int] = {"rare": 45_000, "normal": 40_000, "often": 30_000}
FIRST_QUESTION_MS = 30_000
FIRST_CURVEBALL_MS = 45_000
PAUSE_SILENCE_MS = 1_500  # no presenter speech for this long counts as a natural pause
SLIDE_TRANSITION_MS = 1_500  # nothing fires while the slide is changing
SLIDE_CHANGE_PAUSE_MS = 6_000  # ...but the moment right after counts as a pause


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
        """Silent for PAUSE_SILENCE_MS, or just past a slide change (a slide change is a
        natural pause, which is how slides_down fires "on a slide change" per §6.2)."""
        if self.slide_changed_at_ms is not None:
            since_change = self.now_ms - self.slide_changed_at_ms
            if SLIDE_TRANSITION_MS <= since_change < SLIDE_CHANGE_PAUSE_MS:
                return True
        if self.last_presenter_speech_ms is None:
            return False
        return self.now_ms - self.last_presenter_speech_ms >= PAUSE_SILENCE_MS

    @property
    def in_slide_transition(self) -> bool:
        if self.slide_changed_at_ms is None:
            return False
        return self.now_ms - self.slide_changed_at_ms < SLIDE_TRANSITION_MS


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
        if not curveballs_enabled or curveball_mode.mode == "off":
            self.allowed_kinds: list[CurveballKind] = []
        elif curveball_mode.mode == "choose":
            self.allowed_kinds = list(dict.fromkeys(k for k in curveball_mode.kinds
                                                    if k in allowed_kinds))
        else:
            self.allowed_kinds = list(allowed_kinds)

    def eligible(self, s: SchedulerSnapshot) -> Eligibility:
        """Rules (CLAUDE.md §8, §6.2):
        - only in phase "presenting", never during a slide transition
        - nothing within cooldown_ms of last_event_end_ms
        - question: elapsed ≥ FIRST_QUESTION_MS and questions_asked < question_budget
        - curveballs: elapsed ≥ FIRST_CURVEBALL_MS, curveballs_fired < curveball_budget,
          kinds from curveballs.eligible_kinds(...)
        """
        if s.phase != "presenting" or s.in_slide_transition:
            return Eligibility()
        if s.last_event_end_ms is not None and s.now_ms - s.last_event_end_ms < self.cooldown_ms:
            return Eligibility()
        out = Eligibility()
        if s.elapsed_ms >= FIRST_QUESTION_MS and s.questions_asked < self.question_budget:
            out.question = True
        if s.elapsed_ms >= FIRST_CURVEBALL_MS and s.curveballs_fired < self.curveball_budget:
            out.curveball_kinds = curveballs.eligible_kinds(
                allowed=self.allowed_kinds,
                fired=s.fired_kinds,
                elapsed_ms=s.elapsed_ms,
                duration_target_s=s.duration_target_s,
                slide_number=s.slide_number,
                at_pause=s.at_pause,
            )
        return out
