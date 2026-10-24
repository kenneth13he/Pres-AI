"""The session: state machine, scheduler, orchestrator, curveballs and report, wired together.

Owner: Person C (P0-5, P0-6, P0-8, P0-9). Spec: CLAUDE.md §8. Tests: test_e2e_mock.py.

Why: one place owns the phase transitions so the WebSocket layer in main.py stays thin and
the whole thing runs deterministically in tests with a fake clock. Every public method takes
`now_ms` instead of reading the wall clock.
"""

from __future__ import annotations

from typing import Any

from spec.contracts import (
    CurveballKind,
    Deck,
    Persona,
    Preset,
    Report,
    Resolution,
    SessionConfig,
    SessionEvent,
    SessionPhase,
    TranscriptSegment,
)

from .services import slides
from .services.audience import Orchestrator, OrchestratorContext
from .services.curveballs import CATALOG, CurveballEngine, CurveballRecord
from .services.report import build_report
from .services.scheduler import Scheduler, SchedulerSnapshot
from .services.voice_base import VoiceAdapter

TIME_CRUNCH_MS = 60_000
RECENT_TRANSCRIPT_MS = 30_000
RECOVERY_WINDOW_MS = 60_000
# Curveballs that are a question in disguise: the presenter answers, then we resolve "answered".
ANSWERABLE: set[CurveballKind] = {
    "heckler", "latecomer", "bait", "fact_check", "plain_language", "vip_arrives", "crosstalk",
}
PERSONA_STYLE: dict[CurveballKind, str] = {"heckler": "impatient", "fact_check": "impatient"}
LIVE_PHASES: set[SessionPhase] = {
    "presenting", "interruption", "answering", "curveball", "recovering", "qna",
}


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
        self._question_counter = 0

    # ---- helpers ---------------------------------------------------------------------------

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

    def _resting_phase(self) -> SessionPhase:
        """Where the room returns to after an event: Q&A once it has started, else presenting."""
        return "qna" if self.phase == "qna" or self.qna_asked else "presenting"

    # ---- presenter-side inputs (called by main.py from WebSocket messages) ----------------

    async def start(self, now_ms: int) -> None:
        """SETUP → PRESENTING. Emit session_started {config, preset}; voice.start_voice_session."""
        if self.phase != "setup":
            return
        self.start_ms = now_ms
        self._emit("session_started", now_ms, {"config": self.config.model_dump(),
                                               "preset": self.preset.model_dump()})
        self._set_phase("presenting", now_ms)
        await self.voice.start_voice_session(self.session_id, self.config)

    async def slide_changed(self, now_ms: int, number: int) -> None:
        """Track slide, emit slide_changed, voice.send_context(slide text)."""
        self.slide_number = number
        self.slide_changed_at_ms = now_ms
        self._emit("slide_changed", now_ms, {"slide_number": number})
        await self.voice.send_context(slides.slide_text(self.deck, number))

    async def presenter_transcript(self, now_ms: int, seg: TranscriptSegment) -> None:
        """Append, emit transcript_segment, update last_presenter_speech_ms.
        If an active `distraction` → resolve auto_restored. If phase == answering with a
        pending question → _handle_answer."""
        self.transcript.append(seg)
        self.last_presenter_speech_ms = seg.end_ms if seg.end_ms is not None else seg.start_ms
        self._emit("transcript_segment", now_ms, seg.model_dump())
        if self.phase == "paused":
            return
        active = self.curveballs.active
        if active and active.kind == "distraction":
            await self._resolve(active, now_ms, "auto_restored")
        if self.phase == "answering" and self.pending_question:
            await self._handle_answer(now_ms, seg.text)

    async def control(self, action: str, now_ms: int) -> None:
        """pause (any live phase → PAUSED, voice.cancel_speech) · resume · skip (_skip) ·
        restore_slides (active slides_down/elevator → presenter_restored) ·
        end (→ enter_qna; from qna → finish). Pause/Skip are never penalised."""
        if action == "pause" and self.phase in LIVE_PHASES:
            self.paused_phase = self.phase
            self._set_phase("paused", now_ms)
            self._emit("paused", now_ms)
            await self.voice.cancel_speech()
        elif action == "resume" and self.phase == "paused":
            self._set_phase(self.paused_phase or "presenting", now_ms)
            self.paused_phase = None
            self._emit("resumed", now_ms)
        elif action == "skip" and self.phase in LIVE_PHASES:
            await self._skip(now_ms)
        elif action == "restore_slides":
            active = self.curveballs.active
            if active and active.kind in ("slides_down", "elevator"):
                await self._resolve(active, now_ms, "presenter_restored")
        elif action == "end":
            if self.phase == "qna":
                await self.finish(now_ms)
            elif self.phase in LIVE_PHASES or self.phase == "paused":
                await self.enter_qna(now_ms)

    async def force_curveball(self, kind: CurveballKind, now_ms: int) -> None:
        """Debug/demo only (CLAUDE.md §7). Bypasses eligibility, never the one-at-a-time rule:
        no-op while a curveball or question is active."""
        if self.phase != "presenting" or self.curveballs.active or self.pending_question:
            return
        persona_id = None
        if CATALOG[kind].speaker == "persona":
            persona_id = self._player_for(kind)
        await self._fire_curveball(kind, now_ms, None, persona_id)

    def _player_for(self, kind: CurveballKind) -> str:
        players = [p for p in self.config.personas if kind in p.plays] or self.config.personas
        return players[0].id

    # ---- the clock (main.py calls tick every second) -------------------------------------

    async def tick(self, now_ms: int) -> None:
        """Nothing in setup/paused/report. time_crunch deadline reached → timer_override
        {remaining_ms: 0} and enter_qna. Auto-resolve due curveball. In presenting →
        _maybe_interrupt; in qna → _qna_step."""
        if self.phase in ("setup", "paused", "report"):
            return
        deadline = self.time_crunch_deadline_ms
        if deadline is not None and now_ms >= deadline and self.phase != "qna":
            self.time_crunch_deadline_ms = None
            self._emit("timer_override", now_ms, {"remaining_ms": 0, "style": "expired"})
            await self.enter_qna(now_ms)
            return
        due = self.curveballs.due_for_auto_resolve(now_ms)
        if due:
            await self._resolve(due, now_ms, "auto_restored")
        if self.phase == "presenting":
            await self._maybe_interrupt(now_ms)
        elif self.phase == "qna":
            await self._qna_step(now_ms)

    async def _maybe_interrupt(self, now_ms: int) -> None:
        """Build SchedulerSnapshot → scheduler.eligible → orchestrator.decide(context) →
        _ask or _fire_curveball (only a kind that was eligible)."""
        snap = SchedulerSnapshot(
            phase=self.phase,
            elapsed_ms=self.elapsed_ms(now_ms),
            questions_asked=len([q for q in self.questions
                                 if not q["follow_up_of"] and not q["curveball_id"]]),
            curveballs_fired=len(self.curveballs.records),
            fired_kinds=self.curveballs.fired_kinds,
            last_event_end_ms=self.last_event_end_ms,
            last_presenter_speech_ms=self.last_presenter_speech_ms,
            slide_number=self.slide_number,
            slide_changed_at_ms=self.slide_changed_at_ms,
            duration_target_s=self.config.duration_target_s,
            now_ms=now_ms,
        )
        elig = self.scheduler.eligible(snap)
        if not elig.anything:
            return
        decision = await self.orchestrator.decide(
            self._context(now_ms, elig.question, elig.curveball_kinds))
        if decision.action == "question" and elig.question and decision.persona_id \
                and decision.line and self.persona(decision.persona_id):
            await self._ask(decision.persona_id, decision.line, now_ms, decision.reason,
                            decision.cited_transcript_excerpt, decision.slide_number)
        elif (decision.action == "curveball" and decision.curveball_kind
              and decision.curveball_kind in elig.curveball_kinds):
            kind = decision.curveball_kind
            persona_id = decision.persona_id if self.persona(decision.persona_id) else None
            if CATALOG[kind].speaker == "persona" and persona_id is None:
                persona_id = self._player_for(kind)
            await self._fire_curveball(kind, now_ms, decision.line, persona_id)

    def _context(self, now_ms: int, question_allowed: bool,
                 kinds: list[CurveballKind]) -> OrchestratorContext:
        cutoff = now_ms - RECENT_TRANSCRIPT_MS
        return OrchestratorContext(
            preset_id=self.config.preset_id,
            difficulty=self.config.difficulty,
            personas=self.config.personas,
            slide_number=self.slide_number,
            slide_text=slides.slide_text(self.deck, self.slide_number),
            recent_transcript=[s for s in self.transcript if s.start_ms >= cutoff],
            prior_qa=[{"persona_id": q["persona_id"], "q": q["question"], "a": q["answer"]}
                      for q in self.questions],
            question_allowed=question_allowed,
            eligible_kinds=kinds,
            curveball_budget_remaining=max(
                0, self.scheduler.curveball_budget - len(self.curveballs.records)),
            seconds_since_last_event=(None if self.last_event_end_ms is None
                                      else (now_ms - self.last_event_end_ms) // 1000),
        )

    # ---- questions ------------------------------------------------------------------------

    def _new_question(self, persona_id: str, question: str, now_ms: int, reason: str,
                      cited: str | None, slide_number: int | None,
                      follow_up_of: str | None, curveball_id: str | None) -> dict[str, Any]:
        self._question_counter += 1
        q: dict[str, Any] = {
            "question_id": f"q-{self._question_counter}", "persona_id": persona_id,
            "question": question, "reason": reason, "cited_excerpt": cited,
            "slide_number": slide_number, "follow_up_of": follow_up_of,
            "curveball_id": curveball_id, "answer": None, "asked_at_ms": now_ms,
        }
        self.questions.append(q)
        self._emit("question_queued", now_ms, {k: v for k, v in q.items() if k != "answer"})
        return q

    async def _ask(self, persona_id: str, question: str, now_ms: int, reason: str,
                   cited: str | None, slide_number: int | None,
                   follow_up_of: str | None = None, curveball_id: str | None = None) -> None:
        """Record the question, emit question_queued (payload = CLAUDE.md §7 example),
        INTERRUPTION → _speak → ANSWERING with pending_question set."""
        q = self._new_question(persona_id, question, now_ms, reason, cited, slide_number,
                               follow_up_of, curveball_id)
        if not curveball_id and self.phase == "presenting":
            self._set_phase("interruption", now_ms)
        await self._speak(persona_id, question, now_ms)
        self.pending_question = q
        self._set_phase("answering", now_ms)

    async def _handle_answer(self, now_ms: int, answer: str) -> None:
        """emit answer_received → orchestrator.follow_up. follow_up and followups_used < 1 →
        _ask again with follow_up_of. Otherwise speak the ack line, clear pending, set
        last_event_end_ms; a curveball question resolves "answered"; back to PRESENTING
        (or count a Q&A answer in qna)."""
        q = self.pending_question
        assert q is not None
        q["answer"] = answer
        self._emit("answer_received", now_ms, {"question_id": q["question_id"], "answer": answer})
        persona = self.persona(q["persona_id"]) or self.config.personas[0]
        verdict = await self.orchestrator.follow_up(q["question"], answer, persona,
                                                    self.followups_used)
        if verdict.verdict == "follow_up" and self.followups_used < 1:
            self.followups_used += 1
            await self._ask(q["persona_id"], verdict.line, now_ms, "follow-up", None,
                            q["slide_number"], follow_up_of=q["question_id"],
                            curveball_id=q["curveball_id"])
            return
        await self._speak(q["persona_id"], verdict.line, now_ms)
        self.pending_question = None
        self.followups_used = 0
        self.last_event_end_ms = now_ms
        in_qna = self.qna_asked > 0 or any(
            e.type == "phase_changed" and e.payload.get("to") == "qna" for e in self.events)
        if q["curveball_id"]:
            rec = next(r for r in self.curveballs.records if r.curveball_id == q["curveball_id"])
            await self._resolve(rec, now_ms, "answered")
        elif in_qna:
            self.qna_asked += 1
            self._set_phase("qna", now_ms)
        else:
            self._set_phase("presenting", now_ms)

    async def _speak(self, persona_id: str | None, line: str, now_ms: int,
                     style: str | None = None) -> None:
        """emit ai_speech_started {speaker, line} → voice.request_persona_turn or
        play_moderator_line → emit ai_speech_ended. Only one AI voice ever speaks."""
        speaker = persona_id or "moderator"
        self._emit("ai_speech_started", now_ms, {"speaker": speaker, "line": line})
        if persona_id:
            persona = self.persona(persona_id)
            await self.voice.request_persona_turn(
                persona_id, line, style or (persona.style_hint if persona else None))
        else:
            await self.voice.play_moderator_line(line)
        # The mock finishes instantly; a live adapter emits its own ai_speech_ended later and
        # this one is the floor the UI can rely on.
        self._emit("ai_speech_ended", now_ms, {"speaker": speaker})

    async def _skip(self, now_ms: int) -> None:
        """voice.cancel_speech; emit skipped; clear pending; active curveball → resolve
        "skipped" (recovery None); phase back to presenting/qna."""
        q = self.pending_question
        active = self.curveballs.active
        if not q and not active:
            return
        await self.voice.cancel_speech()
        self._emit("skipped", now_ms, {"question_id": q["question_id"] if q else None,
                                       "curveball_id": active.curveball_id if active else None})
        self.pending_question = None
        self.followups_used = 0
        self.last_event_end_ms = now_ms
        if active:
            await self._resolve(active, now_ms, "skipped")
        else:
            self._set_phase(self._resting_phase(), now_ms)

    # ---- curveballs -------------------------------------------------------------------------

    async def _fire_curveball(self, kind: CurveballKind, now_ms: int, line: str | None,
                              persona_id: str | None) -> None:
        """curveballs.trigger → append event → CURVEBALL. time_crunch: set deadline, emit
        timer_override {remaining_ms: 60000, style: urgent}, then back to PRESENTING (the clock
        is the pressure). moderator/persona speaker → _speak (PERSONA_STYLE for heckler);
        ui speaker → voice.play_sfx. ANSWERABLE kinds become a pending question (ANSWERING);
        others → RECOVERING."""
        rec, event = self.curveballs.trigger(kind, now_ms, line, persona_id)
        self.events.append(event)
        self._set_phase("curveball", now_ms)
        spec = rec.spec
        if kind == "time_crunch":
            self.time_crunch_deadline_ms = now_ms + TIME_CRUNCH_MS
            self._emit("timer_override", now_ms, {"curveball_id": rec.curveball_id,
                                                  "remaining_ms": TIME_CRUNCH_MS,
                                                  "style": "urgent"})
        if spec.speaker == "moderator":
            await self._speak(None, rec.line, now_ms)
        elif spec.speaker == "persona" and rec.persona_id:
            await self._speak(rec.persona_id, rec.line, now_ms, PERSONA_STYLE.get(kind))
        elif spec.sfx:
            await self.voice.play_sfx(spec.sfx)
        if kind in ANSWERABLE and rec.persona_id:
            self.pending_question = self._new_question(
                rec.persona_id, rec.line, now_ms, f"curveball:{kind}", None,
                self.slide_number, None, rec.curveball_id)
            self._set_phase("answering", now_ms)
        elif kind == "time_crunch":
            self._set_phase("presenting", now_ms)  # keep going; the clock is the pressure
        else:
            self._set_phase("recovering", now_ms)

    async def _resolve(self, rec: CurveballRecord, now_ms: int, resolution: Resolution) -> None:
        """curveballs.resolve → if recovery measured, orchestrator.assess_recovery over the
        next RECOVERY_WINDOW_MS of transcript and merge score/evidence/suggestion into the
        event payload → append → last_event_end_ms → PRESENTING (time_crunch stays)."""
        event = self.curveballs.resolve(rec, now_ms, resolution, self.transcript)
        if rec.recovery is not None:
            after = [s for s in self.transcript
                     if rec.at_ms < s.start_ms <= rec.at_ms + RECOVERY_WINDOW_MS]
            assessment = await self.orchestrator.assess_recovery(
                rec.kind, rec.line, after, rec.recovery.resume_after_ms)
            rec.recovery.score = assessment.score
            rec.recovery.evidence = assessment.evidence or rec.recovery.evidence
            rec.recovery.suggestion = assessment.suggestion
            event.payload["recovery"] = rec.recovery.model_dump()
        self.events.append(event)
        self.last_event_end_ms = now_ms
        if rec.kind == "time_crunch":
            return
        if self.phase in ("curveball", "recovering", "answering"):
            self.pending_question = None
            self._set_phase(self._resting_phase(), now_ms)

    # ---- the end --------------------------------------------------------------------------

    async def enter_qna(self, now_ms: int) -> None:
        """Resolve a non-time_crunch active curveball as timed_out → QNA.
        qna_questions == 0 → finish."""
        if self.phase in ("qna", "report"):
            return
        active = self.curveballs.active
        if active and active.kind != "time_crunch":
            await self._resolve(active, now_ms, "timed_out")
        self.pending_question = None
        self.followups_used = 0
        self._set_phase("qna", now_ms)
        if self.config.qna_questions == 0:
            await self.finish(now_ms)

    async def _qna_step(self, now_ms: int) -> None:
        """No pending question: asked < config.qna_questions → orchestrator.decide(question
        only) → _ask, else finish."""
        if self.pending_question:
            return
        if self.qna_asked >= self.config.qna_questions:
            await self.finish(now_ms)
            return
        decision = await self.orchestrator.decide(self._context(now_ms, True, []))
        if decision.action == "question" and decision.persona_id and decision.line \
                and self.persona(decision.persona_id):
            await self._ask(decision.persona_id, decision.line, now_ms, decision.reason,
                            decision.cited_transcript_excerpt, decision.slide_number)
        else:
            await self.finish(now_ms)

    async def finish(self, now_ms: int) -> None:
        """Resolve leftovers timed_out, voice.stop_voice_session, REPORT, self.report =
        build_report(self), emit session_ended {report_url}."""
        if self.ended:
            return
        for rec in self.curveballs.records:
            if rec.resolution is None:
                await self._resolve(rec, now_ms, "timed_out")
        self.pending_question = None
        self.time_crunch_deadline_ms = None
        await self.voice.stop_voice_session()
        self._set_phase("report", now_ms)
        self.report = build_report(self)
        self._emit("session_ended", now_ms,
                   {"report_url": f"/api/sessions/{self.session_id}/report"})
