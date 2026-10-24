"""Higgs (Boson AI) voice adapter — Person B owns this file.

Status: SKELETON. TTS 3 and client-secret minting are implemented from the docs and
untested; Realtime is a TODO until the hour-1 tests in CLAUDE.md §13 pick a shape.
What the docs say (23 Oct 2026), verify before building on it:
  TTS        POST https://api.boson.ai/v1/audio/speech   model higgs-tts-3
             stream=true + response_format="pcm" → 16-bit 24 kHz mono PCM
             tags: <|emotion:anger|> <|style:whispering|> <|prosody:pause|> <|sfx:cough|> <|reset|>
  Realtime   wss://api.boson.ai/v1/realtime?model=higgs-realtime  (OpenAI Realtime-compatible)
             server_vad | semantic_vad | null; barge-in built in; STT via higgs-stt-3.1 →
             conversation.item.input_audio_transcription.completed (final only)
  Secrets    POST /v1/realtime/client_secrets → ephemeral key bai-eph-… for the browser
Money: every session is created with a hard timeout and closed in a `finally`.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import httpx

from spec.contracts import SessionConfig, SessionEvent

from .voice_base import OnEvent, OnTranscript

BASE_URL = "https://api.boson.ai/v1"
PCM_SAMPLE_RATE = 24_000

# Persona → preset voice. Fill from GET /v1/audio/voices during hour-1 test 4.
VOICE_FOR_PERSONA: dict[str, str] = {
    "moderator": "default",
}
# Persona style hint → TTS delivery tags placed at the start of the text.
STYLE_TAGS: dict[str, str] = {
    "impatient": "<|emotion:anger|><|prosody:speed_fast|>",
    "confused": "<|emotion:confusion|>",
    "thoughtful": "<|emotion:contemplation|><|prosody:speed_slow|>",
    "neutral": "",
}


class SpendCounter:
    """We keep our own counter because the vendor dashboard lags (CLAUDE.md §13 Money)."""

    tts_chars = 0
    realtime_ms = 0

    @classmethod
    def estimate_usd(cls) -> float:
        return cls.tts_chars / 1000 * 0.015 + cls.realtime_ms / 60_000 * 0.016


class HiggsVoice:
    def __init__(self) -> None:
        self.api_key = os.environ.get("BOSON_API_KEY", "")
        self.tts_model = os.environ.get("BOSON_TTS_MODEL", "higgs-tts-3")
        self.realtime_model = os.environ.get("BOSON_REALTIME_MODEL", "higgs-realtime")
        self._on_event: OnEvent | None = None
        self._on_transcript: OnTranscript | None = None
        self._session_id = ""
        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=httpx.Timeout(30.0, connect=10.0),
        )

    def on_event(self, callback: OnEvent) -> None:
        self._on_event = callback

    def on_transcript(self, callback: OnTranscript) -> None:
        self._on_transcript = callback

    # ---- TTS 3 (Shape 2 speech path) --------------------------------------------

    async def tts_pcm_stream(
        self, text: str, voice: str, style: str | None = None
    ) -> AsyncIterator[bytes]:
        """Yield raw PCM chunks for `text`. The browser's audio.js plays this format."""
        tagged = STYLE_TAGS.get(style or "neutral", "") + text
        SpendCounter.tts_chars += len(tagged)
        payload = {
            "model": self.tts_model,
            "input": tagged,
            "voice": voice,
            "stream": True,
            "response_format": "pcm",
        }
        async with self._client.stream("POST", "/audio/speech", json=payload) as resp:
            resp.raise_for_status()
            async for chunk in resp.aiter_bytes():
                yield chunk

    # ---- Realtime (Shape 1; also the STT path in Shape 2) ------------------------

    async def mint_client_secret(self) -> dict:
        """Ephemeral browser credential. The API key never leaves this process."""
        resp = await self._client.post("/realtime/client_secrets", json={})
        resp.raise_for_status()
        return resp.json()

    # ---- VoiceAdapter --------------------------------------------------------------

    async def start_voice_session(self, session_id: str, config: SessionConfig) -> None:
        self._session_id = session_id
        # TODO(B, hour 1-4): open the Realtime WebSocket (Shape 1) or start the STT-only
        # session (Shape 2); forward input_audio_transcription.completed to _on_transcript
        # with our own start_ms from speech_started.
        await self._status("not_implemented")

    async def send_context(self, text: str) -> None:
        # TODO(B): session.update / conversation.item.create with slide context (Shape 1).
        return None

    async def request_persona_turn(
        self, persona_id: str, text: str, style: str | None = None
    ) -> None:
        # TODO(B): Shape 1 → make Realtime speak `text` (hour-1 test 2).
        #          Shape 2 → stream tts_pcm_stream(...) to the browser and emit
        #          ai_speech_started / ai_speech_ended around it.
        await self._status(f"persona_turn_not_implemented:{persona_id}")

    async def play_moderator_line(self, text: str) -> None:
        await self.request_persona_turn("moderator", text, "neutral")

    async def play_sfx(self, sfx_id: str) -> None:
        # Vocal sfx (cough, sigh) can go through TTS tags; phone/door are local clips the
        # browser plays from the curveball event's sfx_url. Nothing to do server-side.
        return None

    async def cancel_speech(self) -> None:
        # TODO(B): response.cancel / conversation.item.truncate (Shape 1), or stop the
        # PCM stream (Shape 2).
        return None

    async def stop_voice_session(self) -> None:
        try:
            pass  # TODO(B): close the Realtime socket.
        finally:
            await self._client.aclose()

    async def _status(self, status: str) -> None:
        if self._on_event:
            await self._on_event(
                SessionEvent(
                    type="audio_status",
                    session_id=self._session_id,
                    timestamp_ms=0,
                    payload={"status": status, "adapter": "higgs"},
                )
            )
