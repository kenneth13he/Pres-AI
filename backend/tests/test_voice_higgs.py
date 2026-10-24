"""Higgs TTS adapter without the network: seats, cloned voices, clip files, failure path."""

import json
import struct

import httpx

from backend import presets
from backend.services.voice_higgs import HiggsVoice, SpendCounter, seat_characters, wav
from backend.tests.conftest import make_config, make_session, s

PCM = b"\x01\x00" * 24_000  # one second of 24 kHz 16-bit mono


def higgs(tmp_path, status=200, seen=None, registry=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/audio/voices"):
            return httpx.Response(200, json={"voice_id": "voice_new"}, request=request)
        if seen is not None:
            seen.append(json.loads(request.content))
        if status != 200:
            return httpx.Response(status, json={"error": "nope"}, request=request)
        return httpx.Response(200, content=PCM, request=request)
    reg = tmp_path / "voices.json"
    reg.write_text(json.dumps(registry if registry is not None else {
        "claire|eleanor|": "voice_claire", "james|marcus|": "voice_james",
        "emma|chloe|": "voice_emma", "moderator|nora|": "voice_mod"}))
    client = httpx.AsyncClient(base_url="https://api.boson.ai/v1",
                               transport=httpx.MockTransport(handler))
    return HiggsVoice(client=client, audio_dir=tmp_path, registry=reg)


def test_every_seat_is_a_different_character_in_every_preset():
    for preset in presets.presets().values():
        cfg = make_config(preset_id=preset.id,
                          personas=[p.model_dump() for p in presets.default_personas_for(preset)])
        seats = seat_characters(cfg)
        people = [seats[p.id] for p in cfg.personas]
        assert len(set(people)) == len(people) and seats["moderator"] not in people


def test_wav_header_matches_the_pcm():
    data = wav(PCM)
    assert data[:4] == b"RIFF" and data[8:12] == b"WAVE"
    assert struct.unpack("<I", data[24:28])[0] == 24_000
    assert struct.unpack("<I", data[40:44])[0] == len(PCM)


async def test_a_line_becomes_a_clip_with_its_length_in_the_session_stream(tmp_path):
    seen: list[dict] = []
    session = make_session()
    session.voice = higgs(tmp_path, seen=seen)
    session.voice.on_event(session._on_voice_event)
    before = SpendCounter.tts_chars
    await session.start(0)
    ready = next(e for e in session.events if e.payload.get("status") == "ready")
    assert ready.payload["faces"]["vc"] == "/demo/faces/higgs/claire.png"

    await session.force_curveball("heckler", s(70))
    clip = next(e for e in session.events if e.payload.get("status") == "clip"
                and "wrapper" in e.payload["text"])
    assert clip.payload["speaker"] == "vc" and clip.payload["duration_ms"] == 1000
    assert (tmp_path / clip.payload["url"].removeprefix("/audio/")).read_bytes() == wav(PCM)
    heckle = next(r for r in seen if "wrapper" in r["input"])
    assert heckle["voice"] == "voice_claire" and heckle["response_format"] == "pcm"
    assert heckle["input"].startswith("<|emotion:anger|>")
    assert SpendCounter.tts_chars > before
    # the engine ignores the mic until the line has played (1 s + the echo guard)
    assert session.speaking_until_ms >= s(71)


async def test_tts_failure_is_a_status_not_a_crash(tmp_path):
    v = higgs(tmp_path, status=500)
    events = []

    async def on_event(ev):
        events.append(ev)
    v.on_event(on_event)
    await v.start_voice_session("s1", make_config())
    assert await v.request_persona_turn("vc", "Hello?") is None
    assert events[-1].payload["status"] == "tts_failed"


async def test_a_missing_voice_is_cloned_once_and_remembered(tmp_path):
    v = higgs(tmp_path, registry={})
    await v.start_voice_session("s1", make_config())
    assert await v.request_persona_turn("vc", "Hi.") == 1.0
    assert v._voice_ids["vc"] == "voice_new"
    saved = json.loads((tmp_path / "voices.json").read_text())
    assert saved == {"claire|eleanor|": "voice_new"}
