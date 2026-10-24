"""Opt-in, bounded Boson checks; never print credentials or raw vendor errors.

Run: .venv/bin/python scripts/try_voice.py --live --check transcription
Generated speech is a synthetic fixture, not a microphone or listening test.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import re
import time
import wave
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from websockets.asyncio.client import ClientConnection, connect

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "voice_checks"
API = "https://api.boson.ai/v1"
WS = "wss://api.boson.ai/v1/realtime"
RATE = 24_000
LINE = "Welcome to PresAI. Please begin your presentation."
CHECKS = ("output", "realtime", "transcription", "browser-auth")


class VendorError(Exception):
    """Generic failure: vendor messages may contain private request material."""


def config(*, audio: bool = False, voice: str = "default") -> dict[str, Any]:
    return {"type": "session.update", "session": {
        "model": os.getenv("BOSON_REALTIME_MODEL", "higgs-realtime"),
        "output_modalities": ["audio" if audio else "text"],
        "audio": {
            "input": {"format": {"type": "audio/pcm", "rate": RATE},
                      "turn_detection": None,
                      "transcription": {"model": "higgs-stt-3.1", "language": "en"}},
            "output": {"format": {"type": "audio/pcm", "rate": RATE}, "voice": voice},
        }, "max_output_tokens": 128,
    }}


async def receive(ws: ClientConnection) -> dict[str, Any]:
    event = json.loads(await ws.recv())
    if event.get("type") == "error":
        raise VendorError("vendor_error")
    return event


async def wait_event(ws: ClientConnection, kind: str) -> dict[str, Any]:
    async with asyncio.timeout(20):
        while True:
            event = await receive(ws)
            if event.get("type") == kind:
                return event


@asynccontextmanager
async def socket(key: str, *, ephemeral: bool = False):
    options: dict[str, Any] = {"open_timeout": 15, "close_timeout": 3}
    if ephemeral:
        options["subprotocols"] = ["realtime", f"bai-client-secret.{key}"]
    else:
        options["additional_headers"] = {"Authorization": f"Bearer {key}"}
    async with connect(WS, **options) as ws:
        yield ws


def save_wav(path: Path, pcm: bytes) -> None:
    if not pcm or len(pcm) % 2:
        raise VendorError("invalid_pcm")
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(RATE)
        wav.writeframes(pcm)


async def output(client: httpx.AsyncClient) -> dict[str, Any]:
    started = time.perf_counter()
    first_ms = None
    chunks = []
    async with client.stream("POST", "/v1/audio/speech", json={
        "model": os.getenv("BOSON_TTS_MODEL", "higgs-tts-3"), "input": LINE,
        "voice": "eleanor", "stream": True, "response_format": "pcm",
    }) as response:
        response.raise_for_status()
        async for chunk in response.aiter_bytes():
            if chunk and first_ms is None:
                first_ms = round((time.perf_counter() - started) * 1000)
            chunks.append(chunk)
    pcm = b"".join(chunks)
    save_wav(OUT / "output.wav", pcm)
    return {"status": "pass", "voice": "eleanor", "first_audio_ms": first_ms,
            "audio_duration_ms": round(len(pcm) / 48), "file": "output.wav",
            "audible_quality_verified": False}


def words(text: str) -> list[str]:
    return re.findall(r"\w+", text.casefold())


async def spoken_turn(ws: ClientConnection) -> dict[str, Any]:
    await ws.send(json.dumps({"type": "response.create", "response": {
        "instructions": "Speak only the following exact text, with no additions: " + LINE,
        "input": [{"type": "message", "role": "user", "content": [
            {"type": "input_text", "text": "Read exactly: " + LINE}]}],
        "max_output_tokens": 128,
    }}))
    started, first_ms, caption, pcm = time.perf_counter(), None, "", bytearray()
    while True:
        event = await receive(ws)
        kind = event.get("type")
        if kind == "response.output_audio.delta":
            pcm.extend(base64.b64decode(event["delta"], validate=True))
            if first_ms is None:
                first_ms = round((time.perf_counter() - started) * 1000)
        elif kind == "response.output_audio_transcript.delta":
            caption += event.get("delta", "")
        elif kind == "response.output_audio_transcript.done":
            caption = event.get("transcript", caption)
        elif kind == "response.done":
            completed = event.get("response", {}).get("status") == "completed"
            return {"pcm": bytes(pcm), "first_audio_ms": first_ms,
                    "caption_matches_script": words(caption) == words(LINE),
                    "response_completed": completed}


async def realtime(key: str) -> dict[str, Any]:
    turns = []
    async with socket(key) as ws:
        await ws.send(json.dumps(config(audio=True)))
        await wait_event(ws, "session.created")
        for voice in ("default", "eleanor"):
            if voice != "default":
                await ws.send(json.dumps({"type": "session.update", "session": {
                    "audio": {"output": {"voice": voice}}}}))
                await wait_event(ws, "session.updated")
            turn = await spoken_turn(ws)
            save_wav(OUT / f"realtime_{voice}.wav", turn.pop("pcm"))
            turns.append({"voice": voice, **turn})
    passed = all(t["response_completed"] and t["caption_matches_script"] for t in turns)
    return {"status": "pass" if passed else "fail", "turns": turns,
            "voice_switch_accepted": True, "audible_voice_difference_verified": False}


async def transcription(client: httpx.AsyncClient, key: str) -> dict[str, Any]:
    fixture = OUT / "first_speech.wav"
    if not fixture.exists():
        if not (OUT / "output.wav").exists():
            await output(client)
        fixture = OUT / "output.wav"
    with wave.open(str(fixture), "rb") as wav:
        if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, RATE):
            raise VendorError("unsupported_fixture_format")
        pcm = wav.readframes(wav.getnframes())
    async with socket(key) as ws:
        await ws.send(json.dumps(config()))
        await wait_event(ws, "session.created")
        for offset in range(0, len(pcm), 4800):
            await ws.send(json.dumps({"type": "input_audio_buffer.append",
                "audio": base64.b64encode(pcm[offset:offset + 4800]).decode()}))
            await asyncio.sleep(0.1)
        started = time.perf_counter()
        await ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
        automatic = False
        async with asyncio.timeout(25):
            while True:
                event = await receive(ws)
                automatic |= event.get("type") == "response.created"
                if event.get("type") == "conversation.item.input_audio_transcription.completed":
                    text = event.get("transcript", "")
                    break
        transcript_ms = round((time.perf_counter() - started) * 1000)
        until = time.perf_counter() + 1.5
        while (remaining := until - time.perf_counter()) > 0:
            try:
                event = await asyncio.wait_for(receive(ws), remaining)
            except TimeoutError:
                break
            automatic |= event.get("type") == "response.created"
    return {"status": "pass" if text.strip() and not automatic else "fail",
            "synthetic_fixture": fixture.name, "transcript": text,
            "transcript_after_commit_ms": transcript_ms,
            "autonomous_response_observed": automatic, "quiet_observation_ms": 1500,
            "microphone_verified": False, "speech_timestamps_provided": False}


async def browser_auth(client: httpx.AsyncClient) -> dict[str, Any]:
    response = await client.post("/v1/realtime/client_secrets",
                                 json={"expires_after": {"seconds": 300}})
    response.raise_for_status()
    secret = response.json()
    async with socket(secret["value"], ephemeral=True) as ws:
        await ws.send(json.dumps(config()))
        await wait_event(ws, "session.created")
    return {"status": "pass", "ephemeral_websocket_subprotocol_verified": True,
            "browser_runtime_verified": False}


async def run(selected: str) -> int:
    load_dotenv(ROOT / ".env")
    key = os.getenv("BOSON_API_KEY", "")
    if not key:
        print("BOSON_API_KEY is missing; no requests sent.")
        return 2
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "results.json"
    results = json.loads(path.read_text()) if path.exists() else {}
    requested = CHECKS if selected == "all" else (selected,)
    failed = False
    async with httpx.AsyncClient(base_url=API.removesuffix("/v1"),
            headers={"Authorization": f"Bearer {key}"}, timeout=30) as client:
        for check in requested:
            try:
                async with asyncio.timeout(60):
                    if check == "output":
                        result = await output(client)
                    elif check == "realtime":
                        result = await realtime(key)
                    elif check == "transcription":
                        result = await transcription(client, key)
                    else:
                        result = await browser_auth(client)
            except Exception as exc:
                result = {"status": "fail", "error_type": type(exc).__name__}
            result["checked_at_utc"] = datetime.now(UTC).isoformat()
            results[check] = result
            path.write_text(json.dumps(results, indent=2) + "\n")
            print(json.dumps({check: result}, indent=2))
            failed |= result["status"] != "pass"
    return 1 if failed else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Allow short, billable API calls")
    parser.add_argument("--check", choices=(*CHECKS, "all"), default="output")
    args = parser.parse_args()
    if not args.live:
        parser.error("Pass --live explicitly to send billable Boson requests.")
    raise SystemExit(asyncio.run(run(args.check)))
