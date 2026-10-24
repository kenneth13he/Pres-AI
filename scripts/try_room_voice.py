"""Opt-in localhost presentation smoke: synthetic transcript + real backend Higgs TTS.

Run with the local server configured VOICE_ADAPTER=higgs, ORCHESTRATOR=mock:
    .venv/bin/python scripts/try_room_voice.py --live
Optional --deck demo/sample_pitch.pdf also checks PDF upload and a rendered slide.
Playback acknowledgements are simulated; this is not a browser/microphone/STT test.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from websockets.asyncio.client import ClientConnection, connect

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "voice_checks"
CLAIM = "We can get 100,000 customers in six months."
SHORT_ANSWER = "We plan to grow through universities."
DETAILED_ANSWER = (
    "Two campus pilots have already measured three hundred weekly active users, "
    "and we will compare retention with the next cohort before expanding."
)


class CheckFailure(Exception):
    """Internal check code only; never carries a vendor response body."""


class Probe:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client
        self.events: list[dict[str, Any]] = []
        self.plays: list[dict[str, Any]] = []
        self.tasks: list[asyncio.Task[None]] = []
        self.session_id = ""
        self.stage = "preflight"
        self.finished = False

    def progress(self, stage: str) -> None:
        self.stage = stage
        print(json.dumps({"stage": stage}), flush=True)

    async def json(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        response = await self.client.request(method, path, **kwargs)
        response.raise_for_status()
        return response.json()

    async def snapshot(self) -> dict[str, Any]:
        return await self.json("GET", f"/api/sessions/{self.session_id}")

    async def clock(self) -> int:
        return int((await self.snapshot())["session_clock_ms"])

    def healthy(self) -> None:
        if any(event.get("type") == "error" for event in self.events):
            raise CheckFailure("room_error_event")
        if any(task.done() for task in self.tasks):
            raise CheckFailure("room_transport_closed")

    async def wait(self, predicate: Callable[[], bool], timeout: float = 20) -> None:
        async with asyncio.timeout(timeout):
            while not predicate():
                self.healthy()
                await asyncio.sleep(0.025)
        self.healthy()

    async def event(self, kind: str, *, since: int = 0,
                    predicate: Callable[[dict[str, Any]], bool] = lambda _: True,
                    timeout: float = 20) -> dict[str, Any]:
        def matches() -> list[dict[str, Any]]:
            return [ev for ev in self.events[since:] if ev.get("type") == kind and predicate(ev)]
        await self.wait(lambda: bool(matches()), timeout)
        return matches()[0]

    async def event_pump(self, ws: ClientConnection) -> None:
        async for message in ws:
            if isinstance(message, str):
                self.events.append(json.loads(message))

    async def audio_pump(self, ws: ClientConnection) -> None:
        current: dict[str, Any] | None = None
        pcm = bytearray()
        async for message in ws:
            if isinstance(message, bytes):
                if current is None:
                    raise CheckFailure("audio_without_speaker")
                pcm.extend(message)
                continue
            event = json.loads(message)
            if event.get("type") == "speech_started":
                if current is not None:
                    raise CheckFailure("overlapping_audio_turns")
                current = {"speaker": event.get("speaker"), "text": event.get("text")}
                pcm = bytearray()
            elif event.get("type") == "speech_complete":
                if current is None or not pcm or len(pcm) % 2:
                    raise CheckFailure("missing_or_invalid_pcm")
                current.update({"pcm_bytes": len(pcm), "audio_duration_ms": round(len(pcm) / 48),
                                "first_audio_ms": event.get("first_audio_ms"),
                                "playback_acknowledgement":
                                    "simulated_immediately_after_generation"})
                self.plays.append(current)
                await ws.send(json.dumps({"type": "played", "play_id": event["play_id"]}))
                current = None
            elif event.get("type") == "cancel":
                current = None
                pcm = bytearray()

    async def at_clock(self, target_ms: int) -> None:
        while (remaining := target_ms - await self.clock()) > 0:
            self.healthy()
            await asyncio.sleep(min(remaining / 1000, 10))

    async def synthetic_turn(self, ws: ClientConnection, turn_id: str, text: str) -> None:
        start_ms = await self.clock()
        await ws.send(json.dumps({"type": "presenter_turn_started", "turn_id": turn_id}))
        await asyncio.sleep(0.12)
        end_ms = await self.clock()
        await self.final(ws, turn_id, text, start_ms, end_ms)

    async def final(self, ws: ClientConnection, turn_id: str, text: str,
                    start_ms: int, end_ms: int) -> None:
        await ws.send(json.dumps({"type": "presenter_turn_ended", "turn_id": turn_id}))
        await ws.send(json.dumps({"type": "transcript_segment", "turn_id": turn_id,
            "segment": {"start_ms": start_ms, "end_ms": end_ms,
                        "text": text, "speaker": "presenter", "confidence": None}}))

    async def flow(self, base_url: str, deck: Path | None) -> dict[str, Any]:
        health = await self.json("GET", "/health")
        adapters = health.get("adapters", {})
        if adapters.get("voice") != "higgs" or adapters.get("orchestrator") != "mock":
            raise CheckFailure("requires_higgs_voice_and_mock_orchestrator")
        if not adapters.get("boson_key"):
            raise CheckFailure("backend_boson_key_missing")
        presets = await self.json("GET", "/api/presets")
        preset = next(p for p in presets["presets"] if p["id"] == "startup_pitch")
        roster = {p["id"]: p for p in presets["personas"]}
        config = {"preset_id": "startup_pitch", "personas": [roster[p] for p in preset["personas"]],
                  "difficulty": "normal", "curveballs": {"mode": "off"}, "qna_questions": 0}
        deck_verified = False
        if deck is not None:
            data = await self.json("POST", "/api/slides", files={
                "file": (deck.name, deck.read_bytes(), "application/pdf")})
            config["deck_id"] = data["deck_id"]
            image = await self.client.get(data["slides"][0]["image_url"])
            image.raise_for_status()
            if not image.content.startswith(b"\x89PNG\r\n\x1a\n"):
                raise CheckFailure("slide_png_missing")
            deck_verified = True
        created = await self.json("POST", "/api/sessions", json={"config": config})
        self.session_id = created["session_id"]
        if created["config"]["input_mode"] != "push_to_talk":
            raise CheckFailure("session_default_is_not_push_to_talk")
        ws_base = base_url.replace("http", "ws", 1)
        async with connect(f"{ws_base}/ws/voice/{self.session_id}", close_timeout=2) as audio:
            ready = json.loads(await asyncio.wait_for(audio.recv(), 5))
            if ready.get("type") != "ready":
                raise CheckFailure("audio_not_ready")
            events_url = f"{ws_base}/ws/sessions/{self.session_id}"
            async with connect(events_url, close_timeout=2) as events:
                self.tasks = [asyncio.create_task(self.audio_pump(audio)),
                              asyncio.create_task(self.event_pump(events))]
                try:
                    return await self.session_flow(events, deck_verified)
                finally:
                    for task in self.tasks:
                        task.cancel()
                    await asyncio.gather(*self.tasks, return_exceptions=True)

    async def session_flow(self, ws: ClientConnection, deck_verified: bool) -> dict[str, Any]:
        self.progress("presentation_started")
        await ws.send(json.dumps({"type": "presentation_started"}))
        await self.event("session_started")
        await self.at_clock(2000)
        await self.synthetic_turn(ws, "synthetic-initial", CLAIM)
        await self.event("transcript_segment")
        self.progress("waiting_for_actual_30_second_question_gate")
        await self.at_clock(28000)
        hold_start = await self.clock()
        await ws.send(json.dumps({"type": "presenter_turn_started", "turn_id": "synthetic-held"}))
        await self.at_clock(31500)
        if any(ev["type"] == "question_queued" for ev in self.events):
            raise CheckFailure("held_turn_interrupted_at_question_gate")
        await ws.send(json.dumps({"type": "presenter_turn_ended", "turn_id": "synthetic-held"}))
        await asyncio.sleep(0.5)
        if any(ev["type"] == "question_queued" for ev in self.events):
            raise CheckFailure("question_interrupted_pending_final_transcript")
        hold_end = await self.clock()
        await ws.send(json.dumps({"type": "transcript_segment", "turn_id": "synthetic-held",
            "segment": {"start_ms": hold_start, "end_ms": hold_end, "text": CLAIM,
                        "speaker": "presenter", "confidence": None}}))
        self.progress("grounded_question_and_live_tts")
        question = await self.event("question_queued")
        payload = question["payload"]
        if not payload.get("cited_excerpt") or payload["cited_excerpt"] not in CLAIM:
            raise CheckFailure("question_not_grounded_in_synthetic_claim")
        if payload.get("persona_id") not in ("vc", "student", "professor"):
            raise CheckFailure("question_persona_not_in_preset")
        await self.event("phase_changed",
                         predicate=lambda ev: ev["payload"].get("to") == "answering")
        marker = len(self.events)
        await self.synthetic_turn(ws, "synthetic-short-answer", SHORT_ANSWER)
        follow = await self.event("question_queued", since=marker)
        if follow["payload"].get("follow_up_of") != payload["question_id"]:
            raise CheckFailure("follow_up_not_linked_to_question")
        # A follow-up keeps the existing answering phase; playback end is its boundary.
        await self.event("ai_speech_ended", since=marker)
        marker = len(self.events)
        await self.synthetic_turn(ws, "synthetic-detailed-answer", DETAILED_ANSWER)
        await self.event("phase_changed", since=marker,
                         predicate=lambda ev: ev["payload"].get("to") == "presenting")
        if len(self.plays) < 3:
            raise CheckFailure("question_follow_up_ack_audio_missing")
        self.progress("pause_resume_and_report")
        path = f"/api/sessions/{self.session_id}/control"
        await self.json("POST", path, json={"action": "pause"})
        frozen = (await self.snapshot())["elapsed_ms"]
        await asyncio.sleep(0.15)
        after = (await self.snapshot())["elapsed_ms"]
        if frozen != after:
            raise CheckFailure("paused_elapsed_clock_advanced")
        await self.json("POST", path, json={"action": "resume"})
        await self.json("POST", path, json={"action": "end"})
        await self.event("session_ended")
        report = await self.json("GET", f"/api/sessions/{self.session_id}/report")
        self.finished = True
        if not any(item.get("evidence") == CLAIM for item in report.get("improvements", [])):
            raise CheckFailure("report_claim_evidence_missing")
        self.healthy()
        return {"status": "pass", "default_push_to_talk_verified": True,
                "preset_personas_verified": True, "deck_png_verified": deck_verified,
                "held_floor_across_30_seconds_verified": True,
                "pending_transcript_floor_verified": True, "paused_clock_frozen": True,
                "question": payload, "follow_up": follow["payload"],
                "plays": self.plays, "room_error_events": 0,
                "report_phase_reached": True, "report": report}


async def main(base_url: str, deck: Path | None) -> int:
    started = time.monotonic()
    async with httpx.AsyncClient(base_url=base_url, timeout=10) as client:
        probe = Probe(client)
        try:
            # Reserve the rest of the 100s budget for socket close and best-effort End.
            async with asyncio.timeout(90):
                result = await probe.flow(base_url, deck)
        except Exception as exc:
            result = {"status": "fail", "stage": probe.stage,
                      "session_id": probe.session_id,
                      "error_type": type(exc).__name__,
                      "check_code": str(exc) if isinstance(exc, CheckFailure) else None,
                      "room_error_events": sum(ev.get("type") == "error" for ev in probe.events)}
        finally:
            if probe.session_id and not probe.finished:
                with suppress(Exception):
                    async with asyncio.timeout(3):
                        await probe.json("POST", f"/api/sessions/{probe.session_id}/control",
                                         json={"action": "end"})
    result.update({"checked_at_utc": datetime.now(UTC).isoformat(),
                   "runtime_s": round(time.monotonic() - started, 2),
                   "synthetic_transcripts": True, "microphone_verified": False,
                   "speech_recognition_verified": False, "browser_playback_verified": False,
                   "playback_acknowledgements_simulated": True})
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "room_integration.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Allow short backend Higgs TTS calls")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--deck", type=Path)
    args = parser.parse_args()
    parsed = urlsplit(args.base_url)
    if not args.live:
        parser.error("Pass --live explicitly; the backend will generate billable speech.")
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1"} or parsed.scheme not in {
        "http", "https",
    } or parsed.username or parsed.password or parsed.path not in ("", "/"):
        parser.error("--base-url must be a localhost HTTP(S) origin.")
    raise SystemExit(asyncio.run(main(args.base_url.rstrip("/"), args.deck)))
