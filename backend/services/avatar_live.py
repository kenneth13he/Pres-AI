"""Higgs Avatar realtime: each panelist is one continuous live video stream.

Owner: Person B. Docs: docs.boson.ai/models/higgs-avatar/realtime-sessions (24 Oct 2026).

How it fits together, per call:
  - one LiveKit room (LiveKit Cloud only — Higgs refuses self-hosted servers);
  - one Higgs Avatar session per panelist (POST /v1/avatar/sessions), each joining the room
    as its own participant and publishing that person's live video + voice;
  - our backend joins as the single "agent" participant and streams each line's speech
    (24 kHz, 16-bit mono PCM) to the right avatar with LiveKit's DataStreamAudioOutput;
  - the browser joins with a subscribe-only token and shows each avatar's track in its tile.
No clips, no switching: the avatar idles and lip-syncs inside one stream.

Only Higgs's built-in avatars can be used live (no API to add your own face as of today).
Money: Higgs Avatar from ~$0.07/min per live stream. Every session is created with a hard
`max_duration_seconds` and released in `close()`; nothing outlives the call.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from livekit.agents.voice.avatar import DataStreamAudioOutput

BASE_URL = "https://api.boson.ai/v1"
LIVE_AVATARS = ["builtin_claire_v1", "builtin_emma_v1", "builtin_james_v1"]
# Character names for the voice registry and captions (voices are cloned per character).
AVATAR_CHARACTER = {"builtin_claire_v1": "claire", "builtin_emma_v1": "emma",
                    "builtin_james_v1": "james"}
MAX_CALL_S = int(os.environ.get("BOSON_AVATAR_MAX_S", "1200"))  # 20 min hard stop per call
SAMPLE_RATE = 24_000
FRAME_SAMPLES = 480  # 20 ms


def livekit_configured() -> bool:
    return all(os.environ.get(k) for k in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"))


def _token(identity: str, room: str, *, publish: bool, ttl_s: int) -> str:
    from datetime import timedelta

    from livekit import api

    return (api.AccessToken(os.environ["LIVEKIT_API_KEY"], os.environ["LIVEKIT_API_SECRET"])
            .with_identity(identity)
            .with_ttl(timedelta(seconds=ttl_s))
            .with_grants(api.VideoGrants(room_join=True, room=room, can_publish=publish,
                                         can_publish_data=True, can_subscribe=True))
            .to_jwt())


@dataclass
class LiveSeat:
    persona_id: str
    avatar_id: str
    identity: str
    session_id: str | None = None
    output: DataStreamAudioOutput | None = None  # set once connected


@dataclass
class LiveAvatarRoom:
    session_id: str
    persona_ids: list[str]
    api_key: str = field(default_factory=lambda: os.environ.get("BOSON_API_KEY", ""))

    def __post_init__(self) -> None:
        self.room_name = f"presai-{self.session_id}-{uuid.uuid4().hex[:6]}"
        self.agent_identity = "presai-agent"
        self.seats = {pid: LiveSeat(pid, LIVE_AVATARS[i], f"avatar-{pid}")
                      for i, pid in enumerate(self.persona_ids[:len(LIVE_AVATARS)])}
        self._room = None
        self._http = httpx.AsyncClient(base_url=BASE_URL, timeout=30,
                                       headers={"Authorization": f"Bearer {self.api_key}"})

    def character(self, persona_id: str) -> str | None:
        seat = self.seats.get(persona_id)
        return AVATAR_CHARACTER.get(seat.avatar_id) if seat else None

    def viewer(self) -> dict:
        """What the browser needs to watch the call (a subscribe-only token)."""
        return {
            "url": os.environ["LIVEKIT_URL"],
            "token": _token(f"viewer-{uuid.uuid4().hex[:6]}", self.room_name, publish=False,
                            ttl_s=MAX_CALL_S + 120),
            "identities": {pid: s.identity for pid, s in self.seats.items()},
        }

    async def start(self) -> None:
        """Join as the agent, then bring every avatar into the room. Raises on failure (the
        caller falls back to clips); anything already created is released first."""
        from livekit import rtc
        from livekit.agents.voice.avatar import DataStreamAudioOutput

        try:
            self._room = rtc.Room()
            await self._room.connect(os.environ["LIVEKIT_URL"],
                                     _token(self.agent_identity, self.room_name, publish=True,
                                            ttl_s=MAX_CALL_S + 120))
            for seat in self.seats.values():
                resp = await self._http.post("/avatar/sessions", json={
                    "model": "higgs-avatar",
                    "avatar_id": seat.avatar_id,
                    "max_duration_seconds": MAX_CALL_S,
                    "output": {"width": 480, "height": 640},
                    "transport": {
                        "type": "livekit",
                        "url": os.environ["LIVEKIT_URL"],
                        "room_name": self.room_name,
                        "participant_token": _token(seat.identity, self.room_name, publish=True,
                                                    ttl_s=MAX_CALL_S + 120),
                        "participant_identity": seat.identity,
                        "publisher_identity": self.agent_identity,
                        "audio_source": "data_stream",
                    },
                })
                if resp.status_code >= 400:
                    raise RuntimeError(f"avatar session for {seat.persona_id}: "
                                       f"{resp.status_code} {resp.text[:200]}")
                seat.session_id = resp.json()["id"]
                seat.output = DataStreamAudioOutput(self._room, destination_identity=seat.identity,
                                                    sample_rate=SAMPLE_RATE)
        except BaseException:
            await self.close()
            raise

    async def speak(self, persona_id: str, pcm: AsyncIterator[bytes]) -> float:
        """Stream one line of 24 kHz mono PCM to the avatar and wait until it has been played.
        Returns the seconds of audio pushed."""
        from livekit import rtc

        seat = self.seats[persona_id]
        out = seat.output
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

    def interrupt(self, persona_id: str | None = None) -> None:
        for seat in self.seats.values():
            if seat.output is not None and persona_id in (None, seat.persona_id):
                seat.output.clear_buffer()

    async def close(self) -> None:
        """Release every avatar (stops billing) and leave the room. Safe to call twice."""
        for seat in self.seats.values():
            if seat.session_id:
                try:
                    await self._http.delete(f"/avatar/sessions/{seat.session_id}")
                except httpx.HTTPError:
                    pass
                seat.session_id = None
        if self._room is not None:
            try:
                await self._room.disconnect()
            except Exception:
                pass
            self._room = None
