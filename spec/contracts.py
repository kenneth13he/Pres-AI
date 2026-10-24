"""The only source of event, persona, config and report types.

Why: every owner imports from here; the frontend's mock fixtures are validated
against the JSON schema generated from these models (`make schema`). Nobody
redefines a type locally, in Python or in JavaScript. See CLAUDE.md §7.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

CurveballKind = Literal[
    "time_crunch",
    "slides_down",
    "heckler",
    "latecomer",
    "bait",
    "distraction",
    "vip_arrives",
    "crosstalk",
    "fact_check",
    "elevator",
    "plain_language",
    "dead_room",
]
Difficulty = Literal["friendly", "normal", "brutal"]
InterruptionFrequency = Literal["rare", "normal", "often"]
InputMode = Literal["live", "push_to_talk"]
SessionPhase = Literal[
    "setup",
    "presenting",
    "interruption",
    "answering",
    "curveball",
    "recovering",
    "paused",
    "qna",
    "report",
]
EventType = Literal[
    "session_started",
    "slide_changed",
    "transcript_segment",
    "question_queued",
    "ai_speech_started",
    "ai_speech_ended",
    "answer_received",
    "curveball_triggered",
    "curveball_resolved",
    "timer_override",
    "paused",
    "resumed",
    "skipped",
    "avatar_status",
    "audio_status",
    "phase_changed",
    "session_ended",
    "error",
]
Resolution = Literal["auto_restored", "presenter_restored", "answered", "skipped", "timed_out"]
ControlAction = Literal["pause", "resume", "skip", "restore_slides", "end"]


class Persona(BaseModel):
    id: str
    name: str
    role: str
    focus: list[str]
    skepticism: float = Field(ge=0, le=1)
    style_hint: str | None = None
    voice_id: str | None = None
    avatar_url: str | None = None
    plays: list[CurveballKind] = []
    custom: bool = False  # True → labelled "Custom · fictional" in the UI


class CurveballMode(BaseModel):
    mode: Literal["off", "surprise", "choose"] = "surprise"
    kinds: list[CurveballKind] = []  # used only when mode == "choose"


class SessionConfig(BaseModel):
    preset_id: str  # "startup_pitch" | ... | "custom"
    personas: list[Persona] = Field(min_length=2, max_length=3)
    difficulty: Difficulty = "normal"
    interruption_frequency: InterruptionFrequency = "normal"
    curveballs: CurveballMode = CurveballMode()
    duration_target_s: int = 180
    qna_questions: int = Field(default=2, ge=0, le=3)
    input_mode: InputMode = "live"
    deck_id: str | None = None


class SessionEvent(BaseModel):
    type: EventType
    session_id: str
    timestamp_ms: int
    payload: dict[str, Any] = {}


class Preset(BaseModel):
    id: str
    name: str
    personas: list[str]  # persona ids from the roster
    curveballs_allowed: list[CurveballKind]
    default_difficulty: Difficulty = "normal"
    duration_target_s: int = 180
    tagline: str = ""


class Slide(BaseModel):
    number: int  # 1-based
    text: str
    image_url: str | None = None


class Deck(BaseModel):
    deck_id: str
    filename: str
    page_count: int
    slides: list[Slide]


class TranscriptSegment(BaseModel):
    start_ms: int
    end_ms: int | None = None
    text: str
    speaker: Literal["presenter", "ai"] = "presenter"
    confidence: float | None = None


class Recovery(BaseModel):
    resume_after_ms: int | None = None  # null when it could not be measured
    notes: str | None = None
    score: int | None = Field(default=None, ge=0, le=100)
    evidence: str | None = None
    suggestion: str | None = None


# ---- Orchestrator outputs (structured outputs from Claude; see CLAUDE.md §9) ----


class OrchestratorDecision(BaseModel):
    action: Literal["none", "question", "curveball"]
    persona_id: str | None = None
    curveball_kind: CurveballKind | None = None
    line: str | None = None
    reason: str
    cited_transcript_excerpt: str | None = None
    slide_number: int | None = None


class FollowUpVerdict(BaseModel):
    verdict: Literal["satisfied", "follow_up"]
    line: str
    missing_detail: str | None = None


class RecoveryAssessment(BaseModel):
    score: int | None = Field(default=None, ge=0, le=100)  # None = could not be assessed
    evidence: str | None = None  # verbatim transcript quote, or None
    observation: str
    suggestion: str


# ---- Report (CLAUDE.md §10) ----


class Improvement(BaseModel):
    observation: str
    evidence: str
    suggestion: str


class CurveballReport(BaseModel):
    kind: CurveballKind
    at_ms: int
    resolution: Resolution
    recovery: Recovery | None


class KeyMoment(BaseModel):
    at_ms: int
    type: Literal["question", "curveball", "answer", "phase"]
    summary: str
    persona_id: str | None = None
    kind: CurveballKind | None = None


class PersonaFeedback(BaseModel):
    persona_id: str
    score: int | None = Field(default=None, ge=0, le=100)
    comment: str


class Report(BaseModel):
    session_id: str
    overall_score: int | None = None
    dimensions: dict[str, int | None]
    metrics: dict[str, int | None]
    metric_caveats: list[str] = []
    strengths: list[str] = []
    improvements: list[Improvement] = []
    curveballs: list[CurveballReport] = []
    key_moments: list[KeyMoment] = []
    persona_feedback: list[PersonaFeedback] = []


# Models exported into spec/contracts.schema.json by scripts/gen_schema.py.
SCHEMA_MODELS: list[type[BaseModel]] = [
    Persona,
    CurveballMode,
    SessionConfig,
    SessionEvent,
    Preset,
    Deck,
    TranscriptSegment,
    OrchestratorDecision,
    FollowUpVerdict,
    RecoveryAssessment,
    Report,
]
