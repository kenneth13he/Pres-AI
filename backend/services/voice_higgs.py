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
import json
import os
import time
import uuid
from pathlib import Path

import httpx

from spec.contracts import SessionConfig, SessionEvent

from .avatar_live import LiveAvatarRoom, livekit_configured
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
AVATAR_BUDGET_S = float(os.environ.get("BOSON_AVATAR_BUDGET_S", "10"))
IDLE_S = 2  # first listening loop: short, so a line never waits long for its start frame
TAIL_S = 2.0  # silence after each line: the face settles, and this tail becomes its rest loop
VOICE_REGISTRY = AUDIO_DIR.parent / "voices.json"
# Each character's voice is cloned once from this neutral line, then reused by ID for every
# line, so timbre can't drift between lines (preset + tags re-rolls it every time).
VOICE_SCRIPT = ("Thanks for having me on this call. I'll be listening closely, and I'll probably "
                "have a few questions about your numbers, your customers, and your plan.")
# With a cloned voice only the emotion moves; pitch and pace live in the reference itself.
MOOD_EMOTION: dict[str, str] = {
    "impatient": "<|emotion:anger|>", "confused": "<|emotion:confusion|>",
    "thoughtful": "<|emotion:contemplation|>", "pressing": "<|emotion:determination|>",
    "warm": "<|emotion:contentment|>", "neutral": "",
}
PRESET_VOICES = ["marcus", "eleanor", "jake", "chloe", "oliver", "nora"]
MODERATOR_VOICE = "nora"

# A character's voice belongs to its face: the same person always sounds the same, in every
# session and every preset. Characters that share a base voice are told apart by a fixed
# prosody signature (pitch/pace), so no seat is ever re-voiced to resolve a clash.
# Face files are named `<persona_id>--<character>.jpg` (pinned) or `pool_<n>--<character>.jpg`.
CHARACTER_VOICES: dict[str, tuple[str, str]] = {
    # the meeting-room cast (demo/faces_source/grid_room.png)
    "layla": ("eleanor", ""),
    "mei": ("eleanor", "<|prosody:pitch_high|>"),
    "hannah": ("chloe", ""),
    "ava": ("chloe", "<|prosody:pitch_high|>"),
    "ken": ("jake", ""),
    "leo": ("jake", "<|prosody:pitch_low|>"),
    "finn": ("oliver", ""),
    "ray": ("oliver", "<|prosody:pitch_high|>"),
    "dev": ("marcus", "<|prosody:speed_fast|>"),
    "mr_tan": ("marcus", "<|prosody:speed_slow|>"),
    # the first cast (demo/faces_source/grid.png), kept so its faces still work
    # Higgs's built-in live avatars (realtime mode)
    "claire": ("eleanor", ""),
    "emma": ("chloe", ""),
    "james": ("marcus", ""),
    "grace": ("eleanor", ""),
    "margaret": ("eleanor", "<|prosody:pitch_low|><|prosody:speed_slow|>"),
    "emily": ("chloe", ""),
    "sofia": ("chloe", "<|prosody:pitch_low|>"),
    "ethan": ("jake", ""),
    "daniel": ("jake", "<|prosody:pitch_low|>"),
    "lucas": ("oliver", ""),
    "arjun": ("oliver", "<|prosody:pitch_high|>"),
    "mr_chen": ("marcus", ""),
    "dr_wilson": ("marcus", "<|prosody:speed_slow|>"),
}
# Mood of the moment → emotion. The talking head's expression follows the voice, so this is
# what makes the face frown at a heckle and soften on "fair enough".
MOOD_TAGS: dict[str, str] = {
    "impatient": "<|emotion:anger|><|prosody:speed_fast|>",
    "confused": "<|emotion:confusion|>",
    "thoughtful": "<|emotion:contemplation|>",
    "pressing": "<|emotion:determination|>",
    "warm": "<|emotion:contentment|>",
    "neutral": "",
}

# Roster default voices (distinct within every preset's three seats). Custom personas and
# clashes get the first preset not already at the table.
ROSTER_VOICES: dict[str, str] = {
    "vc": "eleanor", "student": "jake", "professor": "marcus", "methods": "oliver",
    "mentor": "chloe", "classmate": "jake", "hiring_manager": "eleanor",
    "senior_eng": "marcus", "recruiter": "chloe", "customer": "chloe",
    "journalist": "eleanor", "exec": "oliver",
}
STYLE_TAGS = MOOD_TAGS  # older name, kept for callers


def character_of(face: Path | None) -> str | None:
    """`vc--grace.jpg` → "grace"; `pool_1--margaret.jpg` → "margaret"."""
    if face is None or "--" not in face.stem:
        return None
    return face.stem.split("--", 1)[1].split(".")[0]


def delivery_tags(character: str | None, mood: str | None) -> str:
    """One group of delivery tokens (a new group replaces the previous one entirely):
    the mood's emotion plus the character's fixed prosody signature."""
    signature = CHARACTER_VOICES.get(character or "", ("", ""))[1]
    return MOOD_TAGS.get(mood or "neutral", "") + signature


class SpendCounter:
    """We keep our own counter because the vendor dashboard lags (CLAUDE.md §13 Money)."""

    tts_chars = 0
    realtime_ms = 0

    @classmethod
    def estimate_usd(cls) -> float:
        return cls.tts_chars / 1000 * 0.015 + cls.realtime_ms / 60_000 * 0.016


def assign_voices(config: SessionConfig, faces: dict[str, Path] | None = None) -> dict[str, str]:
    """Persona id → base preset voice. A seat with a known character face always uses that
    character's voice (its prosody signature keeps it distinct); a faceless seat uses its
    roster voice, or the first preset not yet at the table."""
    out: dict[str, str] = {"moderator": MODERATOR_VOICE}
    used = {MODERATOR_VOICE}
    for p in config.personas:
        character = character_of((faces or {}).get(p.id))
        if character in CHARACTER_VOICES:
            out[p.id] = CHARACTER_VOICES[character][0]
        else:
            want = p.voice_id or ROSTER_VOICES.get(p.id)
            out[p.id] = want if want in PRESET_VOICES and want not in used else next(
                (v for v in PRESET_VOICES if v not in used), PRESET_VOICES[0])
        used.add(out[p.id])
    return out


def _key(face: Path) -> str:
    return face.stem.split("--", 1)[0]


def assign_faces(persona_ids: list[str], faces_dir: Path | None = None) -> dict[str, Path]:
    """Persona id → portrait. `<persona_id>--<character>` files are pinned; `pool_*` files go to
    the remaining (custom) seats in name order, never repeating a character already seated.
    Faces pinned to other roster personas are never handed out. Test faces (leading "_") are
    used only when nothing else is there. Seats without a face stay illustrated."""
    d = faces_dir or FACES_DIR
    files = sorted(p for p in d.glob("*") if p.suffix.lower() in FACE_EXTS) if d.exists() else []
    out: dict[str, Path] = {}
    for pid in persona_ids:
        pinned = next((f for f in files if _key(f) == pid), None)
        if pinned:
            out[pid] = pinned
    reserved = set(persona_ids) | set(ROSTER_VOICES)
    pool = [f for f in files if _key(f) not in reserved and not f.stem.startswith("_")]
    if not pool:
        pool = [f for f in files if f.stem.startswith("_")]
    for pid in persona_ids:
        if pid in out or not pool:
            continue
        seated = {character_of(f) or f.stem for f in out.values()}
        free = [f for f in pool if (character_of(f) or f.stem) not in seated]
        if free:
            out[pid] = free[0]
        elif len(pool) == 1:
            out[pid] = pool[0]  # a lone test face is shared
    return out


class HiggsVoice:
    """Lines are rendered off the room's critical path: `request_persona_turn` queues the line
    and returns at once; one worker renders the queue in order (TTS ~2 s, + video ~5–8 s) and
    announces each clip as it is ready. `background=False` renders inline (tests)."""

    def __init__(self, client: httpx.AsyncClient | None = None,
                 audio_dir: Path | None = None, faces_dir: Path | None = None,
                 background: bool = True) -> None:
        self.background = background
        self._real_client = client is None  # live avatars only ever with the real API
        self._queue: asyncio.Queue[tuple[str, str, str | None]] = asyncio.Queue()
        self._worker: asyncio.Task[None] | None = None
        self._idle_jobs: list[tuple[str, Path]] = []
        self.api_key = os.environ.get("BOSON_API_KEY", "")
        self.tts_model = os.environ.get("BOSON_TTS_MODEL", "higgs-tts-3")
        self.audio_dir = audio_dir or AUDIO_DIR
        self.faces_dir = faces_dir or FACES_DIR
        self.avatar_enabled = os.environ.get("BOSON_AVATAR_ENABLED", "false") == "true"
        self.avatar_budget_s = AVATAR_BUDGET_S
        self._faces: dict[str, Path] = {}
        self._last_frame: dict[str, Path] = {}   # speaker → where their face is right now
        self._voice_ids: dict[str, str] = {}     # speaker → cloned voice id
        self._voice_jobs: list[str] = []
        self._live: LiveAvatarRoom | None = None   # realtime avatars, when LiveKit is set up
        self._live_pending = False
        self._live_chars: dict[str, str] = {}
        self._clip_faces: dict[str, Path] = {}
        # Cloned voices are on for real use; injected test clients keep the preset path.
        self.custom_voices = (client is None
                              and os.environ.get("BOSON_CUSTOM_VOICES", "true") == "true")
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
        if self._live is not None and speaker in self._live.seats:
            await self._render_live(speaker, text, style)
            return
        cloned = self._voice_ids.get(speaker)
        voice = cloned or self._voices.get(speaker) or PRESET_VOICES[0]
        tags = (MOOD_EMOTION.get(style or "neutral", "") if cloned
                else delivery_tags(character_of(self._faces.get(speaker)), style))
        tagged = tags + text
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
            rest = await self._carry_on(speaker, out / f"{stem}.mp4")
            await self._status("clip", speaker=speaker, voice=voice, text=text, kind="video",
                               url=f"/audio/{self._session_id}/{stem}.mp4",
                               rest_url=f"/audio/{self._session_id}/{rest.name}" if rest else None)
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
        # A silent tail lets the face finish the sentence, close its mouth and settle back to
        # rest by itself, so the clip ends in the pose the idle loop starts from — no snap.
        audio = await _with_silent_tail(mp3, TAIL_S)
        # Start from where this person's face is now (their last frame), not the photo.
        ref = self._last_frame.get(speaker) or face
        ok = await self._avatar_video(ref, audio, dest,
                                      budget_s=self.avatar_budget_s, speaker=speaker)
        return ok

    async def _carry_on(self, speaker: str, video: Path) -> Path | None:
        """After a line: keep the face exactly where it ended. Saves the last frame (the next
        line starts from it) and makes a rest loop from the silent tail — reversed then forward,
        so it begins on the very last frame and loops with no seam. Never the original photo."""
        frame = video.with_suffix(".last.jpg")
        rest = video.with_suffix(".rest.mp4")
        if await _ffmpeg("-sseof", "-0.25", "-i", str(video), "-update", "1", "-frames:v", "1",
                         "-q:v", "2", str(frame)):
            self._last_frame[speaker] = frame
        ok = await _ffmpeg(
            "-sseof", f"-{TAIL_S - 0.2:.1f}", "-i", str(video), "-an", "-filter_complex",
            "[0:v]split[a][b];[a]reverse[r];[r][b]concat=n=2:v=1:a=0[v]",
            "-map", "[v]", "-movflags", "+faststart", str(rest))
        return rest if ok else None

    async def _avatar_video(self, face: Path, audio: tuple[str, bytes, str], dest: Path,
                            budget_s: float, speaker: str = "") -> bool:
        deadline = time.monotonic() + budget_s
        try:
            resp = await self._client.post(
                "/videos",
                data={"model": "higgs-avatar", "size": _video_size(face)},
                files={"ref_image": (face.name, face.read_bytes(), _mime(face)), "input": audio},
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
        live = (self.avatar_enabled and self.background and self._real_client
                and livekit_configured())
        if live:
            # Live avatars: Higgs's built-in faces, one continuous stream each.
            self._live = LiveAvatarRoom(session_id, [p.id for p in config.personas])
            self._live_pending = True
            for pid in self._live.seats:
                character = self._live.character(pid) or pid
                self._live_chars[pid] = character
                self._voices[pid] = CHARACTER_VOICES[character][0]
            self._clip_faces = self._faces  # for any seat that can't go live
            self._faces = {}  # the live stream is the face
        await self._status("ready", voices=self._voices, avatars=self.avatar_enabled,
                           live=live,
                           faces={pid: f"/demo/faces/{p.name}" for pid, p in self._faces.items()})
        if self.custom_voices:
            registry = _load_registry()
            for speaker in [*self._voices]:
                key = self._voice_key(speaker)
                if key in registry:
                    self._voice_ids[speaker] = registry[key]
                elif self.background:
                    self._voice_jobs.append(speaker)
        if self.avatar_enabled:
            for pid, face in self._faces.items():
                cached = self._idle_path(face)
                if cached.exists():
                    await self._status("idle", speaker=pid, url=self._idle_url(face))
                elif self.background:
                    self._idle_jobs.append((pid, face))
        if (self._idle_jobs or self._voice_jobs or self._live_pending) and (
                self._worker is None or self._worker.done()):
            self._worker = asyncio.create_task(self._work())

    # ---- one fixed voice per character ----------------------------------------------------

    def _voice_key(self, speaker: str) -> str:
        character = (self._live_chars.get(speaker) or character_of(self._faces.get(speaker))
                     or speaker)
        base, signature = CHARACTER_VOICES.get(character, (self._voices.get(speaker, ""), ""))
        return f"{character}|{base}|{signature}"

    async def _clone_voice(self, speaker: str) -> None:
        """Say VOICE_SCRIPT once in the character's preset + signature, register it as a
        custom voice, remember the id (registry on disk, so every later session reuses it)."""
        key = self._voice_key(speaker)
        _, base, signature = key.split("|", 2)
        tts = await self._client.post("/audio/speech", json={
            "model": self.tts_model, "input": signature + VOICE_SCRIPT,
            "voice": base or self._voices.get(speaker, PRESET_VOICES[0]), "response_format": "mp3",
        })
        tts.raise_for_status()
        SpendCounter.tts_chars += len(VOICE_SCRIPT)
        reg = await self._client.post("/audio/voices", data={
            "ref_text": VOICE_SCRIPT, "title": f"PresAI {key}"},
            files={"ref_audio": ("ref.mp3", tts.content, "audio/mpeg")})
        reg.raise_for_status()
        body = reg.json()
        voice_id = body.get("voice_id") or body["voice"]  # live API: voice_id; one doc says voice
        registry = _load_registry()
        registry[key] = voice_id
        VOICE_REGISTRY.parent.mkdir(parents=True, exist_ok=True)
        VOICE_REGISTRY.write_text(json.dumps(registry, indent=2))
        for s in self._voices:
            if self._voice_key(s) == key:
                self._voice_ids[s] = voice_id
        await self._status("voice_ready", speaker=speaker, voice=voice_id)

    # ---- idle loops: the face is alive while listening, never a frozen photo ---------------

    def _idle_path(self, face: Path) -> Path:
        return self.audio_dir / "_idle" / f"{face.stem}-{int(face.stat().st_mtime)}-{IDLE_S}s.mp4"

    def _idle_url(self, face: Path) -> str:
        return f"/audio/_idle/{self._idle_path(face).name}"

    async def _render_idle(self, speaker: str, face: Path) -> None:
        """6 s of silence → Higgs Avatar → a listening loop (blinks, small head moves), made
        seamless by playing it forward then backward. Cached per face file, so each face
        costs one render ever. Failures leave the still portrait; nothing else depends on it."""
        dest = self._idle_path(face)
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            raw = dest.with_suffix(".raw.mp4")
            ok = await self._avatar_video(face, ("silence.wav", _silence_wav(IDLE_S), "audio/wav"),
                                          raw, budget_s=40)
            if not ok:
                return
            if not await _pingpong(raw, dest):
                raw.replace(dest)
            raw.unlink(missing_ok=True)
        for pid, f in self._faces.items():
            if f == face:
                await self._status("idle", speaker=pid, url=self._idle_url(face))

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
        """Spoken lines always go first; idle loops fill the gaps between them."""
        while not self._queue.empty() or self._idle_jobs or self._voice_jobs or self._live_pending:
            if self._live_pending:
                self._live_pending = False
                await self._start_live()
            elif self._voice_jobs:
                speaker = self._voice_jobs.pop(0)
                try:
                    if speaker not in self._voice_ids:
                        await self._clone_voice(speaker)
                except Exception as exc:  # keeps the preset voice for this speaker
                    await self._status("voice_failed", speaker=speaker, detail=str(exc)[:200])
            elif not self._queue.empty():
                speaker, text, style = self._queue.get_nowait()
                try:
                    await self._render(speaker, text, style)
                except Exception as exc:  # a broken render never kills the worker
                    await self._status("tts_failed", speaker=speaker, detail=str(exc)[:200])
            else:
                pid, face = self._idle_jobs.pop(0)
                try:
                    await self._render_idle(pid, face)
                except Exception as exc:
                    await self._status("idle_failed", speaker=pid, detail=str(exc)[:200])

    async def play_sfx(self, sfx_id: str) -> None:
        return None  # phone/door are local clips the browser plays from sfx_url

    def fast_speakers(self) -> set[str]:
        """Panelists who can answer instantly (live avatars stream; clips must render)."""
        return set(self._live.seats) if self._live is not None else set()

    async def cancel_speech(self) -> None:
        """Skip/Pause: drop lines not yet rendered (the browser stops what is playing) and cut
        off a live avatar mid-sentence."""
        while not self._queue.empty():
            self._queue.get_nowait()
        if self._live is not None:
            self._live.interrupt()

    async def stop_voice_session(self) -> None:
        # Let the last line (the closing ack) finish, then release the live avatars (billing).
        if self._live is not None:
            live, self._live = self._live, None
            asyncio.create_task(_close_after(live, self._worker))
        await self._status("stopped")

    # ---- live avatars ----------------------------------------------------------------------

    async def _start_live(self) -> None:
        assert self._live is not None
        try:
            await self._live.start()
        except Exception as exc:
            # No LiveKit / no capacity / Higgs refused: everyone falls back to clips.
            self._live = None
            self._live_chars = {}
            self._faces = self._clip_faces
            await self._status("live_failed", detail=str(exc)[:300])
            await self._start_clip_faces(list(self._faces))
            return
        # Seats that didn't get a live slot keep their own face and voice on clips.
        clip_seats = [pid for pid in self._live_chars if pid not in self._live.seats]
        for pid in clip_seats:
            self._live_chars.pop(pid)
            if pid in self._clip_faces:
                self._faces[pid] = self._clip_faces[pid]
                character = character_of(self._faces[pid])
                if character in CHARACTER_VOICES:
                    self._voices[pid] = CHARACTER_VOICES[character][0]
            self._voice_ids.pop(pid, None)
        await self._status("live_ready", **self._live.viewer(), refused=self._live.refused,
                           clip_faces={pid: f"/demo/faces/{self._faces[pid].name}"
                                       for pid in clip_seats if pid in self._faces})
        await self._start_clip_faces(clip_seats)

    async def _start_clip_faces(self, pids: list[str]) -> None:
        """Clip-mode seats need their cloned voice and their first listening loop."""
        registry = _load_registry() if self.custom_voices else {}
        for pid in pids:
            key = self._voice_key(pid)
            if key in registry:
                self._voice_ids[pid] = registry[key]
            elif self.custom_voices:
                self._voice_jobs.append(pid)
            face = self._faces.get(pid)
            if face is None or not self.avatar_enabled:
                continue
            if self._idle_path(face).exists():
                await self._status("idle", speaker=pid, url=self._idle_url(face))
            else:
                self._idle_jobs.append((pid, face))

    async def _render_live(self, speaker: str, text: str, style: str | None) -> None:
        """Stream the line's speech (cloned voice, emotion tag) straight into the avatar."""
        assert self._live is not None
        cloned = self._voice_ids.get(speaker)
        voice = cloned or self._voices.get(speaker) or PRESET_VOICES[0]
        tags = (MOOD_EMOTION.get(style or "neutral", "") if cloned
                else delivery_tags(self._live_chars.get(speaker), style))
        SpendCounter.tts_chars += len(tags + text)

        async def pcm():
            async with self._client.stream("POST", "/audio/speech", json={
                "model": self.tts_model, "input": tags + text, "voice": voice,
                "stream": True, "response_format": "pcm",
            }) as resp:
                resp.raise_for_status()
                async for chunk in resp.aiter_bytes():
                    yield chunk

        await self._status("live_line", speaker=speaker, text=text)
        try:
            seconds = await self._live.speak(speaker, pcm())
        except Exception as exc:
            await self._status("tts_failed", speaker=speaker, detail=str(exc)[:200])
            return
        finally:
            pass
        await self._status("live_done", speaker=speaker, seconds=round(seconds, 2))

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


def _silence_wav(seconds: int) -> bytes:
    import io
    import wave

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24_000)
        w.writeframes(b"\x00\x00" * 24_000 * seconds)
    return buf.getvalue()


async def _pingpong(src: Path, dest: Path) -> bool:
    """Forward then reversed → a loop with no seam. False if ffmpeg is unavailable/fails."""
    import shutil

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return False
    proc = await asyncio.create_subprocess_exec(
        ffmpeg, "-y", "-loglevel", "error", "-i", str(src),
        "-filter_complex", "[0:v]reverse[r];[0:v][r]concat=n=2:v=1:a=0[v]",
        "-map", "[v]", "-an", "-movflags", "+faststart", str(dest),
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )
    _, err = await proc.communicate()
    return proc.returncode == 0 and dest.exists()


async def _with_silent_tail(mp3: bytes, seconds: float) -> tuple[str, bytes, str]:
    """The line's audio with `seconds` of silence appended (mp3, via ffmpeg). Falls back to
    the plain mp3 if ffmpeg is unavailable — the clip then just ends a little abruptly."""
    import shutil

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return ("line.mp3", mp3, "audio/mpeg")
    proc = await asyncio.create_subprocess_exec(
        ffmpeg, "-loglevel", "error", "-f", "mp3", "-i", "pipe:0",
        "-af", f"apad=pad_dur={seconds}", "-ar", "24000", "-ac", "1",
        "-c:a", "libmp3lame", "-b:a", "64k", "-f", "mp3", "pipe:1",  # wav to a pipe has no length
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, _ = await proc.communicate(mp3)
    if proc.returncode != 0 or len(out) < 100:
        return ("line.mp3", mp3, "audio/mpeg")
    return ("line.mp3", out, "audio/mpeg")


def _load_registry() -> dict[str, str]:
    try:
        return json.loads(VOICE_REGISTRY.read_text())
    except (OSError, ValueError):
        return {}


async def _ffmpeg(*args: str) -> bool:
    import shutil

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return False
    proc = await asyncio.create_subprocess_exec(
        ffmpeg, "-y", "-loglevel", "error", *args,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
    await proc.communicate()
    return proc.returncode == 0


async def _close_after(live: LiveAvatarRoom, worker: asyncio.Task | None) -> None:
    if worker is not None:
        try:
            await asyncio.wait_for(asyncio.shield(worker), timeout=20)
        except Exception:
            pass
    await live.close()
