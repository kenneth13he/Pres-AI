"""Local voice APIs separate binary playback from the shared JSON session bus."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend import main
from backend.services.voice_higgs import HiggsVoice, SpendCounter
from backend.services.voice_mock import MockVoice
from backend.tests.conftest import make_session


@pytest.fixture
def local_voice(monkeypatch):
    monkeypatch.setenv("BOSON_API_KEY", "permanent-test-key")
    monkeypatch.setenv("SPEND_SOFT_CAP_USD", "60")
    monkeypatch.setattr(SpendCounter, "tts_chars", 0)
    monkeypatch.setattr(SpendCounter, "realtime_ms", 0)
    monkeypatch.setattr(main, "ROOMS", {})
    requests = []

    def respond(request):
        requests.append(request)
        if request.url.path.endswith("client_secrets"):
            return httpx.Response(200, json={
                "value": "temporary-unit-test", "expires_at": 1000,
                "vendor_private": "do-not-forward", "api_key": "permanent-test-key",
            })
        return httpx.Response(200, content=b"\x00\x00\x01\x00",
                              headers={"content-type": "audio/pcm"})

    voice = HiggsVoice(httpx.AsyncClient(base_url="https://voice.invalid/v1",
                                        transport=httpx.MockTransport(respond)))
    session = make_session()
    session.voice = voice
    main.ROOMS[session.session_id] = main.Room(session)
    with TestClient(main.app) as client:
        yield client, voice, session, requests


def test_temporary_auth_is_filtered_uncacheable_and_manual_commit(local_voice):
    client, _, session, requests = local_voice
    response = client.post(f"/api/sessions/{session.session_id}/voice/client_secret")
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["value"] == "temporary-unit-test"
    assert body["config"]["session"]["audio"]["input"]["turn_detection"] is None
    assert "permanent-test-key" not in response.text and "do-not-forward" not in response.text
    assert json.loads(requests[-1].content) == {"expires_after": {"seconds": 300}}


def test_temporary_auth_rejects_other_origins_missing_or_ended_sessions(local_voice):
    client, _, session, requests = local_voice
    path = f"/api/sessions/{session.session_id}/voice/client_secret"
    assert client.post(path, headers={"origin": "https://elsewhere.invalid"}).status_code == 403
    assert client.post("/api/sessions/missing/voice/client_secret").status_code == 404
    session.phase = "report"
    assert client.post(path).status_code == 409
    session.phase = "setup"
    session.voice = MockVoice()
    assert client.post(path).status_code == 409
    assert requests == []


def test_temporary_auth_failure_never_returns_vendor_body(local_voice):
    client, voice, session, _ = local_voice

    def reject(_):
        return httpx.Response(401, text="vendor-debug-private permanent-test-key")

    voice._client = httpx.AsyncClient(base_url="https://voice.invalid/v1",
                                     transport=httpx.MockTransport(reject))
    response = client.post(f"/api/sessions/{session.session_id}/voice/client_secret")
    assert response.status_code == 502
    assert "401" in response.text
    assert "vendor-debug-private" not in response.text
    assert "permanent-test-key" not in response.text


def test_audio_socket_checks_origin_session_and_single_client(local_voice):
    client, voice, session, _ = local_voice
    path = f"/ws/voice/{session.session_id}"
    with pytest.raises(WebSocketDisconnect) as error:
        with client.websocket_connect(path, headers={"origin": "https://elsewhere.invalid"}):
            pass
    assert error.value.code == 4403
    with pytest.raises(WebSocketDisconnect) as error:
        with client.websocket_connect("/ws/voice/missing"):
            pass
    assert error.value.code == 4404
    with client.websocket_connect(path) as socket:
        assert socket.receive_json() == {"type": "ready", "sample_rate": 24000}
        assert voice.attached
        with pytest.raises(WebSocketDisconnect) as error:
            with client.websocket_connect(path):
                pass
        assert error.value.code == 4409
    assert not voice.attached


def test_test_speech_streams_binary_and_waits_for_browser_playback(local_voice):
    client, _, session, _ = local_voice
    path = f"/api/sessions/{session.session_id}/voice/test"
    assert client.post(path, json={}).status_code == 409  # no connected playback client
    with client.websocket_connect(f"/ws/voice/{session.session_id}") as socket:
        socket.receive_json()
        with ThreadPoolExecutor(max_workers=1) as worker:
            request = worker.submit(client.post, path, json={"text": "Welcome."})
            first = socket.receive_json()
            assert first["type"] == "speech_started"
            assert socket.receive_bytes() == b"\x00\x00\x01\x00"
            complete = socket.receive_json()
            assert complete["type"] == "speech_complete"
            assert not request.done()
            socket.send_json({"type": "played", "play_id": complete["play_id"]})
            response = request.result(timeout=2)
            assert response.status_code == 200 and response.json() == {"ok": True}
    session.phase = "presenting"
    assert client.post(path, json={}).status_code == 409


def test_audio_cancel_unblocks_speech_without_the_room_lock(local_voice):
    client, voice, session, _ = local_voice
    with client.websocket_connect(f"/ws/voice/{session.session_id}") as socket:
        socket.receive_json()
        with ThreadPoolExecutor(max_workers=1) as worker:
            request = worker.submit(
                client.post, f"/api/sessions/{session.session_id}/voice/test",
                json={"text": "Welcome."},
            )
            assert socket.receive_json()["type"] == "speech_started"
            socket.receive_bytes()
            assert socket.receive_json()["type"] == "speech_complete"
            socket.send_json({"type": "cancel"})
            assert socket.receive_json()["type"] == "cancel"
            assert request.result(timeout=2).status_code == 200
            assert not voice.speaking


def test_browser_reconnect_gets_full_clock_even_after_pause_shift(local_voice, monkeypatch):
    client, _, session, _ = local_voice
    room = main.ROOMS[session.session_id]
    room.t0 = 10_000
    session.start_ms = 400  # a previous pause shifted the engine's presentation start
    session.phase = "presenting"
    monkeypatch.setattr(main, "wall_ms", lambda: 13_400)
    response = client.get(f"/api/sessions/{session.session_id}")
    assert response.status_code == 200
    assert response.json()["elapsed_ms"] == 3000
    assert response.json()["session_clock_ms"] == 3400
