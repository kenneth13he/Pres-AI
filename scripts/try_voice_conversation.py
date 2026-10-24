"""Opt-in native speech-to-speech check, using synthetic WAVs as microphone fixtures.

Run: .venv/bin/python scripts/try_voice_conversation.py --live
Optional --fixture accepts one or more PCM16/24kHz/mono WAVs for consecutive turns.
No fixed response text is supplied; Higgs answers the audio conversation naturally.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import sys
import time
import wave
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402
from websockets.asyncio.client import ClientConnection  # noqa: E402

from scripts.try_voice import (  # noqa: E402
    OUT,
    RATE,
    VendorError,
    config,
    receive,
    save_wav,
    socket,
    wait_event,
)

INSTRUCTIONS = (
    "You are PresAI, a friendly presentation rehearsal partner. Listen to what the user "
    "actually says and respond naturally in one concise sentence. If the user asks a "
    "question, answer it. Do not recite a fixed greeting or invent details about slides."
)


def read_fixture(path: Path) -> bytes:
    with wave.open(str(path), "rb") as wav:
        if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, RATE):
            raise VendorError("unsupported_fixture_format")
        pcm = wav.readframes(wav.getnframes())
    if not pcm:
        raise VendorError("empty_fixture")
    return pcm


async def feed_fixture(ws: ClientConnection, pcm: bytes) -> float:
    """Simulate capture: each 100ms chunk is sent after its samples have elapsed."""
    started = time.perf_counter()
    for offset in range(0, len(pcm), 4800):
        chunk = pcm[offset:offset + 4800]
        captured_at = started + (offset + len(chunk)) / (RATE * 2)
        await asyncio.sleep(max(0, captured_at - time.perf_counter()))
        await ws.send(json.dumps({"type": "input_audio_buffer.append",
            "audio": base64.b64encode(chunk).decode()}))
    return time.perf_counter()


async def native_turn(ws: ClientConnection, fixture: Path, number: int) -> dict[str, Any]:
    pcm_input = read_fixture(fixture)
    input_ended = await feed_fixture(ws, pcm_input)
    await ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
    committed_id = None
    added_ids: set[str] = set()
    transcript, transcript_at = "", None
    response_requested = False
    response_completed = False
    first_audio_at = None
    caption = ""
    pcm_output = bytearray()
    async with asyncio.timeout(40):
        while True:
            event = await receive(ws)
            kind = event.get("type")
            if kind == "input_audio_buffer.committed":
                committed_id = event.get("item_id")
            elif kind == "conversation.item.added":
                item = event.get("item", {})
                if item.get("role") == "user":
                    added_ids.add(item.get("id", ""))
            elif kind == "conversation.item.input_audio_transcription.completed":
                if event.get("item_id") == committed_id:
                    transcript = event.get("transcript", "")
                    transcript_at = time.perf_counter()
            elif kind == "response.output_audio.delta":
                chunk = base64.b64decode(event["delta"], validate=True)
                if chunk and first_audio_at is None:
                    first_audio_at = time.perf_counter()
                pcm_output.extend(chunk)
            elif kind == "response.output_audio_transcript.delta":
                caption += event.get("delta", "")
            elif kind == "response.output_audio_transcript.done":
                caption = event.get("transcript", caption)
            elif kind == "response.done":
                response_completed = event.get("response", {}).get("status") == "completed"
                if not response_completed:
                    raise VendorError("response_not_completed")
            if committed_id and committed_id in added_ids and not response_requested:
                # Omit `input`: respond to the committed audio and prior conversation.
                await ws.send(json.dumps({"type": "response.create"}))
                response_requested = True
            if response_completed and transcript_at is not None:
                break
    name = "native_response.wav" if number == 1 else f"native_response_{number}.wav"
    save_wav(OUT / name, bytes(pcm_output))
    passed = bool(transcript.strip() and caption.strip() and first_audio_at is not None)
    return {
        "status": "pass" if passed else "fail", "turn": number,
        "synthetic_fixture": fixture.name, "input_transcript": transcript,
        "assistant_caption": caption, "audio_file": name,
        "input_audio_duration_ms": round(len(pcm_input) / (RATE * 2) * 1000),
        "output_audio_duration_ms": round(len(pcm_output) / (RATE * 2) * 1000),
        "synthetic_input_end_to_first_audio_ms": (
            round((first_audio_at - input_ended) * 1000) if first_audio_at else None),
        "transcript_to_first_audio_ms": (
            round((first_audio_at - transcript_at) * 1000)
            if first_audio_at and transcript_at else None),
        "user_item_added_automatically": committed_id in added_ids,
        "response_completed": response_completed,
        "response_input_override_sent": False,
        "fixed_response_text_supplied": False,
    }


async def run(fixtures: list[Path]) -> int:
    load_dotenv(ROOT / ".env")
    key = os.getenv("BOSON_API_KEY", "")
    if not key:
        print("BOSON_API_KEY is missing; no requests sent.")
        return 2
    OUT.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {
        "checked_at_utc": datetime.now(UTC).isoformat(), "status": "fail", "turns": [],
        "microphone_verified": False, "browser_playback_latency_verified": False,
        "audible_quality_verified": False, "semantic_relevance_requires_review": True,
        "latency_source": "paced synthetic audio end to first received audio chunk",
    }
    try:
        # Validate all files before opening a billable connection.
        for fixture in fixtures:
            read_fixture(fixture)
        async with asyncio.timeout(60), socket(key) as ws:
            settings = config(audio=True)
            settings["session"]["instructions"] = INSTRUCTIONS
            await ws.send(json.dumps(settings))
            await wait_event(ws, "session.created")
            for number, fixture in enumerate(fixtures, 1):
                result["turns"].append(await native_turn(ws, fixture, number))
        result["status"] = (
            "pass" if all(turn["status"] == "pass" for turn in result["turns"]) else "fail")
    except Exception as exc:
        result["error_type"] = type(exc).__name__
    # Synthetic transcripts/captions are useful evidence; suppress raw vendor errors/secrets.
    (OUT / "native_response.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Allow a short, billable session")
    parser.add_argument("--fixture", type=Path, nargs="+", default=[OUT / "first_speech.wav"])
    args = parser.parse_args()
    if not args.live:
        parser.error("Pass --live explicitly to send billable Boson requests.")
    raise SystemExit(asyncio.run(run(args.fixture)))
