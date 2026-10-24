from backend.services.scheduler import Scheduler, SchedulerSnapshot
from spec.contracts import CurveballMode

ALLOWED = ["time_crunch", "slides_down", "heckler"]


def snap(**overrides) -> SchedulerSnapshot:
    base = dict(
        phase="presenting", elapsed_ms=60_000, questions_asked=0, curveballs_fired=0,
        fired_kinds=[], last_event_end_ms=None, last_presenter_speech_ms=57_000,
        slide_number=2, slide_changed_at_ms=None, duration_target_s=180, now_ms=60_000,
    )
    base.update(overrides)
    return SchedulerSnapshot(**base)  # type: ignore[arg-type]


def normal() -> Scheduler:
    return Scheduler("normal", "normal", CurveballMode(mode="surprise"), ALLOWED)  # type: ignore[arg-type]


def test_nothing_before_thirty_seconds():
    assert not normal().eligible(snap(elapsed_ms=20_000, now_ms=20_000)).anything


def test_question_eligible_after_thirty_seconds():
    assert normal().eligible(snap(elapsed_ms=35_000, now_ms=35_000)).question


def test_only_in_presenting_phase():
    for phase in ("answering", "curveball", "recovering", "paused", "qna"):
        assert not normal().eligible(snap(phase=phase)).anything


def test_cooldown_blocks_everything():
    e = normal().eligible(snap(last_event_end_ms=40_000, now_ms=60_000, elapsed_ms=60_000))
    assert not e.anything
    e = normal().eligible(snap(last_event_end_ms=10_000, now_ms=60_000, elapsed_ms=60_000))
    assert e.anything


def test_question_budget_caps():
    assert not normal().eligible(snap(questions_asked=2)).question


def test_friendly_has_no_curveballs():
    sch = Scheduler("friendly", "normal", CurveballMode(mode="surprise"), ALLOWED)  # type: ignore[arg-type]
    assert sch.eligible(snap(elapsed_ms=120_000, now_ms=120_000)).curveball_kinds == []


def test_curveball_kinds_follow_rules():
    kinds = normal().eligible(snap(elapsed_ms=60_000, now_ms=60_000)).curveball_kinds
    assert "slides_down" in kinds and "heckler" in kinds
    assert "time_crunch" not in kinds  # needs >= 50 % of a 180 s target
    kinds = normal().eligible(snap(elapsed_ms=100_000, now_ms=100_000)).curveball_kinds
    assert "time_crunch" in kinds


def test_slides_down_never_on_slide_one():
    kinds = normal().eligible(snap(slide_number=1)).curveball_kinds
    assert "slides_down" not in kinds


def test_choose_mode_restricts_kinds():
    sch = Scheduler("brutal", "often", CurveballMode(mode="choose", kinds=["heckler"]), ALLOWED)  # type: ignore[arg-type]
    assert sch.eligible(snap(elapsed_ms=100_000, now_ms=100_000)).curveball_kinds == ["heckler"]


def test_off_mode_disables_curveballs():
    sch = Scheduler("brutal", "often", CurveballMode(mode="off"), ALLOWED)  # type: ignore[arg-type]
    assert sch.eligible(snap(elapsed_ms=100_000, now_ms=100_000)).curveball_kinds == []
