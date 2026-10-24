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
    return HiggsVoice(client=client, audio_dir=tmp_path, background=False)


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
    clips = [e for e in session.events if e.type == "audio_status"
             and e.payload["status"] == "clip" and "wrapper" in e.payload["text"]]
    assert len(clips) == 1 and clips[0].payload["speaker"] == "vc"
    clip = clips[0]
    assert clip.timestamp_ms == s(70)
    assert clip.payload["url"].startswith(f"/audio/{session.session_id}/")
    assert (tmp_path / clip.payload["url"].removeprefix("/audio/")).read_bytes() == b"ID3fake-mp3"
    heckle = next(r for r in seen if "wrapper" in r["input"])
    assert heckle["voice"] == "eleanor" and heckle["input"].startswith("<|emotion:anger|>")

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
    failed = [e for e in session.events if e.type == "audio_status"
              and e.payload["status"] == "tts_failed" and e.payload["speaker"] == "vc"]
    assert failed


# ---- talking heads (Higgs Avatar) ---------------------------------------------------------

from backend.services.voice_higgs import assign_faces  # noqa: E402


def faces(tmp_path, names):
    d = tmp_path / "faces"
    d.mkdir()
    for n in names:
        (d / n).write_bytes(b"\xff\xd8fakejpeg")
    return d


def test_faces_pinned_then_pooled_and_test_faces_only_as_fallback(tmp_path):
    d = faces(tmp_path, ["vc.jpg", "a.png", "b.jpg", "_test.jpg"])
    got = assign_faces(["vc", "student", "professor"], d)
    assert got["vc"].name == "vc.jpg"
    assert {got["student"].name, got["professor"].name} == {"a.png", "b.jpg"}
    only_test = faces(tmp_path / "x", ["_test.jpg"]) if (tmp_path / "x").mkdir() is None else None
    got = assign_faces(["vc", "student"], only_test)
    assert got["vc"].name == got["student"].name == "_test.jpg"
    assert assign_faces(["vc"], tmp_path / "missing") == {}


def avatar_higgs(tmp_path, video_status="completed", calls=None):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if calls is not None:
            calls.append((request.method, path))
        if path.endswith("/audio/speech"):
            return httpx.Response(200, content=b"ID3fake-mp3", request=request)
        if path.endswith("/videos") and request.method == "POST":
            return httpx.Response(200, json={"id": "video_1", "status": "queued"}, request=request)
        if path.endswith("/videos/video_1"):
            return httpx.Response(200, json={"id": "video_1", "status": video_status},
                                  request=request)
        if path.endswith("/videos/video_1/content"):
            return httpx.Response(200, content=b"fake-mp4", request=request)
        return httpx.Response(404, request=request)
    client = httpx.AsyncClient(base_url="https://api.boson.ai/v1",
                               transport=httpx.MockTransport(handler))
    v = HiggsVoice(client=client, audio_dir=tmp_path / "audio",
                   faces_dir=faces(tmp_path, ["vc.jpg"]), background=False)
    v.avatar_enabled = True
    v.avatar_budget_s = 1.2
    return v


async def test_a_seat_with_a_face_gets_a_lip_synced_video_clip(tmp_path):
    calls: list = []
    session = make_session()
    session.voice = avatar_higgs(tmp_path, calls=calls)
    session.voice.on_event(session._on_voice_event)
    await session.start(0)
    ready = next(e for e in session.events if e.type == "audio_status"
                 and e.payload["status"] == "ready")
    assert ready.payload["faces"] == {"vc": "/demo/faces/vc.jpg"}
    await session.slide_changed(s(1), 2)
    await session.force_curveball("heckler", s(70))
    clip = next(e for e in session.events if e.type == "audio_status"
                and e.payload["status"] == "clip" and e.payload["speaker"] == "vc")
    assert clip.payload["kind"] == "video" and clip.payload["url"].endswith(".mp4")
    assert ("POST", "/v1/videos") in calls


async def test_a_late_render_falls_back_to_the_voice_over_the_portrait(tmp_path):
    session = make_session()
    session.voice = avatar_higgs(tmp_path, video_status="in_progress")
    session.voice.on_event(session._on_voice_event)
    await session.start(0)
    await session.slide_changed(s(1), 2)
    await session.force_curveball("heckler", s(70))
    statuses = [e.payload["status"] for e in session.events if e.type == "audio_status"]
    assert "avatar_late" in statuses
    clip = next(e for e in session.events if e.type == "audio_status"
                and e.payload["status"] == "clip")
    assert clip.payload["kind"] == "audio" and clip.payload["url"].endswith(".mp3")


async def test_background_rendering_never_blocks_the_room_and_keeps_order(tmp_path):
    import asyncio

    order: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        order.append(json.loads(request.content)["input"])
        return httpx.Response(200, content=b"ID3", request=request)

    v = HiggsVoice(client=httpx.AsyncClient(base_url="https://api.boson.ai/v1",
                                           transport=httpx.MockTransport(handler)),
                   audio_dir=tmp_path, faces_dir=tmp_path / "none")
    clips: list[str] = []

    async def on_event(ev):
        if ev.payload["status"] == "clip":
            clips.append(ev.payload["text"])

    v.on_event(on_event)
    await v.start_voice_session("s1", make_config())
    await v.request_persona_turn("vc", "first", None)   # returns before rendering
    await v.play_moderator_line("second")
    assert clips == []
    for _ in range(50):
        if len(clips) == 2:
            break
        await asyncio.sleep(0.01)
    assert clips == ["first", "second"] and order == ["first", "second"]


async def test_the_brain_is_not_asked_every_second_after_a_none():
    from backend.services.audience import MockOrchestrator

    calls = 0

    class Counting(MockOrchestrator):
        async def decide(self, ctx):
            nonlocal calls
            calls += 1
            return await super().decide(ctx)

    session = make_session(difficulty="friendly")
    session.orchestrator = Counting()
    await session.start(0)
    await session.presenter_transcript(s(31), seg(31, "um so yeah, hello there friends"))
    for t in range(32, 40):
        await session.tick(s(t))
    assert calls == 2  # at 32 s and again after the 5 s backoff, not 8 times


def test_video_shape_follows_the_portrait(tmp_path):
    import pymupdf

    from backend.services.voice_higgs import _video_size

    shapes = {(800, 800): "640x640", (600, 800): "480x640", (800, 600): "640x480"}
    for (w, h), want in shapes.items():
        pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, w, h), False)
        pix.save(tmp_path / f"{w}x{h}.png")
        assert _video_size(tmp_path / f"{w}x{h}.png") == want
    assert _video_size(tmp_path / "missing.jpg") == "480x640"


def test_custom_persona_voice_follows_its_face_and_roster_faces_stay_reserved(tmp_path):
    from backend.services.voice_higgs import character_of, delivery_tags
    from spec.contracts import Persona

    d = faces(tmp_path, ["vc--grace.jpg", "student--ethan.jpg", "mentor--emily.jpg",
                         "pool_1--margaret.jpg", "pool_2--lucas.jpg"])
    custom = Persona(id="custom_1", name="Mum", role="baker", focus=["money"], skepticism=0.6,
                     custom=True)
    cfg = make_config(personas=[presets.personas()["vc"].model_dump(),
                                presets.personas()["student"].model_dump(),
                                custom.model_dump()])
    got = assign_faces([p.id for p in cfg.personas], d)
    assert got["custom_1"].name == "pool_1--margaret.jpg"  # not mentor's: that's reserved
    voices = assign_voices(cfg, got)
    # Each character keeps its own voice; Margaret shares Grace's base voice but not her sound.
    assert voices == {"moderator": "nora", "vc": "eleanor", "student": "jake",
                      "custom_1": "eleanor"}
    assert delivery_tags(character_of(got["vc"]), None) == ""
    assert "pitch_low" in delivery_tags(character_of(got["custom_1"]), None)


def test_a_character_sounds_the_same_in_every_preset(tmp_path):
    from backend.services.voice_higgs import CHARACTER_VOICES

    d = faces(tmp_path, ["classmate--daniel.jpg", "student--ethan.jpg",
                         "professor--dr_wilson.jpg"])
    cfg = make_config(preset_id="class_presentation", personas=[
        presets.personas()[pid].model_dump() for pid in ("professor", "student", "classmate")])
    voices = assign_voices(cfg, assign_faces([p.id for p in cfg.personas], d))
    assert voices["classmate"] == CHARACTER_VOICES["daniel"][0]  # never re-voiced for a clash
    assert voices["professor"] == CHARACTER_VOICES["dr_wilson"][0]


def test_mood_sets_the_emotion_and_the_signature_stays():
    from backend.services.voice_higgs import delivery_tags

    assert delivery_tags("margaret", "warm").startswith("<|emotion:contentment|>")
    assert delivery_tags("margaret", "warm").endswith("<|prosody:speed_slow|>")
    assert delivery_tags("grace", "impatient") == "<|emotion:anger|><|prosody:speed_fast|>"
    assert delivery_tags(None, "pressing") == "<|emotion:determination|>"


def test_repo_faces_cover_every_roster_persona():
    from pathlib import Path

    faces_dir = Path(__file__).resolve().parents[2] / "demo" / "faces"
    from backend.services.voice_higgs import CHARACTER_VOICES, character_of

    for pid in presets.personas():
        files = list(faces_dir.glob(f"{pid}--*.jpg"))
        assert len(files) == 1, pid
        assert character_of(files[0]) in CHARACTER_VOICES, files[0].name


async def test_idle_loop_is_rendered_once_per_face_and_announced(tmp_path):
    import asyncio

    posts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/videos") and request.method == "POST":
            posts.append("video")
            return httpx.Response(200, json={"id": "video_1", "status": "queued"}, request=request)
        if path.endswith("/videos/video_1"):
            return httpx.Response(200, json={"id": "video_1", "status": "completed"},
                                  request=request)
        if path.endswith("/content"):
            return httpx.Response(200, content=b"fake-mp4", request=request)
        return httpx.Response(404, request=request)

    def voice():
        v = HiggsVoice(client=httpx.AsyncClient(base_url="https://api.boson.ai/v1",
                                                transport=httpx.MockTransport(handler)),
                       audio_dir=tmp_path / "audio",
                       faces_dir=faces(tmp_path, ["vc--grace.jpg"])
                       if not (tmp_path / "faces").exists() else tmp_path / "faces")
        v.avatar_enabled = True
        return v

    idles: list[str] = []

    async def on_event(ev):
        if ev.payload["status"] == "idle":
            idles.append(ev.payload["url"])

    v = voice()
    v.on_event(on_event)
    await v.start_voice_session("s1", make_config())
    for _ in range(200):  # ffmpeg's first start can take a moment
        if idles:
            break
        await asyncio.sleep(0.05)
    assert idles and idles[0].startswith("/audio/_idle/vc--grace-") and posts == ["video"]
    v2 = voice()  # a new session reuses the cached loop: no second render
    v2.on_event(on_event)
    await v2.start_voice_session("s2", make_config())
    assert len(idles) == 2 and posts == ["video"]


# ---- one fixed voice per character; the face continues from where it is -----------------


async def test_cloned_voice_is_used_with_emotion_only(tmp_path):
    seen: list[dict] = []
    v = higgs(tmp_path, seen=seen)
    await v.start_voice_session("s1", make_config())
    v._voice_ids["vc"] = "voice_abc"
    await v.request_persona_turn("vc", "Isn't this a wrapper?", "impatient")
    assert seen[-1]["voice"] == "voice_abc"
    assert seen[-1]["input"] == "<|emotion:anger|>Isn't this a wrapper?"  # no pace/pitch re-roll


async def test_clone_registers_once_and_is_remembered(tmp_path, monkeypatch):
    import backend.services.voice_higgs as vh

    monkeypatch.setattr(vh, "VOICE_REGISTRY", tmp_path / "voices.json")
    posts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        posts.append(request.url.path)
        if request.url.path.endswith("/audio/voices"):
            return httpx.Response(200, json={"voice_id": "voice_123"}, request=request)
        return httpx.Response(200, content=b"ID3", request=request)

    v = HiggsVoice(client=httpx.AsyncClient(base_url="https://api.boson.ai/v1",
                                           transport=httpx.MockTransport(handler)),
                   audio_dir=tmp_path, faces_dir=faces(tmp_path, ["vc--layla.jpg"]),
                   background=False)
    await v.start_voice_session("s1", make_config())
    await v._clone_voice("vc")
    assert v._voice_ids["vc"] == "voice_123"
    assert json.loads((tmp_path / "voices.json").read_text()) == {"layla|eleanor|": "voice_123"}
    v.custom_voices = True
    v2 = HiggsVoice(client=v._client, audio_dir=tmp_path,
                    faces_dir=tmp_path / "faces", background=False)
    v2.custom_voices = True
    await v2.start_voice_session("s2", make_config())
    assert v2._voice_ids["vc"] == "voice_123"  # from the registry, no second registration
    assert posts.count("/v1/audio/voices") == 1


async def test_next_line_starts_from_the_last_frame_not_the_photo(tmp_path):
    refs: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/audio/speech"):
            return httpx.Response(200, content=b"ID3", request=request)
        if path.endswith("/videos") and request.method == "POST":
            body = request.content
            refs.append("last" if b'filename="clip.last.jpg"' in body else "photo")
            return httpx.Response(200, json={"id": "video_1"}, request=request)
        if path.endswith("/videos/video_1"):
            return httpx.Response(200, json={"status": "completed"}, request=request)
        return httpx.Response(200, content=b"mp4", request=request)

    v = HiggsVoice(client=httpx.AsyncClient(base_url="https://api.boson.ai/v1",
                                           transport=httpx.MockTransport(handler)),
                   audio_dir=tmp_path / "a", faces_dir=faces(tmp_path, ["vc--layla.jpg"]),
                   background=False)
    v.avatar_enabled = True
    await v.start_voice_session("s1", make_config())
    await v.request_persona_turn("vc", "first", None)
    last = tmp_path / "clip.last.jpg"
    last.write_bytes(b"\xff\xd8jpeg")
    v._last_frame["vc"] = last  # what _carry_on records after a real clip
    await v.request_persona_turn("vc", "second", None)
    assert refs == ["photo", "last"]
