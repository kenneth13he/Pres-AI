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

import asyncio
import os
import time
import uuid
from pathlib import Path

import httpx

from spec.contracts import SessionConfig, SessionEvent

from .voice_base import OnEvent, OnTranscript

BASE_URL = "https://api.boson.ai/v1"
AUDIO_DIR = Path(__file__).resolve().parents[2] / "data" / "audio"
# Fictional portraits for the talking heads. `<persona_id>.jpg|png|webp` pins a face to a
# persona; any other image is handed out to the remaining seats in name order. Files whose
# name starts with "_" are used only when nothing else is there (test faces).
FACES_DIR = Path(__file__).resolve().parents[2] / "demo" / "faces"
FACE_EXTS = (".jpg", ".jpeg", ".png", ".webp")
# Measured 24 Oct: a 4 s line renders in ~5 s. Past this budget the voice plays over the
# still portrait instead, so a slow or throttled render never delays the room.
AVATAR_BUDGET_S = float(os.environ.get("BOSON_AVATAR_BUDGET_S", "9"))
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


FEMALE_VOICES = ["eleanor", "chloe"]
MALE_VOICES = ["marcus", "jake", "oliver"]


def face_gender(face: Path | None) -> str | None:
    """Pool faces carry a tag in the name — `pool_1_margaret.f.jpg` — so a custom persona's
    voice can match the face it was given."""
    if face is None:
        return None
    tag = face.stem.rsplit(".", 1)[-1] if "." in face.stem else ""
    return tag if tag in ("f", "m") else None


def assign_voices(config: SessionConfig, faces: dict[str, Path] | None = None) -> dict[str, str]:
    """Persona id → preset voice, all distinct and never the moderator's voice. A persona
    without a roster voice (custom) gets a voice matching its face's gender when known."""
    out: dict[str, str] = {"moderator": MODERATOR_VOICE}
    used = {MODERATOR_VOICE}
    for p in config.personas:
        want = p.voice_id or ROSTER_VOICES.get(p.id)
        if want in PRESET_VOICES and want not in used:
            out[p.id] = want
        else:
            gender = face_gender((faces or {}).get(p.id))
            prefer = (FEMALE_VOICES if gender == "f" else MALE_VOICES if gender == "m" else [])
            out[p.id] = next((v for v in prefer + PRESET_VOICES if v not in used),
                             PRESET_VOICES[0])
        used.add(out[p.id])
    return out


def assign_faces(persona_ids: list[str], faces_dir: Path | None = None) -> dict[str, Path]:
    """Persona id → portrait file. Pinned files first, then the rest in name order; test
    faces (leading "_") only if there are no others. Seats without a face stay illustrated."""
    d = faces_dir or FACES_DIR
    files = sorted(p for p in d.glob("*") if p.suffix.lower() in FACE_EXTS) if d.exists() else []
    pinned = {p.stem: p for p in files}
    # Faces pinned to *other* roster personas are not up for grabs: they belong to someone.
    reserved = set(persona_ids) | set(ROSTER_VOICES)
    pool = [p for p in files if p.stem not in reserved and not p.stem.startswith("_")]
    if not pool:
        pool = [p for p in files if p.stem.startswith("_")]
    out: dict[str, Path] = {}
    for pid in persona_ids:
        if pid in pinned:
            out[pid] = pinned[pid]
    free = [p for p in pool if p not in out.values()]
    for pid in persona_ids:
        if pid in out or not pool:
            continue
        # A single available face is shared; otherwise each seat gets its own until they run out.
        if len(pool) == 1:
            out[pid] = pool[0]
        elif free:
            out[pid] = free.pop(0)
    return out


class HiggsVoice:
    """Lines are rendered off the room's critical path: `request_persona_turn` queues the line
    and returns at once; one worker renders the queue in order (TTS ~2 s, + video ~5–8 s) and
    announces each clip as it is ready. `background=False` renders inline (tests)."""

    def __init__(self, client: httpx.AsyncClient | None = None,
                 audio_dir: Path | None = None, faces_dir: Path | None = None,
                 background: bool = True) -> None:
        self.background = background
        self._queue: asyncio.Queue[tuple[str, str, str | None]] = asyncio.Queue()
        self._worker: asyncio.Task[None] | None = None
        self.api_key = os.environ.get("BOSON_API_KEY", "")
        self.tts_model = os.environ.get("BOSON_TTS_MODEL", "higgs-tts-3")
        self.audio_dir = audio_dir or AUDIO_DIR
        self.faces_dir = faces_dir or FACES_DIR
        self.avatar_enabled = os.environ.get("BOSON_AVATAR_ENABLED", "false") == "true"
        self.avatar_budget_s = AVATAR_BUDGET_S
        self._faces: dict[str, Path] = {}
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
        stem = uuid.uuid4().hex[:12]
        out = self.audio_dir / self._session_id
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{stem}.mp3").write_bytes(resp.content)
        video = await self._talking_head(speaker, resp.content, out / f"{stem}.mp4")
        if video:
            await self._status("clip", speaker=speaker, voice=voice, text=text, kind="video",
                               url=f"/audio/{self._session_id}/{stem}.mp4")
        else:
            await self._status("clip", speaker=speaker, voice=voice, text=text, kind="audio",
                               url=f"/audio/{self._session_id}/{stem}.mp3")

    async def _talking_head(self, speaker: str, mp3: bytes, dest: Path) -> bool:
        """Higgs Avatar: portrait + the line's audio → lip-synced MP4 (with the audio in it).
        False on anything short of a finished video inside the budget — the caller then plays
        the voice over the still portrait. Never raises."""
        face = self._faces.get(speaker)
        if not (self.avatar_enabled and face):
            return False
        deadline = time.monotonic() + self.avatar_budget_s
        try:
            resp = await self._client.post(
                "/videos",
                data={"model": "higgs-avatar", "size": _video_size(face)},
                files={"ref_image": (face.name, face.read_bytes(), _mime(face)),
                       "input": ("line.mp3", mp3, "audio/mpeg")},
            )
            resp.raise_for_status()
            video_id = resp.json()["id"]
            while time.monotonic() < deadline:
                await asyncio.sleep(0.5)
                st = (await self._client.get(f"/videos/{video_id}")).json()
                if st.get("status") == "completed":
                    content = await self._client.get(f"/videos/{video_id}/content")
                    content.raise_for_status()
                    dest.write_bytes(content.content)
                    return True
                if st.get("status") == "failed":
                    break
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            await self._status("avatar_failed", speaker=speaker, detail=str(exc)[:200])
            return False
        await self._status("avatar_late", speaker=speaker)
        return False

    # ---- VoiceAdapter --------------------------------------------------------------------

    async def start_voice_session(self, session_id: str, config: SessionConfig) -> None:
        self._session_id = session_id
        self._faces = assign_faces([p.id for p in config.personas], self.faces_dir)
        self._voices = assign_voices(config, self._faces)
        await self._status("ready", voices=self._voices, avatars=self.avatar_enabled,
                           faces={pid: f"/demo/faces/{p.name}" for pid, p in self._faces.items()})

    async def send_context(self, text: str) -> None:
        return None  # Shape 2 needs no context on the voice side

    async def request_persona_turn(
        self, persona_id: str, text: str, style: str | None = None
    ) -> None:
        await self._say(persona_id, text, style)

    async def play_moderator_line(self, text: str) -> None:
        await self._say("moderator", text, "neutral")

    async def _say(self, speaker: str, text: str, style: str | None) -> None:
        if not self.background:
            await self._render(speaker, text, style)
            return
        self._queue.put_nowait((speaker, text, style))
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._work())

    async def _work(self) -> None:
        while not self._queue.empty():
            speaker, text, style = self._queue.get_nowait()
            try:
                await self._render(speaker, text, style)
            except Exception as exc:  # a broken render never kills the worker
                await self._status("tts_failed", speaker=speaker, detail=str(exc)[:200])

    async def play_sfx(self, sfx_id: str) -> None:
        return None  # phone/door are local clips the browser plays from sfx_url

    async def cancel_speech(self) -> None:
        """Skip/Pause: drop lines not yet rendered (the browser stops what is playing)."""
        while not self._queue.empty():
            self._queue.get_nowait()

    async def stop_voice_session(self) -> None:
        # Let the last line (the closing ack) finish rendering; the worker exits on its own.
        await self._status("stopped")

    async def _status(self, status: str, **extra: object) -> None:
        if self._on_event:
            await self._on_event(SessionEvent(
                type="audio_status", session_id=self._session_id, timestamp_ms=0,
                payload={"status": status, "adapter": "higgs", **extra},
            ))


def _mime(path: Path) -> str:
    return {".png": "image/png", ".webp": "image/webp"}.get(path.suffix.lower(), "image/jpeg")


def _video_size(face: Path) -> str:
    """Match the video's shape to the portrait's, so the face doesn't jump when the still
    photo hands over to the talking head (Higgs sizes: 640x640, 480x640, 640x480)."""
    try:
        import pymupdf

        pix = pymupdf.Pixmap(str(face))
        ratio = pix.width / pix.height
    except Exception:
        return "480x640"
    if ratio > 1.15:
        return "640x480"
    if ratio < 0.87:
        return "480x640"
    return "640x640"
