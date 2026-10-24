"""Boson speech adapter: controlled STT in the browser, streamed TTS on its own socket.

Only the backend holds the permanent key. A speech call completes after browser playback,
not HTTP generation. The engine remains the sole owner of ai_speech_started/ended events.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import suppress
from typing import Any

import httpx

from spec.contracts import SessionConfig, SessionEvent

from .voice_base import OnEvent, OnTranscript

BASE_URL = "https://api.boson.ai/v1"
PCM_SAMPLE_RATE = 24_000
CANCEL_WAIT_S = 2.0
VOICE_FOR_PERSONA = {
    "moderator": "eleanor", "vc": "marcus", "student": "chloe",
    "professor": "oliver", "mentor": "nora",
}
PRESET_VOICES = {"default", "chloe", "eleanor", "jake", "marcus", "nora", "oliver"}
STYLE_TAGS = {
    "impatient": "<|emotion:anger|><|prosody:speed_fast|>",
    "confused": "<|emotion:confusion|>",
    "thoughtful": "<|emotion:contemplation|><|prosody:speed_slow|>",
    "neutral": "",
}
AudioSink = Callable[[str | bytes], Awaitable[None]]


class VoiceError(RuntimeError):
    """Safe to show to the presenter; vendor bodies/credentials never reach logs."""


class SpendCounter:
    tts_chars = 0
    realtime_ms = 0
    reasoning_estimate_usd = 0.0

    @classmethod
    def estimate_usd(cls) -> float:
        return (cls.tts_chars / 1000 * 0.015 + cls.realtime_ms / 60_000 * 0.016
                + cls.reasoning_estimate_usd
                + max(0.0, float(os.environ.get("BOSON_SPEND_CARRYOVER_USD", "0"))))


def realtime_config() -> dict[str, Any]:
    """Manual commit is essential: Boson ignores create_response:false under server VAD."""
    return {
        "type": "session.update",
        "session": {
            "model": os.environ.get("BOSON_REALTIME_MODEL", "higgs-realtime"),
            "output_modalities": ["text"],
            "audio": {
                "input": {
                    "format": {"type": "audio/pcm", "rate": PCM_SAMPLE_RATE},
                    "transcription": {
                        "model": os.environ.get("BOSON_STT_MODEL", "higgs-stt-3.1"),
                        "language": "en",
                    },
                    "turn_detection": None,
                },
                "output": {"format": {"type": "audio/pcm", "rate": PCM_SAMPLE_RATE},
                           "voice": "default"},
            },
            "max_output_tokens": 128,
        },
    }


class HiggsVoice:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self.api_key = os.environ.get("BOSON_API_KEY", "")
        self.tts_model = os.environ.get("BOSON_TTS_MODEL", "higgs-tts-3")
        self._on_event: OnEvent | None = None
        self._on_transcript: OnTranscript | None = None
        self._session_id = ""
        self._sink: AudioSink | None = None
        self._attachment_id = 0
        self._clock: Callable[[], int] = lambda: 0
        self._speech: asyncio.Task[None] | None = None
        self._played = asyncio.Event()
        self._play_id: str | None = None
        self._accept_ack = False
        self._speech_lock = asyncio.Lock()
        self._voices = dict(VOICE_FOR_PERSONA)
        self.speech_ended_at_ms = 0
        self._closed = False
        self._client = client or httpx.AsyncClient(
            base_url=BASE_URL,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=httpx.Timeout(20.0, connect=10.0),
        )

    @property
    def speaking(self) -> bool:
        return self._speech is not None and not self._speech.done()

    @property
    def attached(self) -> bool:
        return self._sink is not None

    @property
    def attachment_id(self) -> int:
        return self._attachment_id

    def attach(self, sink: AudioSink, clock: Callable[[], int]) -> int:
        if self._closed:
            raise VoiceError("The voice session has ended. Create a new room.")
        if self.attached:
            raise VoiceError("An audio client is already connected.")
        self._attachment_id += 1
        self._sink, self._clock = sink, clock
        return self._attachment_id

    async def detach(self, attachment_id: int | None = None) -> bool:
        if attachment_id is not None and attachment_id != self._attachment_id:
            return False
        self._sink = None
        task = self._speech
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            await self._wait_cancelled_speech(task)
        return True

    async def _wait_cancelled_speech(self, task: asyncio.Task[None]) -> None:
        try:
            await asyncio.wait_for(asyncio.shield(task), CANCEL_WAIT_S)
        except asyncio.CancelledError:
            caller = asyncio.current_task()
            if caller is not None and caller.cancelling():
                raise
        except (VoiceError, TimeoutError):
            pass

    def acknowledge(self, play_id: str) -> None:
        if self._accept_ack and play_id == self._play_id:
            self._played.set()

    def on_event(self, callback: OnEvent) -> None:
        self._on_event = callback

    def on_transcript(self, callback: OnTranscript) -> None:
        self._on_transcript = callback

    async def tts_pcm_stream(self, text: str, voice: str,
                             style: str | None = None) -> AsyncIterator[bytes]:
        if SpendCounter.estimate_usd() >= float(os.environ.get("SPEND_SOFT_CAP_USD", "60")):
            raise VoiceError("The local voice spending limit has been reached.")
        tagged = STYLE_TAGS.get(style or "neutral", "") + text
        SpendCounter.tts_chars += len(tagged)
        try:
            async with self._client.stream("POST", "/audio/speech", json={
                "model": self.tts_model, "input": tagged, "voice": voice,
                "stream": True, "response_format": "pcm",
            }) as response:
                if not response.is_success:
                    raise VoiceError(f"Boson speech unavailable (HTTP {response.status_code}).")
                async for chunk in response.aiter_bytes():
                    if chunk:
                        yield chunk
        except httpx.HTTPError:
            raise VoiceError("The Boson speech connection failed. Try again.") from None

    async def mint_client_secret(self) -> dict[str, Any]:
        try:
            response = await self._client.post("/realtime/client_secrets", json={
                "expires_after": {"seconds": 300},
            })
            if not response.is_success:
                raise VoiceError(f"Boson connection unavailable (HTTP {response.status_code}).")
            body = response.json()
            if (not isinstance(body, dict) or not isinstance(body.get("value"), str)
                    or not body["value"]):
                raise VoiceError("Boson did not return a temporary credential.")
            return {"value": body["value"], "expires_at": body.get("expires_at"),
                    "url": "wss://api.boson.ai/v1/realtime", "config": realtime_config()}
        except (httpx.HTTPError, ValueError):
            raise VoiceError("Could not create a temporary voice connection.") from None

    async def start_voice_session(self, session_id: str, config: SessionConfig) -> None:
        if self._closed:
            raise VoiceError("The voice session has ended. Create a new room.")
        self._session_id = session_id
        for i, persona in enumerate(config.personas):
            self._voices[persona.id] = (persona.voice_id if persona.voice_id in PRESET_VOICES
                                       else VOICE_FOR_PERSONA.get(
                                           persona.id, ["marcus", "chloe", "oliver"][i % 3]))
        await self._status("ready" if self.attached else "waiting_for_audio")

    async def send_context(self, text: str) -> None:
        # TTS speaks only the orchestrator's exact line; slide context stays with the brain.
        return None

    async def request_persona_turn(self, persona_id: str, text: str,
                                   style: str | None = None) -> None:
        async with self._speech_lock:
            if self._closed:
                raise VoiceError("The voice session has ended. Create a new room.")
            if self._sink is None:
                raise VoiceError("Audio is disconnected. Reconnect before speaking.")
            self._speech = asyncio.create_task(self._say(
                persona_id, text, style, self._attachment_id))
            task = self._speech
            try:
                await task
            except asyncio.CancelledError:
                caller = asyncio.current_task()
                if caller is not None and caller.cancelling():
                    raise
            finally:
                self.speech_ended_at_ms = self._clock()
                self._speech = None
                self._play_id = None
                self._accept_ack = False

    async def _say(self, persona_id: str, text: str, style: str | None,
                   attachment_id: int) -> None:
        self._play_id = uuid.uuid4().hex
        self._played.clear()
        first_at = None
        started = time.monotonic()
        try:
            async with asyncio.timeout(30):
                await self._status("speaking")  # flushes the engine's start before any PCM
                await self._send({"type": "speech_started", "play_id": self._play_id,
                                  "speaker": persona_id, "text": text}, attachment_id)
                async for chunk in self.tts_pcm_stream(
                    text, self._voices.get(persona_id, "default"), style,
                ):
                    if first_at is None:
                        first_at = round((time.monotonic() - started) * 1000)
                    await self._send(chunk, attachment_id)
                if first_at is None:
                    raise VoiceError("Boson returned no speech audio.")
                self._accept_ack = True
                await self._send({"type": "speech_complete", "play_id": self._play_id,
                                  "first_audio_ms": first_at}, attachment_id)
                await self._played.wait()
        except TimeoutError:
            with suppress(VoiceError):
                await self._send({"type": "cancel"}, attachment_id)
            raise VoiceError("Voice playback timed out. Please reconnect audio.") from None
        except BaseException:
            with suppress(VoiceError):
                await self._send({"type": "cancel"}, attachment_id)
            raise
        finally:
            if self.attached and self._attachment_id == attachment_id and not self._closed:
                await self._status("ready")

    async def _send(self, data: dict[str, Any] | bytes,
                    attachment_id: int | None = None) -> None:
        if (self._sink is None or attachment_id is not None
                and attachment_id != self._attachment_id):
            raise VoiceError("Audio disconnected during speech.")
        try:
            await self._sink(data if isinstance(data, bytes) else json.dumps(data))
        except VoiceError:
            raise
        except Exception:
            raise VoiceError("Audio disconnected during speech.") from None

    async def play_moderator_line(self, text: str) -> None:
        await self.request_persona_turn("moderator", text, "neutral")

    async def play_sfx(self, sfx_id: str) -> None:
        return None

    async def cancel_speech(self) -> None:
        if self._speech and not self._speech.done():
            self._speech.cancel()
        if self._sink:
            with suppress(VoiceError):
                await self._send({"type": "cancel"})

    async def stop_voice_session(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await self.cancel_speech()
            if self._speech and self._speech is not asyncio.current_task():
                await self._wait_cancelled_speech(self._speech)
        finally:
            await self._client.aclose()
            self._closed = True

    async def _status(self, status: str) -> None:
        if self._on_event:
            await self._on_event(SessionEvent(
                type="audio_status", session_id=self._session_id, timestamp_ms=self._clock(),
                payload={"status": status, "adapter": "higgs"},
            ))
