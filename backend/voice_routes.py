"""Voice-only routes: short-lived vendor auth and a separate binary playback channel."""
from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .services.voice_higgs import HiggsVoice, SpendCounter, VoiceError


class TestSpeech(BaseModel):
    persona_id: str = "moderator"
    text: str = Field(default="Welcome to PresAI. Please begin your presentation.",
                      min_length=1, max_length=240)
    style: str = "neutral"


def same_origin(origin: str | None, host: str | None) -> bool:
    return not origin or urlsplit(origin).netloc == host


def install_voice_routes(app: FastAPI, get_room: Callable[[str], Any]) -> None:
    def voice_for(session_id: str) -> tuple[Any, HiggsVoice]:
        room = get_room(session_id)
        voice = room.session.voice
        if not isinstance(voice, HiggsVoice):
            raise HTTPException(409, "Live voice is disabled; choose Higgs in the local config.")
        if room.session.ended:
            raise HTTPException(409, "This session has ended. Create a new room.")
        return room, voice

    @app.post("/api/sessions/{session_id}/voice/client_secret")
    async def client_secret(session_id: str, request: Request) -> JSONResponse:
        if not same_origin(request.headers.get("origin"), request.headers.get("host")):
            raise HTTPException(403, "Voice access requires the local app.")
        _, voice = voice_for(session_id)
        if SpendCounter.estimate_usd() >= float(os.environ.get(
            "SPEND_SOFT_CAP_USD", "60",
        )):
            raise HTTPException(429, "The local voice spending limit has been reached.")
        try:
            body = await voice.mint_client_secret()
        except VoiceError as exc:
            raise HTTPException(502, str(exc)) from None
        return JSONResponse(body, headers={"Cache-Control": "no-store"})

    @app.websocket("/ws/voice/{session_id}")
    async def audio_socket(ws: WebSocket, session_id: str) -> None:
        if not same_origin(ws.headers.get("origin"), ws.headers.get("host")):
            await ws.close(code=4403)
            return
        try:
            room, voice = voice_for(session_id)
        except HTTPException:
            await ws.close(code=4404)
            return
        if voice.attached:
            await ws.close(code=4409)
            return
        await ws.accept()

        async def send(data: str | bytes) -> None:
            if isinstance(data, bytes):
                await ws.send_bytes(data)
            else:
                await ws.send_text(data)

        voice.attach(send, room.now_ms)
        started: float | None = None
        try:
            async with asyncio.timeout(600):
                await ws.send_json({"type": "ready", "sample_rate": 24000})
                while True:
                    msg = await ws.receive_json()
                    kind = msg.get("type")
                    if kind == "played":
                        voice.acknowledge(str(msg.get("play_id", "")))
                    elif kind == "cancel":
                        await voice.cancel_speech()  # never waits on the room/engine lock
                    elif kind == "realtime_started" and started is None:
                        started = time.monotonic()
                    elif kind == "realtime_stopped" and started is not None:
                        SpendCounter.realtime_ms += int((time.monotonic() - started) * 1000)
                        started = None
        except (WebSocketDisconnect, TimeoutError):
            pass
        finally:
            if started is not None:
                SpendCounter.realtime_ms += int((time.monotonic() - started) * 1000)
            await voice.detach()
            try:
                await ws.close()
            except RuntimeError:
                pass

    @app.post("/api/sessions/{session_id}/voice/test")
    async def test_speech(session_id: str, body: TestSpeech, request: Request) -> dict[str, bool]:
        if not same_origin(request.headers.get("origin"), request.headers.get("host")):
            raise HTTPException(403, "Voice access requires the local app.")
        room, voice = voice_for(session_id)
        if room.session.phase != "setup":
            raise HTTPException(409, "Voice checks are available before the presentation starts.")
        if body.persona_id != "moderator" and not room.session.persona(body.persona_id):
            raise HTTPException(400, "Choose a persona from this room.")
        if voice.speaking:
            raise HTTPException(409, "Wait for the current voice check to finish.")
        if not voice.attached:
            raise HTTPException(409, "Connect audio first.")
        try:
            await voice.start_voice_session(session_id, room.session.config)
            await voice.request_persona_turn(body.persona_id, body.text, body.style)
        except VoiceError as exc:
            raise HTTPException(502, str(exc)) from None
        return {"ok": True}
