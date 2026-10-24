"""Voice transport tests use fake HTTP and playback sinks; no vendor calls or keys."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

import httpx
import pytest

from backend.services.voice_higgs import HiggsVoice, SpendCounter, VoiceError, realtime_config
from backend.tests.conftest import make_config


@pytest.fixture(autouse=True)
def voice_environment(monkeypatch):
    monkeypatch.setenv("BOSON_API_KEY", "permanent-test-key")
    monkeypatch.setenv("SPEND_SOFT_CAP_USD", "60")
    monkeypatch.setattr(SpendCounter, "tts_chars", 0)
    monkeypatch.setattr(SpendCounter, "realtime_ms", 0)


class Chunks(httpx.AsyncByteStream):
    def __init__(self, hold: asyncio.Event | None = None) -> None:
        self.hold = hold
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield b"\x00\x01\x02"
        if self.hold:
            await self.hold.wait()
        yield b"\x03\x04\x05"

    async def aclose(self) -> None:
        self.closed = True


def fake_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url="https://voice.invalid/v1",
                            transport=httpx.MockTransport(handler))


async def test_binary_stream_waits_for_playback_and_ignores_premature_or_old_ack():
    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, stream=Chunks(), headers={"content-type": "audio/pcm"})

    voice = HiggsVoice(fake_client(respond))
    finished: asyncio.Queue[str] = asyncio.Queue()
    messages = []
    pcm = []

    async def sink(data):
        if isinstance(data, bytes):
            pcm.append(data)
            return
        msg = json.loads(data)
        messages.append(msg)
        if msg["type"] == "speech_started":
            voice.acknowledge(msg["play_id"])  # impossible before playback: must be ignored
        elif msg["type"] == "speech_complete":
            await finished.put(msg["play_id"])

    voice.attach(sink, lambda: 1234)
    await voice.start_voice_session("room", make_config())
    first = asyncio.create_task(voice.request_persona_turn("vc", "Give evidence.", "impatient"))
    first_id = await asyncio.wait_for(finished.get(), 1)
    await asyncio.sleep(0)
    assert not first.done() and voice.speaking
    assert b"".join(pcm) == b"\x00\x01\x02\x03\x04\x05"
    assert requests[0]["voice"] == "marcus"
    assert requests[0]["input"].startswith("<|emotion:anger|>")
    second = asyncio.create_task(voice.play_moderator_line("Thank you."))
    await asyncio.sleep(0)
    assert len(requests) == 1  # the next voice cannot start during playback

    voice.acknowledge("old-or-unknown-id")
    await asyncio.sleep(0)
    assert not first.done()
    voice.acknowledge(first_id)
    await asyncio.wait_for(first, 1)
    second_id = await asyncio.wait_for(finished.get(), 1)
    assert second_id != first_id and len(requests) == 2
    voice.acknowledge(first_id)  # a delayed first-turn acknowledgement cannot end turn two
    await asyncio.sleep(0)
    assert not second.done()
    voice.acknowledge(second_id)
    await asyncio.wait_for(second, 1)
    assert voice.speech_ended_at_ms == 1234 and not voice.speaking
    assert not any(msg["type"].startswith("ai_speech_") for msg in messages)
    await voice.stop_voice_session()


async def test_cancel_stops_an_inflight_http_stream_and_releases_the_turn():
    hold = asyncio.Event()
    stream = Chunks(hold)
    voice = HiggsVoice(fake_client(lambda _: httpx.Response(200, stream=stream)))
    first_chunk = asyncio.Event()
    messages = []

    async def sink(data):
        messages.append(data)
        if isinstance(data, bytes):
            first_chunk.set()

    voice.attach(sink, lambda: 2000)
    task = asyncio.create_task(voice.play_moderator_line("Welcome."))
    await asyncio.wait_for(first_chunk.wait(), 1)
    await voice.cancel_speech()
    await asyncio.wait_for(task, 1)
    assert stream.closed and not voice.speaking
    assert len([msg for msg in messages if isinstance(msg, bytes)]) == 1
    assert any(isinstance(msg, str) and json.loads(msg)["type"] == "cancel"
               for msg in messages)
    await voice.stop_voice_session()


async def test_caller_cancellation_propagates_for_safe_shutdown():
    voice = HiggsVoice(fake_client(lambda _: httpx.Response(200, stream=Chunks(asyncio.Event()))))
    first_chunk = asyncio.Event()

    async def sink(data):
        if isinstance(data, bytes):
            first_chunk.set()

    voice.attach(sink, lambda: 100)
    task = asyncio.create_task(voice.play_moderator_line("Welcome."))
    await asyncio.wait_for(first_chunk.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not voice.speaking
    await voice.stop_voice_session()


async def test_disconnect_releases_wait_for_playback_and_shutdown_is_repeatable():
    voice = HiggsVoice(fake_client(lambda _: httpx.Response(200, stream=Chunks())))
    complete = asyncio.Event()

    async def sink(data):
        if isinstance(data, str) and json.loads(data)["type"] == "speech_complete":
            complete.set()

    voice.attach(sink, lambda: 100)
    task = asyncio.create_task(voice.play_moderator_line("Welcome."))
    await asyncio.wait_for(complete.wait(), 1)
    await voice.detach()
    await asyncio.wait_for(task, 1)
    assert not voice.attached and not voice.speaking
    await voice.stop_voice_session()
    await voice.stop_voice_session()
    with pytest.raises(VoiceError, match="ended"):
        await voice.start_voice_session("room", make_config())


@pytest.mark.parametrize("payload", [[], {}, {"value": ""}, {"value": 42}])
async def test_malformed_temporary_credentials_have_a_safe_error(payload):
    voice = HiggsVoice(fake_client(lambda _: httpx.Response(200, json=payload)))
    try:
        with pytest.raises(VoiceError, match="temporary"):
            await voice.mint_client_secret()
    finally:
        await voice.stop_voice_session()


async def test_vendor_error_body_and_transport_details_are_not_exposed():
    private = "permanent-test-key vendor-debug-private"
    voice = HiggsVoice(fake_client(lambda _: httpx.Response(401, text=private)))
    try:
        with pytest.raises(VoiceError) as error:
            await voice.mint_client_secret()
        assert "401" in str(error.value) and private not in str(error.value)
        with pytest.raises(VoiceError) as error:
            _ = [chunk async for chunk in voice.tts_pcm_stream("Hello.", "default")]
        assert "401" in str(error.value) and private not in str(error.value)
    finally:
        await voice.stop_voice_session()


async def test_no_audio_client_or_spend_limit_never_calls_the_vendor(monkeypatch):
    calls = []
    voice = HiggsVoice(fake_client(lambda request: calls.append(request)))
    with pytest.raises(VoiceError, match="disconnected"):
        await voice.play_moderator_line("Welcome.")
    monkeypatch.setattr(SpendCounter, "tts_chars", 4_000_000)
    with pytest.raises(VoiceError, match="spending"):
        _ = [chunk async for chunk in voice.tts_pcm_stream("Hello.", "default")]
    assert calls == []
    await voice.stop_voice_session()


def test_realtime_listens_silently_with_manual_commit():
    config = realtime_config()["session"]
    assert config["audio"]["input"]["turn_detection"] is None
    assert config["output_modalities"] == ["text"]
    assert config["audio"]["input"]["format"] == {"type": "audio/pcm", "rate": 24000}
