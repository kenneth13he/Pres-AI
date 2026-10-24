import pytest
from pydantic import ValidationError

from backend import presets
from scripts.gen_schema import build
from spec.contracts import SCHEMA_MODELS, CurveballMode, SessionConfig, SessionEvent


def test_schema_covers_every_exported_model():
    defs = build()["$defs"]
    for model in SCHEMA_MODELS:
        assert model.__name__ in defs


def test_session_config_takes_one_to_three_personas():
    roster = list(presets.personas().values())
    for bad in (roster[:0], roster[:4]):
        with pytest.raises(ValidationError):
            SessionConfig(preset_id="startup_pitch", personas=bad)
    assert len(SessionConfig(preset_id="startup_pitch", personas=roster[:1]).personas) == 1
    cfg = SessionConfig(preset_id="startup_pitch", personas=roster[:2])
    assert cfg.curveballs == CurveballMode(mode="surprise")
    assert cfg.difficulty == "normal"


def test_event_wire_format_is_snake_case():
    ev = SessionEvent(type="slide_changed", session_id="x", timestamp_ms=1,
                      payload={"slide_number": 2})
    assert set(ev.model_dump()) == {"type", "session_id", "timestamp_ms", "payload"}


def test_every_preset_names_known_personas_and_kinds():
    for preset in presets.presets().values():
        assert len(preset.personas) == 3
        assert preset.curveballs_allowed
