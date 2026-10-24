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
from .services.curveballs import CATALOG
from .services.voice_base import VoiceAdapter
from .services.voice_higgs import HiggsVoice, SpendCounter, seat_characters
from .services.voice_mock import MockVoice

load_dotenv()
ROOT = Path(__file__).resolve().parents[1]
TICK_S = 1.0


def wall_ms() -> int:
    return int(time.time() * 1000)


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
        self.lock = asyncio.Lock()
        self.t0: int | None = None
        self._flushes: set[asyncio.Task[None]] = set()
        self.cleanup: asyncio.Task[None] | None = None

    def schedule_flush(self) -> None:
        task = asyncio.get_running_loop().create_task(self.flush())
        self._flushes.add(task)  # keep a reference until it finishes
        task.add_done_callback(self._flushes.discard)

    def now_ms(self) -> int:
        return 0 if self.t0 is None else wall_ms() - self.t0

    async def flush(self) -> None:
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
        async with self.lock:
            try:
                await coro
            except Exception as exc:  # a failed LLM/TTS call never breaks the session
                self.session.events.append(SessionEvent(
                    type="error", session_id=self.session.session_id,
                    timestamp_ms=self.now_ms(), payload={"message": str(exc)[:300]},
                ))
            await self.flush()

    async def tick_forever(self) -> None:
        while not self.session.ended:
            await asyncio.sleep(TICK_S)
            await self.run(self.session.tick(self.now_ms()))


ROOMS: dict[str, Room] = {}


def make_orchestrator() -> Orchestrator:
    if os.environ.get("ORCHESTRATOR", "mock") == "claude" and os.environ.get("ANTHROPIC_API_KEY"):
        return ClaudeOrchestrator()
    return MockOrchestrator()


def make_voice() -> VoiceAdapter:
    if os.environ.get("VOICE_ADAPTER", "mock") == "higgs" and os.environ.get("BOSON_API_KEY"):
        return HiggsVoice()
    return MockVoice()


@asynccontextmanager
async def lifespan(_: FastAPI):
    presets.presets()  # fail fast on a bad YAML
    yield
    for room in ROOMS.values():
        if room.ticker:
            room.ticker.cancel()
        await _release_live(room)  # live faces bill per minute: never leave them running


async def _release_live(room: Room) -> None:
    release = getattr(room.session.voice, "release_live", None)
    if release is not None:
        await release()


async def _release_if_abandoned(room: Room, after_s: float = 60) -> None:
    """Everyone closed the tab without ending the call: release the live faces."""
    await asyncio.sleep(after_s)
    if not room.sockets:
        await _release_live(room)


app = FastAPI(title="PresAI", lifespan=lifespan)


# ---- REST ---------------------------------------------------------------------------


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "adapters": {
            "voice": os.environ.get("VOICE_ADAPTER", "mock"),
            "orchestrator": os.environ.get("ORCHESTRATOR", "mock"),
            "boson_key": bool(os.environ.get("BOSON_API_KEY")),
            "anthropic_key": bool(os.environ.get("ANTHROPIC_API_KEY")),
            "avatar": os.environ.get("BOSON_AVATAR_ENABLED", "false") == "true",
        },
        "spend": {"tts_chars": SpendCounter.tts_chars, "realtime_ms": SpendCounter.realtime_ms,
                  "estimate_usd": round(SpendCounter.estimate_usd(), 3),
                  "soft_cap_usd": float(os.environ.get("SPEND_SOFT_CAP_USD", "60"))},
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
        background=True,  # the brain thinks beside the room; the mic is never blocked
    )
    room = Room(session)
    session.clock = room.now_ms
    # Lines and clips produced in the background reach the browser as soon as they exist.
    session.on_append = lambda: room.schedule_flush()
    ROOMS[session_id] = room
    return {"session_id": session_id, "config": config.model_dump(), "preset": preset.model_dump()}


def _room(session_id: str) -> Room:
    room = ROOMS.get(session_id)
    if room is None:
        raise HTTPException(404, "no such session")
    return room


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str) -> dict[str, Any]:
    s = _room(session_id).session
    return {
        "session_id": s.session_id, "phase": s.phase, "config": s.config.model_dump(),
        "preset": s.preset.model_dump(), "slide_number": s.slide_number,
        "elapsed_ms": (s.elapsed_ms(_room(session_id).now_ms())
                       if s.start_ms is not None else 0),
        "deck": s.deck.model_dump() if s.deck else None,
        "faces": {p.id: f"/demo/faces/higgs/{seat_characters(s.config)[p.id][0]}.png"
                  for p in s.config.personas},
        "events": [e.model_dump() for e in s.events],
    }


class Control(BaseModel):
    action: ControlAction


@app.post("/api/sessions/{session_id}/control")
async def control(session_id: str, body: Control) -> dict[str, str]:
    room = _room(session_id)
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
    for ev in room.session.events:  # replay so a reconnecting room catches up
        await ws.send_text(ev.model_dump_json())
    try:
        while True:
            msg = json.loads(await ws.receive_text())
            await _handle_client_message(room, msg)
    except WebSocketDisconnect:
        pass
    finally:
        room.sockets.discard(ws)
        if not room.sockets:
            room.cleanup = asyncio.create_task(_release_if_abandoned(room))


async def _handle_client_message(room: Room, msg: dict[str, Any]) -> None:
    s = room.session
    t = msg.get("type")
    if t == "presentation_started" and room.t0 is None:
        room.t0 = wall_ms()  # the session clock starts now
    ts = room.now_ms()
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
        await room.run(s.presenter_transcript(ts, seg))
    elif t == "presentation_ended":
        await room.run(s.control("end", ts))
    elif t == "control":
        await room.run(s.control(str(msg.get("action")), ts))


# ---- static: decks, demo assets, the frontend (last, so routes win) -------------------

(ROOT / "data" / "decks").mkdir(parents=True, exist_ok=True)
app.mount("/decks", StaticFiles(directory=ROOT / "data" / "decks"), name="decks")
(ROOT / "data" / "audio").mkdir(parents=True, exist_ok=True)
app.mount("/audio", StaticFiles(directory=ROOT / "data" / "audio"), name="audio")
app.mount("/demo", StaticFiles(directory=ROOT / "demo"), name="demo")
app.mount("/", StaticFiles(directory=ROOT / "frontend", html=True), name="frontend")
