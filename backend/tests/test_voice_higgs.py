"""Higgs TTS adapter without the network: voices, tags, clip files, failure path."""

import json

import httpx

from backend import presets
from backend.services.voice_higgs import HiggsVoice, SpendCounter, assign_voices
from backend.tests.conftest import make_config, make_session, s, seg


def higgs(tmp_path, status=200, seen=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(json.loads(request.content))
        if status != 200:
            return httpx.Response(status, json={"error": "nope"}, request=request)
        return httpx.Response(200, content=b"ID3fake-mp3", request=request)
    client = httpx.AsyncClient(base_url="https://api.boson.ai/v1",
                               transport=httpx.MockTransport(handler))
    return HiggsVoice(client=client, audio_dir=tmp_path)


def test_every_seat_gets_a_distinct_voice_not_the_moderators():
    cfg = make_config()
    voices = assign_voices(cfg)
    seats = [voices[p.id] for p in cfg.personas]
    assert len(set(seats)) == len(seats) and voices["moderator"] not in seats
    for preset in presets.presets().values():
        cfg = make_config(preset_id=preset.id,
                          personas=[p.model_dump() for p in presets.default_personas_for(preset)])
        seats = [assign_voices(cfg)[p.id] for p in cfg.personas]
        assert len(set(seats)) == 3, preset.id


async def test_persona_line_becomes_a_clip_event_in_the_session_stream(tmp_path):
    seen: list[dict] = []
    session = make_session()
    session.voice = higgs(tmp_path, seen=seen)
    session.voice.on_event(session._on_voice_event)
    before = SpendCounter.tts_chars
    await session.start(0)
    await session.slide_changed(s(1), 2)
    await session.force_curveball("heckler", s(70))
    clips = [e for e in session.events
             if e.type == "audio_status" and e.payload["status"] == "clip"]
    assert len(clips) == 1
    clip = clips[0]
    assert clip.payload["speaker"] == "vc" and clip.timestamp_ms == s(70)
    assert clip.payload["url"].startswith(f"/audio/{session.session_id}/")
    assert (tmp_path / clip.payload["url"].removeprefix("/audio/")).read_bytes() == b"ID3fake-mp3"
    assert seen[0]["voice"] == "eleanor" and seen[0]["input"].startswith("<|emotion:anger|>")
    assert SpendCounter.tts_chars > before


async def test_tts_failure_is_a_status_not_a_crash(tmp_path):
    session = make_session()
    session.voice = higgs(tmp_path, status=500)
    session.voice.on_event(session._on_voice_event)
    await session.start(0)
    await session.slide_changed(s(1), 2)
    await session.presenter_transcript(s(33), seg(33, "We will have 100,000 users by June."))
    await session.tick(s(36))
    assert session.phase == "answering"
    failed = [e for e in session.events
              if e.type == "audio_status" and e.payload["status"] == "tts_failed"]
    assert failed and failed[0].payload["speaker"] == "vc"
