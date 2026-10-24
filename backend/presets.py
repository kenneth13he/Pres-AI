"""Load the persona roster and presets from backend/scenarios/*.yaml.

Why: content, not code. Anyone may add a persona or a preset by editing YAML; the
schema is `spec/contracts.py` and a bad file fails here, loudly, at startup.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

from spec.contracts import Persona, Preset

SCENARIOS = Path(__file__).resolve().parent / "scenarios"


@lru_cache(maxsize=1)
def personas() -> dict[str, Persona]:
    raw = yaml.safe_load((SCENARIOS / "personas.yaml").read_text())
    return {p["id"]: Persona.model_validate(p) for p in raw["personas"]}


@lru_cache(maxsize=1)
def presets() -> dict[str, Preset]:
    out: dict[str, Preset] = {}
    for path in sorted(SCENARIOS.glob("*.yaml")):
        if path.name == "personas.yaml":
            continue
        preset = Preset.model_validate(yaml.safe_load(path.read_text()))
        unknown = [pid for pid in preset.personas if pid not in personas()]
        if unknown:
            raise ValueError(f"{path.name} names unknown personas: {unknown}")
        out[preset.id] = preset
    return out


def default_personas_for(preset: Preset) -> list[Persona]:
    return [personas()[pid] for pid in preset.personas]
