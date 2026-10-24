"""The session: state machine, scheduler, orchestrator, curveballs and report, wired together.

Owner: Person C (P0-5, P0-6, P0-8, P0-9). Spec: CLAUDE.md §8. Tests: test_e2e_mock.py.

Why: one place owns the phase transitions so the WebSocket layer in main.py stays thin and
the whole thing runs deterministically in tests with a fake clock. Every public method takes
`now_ms` instead of reading the wall clock. The state fields and method signatures below are
the contract with main.py and the tests; the bodies are skeletons.
"""

from __future__ import annotations

from typing import Any

from spec.contracts import (
    CurveballKind,
    Deck,
    Persona,
    Preset,
    Report,
    SessionConfig,
    SessionEvent,
    SessionPhase,
    TranscriptSegment,
)

from .services.audience import Orchestrator
from .services.curveballs import CurveballEngine
from .services.scheduler import Scheduler
from .services.voice_base import VoiceAdapter

TIME_CRUNCH_MS = 60_000
RECENT_TRANSCRIPT_MS = 30_000
RECOVERY_WINDOW_MS = 60_000
# Curveballs that are a question in disguise: the presenter answers, then we resolve "answered".
ANSWERABLE: set[CurveballKind] = {
    "heckler", "latecomer", "bait", "fact_check", "plain_language", "vip_arrives", "crosstalk",
}
PERSONA_STYLE: dict[CurveballKind, str] = {"heckler": "impatient", "fact_check": "impatient"}


class Session:
    def __init__(
        self,
        session_id: str,
        config: SessionConfig,
        preset: Preset,
        orchestrator: Orchestrator,
        voice: VoiceAdapter,
        deck: Deck | None = None,
        curveballs_enabled: bool = True,
    ) -> None:
        self.session_id = session_id
        self.config = config
        self.preset = preset
        self.orchestrator = orchestrator
        self.voice = voice
        self.deck = deck
        self.phase: SessionPhase = "setup"
        self.events: list[SessionEvent] = []
        self.transcript: list[TranscriptSegment] = []
        # question dicts: question_id, persona_id, question, reason, cited_excerpt,
        # slide_number, follow_up_of, curveball_id, answer, asked_at_ms
        self.questions: list[dict[str, Any]] = []
        self.curveballs = CurveballEngine(session_id)
        self.scheduler = Scheduler(
            config.difficulty, config.interruption_frequency, config.curveballs,
            preset.curveballs_allowed, curveballs_enabled,
        )
        self.start_ms: int | None = None
        self.slide_number = 1
        self.slide_changed_at_ms: int | None = None
        self.last_event_end_ms: int | None = None
        self.last_presenter_speech_ms: int | None = None
        self.paused_phase: SessionPhase | None = None
        self.time_crunch_deadline_ms: int | None = None
        self.pending_question: dict[str, Any] | None = None
        self.followups_used = 0
        self.qna_asked = 0
        self.report: Report | None = None

    # ---- helpers (implemented: main.py and tests rely on them) ----------------------------

    @property
    def ended(self) -> bool:
        return self.phase == "report"

    def elapsed_ms(self, now_ms: int) -> int:
        return 0 if self.start_ms is None else now_ms - self.start_ms

    def persona(self, persona_id: str | None) -> Persona | None:
        return next((p for p in self.config.personas if p.id == persona_id), None)

    def drain(self, since: int) -> list[SessionEvent]:
        return self.events[since:]

    def _emit(self, type_: str, now_ms: int, payload: dict[str, Any] | None = None) -> SessionEvent:
        ev = SessionEvent(type=type_, session_id=self.session_id, timestamp_ms=now_ms,  # type: ignore[arg-type]
                          payload=payload or {})
        self.events.append(ev)
        return ev

    def _set_phase(self, phase: SessionPhase, now_ms: int) -> None:
        if phase == self.phase:
            return
        previous, self.phase = self.phase, phase
        self._emit("phase_changed", now_ms, {"from": previous, "to": phase})

    # ---- presenter-side inputs (called by main.py from WebSocket messages) ----------------

    async def start(self, now_ms: int) -> None:
        """SETUP → PRESENTING. Emit session_started {config, preset}; voice.start_voice_session."""
        raise NotImplementedError  # TODO(C)

    async def slide_changed(self, now_ms: int, number: int) -> None:
        """Track slide, emit slide_changed, voice.send_context(slide text)."""
        raise NotImplementedError  # TODO(C)

    async def presenter_transcript(self, now_ms: int, seg: TranscriptSegment) -> None:
        """Append, emit transcript_segment, update last_presenter_speech_ms.
        If an active `distraction` → resolve auto_restored. If phase == answering with a
        pending question → _handle_answer."""
        raise NotImplementedError  # TODO(C)

    async def control(self, action: str, now_ms: int) -> None:
        """pause (any live phase → PAUSED, voice.cancel_speech) · resume · skip (_skip) ·
        restore_slides (active slides_down/elevator → presenter_restored) ·
        end (→ enter_qna; from qna → finish). Pause/Skip are never penalised."""
        raise NotImplementedError  # TODO(C)

    async def force_curveball(self, kind: CurveballKind, now_ms: int) -> None:
        """Debug/demo only (CLAUDE.md §7). Bypasses eligibility, never the one-at-a-time rule:
        no-op while a curveball or question is active."""
        raise NotImplementedError  # TODO(C)

    # ---- the clock (main.py calls tick every second) -------------------------------------

    async def tick(self, now_ms: int) -> None:
        """Nothing in setup/paused/report. time_crunch deadline reached → timer_override
        {remaining_ms: 0} and enter_qna. Auto-resolve due curveball. In presenting →
        _maybe_interrupt; in qna → _qna_step."""
        raise NotImplementedError  # TODO(C)

    async def _maybe_interrupt(self, now_ms: int) -> None:
        """Build SchedulerSnapshot → scheduler.eligible → orchestrator.decide(context) →
        _ask or _fire_curveball (only a kind that was eligible)."""
        raise NotImplementedError  # TODO(C)

    # ---- questions ------------------------------------------------------------------------

    async def _ask(self, persona_id: str, question: str, now_ms: int, reason: str,
                   cited: str | None, slide_number: int | None,
                   follow_up_of: str | None = None, curveball_id: str | None = None) -> None:
        """Record the question, emit question_queued (payload = CLAUDE.md §7 example),
        INTERRUPTION → _speak → ANSWERING with pending_question set."""
        raise NotImplementedError  # TODO(C)

    async def _handle_answer(self, now_ms: int, answer: str) -> None:
        """emit answer_received → orchestrator.follow_up. follow_up and followups_used < 1 →
        _ask again with follow_up_of. Otherwise speak the ack line, clear pending, set
        last_event_end_ms; a curveball question resolves "answered"; back to PRESENTING
        (or count a Q&A answer in qna)."""
        raise NotImplementedError  # TODO(C)

    async def _speak(self, persona_id: str | None, line: str, now_ms: int,
                     style: str | None = None) -> None:
        """emit ai_speech_started {speaker, line} → voice.request_persona_turn or
        play_moderator_line → emit ai_speech_ended. Only one AI voice ever speaks."""
        raise NotImplementedError  # TODO(C)

    async def _skip(self, now_ms: int) -> None:
        """voice.cancel_speech; emit skipped; clear pending; active curveball → resolve
        "skipped" (recovery None); phase back to presenting/qna."""
        raise NotImplementedError  # TODO(C)

    # ---- curveballs -------------------------------------------------------------------------

    async def _fire_curveball(self, kind: CurveballKind, now_ms: int, line: str | None,
                              persona_id: str | None) -> None:
        """curveballs.trigger → append event → CURVEBALL. time_crunch: set deadline, emit
        timer_override {remaining_ms: 60000, style: urgent}, then back to PRESENTING (the clock
        is the pressure). moderator/persona speaker → _speak (PERSONA_STYLE for heckler);
        ui speaker → voice.play_sfx. ANSWERABLE kinds become a pending question (ANSWERING);
        others → RECOVERING."""
        raise NotImplementedError  # TODO(C)

    async def _resolve(self, rec, now_ms: int, resolution: str) -> None:
        """curveballs.resolve → if recovery measured, orchestrator.assess_recovery over the
        next RECOVERY_WINDOW_MS of transcript and merge score/evidence/suggestion into the
        event payload → append → last_event_end_ms → PRESENTING (time_crunch stays)."""
        raise NotImplementedError  # TODO(C)

    # ---- the end --------------------------------------------------------------------------

    async def enter_qna(self, now_ms: int) -> None:
        """Resolve a non-time_crunch active curveball as timed_out → QNA.
        qna_questions == 0 → finish."""
        raise NotImplementedError  # TODO(C)

    async def _qna_step(self, now_ms: int) -> None:
        """No pending question: asked < config.qna_questions → orchestrator.decide(question
        only) → _ask, else finish."""
        raise NotImplementedError  # TODO(C)

    async def finish(self, now_ms: int) -> None:
        """Resolve leftovers timed_out, voice.stop_voice_session, REPORT, self.report =
        build_report(self), emit session_ended {report_url}."""
        raise NotImplementedError  # TODO(C)
