"""The live-face pool without Higgs: refused starts retry, dead or expiring faces are
replaced (new one live before the old one closes), an idle pool shuts itself down."""

import asyncio
from typing import Any

from backend.services import avatar_live
from backend.services.avatar_live import MAX_CALL_S, REFRESH_S, FacePool


class FakeRoom:
    def __init__(self, character):
        self.character, self.up, self.closed = character, True, False

    def alive(self, character):
        return self.up and not self.closed

    def viewer(self):
        return {"url": "wss://x", "room": f"r-{id(self)}", "token": "t"}

    async def close(self):
        self.closed = True


def pool_with(refusals: dict[str, int], now: list[float]) -> Any:
    async def opener(character):
        if refusals.get(character, 0):
            refusals[character] -= 1
            raise RuntimeError("Every realtime avatar slot is in use")
        return FakeRoom(character)
    return FacePool(["claire", "james"], opener=opener,  # type: ignore[arg-type]
                    clock=lambda: now[0])


async def test_a_refused_face_keeps_trying_and_listeners_hear_when_it_is_up():
    now = [0.0]
    pool = pool_with({"james": 2}, now)
    heard: list[str] = []

    async def listener(c):
        heard.append(c)
    pool.listeners.add(listener)
    assert await pool.refresh("claire")
    assert not await pool.refresh("james") and not await pool.refresh("james")
    assert "slot is in use" in pool.status()["james"]
    assert await pool.refresh("james")
    assert heard == ["claire", "james"] and pool.status() == {"claire": "live", "james": "live"}


async def test_a_face_that_left_or_is_about_to_expire_is_replaced_new_first():
    now = [0.0]
    pool = pool_with({}, now)
    await pool.refresh("claire")
    await pool.refresh("james")
    assert not pool._due("claire")
    old = pool.rooms["claire"]
    old.up = False  # the avatar dropped out of its room
    assert pool._due("claire") and pool.room("claire") is None
    await pool.refresh("claire")
    assert pool.rooms["claire"] is not old and old.closed

    now[0] = MAX_CALL_S - REFRESH_S + 1
    assert pool._due("james")


async def test_an_idle_pool_releases_every_face(monkeypatch):
    monkeypatch.setattr(avatar_live, "POOL_IDLE_S", 10)
    monkeypatch.setattr(avatar_live, "STAGGER_S", 0)
    now = [0.0]
    pool = pool_with({}, now)
    pool.start()
    for _ in range(10):
        await asyncio.sleep(0)
    rooms = list(pool.rooms.values())
    assert len(rooms) == 2
    now[0] = 11
    await asyncio.wait_for(pool._task, 6)  # type: ignore[arg-type]
    assert pool.rooms == {} and all(r.closed for r in rooms)
