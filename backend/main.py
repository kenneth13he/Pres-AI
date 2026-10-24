"""FastAPI: REST + WebSocket API, and the static frontend, in one process (CLAUDE.md §4, §7).

Routes are registered before the static mounts so `/api/*`, `/ws/*` and `/health` win.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from spec.contracts import (
    ControlAction,
    CurveballKind,
    Persona,
    SessionConfig,
    SessionEvent,
    TranscriptSegment,
)

from . import presets
from .engine import Session
from .services import slides
from .services.audience import ClaudeOrchestrator, MockOrchestrator, Orchestrator
from .services.audience_boson import BosonOrchestrator
from .services.curveballs import CATALOG
from .services.reasoning_budget import diagnostics as reasoning_budget_status
from .services.voice_base import VoiceAdapter
from .services.voice_higgs import HiggsVoice, SpendCounter
from .services.voice_mock import MockVoice
from .session_records import SessionRecords
from .voice_routes import install_voice_routes

load_dotenv()
ROOT = Path(__file__).resolve().parents[1]
TICK_S = 1.0
SESSION_RECORDS = SessionRecords(ROOT / "data" / "sessions")


def wall_ms() -> int:
    return int(time.time() * 1000)


def reasoning_status(orchestrator: Orchestrator) -> dict[str, Any]:
    diagnostic = getattr(orchestrator, "diagnostics", None)
    result = diagnostic() if callable(diagnostic) else None
    return result if isinstance(result, dict) else {"adapter": "unknown", "model": None}


class Room:
    """A live session plus its WebSocket subscribers and its ticker task.

    Timebase: the engine and every event use the *session clock* — ms since the presenter
    pressed Start (engine.py docstring). `t0` is set when `presentation_started` arrives, so
    the browser's own relative timestamps line up with ours."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.sockets: set[WebSocket] = set()
        self.sent = 0
        self.ticker: asyncio.Task[None] | None = None
        self.workers: set[asyncio.Task[None]] = set()
        self.active_task: asyncio.Task[Any] | None = None
        self.lock = asyncio.Lock()
        self.flush_lock = asyncio.Lock()
        self.t0: int | None = None
        self.record_attempted = False
        self.reasoning_problems_seen = 0
        brain = reasoning_status(session.orchestrator)
        self.run_settings = {
            "voice_adapter": "higgs" if isinstance(session.voice, HiggsVoice) else "mock",
            "orchestrator": brain["adapter"], "model": brain.get("model"),
            "avatar_enabled": os.environ.get("BOSON_AVATAR_ENABLED", "false") == "true",
            "debug_curveball_endpoint": (
                os.environ.get("DEBUG_CURVEBALL_ENDPOINT", "true") == "true"),
        }
        session.voice.on_event(self.voice_event)

    async def voice_event(self, event: SessionEvent) -> None:
        event.timestamp_ms = self.now_ms()
        self.session.events.append(event)
        await self.flush()

    def now_ms(self) -> int:
        return 0 if self.t0 is None else wall_ms() - self.t0

    async def flush(self) -> None:
        async with self.flush_lock:
            await self._flush()

    async def _flush(self) -> None:
        if (self.session.phase == "report" and self.session.report is not None
                and not self.record_attempted):
            self.record_attempted = True
            try:
                SESSION_RECORDS.save(session_snapshot(self), self.session.report.model_dump())
            except (OSError, ValueError, TypeError):
                self.session.events.append(SessionEvent(
                    type="error", session_id=self.session.session_id,
                    timestamp_ms=self.now_ms(),
                    payload={"where": "session.save",
                             "message": ("The report is available, but its local backup "
                                         "could not be saved.")},
                ))
        pending = self.session.drain(self.sent)
        self.sent = len(self.session.events)
        for ev in pending:
            data = ev.model_dump_json()
            for ws in list(self.sockets):
                try:
                    await ws.send_text(data)
                except Exception:
                    self.sockets.discard(ws)

    async def run(self, coro) -> None:
        started = False
        try:
            async with self.lock:
                started = True
                self.active_task = asyncio.current_task()
                try:
                    await coro
                except Exception as exc:  # a failed LLM/TTS call never breaks the session
                    self.session.events.append(SessionEvent(
                        type="error", session_id=self.session.session_id,
                        timestamp_ms=self.now_ms(), payload={"message": str(exc)[:300]},
                    ))
                finally:
                    self.active_task = None
                diagnostic = reasoning_status(self.session.orchestrator)
                totals = diagnostic.get("totals") or {}
                problems = totals.get("failures", 0) + totals.get("rejections", 0)
                if problems > self.reasoning_problems_seen:
                    self.reasoning_problems_seen = problems
                    self.session.events.append(SessionEvent(
                        type="error", session_id=self.session.session_id,
                        timestamp_ms=self.now_ms(),
                        payload={"where": "orchestrator.fallback",
                                 "message": ("Audience reasoning could not complete that turn. "
                                             "A safe fallback was used; this run needs review.")},
                    ))
                await self.flush()
        finally:
            if not started:
                coro.close()  # cancellation while waiting for the lock must not leak a coroutine

    async def prepare_control(self, action: str) -> None:
        """Controls invalidate a slow audience call before waiting for its room lock."""
        if action not in ("pause", "skip", "end"):
            return
        self.session.prepare_control(action)
        try:
            await self.session.voice.cancel_speech()
        except Exception:
            self.session.events.append(SessionEvent(
                type="error", session_id=self.session.session_id, timestamp_ms=self.now_ms(),
                payload={"where": "voice.cancel_speech",
                         "message": "Audio cancellation failed; the control still applies."},
            ))

    async def tick_forever(self) -> None:
        while not self.session.ended:
            await asyncio.sleep(TICK_S)
            await self.run(self.session.tick(self.now_ms()))


ROOMS: dict[str, Room] = {}


def make_orchestrator() -> Orchestrator:
    mode = os.environ.get("ORCHESTRATOR", "mock")
    if mode == "mock":
        return MockOrchestrator()
    if mode == "claude" and os.environ.get("ANTHROPIC_API_KEY"):
        return ClaudeOrchestrator()
    if mode == "boson" and os.environ.get("BOSON_API_KEY"):
        return BosonOrchestrator(max_output_tokens=int(
            os.environ.get("BOSON_REASONING_MAX_OUTPUT_TOKENS", "768")))
    raise HTTPException(503, "The selected audience model is not configured. "
                        "No test fallback was used.")


def make_voice() -> VoiceAdapter:
    if os.environ.get("VOICE_ADAPTER", "mock") == "higgs" and os.environ.get("BOSON_API_KEY"):
        return HiggsVoice()
    return MockVoice()


@asynccontextmanager
async def lifespan(_: FastAPI):
    presets.presets()  # fail fast on a bad YAML
    yield
    tasks = []
    for room in ROOMS.values():
        room.session.presenter_turn_cancelled()
        if room.ticker:
            room.ticker.cancel()
            tasks.append(room.ticker)
        for worker in room.workers:
            worker.cancel()
            tasks.append(worker)
        try:
            await room.session.voice.stop_voice_session()
        except Exception:
            pass  # shutting down one disconnected room must not leak the others
    if tasks:
        try:
            async with asyncio.timeout(2):
                await asyncio.gather(*tasks, return_exceptions=True)
        except TimeoutError:
            pass


app = FastAPI(title="PresAI", lifespan=lifespan)


# ---- REST ---------------------------------------------------------------------------


@app.get("/health")
def health() -> dict[str, Any]:
    configured = os.environ.get("ORCHESTRATOR", "mock")
    effective = configured if configured == "mock" or (
        configured == "claude" and os.environ.get("ANTHROPIC_API_KEY")
        or configured == "boson" and os.environ.get("BOSON_API_KEY")) else "unavailable"
    return {
        "ok": effective != "unavailable",
        "adapters": {
            "voice": os.environ.get("VOICE_ADAPTER", "mock"),
            "orchestrator": effective,
            "orchestrator_configured": configured,
            "boson_key": bool(os.environ.get("BOSON_API_KEY")),
            "anthropic_key": bool(os.environ.get("ANTHROPIC_API_KEY")),
            "avatar": os.environ.get("BOSON_AVATAR_ENABLED", "false") == "true",
        },
        "spend": {"tts_chars": SpendCounter.tts_chars, "realtime_ms": SpendCounter.realtime_ms,
                  "estimate_usd": round(SpendCounter.estimate_usd(), 3),
                  "soft_cap_usd": float(os.environ.get("SPEND_SOFT_CAP_USD", "60")),
                  "reasoning": reasoning_budget_status()},
        "sessions": len(ROOMS),
    }


@app.get("/api/presets")
def list_presets() -> dict[str, Any]:
    return {
        "presets": [p.model_dump() for p in presets.presets().values()],
        "personas": [p.model_dump() for p in presets.personas().values()],
        "curveballs": [
            {"kind": k, "speaker": s.speaker, "priority": s.priority, "line": s.default_line}
            for k, s in CATALOG.items()
        ],
    }


@app.post("/api/slides")
async def upload_slides(file: Annotated[UploadFile, File()]) -> dict[str, Any]:
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(400, "upload a PDF")
    try:  # rendering takes seconds for a big deck; keep the event loop (and rooms) free
        deck = await run_in_threadpool(slides.ingest_pdf, await file.read(),
                                       file.filename or "deck.pdf")
    except slides.DeckError as exc:
        raise HTTPException(400, str(exc)) from exc
    return deck.model_dump()


class CreateSession(BaseModel):
    config: SessionConfig
    custom_personas: list[str] = []  # free-text descriptions → expanded into Persona (P0-3b)


@app.post("/api/sessions")
async def create_session(body: CreateSession) -> dict[str, Any]:
    preset = presets.presets().get(body.config.preset_id)
    if preset is None and body.config.preset_id != "custom":
        raise HTTPException(404, "unknown preset")
    if preset is None:
        preset = presets.presets()["startup_pitch"].model_copy(
            update={"id": "custom", "name": "Custom", "curveballs_allowed": list(CATALOG)})
    orchestrator = make_orchestrator()
    extra: list[Persona] = [
        await orchestrator.expand_persona(text, i + 1)
        for i, text in enumerate(body.custom_personas)
    ]
    config = body.config.model_copy(update={"personas": (body.config.personas + extra)[:3]})
    if len(config.personas) < 2:
        raise HTTPException(400, "pick at least two personas")
    session_id = uuid.uuid4().hex[:8]
    session = Session(
        session_id, config, preset, orchestrator, make_voice(),
        deck=slides.get_deck(config.deck_id),
        curveballs_enabled=os.environ.get("CURVEBALLS_ENABLED", "true") == "true",
    )
    ROOMS[session_id] = Room(session)
    return {"session_id": session_id, "config": config.model_dump(), "preset": preset.model_dump()}


def _room(session_id: str) -> Room:
    room = ROOMS.get(session_id)
    if room is None:
        raise HTTPException(404, "no such session")
    return room


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str) -> dict[str, Any]:
    if session_id in ROOMS:
        return session_snapshot(ROOMS[session_id])
    saved = SESSION_RECORDS.load(session_id)
    if saved is not None:
        return saved["snapshot"]
    raise HTTPException(404, "no such session")


def session_snapshot(room: Room) -> dict[str, Any]:
    s = room.session
    timer_now = (s.paused_at_ms if s.phase == "paused" and s.paused_at_ms is not None
                 else room.now_ms())
    return {
        "session_id": s.session_id, "phase": s.phase, "config": s.config.model_dump(),
        "preset": s.preset.model_dump(), "slide_number": s.slide_number,
        "elapsed_ms": (s.elapsed_ms(timer_now)
                       if s.start_ms is not None else 0),
        "session_clock_ms": room.now_ms(),
        "timer_remaining_ms": (max(0, s.time_crunch_deadline_ms - timer_now)
                               if s.time_crunch_deadline_ms is not None else None),
        "deck": s.deck.model_dump() if s.deck else None,
        "events": [e.model_dump() for e in s.events],
        "reasoning": reasoning_status(s.orchestrator), "run_settings": dict(room.run_settings),
    }


class Control(BaseModel):
    action: ControlAction


@app.post("/api/sessions/{session_id}/control")
async def control(session_id: str, body: Control) -> dict[str, str]:
    room = _room(session_id)
    await room.prepare_control(body.action)
    await room.run(room.session.control(body.action, room.now_ms()))
    return {"phase": room.session.phase}


class ForceCurveball(BaseModel):
    kind: CurveballKind


@app.post("/api/sessions/{session_id}/curveball")
async def force_curveball(session_id: str, body: ForceCurveball) -> dict[str, str]:
    if os.environ.get("DEBUG_CURVEBALL_ENDPOINT", "true") != "true":
        raise HTTPException(403, "debug endpoint disabled")
    room = _room(session_id)
    await room.run(room.session.force_curveball(body.kind, room.now_ms()))
    return {"phase": room.session.phase}


@app.get("/api/sessions/{session_id}/report")
def get_report(session_id: str) -> dict[str, Any]:
    if session_id not in ROOMS:
        saved = SESSION_RECORDS.load(session_id)
        if saved is not None:
            return saved["report"]
        raise HTTPException(404, "no such session")
    s = _room(session_id).session
    if s.report is None:
        raise HTTPException(409, "session not finished")
    return s.report.model_dump()


# ---- WebSocket ----------------------------------------------------------------------


@app.websocket("/ws/sessions/{session_id}")
async def ws_session(ws: WebSocket, session_id: str) -> None:
    room = ROOMS.get(session_id)
    if room is None:
        await ws.close(code=4404)
        return
    await ws.accept()
    room.sockets.add(ws)
    captured_turn_ids: set[str] = set()
    jobs: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=64)
    closing = False

    def is_control(message: dict[str, Any]) -> bool:
        return message.get("type") in ("control", "presentation_ended")

    async def work() -> None:
        while True:
            message = await jobs.get()
            if message is None:
                return
            if closing and not is_control(message):
                continue
            try:
                await _handle_client_message(room, message, control_prepared=True)
            except Exception:
                room.session.events.append(SessionEvent(
                    type="error", session_id=session_id, timestamp_ms=room.now_ms(),
                    payload={"message": "A room input could not be processed."},
                ))
                await room.flush()

    worker = asyncio.create_task(work())
    room.workers.add(worker)
    worker.add_done_callback(room.workers.discard)
    for ev in room.session.events:  # replay so a reconnecting room catches up
        await ws.send_text(ev.model_dump_json())
    try:
        while True:
            msg = json.loads(await ws.receive_text())
            kind = msg.get("type")
            if kind == "presenter_turn_started":
                captured_turn_ids.add(str(msg.get("turn_id") or "legacy"))
            if kind in ("presenter_turn_started", "presenter_turn_ended",
                        "presenter_turn_cancelled", "presenter_speech_activity"):
                # Keep reading these even while the worker awaits a follow-up or speech.
                await _handle_client_message(room, msg)
            elif kind == "presentation_started" and room.session.phase == "setup":
                await _handle_client_message(room, msg)
            else:
                if is_control(msg):
                    action = "end" if kind == "presentation_ended" else str(msg.get("action"))
                    await room.prepare_control(action)
                try:
                    jobs.put_nowait(msg)
                except asyncio.QueueFull:
                    await ws.close(code=4429, reason="Too many pending room actions.")
                    break
    except WebSocketDisconnect:
        pass
    finally:
        closing = True
        room.sockets.discard(ws)
        if room.session.presenter_turn_id in captured_turn_ids:
            room.session.presenter_turn_cancelled(room.session.presenter_turn_id)
        if room.active_task is worker:
            room.session.invalidate_audience_decisions()
            try:
                await room.session.voice.cancel_speech()
            except Exception:
                pass
        # Preserve controls already requested by this client, but discard queued stale
        # input. The current bounded model/audio operation unwinds to a valid phase.
        controls = []
        while not jobs.empty():
            message = jobs.get_nowait()
            if message is not None and is_control(message):
                controls.append(message)
        for message in controls:
            jobs.put_nowait(message)
        await jobs.put(None)


async def _handle_client_message(room: Room, msg: dict[str, Any],
                                  control_prepared: bool = False) -> None:
    s = room.session
    t = msg.get("type")
    if t == "presentation_started" and room.t0 is None:
        room.t0 = wall_ms()  # the session clock starts now
    ts = room.now_ms()
    if t == "presentation_ended" and not control_prepared:
        await room.prepare_control("end")
    elif t == "control" and not control_prepared:
        await room.prepare_control(str(msg.get("action")))
    if t == "presentation_started":
        await room.run(s.start(ts))
        if room.ticker is None:
            room.ticker = asyncio.create_task(room.tick_forever())
    elif t == "slide_changed":
        await room.run(s.slide_changed(ts, int(msg.get("slide_number", 1))))
    elif t == "transcript_segment":
        # Browser STT / push-to-talk path (Shape 2, hour-5 fallback). Live Higgs STT arrives
        # through the voice adapter instead.
        seg = TranscriptSegment.model_validate(msg.get("segment", {}))
        turn_id = msg.get("turn_id")
        await room.run(s.presenter_transcript(
            ts, seg, turn_id=turn_id if isinstance(turn_id, str) else None))
    elif t == "presenter_turn_started":
        s.presenter_turn_started(ts, str(msg.get("turn_id") or "legacy"))
    elif t == "presenter_turn_ended":
        s.presenter_turn_ended(ts, str(msg.get("turn_id") or "legacy"))
    elif t == "presenter_turn_cancelled":
        turn_id = msg.get("turn_id")
        s.presenter_turn_cancelled(str(turn_id) if turn_id is not None else None)
    elif t == "presenter_speech_activity":
        # Finals arrive after a pause. Keep the scheduler informed while speech is ongoing.
        if s.phase not in ("paused", "report", "setup"):
            s.last_presenter_speech_ms = ts
    elif t == "presentation_ended":
        await room.run(s.control("end", ts))
    elif t == "control":
        await room.run(s.control(str(msg.get("action")), ts))


# ---- static: decks, demo assets, the frontend (last, so routes win) -------------------

install_voice_routes(app, _room)

(ROOT / "data" / "decks").mkdir(parents=True, exist_ok=True)
app.mount("/decks", StaticFiles(directory=ROOT / "data" / "decks"), name="decks")
app.mount("/demo", StaticFiles(directory=ROOT / "demo"), name="demo")
app.mount("/", StaticFiles(directory=ROOT / "frontend", html=True), name="frontend")
