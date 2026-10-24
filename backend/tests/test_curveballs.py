from backend.services.curveballs import CATALOG, MVP_KINDS, CurveballEngine, eligible_kinds
from backend.tests.conftest import seg


def test_catalog_has_every_kind_and_the_mvp_three():
    assert len(CATALOG) == 12
    for kind in MVP_KINDS:
        assert CATALOG[kind].priority == "P0"


def test_eligible_kinds_respects_min_elapsed_and_no_repeat():
    kinds = eligible_kinds(allowed=["heckler", "latecomer"], fired=[], elapsed_ms=70_000,
                           duration_target_s=180, slide_number=2, at_pause=True)
    assert kinds == ["heckler"]  # latecomer needs 90 s
    kinds = eligible_kinds(allowed=["heckler"], fired=["heckler"], elapsed_ms=70_000,
                           duration_target_s=180, slide_number=2, at_pause=True)
    assert kinds == []


def test_distraction_fires_mid_speech_others_need_a_pause():
    kinds = eligible_kinds(allowed=["distraction", "heckler"], fired=[], elapsed_ms=70_000,
                           duration_target_s=180, slide_number=2, at_pause=False)
    assert kinds == ["distraction"]


def test_resolve_measures_resume_gap_from_transcript():
    eng = CurveballEngine("s")
    rec, ev = eng.trigger("slides_down", 125_000, None, None)
    assert ev.payload["ui_effect"] == "slides_black"
    assert ev.payload["auto_resolve_after_ms"] == 30_000
    transcript = [seg(100, "before the event"), seg(128.4, "So, the problem again is...")]
    done = eng.resolve(rec, 155_000, "auto_restored", transcript)
    assert done.payload["recovery"]["resume_after_ms"] == 3_400
    assert eng.active is None


def test_resolve_without_speech_is_null_not_zero():
    eng = CurveballEngine("s")
    rec, _ = eng.trigger("slides_down", 125_000, None, None)
    done = eng.resolve(rec, 155_000, "auto_restored", [seg(100, "before")])
    assert done.payload["recovery"]["resume_after_ms"] is None


def test_skipped_has_no_recovery():
    eng = CurveballEngine("s")
    rec, _ = eng.trigger("heckler", 70_000, "Isn't this just a wrapper?", "vc")
    done = eng.resolve(rec, 72_000, "skipped", [seg(75, "whatever")])
    assert done.payload["recovery"] is None


def test_auto_resolve_due():
    eng = CurveballEngine("s")
    rec, _ = eng.trigger("slides_down", 0, None, None)
    assert eng.due_for_auto_resolve(29_999) is None
    assert eng.due_for_auto_resolve(30_000) is rec
