"""Higgs (Boson AI) voices — Person B owns this file.

Each line is rendered by Higgs TTS 3 in that panelist's own cloned voice (raw 24 kHz PCM,
~1 s for a sentence), saved as a WAV under data/audio/<session>/ and announced with an
`audio_status` "clip" event; the browser plays clips one at a time. The line's exact length
goes back to the engine, which ignores the mic until it has finished playing.

Faces: Higgs's built-in avatars (Claire, Emma, James), as stills in demo/faces/higgs/.
Voices: each character's voice was cloned once from a preset (data/voices.json) and is reused
by id, so the same face always has the same voice. Speech-to-text is the browser's (mic.js).
Money: $0.015 per 1K characters; a 20-word line is ~$0.0015. SpendCounter feeds /health.
"""

from __future__ import annotations

import asyncio
import json
import os
import struct
import uuid
from pathlib import Path

import httpx

from spec.contracts import SessionConfig, SessionEvent

from .voice_base import OnEvent, OnTranscript

BASE_URL = "https://api.boson.ai/v1"
ROOT = Path(__file__).resolve().parents[2]
AUDIO_DIR = ROOT / "data" / "audio"
VOICE_REGISTRY = ROOT / "data" / "voices.json"
SAMPLE_RATE = 24_000
# Seat order → character: their face (demo/faces/higgs/<name>.png) and the preset their
# voice was cloned from.
CHARACTERS: list[tuple[str, str]] = [("claire", "eleanor"), ("james", "marcus"),
                                     ("emma", "chloe")]
MODERATOR = ("moderator", "nora")
VOICE_SCRIPT = ("Thanks for having me on this call. I'll be listening closely, and I'll probably "
                "have a few questions about your numbers, your customers, and your plan.")
MOOD_EMOTION: dict[str, str] = {
    "impatient": "<|emotion:anger|>", "confused": "<|emotion:confusion|>",
    "thoughtful": "<|emotion:contemplation|>", "pressing": "<|emotion:determination|>",
    "warm": "<|emotion:contentment|>", "neutral": "",
}


class SpendCounter:
    """We keep our own counter because the vendor dashboard lags (CLAUDE.md §13 Money)."""

    tts_chars = 0
    realtime_ms = 0

    @classmethod
    def estimate_usd(cls) -> float:
        return cls.tts_chars / 1000 * 0.015 + cls.realtime_ms / 60_000 * 0.016


def seat_characters(config: SessionConfig) -> dict[str, tuple[str, str]]:
    """Persona id → (character, base preset voice), by seat order; plus the moderator."""
    out = {p.id: CHARACTERS[i % len(CHARACTERS)] for i, p in enumerate(config.personas)}
    out["moderator"] = MODERATOR
    return out


def wav(pcm: bytes) -> bytes:
    """16-bit mono PCM → a WAV file the browser can play."""
    return (b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt "
            + struct.pack("<IHHIIHH", 16, 1, 1, SAMPLE_RATE, SAMPLE_RATE * 2, 2, 16)
            + b"data" + struct.pack("<I", len(pcm)) + pcm)


class HiggsVoice:
    def __init__(self, client: httpx.AsyncClient | None = None,
                 audio_dir: Path | None = None, registry: Path | None = None) -> None:
        self.api_key = os.environ.get("BOSON_API_KEY", "")
        self.tts_model = os.environ.get("BOSON_TTS_MODEL", "higgs-tts-3")
        self.audio_dir = audio_dir or AUDIO_DIR
        self.registry = registry or VOICE_REGISTRY
        self._client = client or httpx.AsyncClient(
            base_url=BASE_URL, headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=httpx.Timeout(15.0, connect=5.0))
        self._seats: dict[str, tuple[str, str]] = {}
        self._voice_ids: dict[str, str] = {}
        self._session_id = ""
        self._on_event: OnEvent | None = None
        self._lock = asyncio.Lock()  # one line renders at a time, in order

    def on_event(self, callback: OnEvent) -> None:
        self._on_event = callback

    def on_transcript(self, callback: OnTranscript) -> None:
        return None  # speech-to-text is the browser's

    async def start_voice_session(self, session_id: str, config: SessionConfig) -> None:
        self._session_id = session_id
        self._seats = seat_characters(config)
        registry = self._load_registry()
        for speaker, (character, base) in self._seats.items():
            voice_id = registry.get(f"{character}|{base}|")
            if voice_id:
                self._voice_ids[speaker] = voice_id
        await self._status(
            "ready", faces={pid: f"/demo/faces/higgs/{c}.png"
                            for pid, (c, _) in self._seats.items() if pid != "moderator"})

    async def request_persona_turn(self, persona_id: str, text: str,
                                   style: str | None = None) -> float | None:
        return await self._say(persona_id, text, style)

    async def play_moderator_line(self, text: str) -> float | None:
        return await self._say("moderator", text, None)

    async def _say(self, speaker: str, text: str, mood: str | None) -> float | None:
        """Render the line and announce the clip. Returns its length in seconds, or None if
        the render failed (the caption still shows the line; the room carries on)."""
        async with self._lock:
            if speaker not in self._voice_ids and speaker in self._seats:
                try:
                    await self._clone(speaker)
                except Exception as exc:  # keep the preset voice for this speaker
                    await self._status("voice_failed", speaker=speaker, detail=str(exc)[:200])
            voice = (self._voice_ids.get(speaker)
                     or self._seats.get(speaker, MODERATOR)[1])
            tagged = MOOD_EMOTION.get(mood or "neutral", "") + text
            SpendCounter.tts_chars += len(tagged)
            try:
                resp = await self._client.post("/audio/speech", json={
                    "model": self.tts_model, "input": tagged, "voice": voice,
                    "response_format": "pcm"})
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                await self._status("tts_failed", speaker=speaker, detail=str(exc)[:200])
                return None
            out = self.audio_dir / self._session_id
            out.mkdir(parents=True, exist_ok=True)
            name = f"{uuid.uuid4().hex[:12]}.wav"
            (out / name).write_bytes(wav(resp.content))
            seconds = len(resp.content) / (SAMPLE_RATE * 2)
            await self._status("clip", speaker=speaker, text=text,
                               url=f"/audio/{self._session_id}/{name}",
                               duration_ms=round(seconds * 1000))
            return seconds

    async def _clone(self, speaker: str) -> None:
        """One-time per character: say VOICE_SCRIPT in its preset, register it as a custom
        voice, remember the id on disk so every later session reuses it."""
        character, base = self._seats[speaker]
        tts = await self._client.post("/audio/speech", json={
            "model": self.tts_model, "input": VOICE_SCRIPT, "voice": base,
            "response_format": "mp3"})
        tts.raise_for_status()
        SpendCounter.tts_chars += len(VOICE_SCRIPT)
        reg = await self._client.post(
            "/audio/voices", data={"ref_text": VOICE_SCRIPT, "title": f"PresAI {character}"},
            files={"ref_audio": ("ref.mp3", tts.content, "audio/mpeg")})
        reg.raise_for_status()
        body = reg.json()
        voice_id = body.get("voice_id") or body["voice"]
        registry = self._load_registry()
        registry[f"{character}|{base}|"] = voice_id
        self.registry.parent.mkdir(parents=True, exist_ok=True)
        self.registry.write_text(json.dumps(registry, indent=2))
        for s, seat in self._seats.items():
            if seat == (character, base):
                self._voice_ids[s] = voice_id

    def _load_registry(self) -> dict[str, str]:
        try:
            return json.loads(self.registry.read_text())
        except (OSError, ValueError):
            return {}

    async def send_context(self, text: str) -> None:
        return None

    async def play_sfx(self, sfx_id: str) -> None:
        return None  # phone/door are local clips the browser plays from sfx_url

    async def cancel_speech(self) -> None:
        return None  # the browser stops what is playing; nothing is queued here

    async def stop_voice_session(self) -> None:
        await self._status("stopped")

    async def _status(self, status: str, **extra: object) -> None:
        if self._on_event:
            await self._on_event(SessionEvent(
                type="audio_status", session_id=self._session_id, timestamp_ms=0,
                payload={"status": status, "adapter": "higgs", **extra}))
