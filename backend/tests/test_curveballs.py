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


def test_trigger_keeps_persona_only_for_persona_speakers():
    eng = CurveballEngine("s")
    rec, ev = eng.trigger("slides_down", 60_000, None, "vc")
    assert rec.persona_id is None and ev.payload["speaker"] == "moderator"
    rec2, ev2 = eng.trigger("heckler", 61_000, None, "vc")
    assert rec2.persona_id == "vc" and ev2.payload["speaker"] == "persona"
    assert ev2.payload["line"] == CATALOG["heckler"].default_line  # default line when none given
    assert eng.fired_kinds == ["slides_down", "heckler"]


def test_trigger_uses_generated_line_and_sfx_url():
    eng = CurveballEngine("s")
    _, ev = eng.trigger("heckler", 60_000, "Isn't this just a wrapper around an API?", "vc")
    assert ev.payload["line"] == "Isn't this just a wrapper around an API?"
    _, sfx = eng.trigger("distraction", 61_000, None, None)
    assert sfx.payload["sfx_url"] == "/demo/sfx/phone_ring.mp3"
    assert sfx.payload["ui_effect"] == "sfx"


def test_resume_gap_ignores_ai_speech_and_earlier_segments():
    eng = CurveballEngine("s")
    rec, _ = eng.trigger("slides_down", 100_000, None, None)
    transcript = [
        seg(99, "right before"),
        seg(101, "moderator line", 2.0).model_copy(update={"speaker": "ai"}),
        seg(106, "later presenter speech"),
        seg(104.5, "earlier presenter speech, listed out of order"),
    ]
    done = eng.resolve(rec, 130_000, "presenter_restored", transcript)
    assert done.payload["recovery"]["resume_after_ms"] == 4_500
    assert done.payload["recovery"]["evidence"] == "earlier presenter speech, listed out of order"
