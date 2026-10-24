"""The session: one conversation between the presenter and the panel.

Owner: Person C. Spec: CLAUDE.md §8. Tests: test_e2e_mock.py.

How it works: every presenter sentence (and every long silence) asks the brain one thing:
"what does the panel do now?" (`Orchestrator.turn`). The answer is to wait, or one panelist
says one line: a reply, a reaction, a question, a follow-up or a curveball. While a panelist
is talking the room ignores the mic, so the panel never hears itself.

Timebase: every `now_ms`, event `timestamp_ms` and transcript time is milliseconds since the
presentation started (the session clock). `clock` (set by main.py) reads it for work that
finishes later than it started, like a brain call.

Pause: paused time never counts. On resume, deadline-like timestamps move forward by the
paused duration (CLAUDE.md §2, §5.4).
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable
from typing import Any

from spec.contracts import (
    CurveballKind,
    Deck,
    PanelTurn,
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
from .services.audience import Line, Orchestrator, OrchestratorContext, Trigger
from .services.curveballs import CATALOG, CurveballEngine, CurveballRecord, paused_between
from .services.report import build_report
from .services.scheduler import Scheduler, SchedulerSnapshot
from .services.voice_base import VoiceAdapter

log = logging.getLogger(__name__)
_WORD = re.compile(r"[a-z0-9']+")


def _words(text: str) -> list[str]:
    return _WORD.findall(text.lower())

TIME_CRUNCH_MS = 60_000
RECOVERY_WINDOW_MS = 60_000
CONVERSATION_LINES = 24     # what the brain sees: the last ~two minutes of a call
SILENCE_MS = 5_000          # the presenter has gone quiet: the panel may fill the gap
ECHO_GUARD_MS = 500         # after a panelist stops, before the mic counts again
ECHO_OVERLAP = 0.6          # this share of the words were the panelist's own: it's echo
WORD_MS = 350               # speech-length estimate when the voice can't say
SLIDE_CURVEBALLS: set[CurveballKind] = {"slides_down", "elevator"}
# Curveballs that are a question in disguise: the presenter's next words answer them.
ANSWERABLE: set[CurveballKind] = {
    "heckler", "latecomer", "bait", "fact_check", "plain_language", "vip_arrives", "crosstalk",
}
PERSONA_STYLE: dict[CurveballKind, str] = {"heckler": "impatient", "fact_check": "impatient"}
LIVE_PHASES: set[SessionPhase] = {"presenting", "qna"}


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
        background: bool = False,
    ) -> None:
        self.session_id = session_id
        self.config = config
        self.preset = preset
        self.orchestrator = orchestrator
        self.voice = voice
        self.deck = deck
        # True in the server: brain calls run beside the room, so the mic is never blocked.
        # False in tests: every call finishes before the method returns (deterministic).
        self.background = background
        self.phase: SessionPhase = "setup"
        self.events: list[SessionEvent] = []
        self.transcript: list[TranscriptSegment] = []
        self.lines: list[Line] = []  # the conversation, presenter and panel
        # question dicts: question_id, persona_id, question, reason, cited_excerpt,
        # slide_number, follow_up_of, curveball_id, answer, skipped, asked_at_ms
        self.questions: list[dict[str, Any]] = []
        self.open_question: dict[str, Any] | None = None
        self.followups_used = 0
        self.curveballs = CurveballEngine(session_id)
        allowed: list[CurveballKind] = [k for k in preset.curveballs_allowed
                                        if deck is not None or k not in SLIDE_CURVEBALLS]
        self.scheduler = Scheduler(config.difficulty, config.interruption_frequency,
                                   config.curveballs, allowed, curveballs_enabled)
        self.start_ms: int | None = None
        self.slide_number = 1
        self.slide_changed_at_ms: int | None = None
        self.last_presenter_speech_ms: int | None = None
        self.last_panel_ms: int | None = None
        self.speaking_until_ms = 0
        self.paused_phase: SessionPhase | None = None
        self.paused_at_ms: int | None = None
        self.pauses: list[tuple[int, int]] = []
        self.time_crunch_deadline_ms: int | None = None
        self.in_qna = False
        self.qna_asked = 0
        self.report: Report | None = None
        self.clock: Callable[[], int] | None = None
        self.on_append: Callable[[], None] | None = None
        self._clock_ms = 0
        self._question_counter = 0
        self._silence_armed = False  # the presenter spoke since the panel last considered them
        self._thinking: asyncio.Task[None] | None = None
        self._pending: Trigger | None = None
        self.voice.on_event(self._on_voice_event)

    async def _on_voice_event(self, ev: SessionEvent) -> None:
        self.events.append(ev.model_copy(update={"session_id": self.session_id,
                                                 "timestamp_ms": self._now()}))
        if self.on_append:
            self.on_append()

    # ---- helpers ---------------------------------------------------------------------------

    @property
    def ended(self) -> bool:
        return self.phase == "report"

    def _now(self) -> int:
        return self.clock() if self.clock else self._clock_ms

    def elapsed_ms(self, now_ms: int) -> int:
        return 0 if self.start_ms is None else now_ms - self.start_ms

    def persona(self, persona_id: str | None) -> Persona | None:
        return next((p for p in self.config.personas if p.id == persona_id), None)

    def drain(self, since: int) -> list[SessionEvent]:
        return self.events[since:]

    def _append(self, ev: SessionEvent) -> None:
        self._clock_ms = max(self._clock_ms, ev.timestamp_ms)
        self.events.append(ev)
        if self.background and self.on_append:
            self.on_append()  # work finishing outside a room action still reaches the browser

    def _emit(self, type_: str, now_ms: int, payload: dict[str, Any] | None = None) -> None:
        self._append(SessionEvent(type=type_, session_id=self.session_id,  # type: ignore[arg-type]
                                  timestamp_ms=now_ms, payload=payload or {}))

    def _error(self, now_ms: int, where: str, exc: Exception) -> None:
        """A failed brain or voice call is logged and shown; the session keeps going (§8)."""
        message = f"{type(exc).__name__}: {exc}".rstrip(": ")
        log.warning("%s failed in %s: %s", self.session_id, where, message)
        self._emit("error", now_ms, {"where": where, "message": message[:300]})

    def _set_phase(self, phase: SessionPhase, now_ms: int) -> None:
        if phase != self.phase:
            previous, self.phase = self.phase, phase
            self._emit("phase_changed", now_ms, {"from": previous, "to": phase})

    def _player_for(self, kind: CurveballKind) -> str:
        players = [p for p in self.config.personas if kind in p.plays] or self.config.personas
        return players[0].id

    # ---- presenter-side inputs (main.py, from the WebSocket) ------------------------------

    async def start(self, now_ms: int) -> None:
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
        await self._kick("joined")  # someone says hello, in their own words

    async def slide_changed(self, now_ms: int, number: int) -> None:
        self.slide_number = number
        self.slide_changed_at_ms = now_ms
        self._emit("slide_changed", now_ms, {"slide_number": number})

    async def presenter_transcript(self, now_ms: int, seg: TranscriptSegment) -> None:
        """One finished presenter sentence. Dropped while paused, ended, or while a panelist
        is talking (that is the panel's own voice coming back through the mic)."""
        if self.phase not in LIVE_PHASES or seg.speaker != "presenter":
            return
        if now_ms < self.speaking_until_ms and self._is_echo(seg.text):
            return
        self.transcript.append(seg)
        self.lines.append(Line("presenter", seg.text, seg.start_ms))
        self.last_presenter_speech_ms = seg.end_ms if seg.end_ms is not None else seg.start_ms
        self._silence_armed = True
        self._emit("transcript_segment", now_ms, seg.model_dump())
        active = self.curveballs.active
        if active and (active.kind == "distraction" or active.kind in ANSWERABLE):
            await self._resolve(active, now_ms, "answered" if active.kind in ANSWERABLE
                                else "auto_restored")
        q = self.open_question
        if q is not None:
            q["answer"] = f"{q['answer']} {seg.text}" if q["answer"] else seg.text
            self._emit("answer_received", now_ms,
                       {"question_id": q["question_id"], "answer": seg.text})
        await self._kick("spoke")

    def _is_echo(self, text: str) -> bool:
        """While a panelist talks, the mic can pick their voice back up. Drop only what is
        mostly their own words, so a presenter who talks over them is still heard."""
        panel = next((ln for ln in reversed(self.lines) if ln.speaker != "presenter"), None)
        heard = set(_words(text))
        if panel is None or not heard:
            return False
        return len(heard & set(_words(panel.text))) / len(heard) >= ECHO_OVERLAP

    async def control(self, action: str, now_ms: int) -> None:
        """pause · resume · skip · restore_slides · end. Pause and Skip are never penalised."""
        if action == "pause" and self.phase in LIVE_PHASES:
            self.paused_phase, self.paused_at_ms = self.phase, now_ms
            self._set_phase("paused", now_ms)
            self._emit("paused", now_ms)
            self.speaking_until_ms = 0
            await self._cancel_voice(now_ms)
        elif action == "resume" and self.phase == "paused":
            self._unpause(now_ms)
            self._set_phase(self.paused_phase or "presenting", now_ms)
            self.paused_phase = None
            self._emit("resumed", now_ms)
        elif action == "skip" and self.phase in LIVE_PHASES:
            await self._skip(now_ms)
        elif action == "restore_slides" and self.phase in LIVE_PHASES:
            active = self.curveballs.active
            if active and active.kind in SLIDE_CURVEBALLS:
                await self._resolve(active, now_ms, "presenter_restored")
        elif action == "end":
            if self.in_qna:
                await self.finish(now_ms)
            elif self.phase in LIVE_PHASES or self.phase == "paused":
                await self.enter_qna(now_ms)

    async def force_curveball(self, kind: CurveballKind, now_ms: int) -> None:
        """Debug/demo only (CLAUDE.md §7): no-op unless presenting with nothing active."""
        if self.phase != "presenting" or self.curveballs.active:
            return
        persona_id = self._player_for(kind) if CATALOG[kind].speaker == "persona" else None
        await self._fire_curveball(kind, now_ms, None, persona_id)

    # ---- the clock (main.py ticks every second) ---------------------------------------------

    async def tick(self, now_ms: int) -> None:
        if self.phase not in LIVE_PHASES:
            return
        self._clock_ms = max(self._clock_ms, now_ms)
        if self.time_crunch_deadline_ms is not None and now_ms >= self.time_crunch_deadline_ms:
            self.time_crunch_deadline_ms = None
            self._emit("timer_override", now_ms, {"remaining_ms": 0, "style": "expired"})
            await self.enter_qna(now_ms, crunch_resolution="timed_out")
            return
        active = self.curveballs.active
        due = self.curveballs.due_for_auto_resolve(
            now_ms, paused_between(self.pauses, active.at_ms, now_ms) if active else 0)
        if due:
            await self._resolve(due, now_ms, "auto_restored")
        quiet_for = (None if self.last_presenter_speech_ms is None
                     else now_ms - self.last_presenter_speech_ms)
        if (self.phase == "presenting" and self._silence_armed and quiet_for is not None
                and quiet_for >= SILENCE_MS and now_ms >= self.speaking_until_ms):
            self._silence_armed = False
            await self._kick("silence")

    # ---- thinking: one brain call, then at most one line --------------------------------

    async def _kick(self, trigger: Trigger) -> None:
        """Ask the brain what happens next. In the server this runs beside the room, and a
        sentence that lands while the brain is busy is folded into the next call."""
        if not self.background:
            await self._think(trigger)
            return
        if self._thinking is not None and not self._thinking.done():
            self._pending = trigger
            return
        self._pending = None
        self._thinking = asyncio.get_running_loop().create_task(self._think_loop(trigger))

    async def _think_loop(self, trigger: Trigger) -> None:
        while True:
            try:
                await self._think(trigger)
            except Exception as exc:  # a background think never dies silently
                self._error(self._now(), "engine.think", exc)
            if self._pending is None:
                return
            trigger, self._pending = self._pending, None

    async def _think(self, trigger: Trigger) -> None:
        if self.phase not in LIVE_PHASES:
            return
        if self.in_qna and self.open_question is None:
            trigger = "qna"  # between closing questions: the panel asks the next one
        now = self._now()
        ctx = self._context(now, trigger)
        try:
            turn = await self.orchestrator.turn(ctx)
        except Exception as exc:
            self._error(now, "orchestrator.turn", exc)
            turn = None
        if self.phase not in LIVE_PHASES:
            return  # paused or ended while the brain was thinking
        now = self._now()
        if (turn is not None and turn.action == "curveball"
                and turn.curveball_kind in ctx.eligible_kinds
                and self.phase == "presenting" and self.curveballs.active is None):
            assert turn.curveball_kind is not None
            await self._fire_curveball(turn.curveball_kind, now, turn.line, turn.persona_id)
        elif (turn is not None and turn.action == "speak" and turn.line
                and self.persona(turn.persona_id)):
            await self._say(turn, now)
        else:
            self._close_answered()
        if self.in_qna and self.open_question is None and self.phase == "qna":
            if self.qna_asked >= self.config.qna_questions or trigger == "qna":
                await self.finish(self._now())  # out of questions, or nothing left to ask
            else:
                await self._kick("qna")  # that thread is done: the next closing question

    def _context(self, now_ms: int, trigger: Trigger) -> OrchestratorContext:
        eligible: list[CurveballKind] = []
        if self.phase == "presenting" and self.curveballs.active is None:
            snap = SchedulerSnapshot(
                phase="presenting", elapsed_ms=self.elapsed_ms(now_ms), questions_asked=0,
                curveballs_fired=len(self.curveballs.records),
                fired_kinds=self.curveballs.fired_kinds, last_event_end_ms=self.last_panel_ms,
                last_presenter_speech_ms=self.last_presenter_speech_ms,
                slide_number=self.slide_number, slide_changed_at_ms=self.slide_changed_at_ms,
                duration_target_s=self.config.duration_target_s, now_ms=now_ms)
            eligible = self.scheduler.eligible(snap).curveball_kinds
        q = self.open_question
        return OrchestratorContext(
            preset_id=self.config.preset_id,
            difficulty=self.config.difficulty,
            personas=self.config.personas,
            slide_number=self.slide_number,
            slide_text=slides.slide_text(self.deck, self.slide_number),
            conversation=self.lines[-CONVERSATION_LINES:],
            trigger=trigger,
            elapsed_s=self.elapsed_ms(now_ms) // 1000,
            seconds_since_panel_spoke=(None if self.last_panel_ms is None
                                       else (now_ms - self.last_panel_ms) // 1000),
            open_question=Line(q["persona_id"], q["question"], q["asked_at_ms"]) if q else None,
            follow_ups_used=self.followups_used,
            questions_asked=self._questions_asked(),
            question_budget=self.scheduler.question_budget,
            eligible_kinds=eligible,
            curveball_budget_remaining=max(
                0, self.scheduler.curveball_budget - len(self.curveballs.records)),
            qna_left=max(0, self.config.qna_questions - self.qna_asked),
        )

    def _questions_asked(self) -> int:
        return len([q for q in self.questions if not q["follow_up_of"] and not q["curveball_id"]])

    async def _say(self, turn: PanelTurn, now_ms: int) -> None:
        """One panelist speaks. A question opens a thread (a follow-up stays on it); anything
        else closes a thread that has been answered."""
        assert turn.persona_id and turn.line
        q = self.open_question
        if turn.is_question:
            if (q is not None and q["answer"] and q["persona_id"] == turn.persona_id
                    and self.followups_used < 1 and not q["curveball_id"]):
                self.followups_used += 1
                q = self._new_question(turn.persona_id, turn.line, now_ms, "follow-up",
                                       None, q["question_id"], None)
            else:
                self._close_answered(force=True)
                q = self._new_question(turn.persona_id, turn.line, now_ms, turn.reason,
                                       turn.cited_transcript_excerpt, None, None)
                if self.in_qna:
                    self.qna_asked += 1
            self.open_question = q
        else:
            self._close_answered()
        await self._speak(turn.persona_id, turn.line, now_ms, turn.mood)

    def _close_answered(self, force: bool = False) -> None:
        """A thread is over once it has an answer (or, with `force`, when another starts)."""
        q = self.open_question
        if q is not None and (q["answer"] or force):
            self.open_question = None
            self.followups_used = 0

    def _new_question(self, persona_id: str, question: str, now_ms: int, reason: str,
                      cited: str | None, follow_up_of: str | None,
                      curveball_id: str | None) -> dict[str, Any]:
        self._question_counter += 1
        q: dict[str, Any] = {
            "question_id": f"q-{self._question_counter}", "persona_id": persona_id,
            "question": question, "reason": reason, "cited_excerpt": cited,
            "slide_number": self.slide_number, "follow_up_of": follow_up_of,
            "curveball_id": curveball_id, "answer": None, "skipped": False,
            "asked_at_ms": now_ms,
        }
        self.questions.append(q)
        self._emit("question_queued", now_ms,
                   {k: v for k, v in q.items() if k not in ("answer", "skipped")})
        return q

    async def _speak(self, persona_id: str | None, line: str, now_ms: int,
                     style: str | None = None) -> None:
        """ai_speech_started → the voice → ai_speech_ended. The mic is ignored until the
        line has finished playing, so the panel never answers its own voice."""
        speaker = persona_id or "moderator"
        self._emit("ai_speech_started", now_ms, {"speaker": speaker, "line": line})
        seconds: float | None = None
        try:
            if persona_id:
                persona = self.persona(persona_id)
                seconds = await self.voice.request_persona_turn(
                    persona_id, line, style or (persona.style_hint if persona else None))
            else:
                seconds = await self.voice.play_moderator_line(line)
        except Exception as exc:
            self._error(now_ms, "voice.speak", exc)
        done = max(now_ms, self._now())
        length_ms = int(seconds * 1000) if seconds is not None else len(line.split()) * WORD_MS
        self.speaking_until_ms = max(self.speaking_until_ms, done) + length_ms + ECHO_GUARD_MS
        self.lines.append(Line(speaker, line, now_ms))
        self.last_panel_ms = now_ms
        self._emit("ai_speech_ended", done, {"speaker": speaker})

    async def _cancel_voice(self, now_ms: int) -> None:
        try:
            await self.voice.cancel_speech()
        except Exception as exc:
            self._error(now_ms, "voice.cancel_speech", exc)

    async def _skip(self, now_ms: int) -> None:
        """Skip the open question or the active curveball (not time_crunch). Never penalised."""
        q = self.open_question
        active = self.curveballs.active
        target = active if active and active.kind != "time_crunch" else None
        if q is None and target is None:
            return
        await self._cancel_voice(now_ms)
        self.speaking_until_ms = 0
        self._emit("skipped", now_ms, {"question_id": q["question_id"] if q else None,
                                       "curveball_id": target.curveball_id if target else None})
        if q is not None:
            q["skipped"] = True
            self.open_question = None
            self.followups_used = 0
        if target is not None:
            await self._resolve(target, now_ms, "skipped")

    def _unpause(self, now_ms: int) -> None:
        if self.paused_at_ms is None:
            return
        delta = now_ms - self.paused_at_ms
        self.pauses.append((self.paused_at_ms, now_ms))
        self.paused_at_ms = None
        if delta <= 0:
            return
        if self.start_ms is not None:
            self.start_ms += delta
        if self.time_crunch_deadline_ms is not None:
            self.time_crunch_deadline_ms += delta
        if self.last_panel_ms is not None:
            self.last_panel_ms += delta
        if self.last_presenter_speech_ms is not None:
            self.last_presenter_speech_ms += delta
        if self.slide_changed_at_ms is not None:
            self.slide_changed_at_ms += delta

    # ---- curveballs -------------------------------------------------------------------------

    async def _fire_curveball(self, kind: CurveballKind, now_ms: int, line: str | None,
                              persona_id: str | None) -> None:
        spec = CATALOG[kind]
        if spec.speaker == "persona" and not self.persona(persona_id):
            persona_id = self._player_for(kind)
        rec, event = self.curveballs.trigger(kind, now_ms, line, persona_id)
        self._append(event)
        self._close_answered(force=True)
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
            self.open_question = self._new_question(
                rec.persona_id or self._player_for(kind), rec.line, now_ms, f"curveball:{kind}",
                None, None, rec.curveball_id)

    async def _resolve(self, rec: CurveballRecord, now_ms: int, resolution: Resolution) -> None:
        """Timing is measured now; the rubric score is added in `finish`, so a slow
        assessment never holds up the call."""
        if rec.resolution is None:
            self._append(self.curveballs.resolve(rec, now_ms, resolution, self.transcript,
                                                 self.pauses))

    async def _assess(self, rec: CurveballRecord) -> None:
        if rec.recovery is None:
            return
        after = [s for s in self.transcript
                 if rec.at_ms < s.start_ms <= rec.at_ms + RECOVERY_WINDOW_MS]
        try:
            a = await self.orchestrator.assess_recovery(rec.kind, rec.line, after,
                                                        rec.recovery.resume_after_ms)
        except Exception as exc:
            self._error(self._now(), "orchestrator.assess_recovery", exc)
            return
        rec.recovery.score = a.score
        rec.recovery.evidence = a.evidence or rec.recovery.evidence
        rec.recovery.suggestion = a.suggestion

    # ---- the end --------------------------------------------------------------------------

    async def enter_qna(self, now_ms: int, crunch_resolution: Resolution = "answered") -> None:
        if self.in_qna or self.ended:
            return
        if self.phase == "paused":
            self._unpause(now_ms)
            self.paused_phase = None
        self.in_qna = True
        self._cut_off_open(now_ms, "presentation ended")
        self.time_crunch_deadline_ms = None
        for rec in list(self.curveballs.records):
            if rec.resolution is None:
                await self._resolve(rec, now_ms,
                                    crunch_resolution if rec.kind == "time_crunch" else "timed_out")
        self._set_phase("qna", now_ms)
        if self.config.qna_questions == 0:
            await self.finish(now_ms)
        else:
            await self._kick("qna")

    def _cut_off_open(self, now_ms: int, reason: str) -> None:
        """The room, not the presenter, ended an unanswered question: skipped, never
        "unanswered"."""
        q = self.open_question
        if q is None:
            return
        if not q["answer"]:
            q["skipped"] = True
            q["cut_off"] = reason
            self._emit("skipped", now_ms, {"question_id": q["question_id"],
                                           "curveball_id": q["curveball_id"], "reason": reason})
        self.open_question = None
        self.followups_used = 0

    async def finish(self, now_ms: int) -> None:
        if self.ended:
            return
        self._cut_off_open(now_ms, "session ended")
        for rec in self.curveballs.records:
            if rec.resolution is None:
                await self._resolve(rec, now_ms, "timed_out")
        self.time_crunch_deadline_ms = None
        self._set_phase("report", now_ms)
        await asyncio.gather(*(self._assess(r) for r in self.curveballs.records))
        try:
            await self.voice.stop_voice_session()
        except Exception as exc:
            self._error(now_ms, "voice.stop_voice_session", exc)
        self.report = build_report(self)
        self._emit("session_ended", now_ms,
                   {"report_url": f"/api/sessions/{self.session_id}/report"})
