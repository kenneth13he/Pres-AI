"""The curveball catalog, trigger rules, and recovery measurement.

Owner: Person C (P0-9, P1-2, P2-2). Spec: CLAUDE.md §6 and spec/curveballs.md.
Tests: backend/tests/test_curveballs.py.

The catalog below is content and is complete; the functions are skeletons.
Never invent a timing: a value that cannot be measured is None.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from spec.contracts import CurveballKind, Recovery, Resolution, SessionEvent, TranscriptSegment

Speaker = Literal["moderator", "persona", "ui"]


@dataclass(frozen=True)
class CurveballSpec:
    kind: CurveballKind
    speaker: Speaker
    ui_effect: str | None
    default_line: str
    min_elapsed_ms: int
    auto_resolve_ms: int | None = None
    needs_pause: bool = True  # False → fires mid-speech by design (distraction)
    never_on_slide_1: bool = False
    after_fraction_of_target: float = 0.0  # time_crunch: ≥ 50 % of the target
    sfx: str | None = None
    priority: str = "P2"


CATALOG: dict[CurveballKind, CurveballSpec] = {
    "time_crunch": CurveballSpec(
        "time_crunch", "moderator", "timer_red",
        "Sorry — we're running behind. You've got sixty seconds.",
        min_elapsed_ms=45_000, after_fraction_of_target=0.5, priority="P0",
    ),
    "slides_down": CurveballSpec(
        "slides_down", "moderator", "slides_black",
        "Sorry — the projector just disconnected. Can you keep going?",
        min_elapsed_ms=60_000, auto_resolve_ms=30_000, never_on_slide_1=True, priority="P0",
    ),
    "heckler": CurveballSpec(
        "heckler", "persona", "tile_flash",
        "Hang on — isn't this just a thin wrapper around something that already exists?",
        min_elapsed_ms=60_000, priority="P0",
    ),
    "latecomer": CurveballSpec(
        "latecomer", "persona", "tile_flash",
        "Sorry, I just walked in — can you give me the twenty-second version?",
        min_elapsed_ms=90_000, priority="P1",
    ),
    "bait": CurveballSpec(
        "bait", "persona", "tile_flash",
        "How does this hold up under the regulatory changes coming next year?",
        min_elapsed_ms=60_000, priority="P1",
    ),
    "distraction": CurveballSpec(
        "distraction", "ui", "sfx", "", min_elapsed_ms=45_000, needs_pause=False,
        sfx="phone_ring", priority="P1",
    ),
    "vip_arrives": CurveballSpec(
        "vip_arrives", "moderator", "tile_add",
        "The decision-maker just joined for two minutes. What do they need to hear?",
        min_elapsed_ms=90_000, priority="P1",
    ),
    "crosstalk": CurveballSpec(
        "crosstalk", "persona", "tile_flash", "", min_elapsed_ms=90_000, priority="P2",
    ),
    "fact_check": CurveballSpec(
        "fact_check", "persona", "tile_flash",
        "Your slide says forty percent — I've seen numbers closer to fifteen. Where is yours from?",
        min_elapsed_ms=60_000, priority="P2",
    ),
    "elevator": CurveballSpec(
        "elevator", "moderator", "slides_dim",
        "Pretend we're in an elevator. Thirty seconds, no slides.",
        min_elapsed_ms=60_000, auto_resolve_ms=30_000, priority="P2",
    ),
    "plain_language": CurveballSpec(
        "plain_language", "persona", "tile_flash",
        "Could you explain that to someone with no background in this at all?",
        min_elapsed_ms=60_000, priority="P2",
    ),
    "dead_room": CurveballSpec(
        "dead_room", "ui", "tiles_blank", "", min_elapsed_ms=60_000, auto_resolve_ms=45_000,
        priority="P2",
    ),
}

MVP_KINDS: list[CurveballKind] = ["time_crunch", "slides_down", "heckler"]


def eligible_kinds(
    *,
    allowed: list[CurveballKind],
    fired: list[CurveballKind],
    elapsed_ms: int,
    duration_target_s: int,
    slide_number: int,
    at_pause: bool,
) -> list[CurveballKind]:
    """Trigger rules from CLAUDE.md §6.2:
    - a kind never repeats within a session
    - elapsed ≥ spec.min_elapsed_ms, and ≥ after_fraction_of_target × target
    - never_on_slide_1 kinds skip slide 1
    - needs_pause kinds only at a pause; distraction fires mid-speech by design
    """
    # TODO(C)
    raise NotImplementedError


@dataclass
class CurveballRecord:
    curveball_id: str
    kind: CurveballKind
    at_ms: int
    line: str
    persona_id: str | None
    resolution: Resolution | None = None
    resolved_at_ms: int | None = None
    recovery: Recovery | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def spec(self) -> CurveballSpec:
        return CATALOG[self.kind]


class CurveballEngine:
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.records: list[CurveballRecord] = []
        self._counter = 0

    @property
    def active(self) -> CurveballRecord | None:
        # TODO(C): the most recent record without a resolution, else None.
        raise NotImplementedError

    @property
    def fired_kinds(self) -> list[CurveballKind]:
        return [r.kind for r in self.records]

    def trigger(
        self, kind: CurveballKind, now_ms: int, line: str | None, persona_id: str | None
    ) -> tuple[CurveballRecord, SessionEvent]:
        """Create the record and the `curveball_triggered` event (payload shape: CLAUDE.md §7:
        curveball_id, kind, speaker, persona_id, line, ui_effect, auto_resolve_after_ms,
        sfx_url). persona_id is kept only when spec.speaker == "persona"."""
        # TODO(C)
        raise NotImplementedError

    def due_for_auto_resolve(self, now_ms: int) -> CurveballRecord | None:
        # TODO(C): the active record if its spec.auto_resolve_ms has elapsed since at_ms.
        raise NotImplementedError

    def resolve(
        self,
        rec: CurveballRecord,
        now_ms: int,
        resolution: Resolution,
        transcript: list[TranscriptSegment],
    ) -> SessionEvent:
        """Mark resolved and return the `curveball_resolved` event. `skipped` → recovery None;
        otherwise recovery = measure_recovery(...). Rubric scores are added later by the
        orchestrator's recovery assessment (engine._resolve)."""
        # TODO(C)
        raise NotImplementedError


def measure_recovery(rec: CurveballRecord, transcript: list[TranscriptSegment]) -> Recovery:
    """Timing only: resume_after_ms = first presenter segment after rec.at_ms minus rec.at_ms.
    No speech after the event → resume_after_ms=None with a note saying so. Never 0 by default."""
    # TODO(C)
    raise NotImplementedError
