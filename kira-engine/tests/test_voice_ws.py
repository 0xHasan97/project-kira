"""The `/v1/voice` handshake: the token rides the first frame, and nothing else gets read.

A browser cannot set headers on a WebSocket, so the engine takes the token from the `hello` frame.
These two tests are the whole security story of that shortcut: a wrong token closes the socket with
4401 before a single byte of audio is accepted, and a right one gets the status block — with no key,
no path and no token echoed back.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_bad_hello_closes_4401(harness):
    with TestClient(harness.app) as client:
        with client.websocket_connect("/v1/voice") as ws:
            ws.send_json({"type": "hello", "token": "wrong"})
            message = ws.receive()
            assert message["type"] == "websocket.close"
            assert message.get("code") == 4401


def test_missing_hello_closes_4401(harness):
    with TestClient(harness.app) as client:
        with client.websocket_connect("/v1/voice") as ws:
            # Audio before any hello: there is no authenticated call to attach it to.
            ws.send_json({"type": "audio", "pcm": "AAAA"})
            assert ws.receive().get("code") == 4401


def test_hello_returns_ready(harness):
    from conftest import TEST_TOKEN

    with TestClient(harness.app) as client:
        with client.websocket_connect("/v1/voice") as ws:
            ws.send_json({"type": "hello", "token": TEST_TOKEN})
            ready = ws.receive_json()
            assert ready["type"] == "ready"
            assert ready["session_id"]
            assert set(ready["voice"]) == {"stt", "tts", "vision", "limits"}
            assert ready["limits"] == {"max_utterance_s": 30, "silence_ms": 700}
            assert ready["voice"] == harness.engine.voice.status()
            assert TEST_TOKEN not in str(ready)
            assert "key-" not in str(ready)
            ws.send_json({"type": "close"})
