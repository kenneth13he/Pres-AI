"""Shared fixtures: a silent, deterministic session with a fake clock."""

from __future__ import annotations

from typing import Any

import pytest

from backend import presets
from backend.engine import Session
from backend.services.audience import MockOrchestrator
from backend.services.voice_mock import MockVoice
from spec.contracts import SessionConfig, TranscriptSegment


def make_config(**overrides: Any) -> SessionConfig:
    preset = presets.presets()["startup_pitch"]
    base: dict[str, Any] = {
        "preset_id": preset.id,
        "personas": [p.model_dump() for p in presets.default_personas_for(preset)],
        "difficulty": "normal",
        "interruption_frequency": "normal",
        "curveballs": {"mode": "surprise"},
        "duration_target_s": 180,
        "qna_questions": 1,
    }
    base.update(overrides)
    return SessionConfig.model_validate(base)


def make_session(**overrides: Any) -> Session:
    config = make_config(**overrides)
    preset = presets.presets()[config.preset_id]
    return Session("test-001", config, preset, MockOrchestrator(), MockVoice())


def seg(start_s: float, text: str, dur_s: float = 3.0) -> TranscriptSegment:
    return TranscriptSegment(start_ms=int(start_s * 1000), end_ms=int((start_s + dur_s) * 1000),
                             text=text)


@pytest.fixture
def session() -> Session:
    return make_session()


@pytest.fixture(autouse=True)
def offline_adapters(monkeypatch):
    """A configured live .env must never turn an offline test into a vendor call."""
    monkeypatch.setenv("ORCHESTRATOR", "mock")
    monkeypatch.setenv("VOICE_ADAPTER", "mock")
    monkeypatch.setenv("BOSON_SPEND_CARRYOVER_USD", "0")


def s(seconds: float) -> int:
    """Seconds → ms, for a readable fake clock (session starts at t=0)."""
    return int(seconds * 1000)
