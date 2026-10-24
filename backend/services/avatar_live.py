"""Higgs Avatar realtime: each panelist's face is one continuous live, lip-synced stream.

Owner: Person B. Docs: docs.boson.ai/models/higgs-avatar/realtime-sessions (24 Oct 2026).

How it fits together, per panelist (one `LiveAvatarRoom` each):
  - one LiveKit room (LiveKit Cloud only — Higgs refuses self-hosted servers);
  - one Higgs Avatar session (POST /v1/avatar/sessions) that joins it and publishes that
    person's video + voice;
  - our backend joins as the "agent" and streams each line's speech (24 kHz 16-bit mono PCM)
    to the avatar with LiveKit's DataStreamAudioOutput;
  - the browser joins with a subscribe-only token and puts the video in that person's tile.

Measured 24 Oct on one key: three avatars run at once, but only one per LiveKit room (a
second avatar in the same room is accepted and never joins), and creating them back to back
is rate-limited (429). Starting one is also flaky: "avatar_id was not found" and "every
realtime avatar slot is in use" come and go, so a face can take a minute or more to come up.
That is why the faces live in `FacePool`: started when the server boots, kept up across
calls, so a call never waits on Higgs. Until a face is live its lines play over the still.

Money: ~$0.07/min per live face, ~$12/h for three while the pool is up. Every avatar has a
hard `max_duration_seconds`; the pool replaces each before it expires, shuts down after
POOL_IDLE_S with no call, and releases everything on server shutdown.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from livekit.agents.voice.avatar import DataStreamAudioOutput

BASE_URL = "https://api.boson.ai/v1"
MAX_CALL_S = int(os.environ.get("BOSON_AVATAR_MAX_S", "3600"))  # hard stop per face
SAMPLE_RATE = 24_000
FRAME_SAMPLES = 480  # 20 ms
JOIN_TIMEOUT_S = 20  # an accepted avatar that hasn't published video by then never will
STAGGER_S = 15       # between avatar starts (faster gets 429 rate_limit_exceeded)
RETRY_S = 8          # after a refused start ("not found" / "slots in use" pass quickly)
REFRESH_S = 120      # replace a face this long before its max_duration runs out
POOL_IDLE_S = int(os.environ.get("BOSON_AVATAR_IDLE_S", "7200"))  # no call this long: stop


def livekit_configured() -> bool:
    return all(os.environ.get(k) for k in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"))


def _token(identity: str, room: str, *, publish: bool) -> str:
    from datetime import timedelta

    from livekit import api

    return (api.AccessToken(os.environ["LIVEKIT_API_KEY"], os.environ["LIVEKIT_API_SECRET"])
            .with_identity(identity)
            .with_ttl(timedelta(seconds=MAX_CALL_S + 120))
            .with_grants(api.VideoGrants(room_join=True, room=room, can_publish=publish,
                                         can_publish_data=True, can_subscribe=True))
            .to_jwt())


@dataclass
class LiveSeat:
    persona_id: str
    avatar_id: str
    identity: str
    session_id: str | None = None
    output: DataStreamAudioOutput | None = None


class LiveAvatarRoom:
    """One panelist's live face: its own LiveKit room with one avatar in it."""

    def __init__(self, session_id: str) -> None:
        self.room_name = f"presai-{session_id}-{uuid.uuid4().hex[:6]}"
        self.agent_identity = "presai-agent"
        self.seats: dict[str, LiveSeat] = {}  # only seats that are live
        self._room: Any = None
        self._closed = False
        self._http = httpx.AsyncClient(
            base_url=BASE_URL, timeout=30,
            headers={"Authorization": f"Bearer {os.environ.get('BOSON_API_KEY', '')}"})

    def viewer(self) -> dict[str, str]:
        """What the browser needs to watch the call: a subscribe-only token."""
        return {"url": os.environ["LIVEKIT_URL"], "room": self.room_name,
                "token": _token(f"viewer-{uuid.uuid4().hex[:6]}", self.room_name, publish=False)}

    async def connect(self) -> None:
        from livekit import rtc

        self._room = rtc.Room()
        await self._room.connect(os.environ["LIVEKIT_URL"],
                                 _token(self.agent_identity, self.room_name, publish=True))

    async def add_seat(self, persona_id: str, avatar_id: str) -> str:
        """Bring one avatar into the room; returns its participant identity once it is
        publishing video. Raises (and releases it) if it is refused or never shows up."""
        from livekit.agents.voice.avatar import DataStreamAudioOutput

        if self._room is None or self._closed:
            raise RuntimeError("live room is closed")
        seat = LiveSeat(persona_id, avatar_id, f"avatar-{persona_id}")
        resp = await self._http.post("/avatar/sessions", json={
            "model": "higgs-avatar", "avatar_id": avatar_id,
            "max_duration_seconds": MAX_CALL_S, "output": {"width": 480, "height": 640},
            "transport": {
                "type": "livekit", "url": os.environ["LIVEKIT_URL"], "room_name": self.room_name,
                "participant_token": _token(seat.identity, self.room_name, publish=True),
                "participant_identity": seat.identity,
                "publisher_identity": self.agent_identity, "audio_source": "data_stream",
            },
        })
        if resp.status_code >= 400:
            raise RuntimeError(f"{avatar_id}: {resp.status_code} {resp.text[:200]}")
        seat.session_id = resp.json()["id"]
        if not await self._joined(seat.identity, JOIN_TIMEOUT_S) or self._closed:
            await self._release(seat)
            raise RuntimeError(f"{avatar_id} never joined the room")
        seat.output = DataStreamAudioOutput(self._room, destination_identity=seat.identity,
                                            sample_rate=SAMPLE_RATE)
        self.seats[persona_id] = seat
        return seat.identity

    async def _joined(self, identity: str, timeout_s: float) -> bool:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_s
        while loop.time() < deadline and not self._closed:
            participant = self._room.remote_participants.get(identity)
            pubs = participant.track_publications.values() if participant else ()
            if any(p.kind == 2 for p in pubs):  # rtc.TrackKind.KIND_VIDEO
                return True
            await asyncio.sleep(0.25)
        return False

    async def speak(self, persona_id: str, pcm: AsyncIterator[bytes]) -> float:
        """Stream one line of PCM to the avatar and wait until it has been played.
        Returns the seconds of audio pushed."""
        from livekit import rtc

        out = self.seats[persona_id].output
        assert out is not None
        pushed = 0.0
        buf = b""
        step = FRAME_SAMPLES * 2
        async for chunk in pcm:
            buf += chunk
            while len(buf) >= step:
                frame, buf = buf[:step], buf[step:]
                await out.capture_frame(rtc.AudioFrame(frame, SAMPLE_RATE, 1, FRAME_SAMPLES))
                pushed += FRAME_SAMPLES / SAMPLE_RATE
        if len(buf) >= 2:
            n = len(buf) // 2
            await out.capture_frame(rtc.AudioFrame(buf[: n * 2], SAMPLE_RATE, 1, n))
            pushed += n / SAMPLE_RATE
        out.flush()
        try:
            await asyncio.wait_for(out.wait_for_playout(), timeout=pushed + 8)
        except TimeoutError:
            pass
        return pushed

    def alive(self, persona_id: str) -> bool:
        """Still connected and the avatar still in the room."""
        seat = self.seats.get(persona_id)
        return (seat is not None and self._room is not None and not self._closed
                and seat.identity in self._room.remote_participants)

    def interrupt(self) -> None:
        for seat in self.seats.values():
            if seat.output is not None:
                seat.output.clear_buffer()

    async def _release(self, seat: LiveSeat) -> None:
        if seat.session_id:
            try:
                await self._http.delete(f"/avatar/sessions/{seat.session_id}")
            except httpx.HTTPError:
                pass
            seat.session_id = None

    async def close(self) -> None:
        """Release every avatar (stops billing) and leave the room. Safe to call twice."""
        self._closed = True
        for seat in list(self.seats.values()):
            await self._release(seat)
        self.seats.clear()
        if self._room is not None:
            try:
                await self._room.disconnect()
            except Exception:
                pass
            self._room = None


async def open_face(character: str) -> LiveAvatarRoom:
    """A new room with Higgs's built-in `character` avatar live in it; raises if refused."""
    room = LiveAvatarRoom("pool")
    try:
        await room.connect()
        await room.add_seat(character, f"builtin_{character}_v1")
    except BaseException:
        await room.close()
        raise
    return room


class FacePool:
    """The panel's live faces, one per character, kept up across calls.

    One keeper task walks the characters: a face that is missing, gone from its room or near
    its max duration gets a new room (started STAGGER_S apart, retried every RETRY_S); the new
    room goes live first, then listeners hear about it, then the old one closes. Sessions
    borrow faces (`room`) and listen for new ones; they never close them.
    """

    def __init__(self, characters: list[str],
                 opener: Callable[[str], Awaitable[LiveAvatarRoom]] = open_face,
                 clock: Callable[[], float] | None = None) -> None:
        self.characters = characters
        self.rooms: dict[str, LiveAvatarRoom] = {}
        self.errors: dict[str, str] = {}
        self.listeners: set[Callable[[str], Awaitable[None]]] = set()
        self._born: dict[str, float] = {}
        self._opener = opener
        self._clock = clock
        self._task: asyncio.Task[None] | None = None
        self._last_used = 0.0

    def _now(self) -> float:
        return self._clock() if self._clock else asyncio.get_running_loop().time()

    def start(self) -> None:
        self._last_used = self._now()
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._keep())

    def room(self, character: str) -> LiveAvatarRoom | None:
        room = self.rooms.get(character)
        return room if room is not None and room.alive(character) else None

    def status(self) -> dict[str, str]:
        return {c: "live" if self.room(c) else self.errors.get(c, "starting")
                for c in self.characters}

    def _due(self, character: str) -> bool:
        if self.room(character) is None:
            return True
        return self._now() - self._born[character] > MAX_CALL_S - REFRESH_S

    async def _keep(self) -> None:
        while True:
            if self.listeners:
                self._last_used = self._now()
            elif self._now() - self._last_used > POOL_IDLE_S:
                await self.close()  # nobody has called in a while: stop paying
                return
            due = [c for c in self.characters if self._due(c)]
            if not due:
                await asyncio.sleep(5)
                continue
            for character in due:
                if await self.refresh(character):
                    await asyncio.sleep(STAGGER_S)
                else:
                    await asyncio.sleep(RETRY_S)

    async def refresh(self, character: str) -> bool:
        """One attempt at a new face for `character`; True if it went live."""
        try:
            new = await self._opener(character)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.errors[character] = f"{type(exc).__name__}: {exc}"[:300]
            return False
        old = self.rooms.get(character)
        self.rooms[character] = new
        self._born[character] = self._now()
        self.errors.pop(character, None)
        for listener in list(self.listeners):
            try:
                await listener(character)
            except Exception:
                pass
        if old is not None:
            await old.close()
        return True

    async def close(self) -> None:
        task, self._task = self._task, None
        if task is not None and task is not asyncio.current_task():
            task.cancel()
        rooms, self.rooms = self.rooms, {}
        for room in rooms.values():
            await room.close()
