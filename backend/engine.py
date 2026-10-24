"""The session: state machine, scheduler, orchestrator, curveballs and report, wired together.

Owner: Person C (P0-5, P0-6, P0-8, P0-9). Spec: CLAUDE.md §8. Tests: test_e2e_mock.py.

Why: one place owns the phase transitions so the WebSocket layer in main.py stays thin and
the whole thing runs deterministically in tests with a fake clock. Every public method takes
`now_ms` instead of reading the wall clock.

Timebase: every `now_ms`, event `timestamp_ms` and transcript `start_ms`/`end_ms` is
**milliseconds since the presentation started** (the session clock). main.py converts the
wall clock; the browser's segments are relative to its own Start click, which is the same
instant give or take network latency.

Pause: paused time never counts. On resume every stored timestamp is shifted forward by the
paused duration, so cooldowns, the time_crunch deadline, auto-resolve and the measured
resume gap all behave as if the pause had not happened (CLAUDE.md §2, §5.4).
"""

from __future__ import annotations

import logging
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
from .services.curveballs import CATALOG, CurveballEngine, CurveballRecord, paused_between
from .services.report import build_report
from .services.scheduler import Scheduler, SchedulerSnapshot
from .services.voice_base import VoiceAdapter

log = logging.getLogger(__name__)

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
        # slide_number, follow_up_of, curveball_id, answer, skipped, asked_at_ms
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
        self.paused_at_ms: int | None = None
        self.pauses: list[tuple[int, int]] = []  # closed pause intervals, session clock
        self.time_crunch_deadline_ms: int | None = None
        self.pending_question: dict[str, Any] | None = None
        self.followups_used = 0
        self.in_qna = False
        self.qna_asked = 0
        self.report: Report | None = None
        self._question_counter = 0
        self._clock_ms = 0  # last session-clock time seen, stamps adapter events
        self.voice.on_event(self._on_voice_event)

    async def _on_voice_event(self, ev: SessionEvent) -> None:
        """Adapter events (audio clips, status) join the session stream on our clock."""
        self.events.append(ev.model_copy(update={"session_id": self.session_id,
                                                 "timestamp_ms": self._clock_ms}))

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
        self._clock_ms = now_ms
        ev = SessionEvent(type=type_, session_id=self.session_id, timestamp_ms=now_ms,  # type: ignore[arg-type]
                          payload=payload or {})
        self.events.append(ev)
        return ev

    def _error(self, now_ms: int, where: str, exc: Exception) -> None:
        """A failed LLM/TTS call is logged and shown, and the session keeps going (§8)."""
        log.warning("%s failed in %s: %s", self.session_id, where, exc)
        self._emit("error", now_ms, {"where": where, "message": str(exc)[:300]})

    def _set_phase(self, phase: SessionPhase, now_ms: int) -> None:
        if phase == self.phase:
            return
        previous, self.phase = self.phase, phase
        self._emit("phase_changed", now_ms, {"from": previous, "to": phase})

    def _resting_phase(self) -> SessionPhase:
        """Where the room returns to after an event."""
        return "qna" if self.in_qna else "presenting"

    def _player_for(self, kind: CurveballKind) -> str:
        players = [p for p in self.config.personas if kind in p.plays] or self.config.personas
        return players[0].id

    # ---- presenter-side inputs (called by main.py from WebSocket messages) ----------------

    async def start(self, now_ms: int) -> None:
        """SETUP → PRESENTING. Emit session_started {config, preset}; voice.start_voice_session."""
        if self.phase != "setup":
            return
        self.start_ms = now_ms
        self._emit("session_started", now_ms, {"config": self.config.model_dump(),
                                               "preset": self.preset.model_dump()})
        self._set_phase("presenting", now_ms)
        try:
            await self.voice.start_voice_session(self.session_id, self.config)
        except Exception as exc:
            self._error(now_ms, "voice.start_voice_session", exc)

    async def slide_changed(self, now_ms: int, number: int) -> None:
        """Track slide, emit slide_changed, voice.send_context(slide text)."""
        self.slide_number = number
        self.slide_changed_at_ms = now_ms
        self._emit("slide_changed", now_ms, {"slide_number": number})
        try:
            await self.voice.send_context(slides.slide_text(self.deck, number))
        except Exception as exc:
            self._error(now_ms, "voice.send_context", exc)

    async def presenter_transcript(self, now_ms: int, seg: TranscriptSegment) -> None:
        """Append a presenter segment, emit transcript_segment, update last_presenter_speech_ms.
        Ignored while paused or ended; AI segments are captions, never answers.
        An active `distraction` resolves on the next speech. In `answering` → _handle_answer."""
        if self.phase in ("paused", "report", "setup"):
            return
        if seg.speaker != "presenter":
            return
        self.transcript.append(seg)
        self.last_presenter_speech_ms = seg.end_ms if seg.end_ms is not None else seg.start_ms
        self._emit("transcript_segment", now_ms, seg.model_dump())
        active = self.curveballs.active
        if active and active.kind == "distraction":
            await self._resolve(active, now_ms, "auto_restored")
        if self.phase == "answering" and self.pending_question:
            await self._handle_answer(now_ms, seg.text)

    async def control(self, action: str, now_ms: int) -> None:
        """pause · resume · skip · restore_slides · end. Pause and Skip are never penalised."""
        if action == "pause" and self.phase in LIVE_PHASES:
            self.paused_phase = self.phase
            self.paused_at_ms = now_ms
            self._set_phase("paused", now_ms)
            self._emit("paused", now_ms)
            try:
                await self.voice.cancel_speech()
            except Exception as exc:
                self._error(now_ms, "voice.cancel_speech", exc)
        elif action == "resume" and self.phase == "paused":
            self._unpause(now_ms)
            self._set_phase(self.paused_phase or self._resting_phase(), now_ms)
            self.paused_phase = None
            self._emit("resumed", now_ms)
        elif action == "skip" and self.phase in LIVE_PHASES:
            await self._skip(now_ms)
        elif action == "restore_slides" and self.phase in LIVE_PHASES:
            active = self.curveballs.active
            if active and active.kind in ("slides_down", "elevator"):
                await self._resolve(active, now_ms, "presenter_restored")
        elif action == "end":
            if self.in_qna:
                await self.finish(now_ms)
            elif self.phase in LIVE_PHASES or self.phase == "paused":
                await self.enter_qna(now_ms)

    def _unpause(self, now_ms: int) -> None:
        """Close the pause interval and move every *deadline-like* timestamp forward by the
        paused duration so paused time never counts against the presenter. Event-like
        timestamps (when a curveball fired, when a question was asked) stay on the session
        clock so the report agrees with the event log; recovery timing subtracts `pauses`."""
        if self.paused_at_ms is None:
            return
        delta_ms = now_ms - self.paused_at_ms
        self.pauses.append((self.paused_at_ms, now_ms))
        self.paused_at_ms = None
        if delta_ms <= 0:
            return
        if self.start_ms is not None:
            self.start_ms += delta_ms
        if self.time_crunch_deadline_ms is not None:
            self.time_crunch_deadline_ms += delta_ms
        if self.last_event_end_ms is not None:
            self.last_event_end_ms += delta_ms
        if self.last_presenter_speech_ms is not None:
            self.last_presenter_speech_ms += delta_ms
        if self.slide_changed_at_ms is not None:
            self.slide_changed_at_ms += delta_ms

    def _paused_since(self, start_ms: int, now_ms: int) -> int:
        return paused_between(self.pauses, start_ms, now_ms)

    async def force_curveball(self, kind: CurveballKind, now_ms: int) -> None:
        """Debug/demo only (CLAUDE.md §7). Bypasses eligibility, never the one-at-a-time rule:
        no-op unless presenting with nothing active."""
        if self.phase != "presenting" or self.curveballs.active or self.pending_question:
            return
        persona_id = self._player_for(kind) if CATALOG[kind].speaker == "persona" else None
        await self._fire_curveball(kind, now_ms, None, persona_id)

    # ---- the clock (main.py calls tick every second) -------------------------------------

    async def tick(self, now_ms: int) -> None:
        if self.phase in ("setup", "paused", "report"):
            return
        deadline = self.time_crunch_deadline_ms
        if deadline is not None and now_ms >= deadline:
            await self._time_crunch_expired(now_ms)
            return
        active = self.curveballs.active
        due = self.curveballs.due_for_auto_resolve(
            now_ms, self._paused_since(active.at_ms, now_ms) if active else 0)
        if due:
            await self._resolve(due, now_ms, "auto_restored")
        if self.phase == "presenting":
            await self._maybe_interrupt(now_ms)
        elif self.phase == "qna":
            await self._qna_step(now_ms)

    async def _time_crunch_expired(self, now_ms: int) -> None:
        """The countdown hit zero: resolve the crunch on its own metric (not a resume gap),
        then Q&A."""
        self.time_crunch_deadline_ms = None
        self._emit("timer_override", now_ms, {"remaining_ms": 0, "style": "expired"})
        await self.enter_qna(now_ms, crunch_resolution="timed_out")

    def _cut_off_pending(self, now_ms: int, reason: str) -> None:
        """The room, not the presenter, ended a pending question: it is `skipped` (never
        "unanswered") and the UI hears about it."""
        q = self.pending_question
        if q is None:
            return
        q["skipped"] = True
        q["cut_off"] = reason
        self._emit("skipped", now_ms, {"question_id": q["question_id"],
                                       "curveball_id": q["curveball_id"], "reason": reason})
        self.pending_question = None
        self.followups_used = 0

    async def _maybe_interrupt(self, now_ms: int) -> None:
        """SchedulerSnapshot → scheduler.eligible → orchestrator.decide → _ask / _fire_curveball
        (only a kind that was eligible). A failed decide is an error event, nothing more."""
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
        try:
            decision = await self.orchestrator.decide(
                self._context(now_ms, elig.question, elig.curveball_kinds))
        except Exception as exc:
            self._error(now_ms, "orchestrator.decide", exc)
            return
        if decision.action == "question" and elig.question:
            if self._grounded(decision) and decision.persona_id and decision.line:
                await self._ask(decision.persona_id, decision.line, now_ms, decision.reason,
                                decision.cited_transcript_excerpt, decision.slide_number)
        elif (decision.action == "curveball" and decision.curveball_kind
              and decision.curveball_kind in elig.curveball_kinds):
            kind = decision.curveball_kind
            persona_id = decision.persona_id if self.persona(decision.persona_id) else None
            if CATALOG[kind].speaker == "persona" and persona_id is None:
                persona_id = self._player_for(kind)
            await self._fire_curveball(kind, now_ms, decision.line, persona_id)

    def _grounded(self, decision) -> bool:
        """§13: a question without a cited excerpt or a slide number does not get asked."""
        if not self.persona(decision.persona_id):
            return False
        return bool(decision.cited_transcript_excerpt) or decision.slide_number is not None

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
            prior_qa=[{"persona_id": q["persona_id"], "q": q["question"],
                       "cited": q["cited_excerpt"], "a": q["answer"]}
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
            "curveball_id": curveball_id, "answer": None, "skipped": False,
            "asked_at_ms": now_ms,
        }
        self.questions.append(q)
        self._emit("question_queued", now_ms,
                   {k: v for k, v in q.items() if k not in ("answer", "skipped")})
        return q

    async def _ask(self, persona_id: str, question: str, now_ms: int, reason: str,
                   cited: str | None, slide_number: int | None,
                   follow_up_of: str | None = None, curveball_id: str | None = None) -> None:
        """Record, emit question_queued, INTERRUPTION → _speak → ANSWERING with the question
        pending. The phase moves on even if speech fails."""
        q = self._new_question(persona_id, question, now_ms, reason, cited, slide_number,
                               follow_up_of, curveball_id)
        if not curveball_id and self.phase == "presenting":
            self._set_phase("interruption", now_ms)
        await self._speak(persona_id, question, now_ms)
        self.pending_question = q
        self._set_phase("answering", now_ms)

    async def _handle_answer(self, now_ms: int, answer: str) -> None:
        """answer_received → orchestrator.follow_up. One follow-up max; then the ack line,
        the cooldown starts, a curveball question resolves "answered", and the room returns
        to presenting or Q&A."""
        q = self.pending_question
        assert q is not None
        q["answer"] = answer
        self._emit("answer_received", now_ms, {"question_id": q["question_id"], "answer": answer})
        persona = self.persona(q["persona_id"]) or self.config.personas[0]
        try:
            verdict = await self.orchestrator.follow_up(q["question"], answer, persona,
                                                        self.followups_used)
        except Exception as exc:
            self._error(now_ms, "orchestrator.follow_up", exc)
            verdict = None
        if verdict and verdict.verdict == "follow_up" and self.followups_used < 1:
            self.followups_used += 1
            await self._ask(q["persona_id"], verdict.line, now_ms, "follow-up", None,
                            q["slide_number"], follow_up_of=q["question_id"],
                            curveball_id=q["curveball_id"])
            return
        ack = verdict.line if verdict and verdict.verdict == "satisfied" else "Thanks — go on."
        await self._speak(q["persona_id"], ack, now_ms)
        self.pending_question = None
        self.followups_used = 0
        self.last_event_end_ms = now_ms
        if q["curveball_id"]:
            rec = next(r for r in self.curveballs.records if r.curveball_id == q["curveball_id"])
            await self._resolve(rec, now_ms, "answered")
            return
        if self.in_qna:
            self.qna_asked += 1
        self._set_phase(self._resting_phase(), now_ms)

    async def _speak(self, persona_id: str | None, line: str, now_ms: int,
                     style: str | None = None) -> None:
        """ai_speech_started → the voice seam → ai_speech_ended. Only one AI voice ever
        speaks. A voice failure is an error event; the pair of speech events still closes."""
        speaker = persona_id or "moderator"
        self._emit("ai_speech_started", now_ms, {"speaker": speaker, "line": line})
        try:
            if persona_id:
                persona = self.persona(persona_id)
                await self.voice.request_persona_turn(
                    persona_id, line, style or (persona.style_hint if persona else None))
            else:
                await self.voice.play_moderator_line(line)
        except Exception as exc:
            self._error(now_ms, "voice.speak", exc)
        self._emit("ai_speech_ended", now_ms, {"speaker": speaker})

    async def _skip(self, now_ms: int) -> None:
        """Skip the pending question (marking it skipped, not unanswered) or the active
        non-time_crunch curveball. Never penalised: a skipped curveball has recovery null."""
        q = self.pending_question
        active = self.curveballs.active
        target = None
        if q and q["curveball_id"]:
            target = next(r for r in self.curveballs.records
                          if r.curveball_id == q["curveball_id"])
        elif not q and active and active.kind != "time_crunch":
            target = active
        if not q and target is None:
            return
        try:
            await self.voice.cancel_speech()
        except Exception as exc:
            self._error(now_ms, "voice.cancel_speech", exc)
        self._emit("skipped", now_ms, {"question_id": q["question_id"] if q else None,
                                       "curveball_id": target.curveball_id if target else None})
        if q:
            q["skipped"] = True
            if self.in_qna:
                self.qna_asked += 1
        self.pending_question = None
        self.followups_used = 0
        self.last_event_end_ms = now_ms
        if target is not None:
            await self._resolve(target, now_ms, "skipped")
        else:
            self._set_phase(self._resting_phase(), now_ms)

    # ---- curveballs -------------------------------------------------------------------------

    async def _fire_curveball(self, kind: CurveballKind, now_ms: int, line: str | None,
                              persona_id: str | None) -> None:
        """curveballs.trigger → CURVEBALL → deliver (moderator / persona / sfx) → then:
        answerable kinds wait for an answer (ANSWERING), time_crunch keeps presenting with the
        countdown, everything else RECOVERING until resolved."""
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
            try:
                await self.voice.play_sfx(spec.sfx)
            except Exception as exc:
                self._error(now_ms, "voice.play_sfx", exc)
        if kind in ANSWERABLE:
            answerer = rec.persona_id or self._player_for(kind)
            self.pending_question = self._new_question(
                answerer, rec.line, now_ms, f"curveball:{kind}", None,
                self.slide_number, None, rec.curveball_id)
            self._set_phase("answering", now_ms)
        elif kind == "time_crunch":
            self.last_event_end_ms = now_ms  # the cooldown applies; the clock is the pressure
            self._set_phase("presenting", now_ms)
        else:
            self._set_phase("recovering", now_ms)

    async def _resolve(self, rec: CurveballRecord, now_ms: int, resolution: Resolution) -> None:
        """curveballs.resolve → the orchestrator's rubric score merged into the measured
        recovery (a failed assessment leaves the timing and no score) → event → cooldown →
        back to presenting / Q&A."""
        if rec.resolution is not None:
            if self.phase == "answering" and self.pending_question is None:
                self._set_phase(self._resting_phase(), now_ms)
            return
        event = self.curveballs.resolve(rec, now_ms, resolution, self.transcript, self.pauses)
        if rec.recovery is not None:
            after = [s for s in self.transcript
                     if rec.at_ms < s.start_ms <= rec.at_ms + RECOVERY_WINDOW_MS]
            try:
                assessment = await self.orchestrator.assess_recovery(
                    rec.kind, rec.line, after, rec.recovery.resume_after_ms)
                rec.recovery.score = assessment.score
                rec.recovery.evidence = assessment.evidence or rec.recovery.evidence
                rec.recovery.suggestion = assessment.suggestion
            except Exception as exc:
                self._error(now_ms, "orchestrator.assess_recovery", exc)
            event.payload["recovery"] = rec.recovery.model_dump()
        self.events.append(event)
        self.last_event_end_ms = now_ms
        if rec.kind == "time_crunch":
            return
        if self.phase in ("curveball", "recovering", "answering"):
            self.pending_question = None
            self._set_phase(self._resting_phase(), now_ms)

    # ---- the end --------------------------------------------------------------------------

    async def enter_qna(self, now_ms: int, crunch_resolution: Resolution = "answered") -> None:
        """Presenting is over: a pending question is cut off (skipped, not penalised), an
        open curveball resolves `timed_out`, an open time_crunch resolves `crunch_resolution`
        (the presenter closing before the deadline is `answered`) and its deadline is
        disarmed → QNA. qna_questions == 0 → finish."""
        if self.in_qna or self.ended:
            return
        if self.phase == "paused":
            self._unpause(now_ms)
            self.paused_phase = None
        self.in_qna = True  # before resolving, so the resting phase is already Q&A
        self._cut_off_pending(now_ms, "presentation ended")
        self.time_crunch_deadline_ms = None
        for rec in list(self.curveballs.records):
            if rec.resolution is None:
                await self._resolve(rec, now_ms,
                                    crunch_resolution if rec.kind == "time_crunch" else "timed_out")
        self._set_phase("qna", now_ms)
        if self.config.qna_questions == 0:
            await self.finish(now_ms)

    async def _qna_step(self, now_ms: int) -> None:
        if self.pending_question:
            return
        if self.qna_asked >= self.config.qna_questions:
            await self.finish(now_ms)
            return
        try:
            ctx = self._context(now_ms, True, [])
            ctx.qna = True
            ctx.recent_transcript = self.transcript[-12:]  # the whole talk's tail, not 30 s
            decision = await self.orchestrator.decide(ctx)
        except Exception as exc:
            self._error(now_ms, "orchestrator.decide", exc)
            await self.finish(now_ms)
            return
        if decision.action == "question" and self._grounded(decision) \
                and decision.persona_id and decision.line:
            await self._ask(decision.persona_id, decision.line, now_ms, decision.reason,
                            decision.cited_transcript_excerpt, decision.slide_number)
        else:
            await self.finish(now_ms)

    async def finish(self, now_ms: int) -> None:
        """Resolve leftovers timed_out, stop the voice, REPORT, build the report."""
        if self.ended:
            return
        self._cut_off_pending(now_ms, "session ended")
        for rec in self.curveballs.records:
            if rec.resolution is None:
                await self._resolve(rec, now_ms, "timed_out")
        self.time_crunch_deadline_ms = None
        try:
            await self.voice.stop_voice_session()
        except Exception as exc:
            self._error(now_ms, "voice.stop_voice_session", exc)
        self._set_phase("report", now_ms)
        self.report = build_report(self)
        self._emit("session_ended", now_ms,
                   {"report_url": f"/api/sessions/{self.session_id}/report"})
