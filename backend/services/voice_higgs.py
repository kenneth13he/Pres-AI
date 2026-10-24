"""Higgs (Boson AI) voice adapter — Person B owns this file.

Status: Shape 2 (split), TTS half. Every persona and moderator line is rendered by Higgs
TTS 3 as an mp3 clip in that persona's preset voice, saved under data/audio/<session>/ and
announced with an `audio_status` event carrying the clip URL; the browser plays the clips in
order. Speech-to-text is still the browser's (mic.js) until the Realtime/STT half lands.

What the docs say (23 Oct 2026), verified live the same day:
  TTS        POST https://api.boson.ai/v1/audio/speech   model higgs-tts-3   ~2 s per line
             presets: chloe, eleanor, jake, marcus, nora, oliver (GET /v1/audio/voices is
             the *custom* voice list and is empty for us)
             tags: <|emotion:anger|> <|style:whispering|> <|prosody:pause|> <|sfx:cough|>
  Realtime   wss://api.boson.ai/v1/realtime?model=higgs-realtime — TODO(B), Shape 1 / STT
Money: $0.015 per 1K characters; a 20-word line is ~$0.0015. SpendCounter feeds /health.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import httpx

from spec.contracts import SessionConfig, SessionEvent

from .voice_base import OnEvent, OnTranscript

BASE_URL = "https://api.boson.ai/v1"
AUDIO_DIR = Path(__file__).resolve().parents[2] / "data" / "audio"
PRESET_VOICES = ["marcus", "eleanor", "jake", "chloe", "oliver", "nora"]
MODERATOR_VOICE = "nora"

# Roster default voices (distinct within every preset's three seats). Custom personas and
# clashes get the first preset not already at the table.
ROSTER_VOICES: dict[str, str] = {
    "vc": "eleanor", "student": "jake", "professor": "marcus", "methods": "oliver",
    "mentor": "chloe", "classmate": "jake", "hiring_manager": "eleanor",
    "senior_eng": "marcus", "recruiter": "chloe", "customer": "chloe",
    "journalist": "eleanor", "exec": "oliver",
}
# Persona style hint → TTS delivery tags at the start of the text.
STYLE_TAGS: dict[str, str] = {
    "impatient": "<|emotion:anger|><|prosody:speed_fast|>",
    "confused": "<|emotion:confusion|>",
    "thoughtful": "<|emotion:contemplation|>",
    "neutral": "",
}


class SpendCounter:
    """We keep our own counter because the vendor dashboard lags (CLAUDE.md §13 Money)."""

    tts_chars = 0
    realtime_ms = 0

    @classmethod
    def estimate_usd(cls) -> float:
        return cls.tts_chars / 1000 * 0.015 + cls.realtime_ms / 60_000 * 0.016


def assign_voices(config: SessionConfig) -> dict[str, str]:
    """Persona id → preset voice, all distinct and never the moderator's voice."""
    out: dict[str, str] = {"moderator": MODERATOR_VOICE}
    used = {MODERATOR_VOICE}
    for p in config.personas:
        want = p.voice_id or ROSTER_VOICES.get(p.id)
        if want in PRESET_VOICES and want not in used:
            out[p.id] = want
        else:
            out[p.id] = next((v for v in PRESET_VOICES if v not in used), PRESET_VOICES[0])
        used.add(out[p.id])
    return out


class HiggsVoice:
    def __init__(self, client: httpx.AsyncClient | None = None,
                 audio_dir: Path | None = None) -> None:
        self.api_key = os.environ.get("BOSON_API_KEY", "")
        self.tts_model = os.environ.get("BOSON_TTS_MODEL", "higgs-tts-3")
        self.audio_dir = audio_dir or AUDIO_DIR
        self._on_event: OnEvent | None = None
        self._on_transcript: OnTranscript | None = None
        self._session_id = ""
        self._voices: dict[str, str] = {"moderator": MODERATOR_VOICE}
        self._client = client or httpx.AsyncClient(
            base_url=BASE_URL,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=httpx.Timeout(15.0, connect=5.0),
        )

    def on_event(self, callback: OnEvent) -> None:
        self._on_event = callback

    def on_transcript(self, callback: OnTranscript) -> None:
        self._on_transcript = callback

    # ---- TTS ---------------------------------------------------------------------------

    async def _render(self, speaker: str, text: str, style: str | None) -> None:
        """Render one line to an mp3 clip and announce it. A failure is an audio_status with
        status "tts_failed": the caption already showed the line, so the room carries on."""
        voice = self._voices.get(speaker) or PRESET_VOICES[0]
        tagged = STYLE_TAGS.get(style or "neutral", "") + text
        SpendCounter.tts_chars += len(tagged)
        try:
            resp = await self._client.post("/audio/speech", json={
                "model": self.tts_model, "input": tagged, "voice": voice,
                "response_format": "mp3",
            })
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            await self._status("tts_failed", speaker=speaker, detail=str(exc)[:200])
            return
        name = f"{uuid.uuid4().hex[:12]}.mp3"
        out = self.audio_dir / self._session_id
        out.mkdir(parents=True, exist_ok=True)
        (out / name).write_bytes(resp.content)
        await self._status("clip", speaker=speaker, voice=voice, text=text,
                           url=f"/audio/{self._session_id}/{name}")

    # ---- VoiceAdapter --------------------------------------------------------------------

    async def start_voice_session(self, session_id: str, config: SessionConfig) -> None:
        self._session_id = session_id
        self._voices = assign_voices(config)
        await self._status("ready", voices=self._voices)

    async def send_context(self, text: str) -> None:
        return None  # Shape 2 needs no context on the voice side

    async def request_persona_turn(
        self, persona_id: str, text: str, style: str | None = None
    ) -> None:
        await self._render(persona_id, text, style)

    async def play_moderator_line(self, text: str) -> None:
        await self._render("moderator", text, "neutral")

    async def play_sfx(self, sfx_id: str) -> None:
        return None  # phone/door are local clips the browser plays from sfx_url

    async def cancel_speech(self) -> None:
        return None  # clips are played by the browser; it cancels its own queue on Skip

    async def stop_voice_session(self) -> None:
        await self._status("stopped")

    async def _status(self, status: str, **extra: object) -> None:
        if self._on_event:
            await self._on_event(SessionEvent(
                type="audio_status", session_id=self._session_id, timestamp_ms=0,
                payload={"status": status, "adapter": "higgs", **extra},
            ))
