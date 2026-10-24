"""Higgs (Boson AI) voices — Person B owns this file.

Each line is rendered by Higgs TTS 3 in that panelist's own cloned voice (raw 24 kHz PCM,
~1 s for a sentence), saved as a WAV under data/audio/<session>/ and announced with an
`audio_status` "clip" event; the browser plays clips one at a time. The line's exact length
goes back to the engine, which ignores the mic until it has finished playing.

Faces: Higgs's built-in avatars (Claire, James, Emma). Each starts as a still (demo/faces/
higgs/) and becomes a live, lip-synced stream once its avatar has joined (avatar_live.py);
from then on that panelist's lines are streamed into their live face instead of a clip.
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

from .avatar_live import STAGGER_S, LiveAvatarRoom, livekit_configured
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
LIVE_TRIES = 5      # a seat refused a live slot ("every slot is in use") tries again...
LIVE_RETRY_S = 20   # ...this often; meanwhile it keeps its still face and voice
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
        self._lock = asyncio.Lock()  # one line at a time, in order
        # Live faces only with the real API and LiveKit configured (never in tests).
        self.live_enabled = (client is None and livekit_configured()
                             and os.environ.get("BOSON_AVATAR_ENABLED", "false") == "true")
        self._live: dict[str, LiveAvatarRoom] = {}  # persona id → their live face, once live
        self._live_task: asyncio.Task[None] | None = None

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
        if self.live_enabled and self._live_task is None:
            self._live_task = asyncio.create_task(self._bring_faces_live(session_id))

    async def _bring_faces_live(self, session_id: str) -> None:
        """Turn each still face into its live avatar, one at a time (Higgs rate-limits
        starting them back to back). A seat that fails just keeps its still face."""
        seats = [(pid, c) for pid, (c, _) in self._seats.items() if pid != "moderator"]
        for i, (pid, character) in enumerate(seats):
            if i:
                await asyncio.sleep(STAGGER_S)
            for attempt in range(LIVE_TRIES):
                if attempt:
                    await asyncio.sleep(LIVE_RETRY_S)  # Higgs's shared slots free up
                room = LiveAvatarRoom(session_id)
                try:
                    await room.connect()
                    identity = await room.add_seat(pid, f"builtin_{character}_v1")
                except asyncio.CancelledError:
                    await room.close()
                    raise
                except Exception as exc:
                    await room.close()
                    await self._status("live_failed", speaker=pid, attempt=attempt + 1,
                                       detail=f"{type(exc).__name__}: {exc}"[:300])
                    continue
                self._live[pid] = room
                await self._status("live_seat", speaker=pid, identity=identity, **room.viewer())
                break

    async def request_persona_turn(self, persona_id: str, text: str,
                                   style: str | None = None) -> float | None:
        return await self._say(persona_id, text, style)

    async def play_moderator_line(self, text: str) -> float | None:
        return await self._say("moderator", text, None)

    async def _say(self, speaker: str, text: str, mood: str | None) -> float | None:
        """Speak one line: streamed into the live face if that seat is live (returns once it
        has played), otherwise rendered as a clip over the still face (returns its length).
        None if it failed (the caption still shows the line; the room carries on)."""
        async with self._lock:
            if speaker in self._live:
                return await self._say_live(speaker, text, mood)
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

    async def _say_live(self, speaker: str, text: str, mood: str | None) -> float | None:
        voice = self._voice_ids.get(speaker) or self._seats[speaker][1]
        tagged = MOOD_EMOTION.get(mood or "neutral", "") + text
        SpendCounter.tts_chars += len(tagged)

        async def pcm():
            async with self._client.stream("POST", "/audio/speech", json={
                    "model": self.tts_model, "input": tagged, "voice": voice,
                    "stream": True, "response_format": "pcm"}) as resp:
                resp.raise_for_status()
                async for chunk in resp.aiter_bytes():
                    yield chunk

        await self._status("live_line", speaker=speaker, text=text)
        try:
            await self._live[speaker].speak(speaker, pcm())
        except Exception as exc:
            await self._status("tts_failed", speaker=speaker, detail=str(exc)[:200])
            return None
        await self._status("live_done", speaker=speaker)
        return 0.0  # already played

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
        for room in self._live.values():  # clips are stopped by the browser; live faces here
            room.interrupt()

    async def stop_voice_session(self) -> None:
        await self.release_live()
        await self._status("stopped")

    async def release_live(self) -> None:
        """Stop billing: release every live face. Safe to call twice."""
        if self._live_task is not None:
            self._live_task.cancel()
        live, self._live = self._live, {}
        for room in live.values():
            await room.close()

    async def _status(self, status: str, **extra: object) -> None:
        if self._on_event:
            await self._on_event(SessionEvent(
                type="audio_status", session_id=self._session_id, timestamp_ms=0,
                payload={"status": status, "adapter": "higgs", **extra}))
