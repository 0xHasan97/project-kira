"""The studio server door: one child process, one forwarded request, no path outside the API."""

from __future__ import annotations

import httpx
import pytest

from kira.studio_server import StudioRefused, StudioServer

HEALTH = {"ok": True, "build": "text-image-v1", "issues": []}


def _health_client(payload: dict | None = HEALTH, *, dead: bool = False) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if dead:
            raise httpx.ConnectError("nothing is listening", request=request)
        if request.url.path == "/api/health":
            return httpx.Response(200, json=payload or HEALTH)
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


class Recorder:
    """What the proxy actually put on the wire, and one canned answer back."""

    def __init__(self, response: httpx.Response | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self.response = response or httpx.Response(200, json={"ok": True})

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.response


def _server(harness, monkeypatch, *, health: bool = True) -> StudioServer:
    monkeypatch.delenv("KIRA_STUDIO_URL", raising=False)
    return StudioServer(harness.engine.config, harness.engine.studio, client=_health_client(dead=not health))


def test_status_reports_a_studio_that_answers(harness, monkeypatch):
    # The status is what the screen shows before anything is started: a child of ours, a studio the
    # user opened themselves, or nothing at all. "Running" is the server answering, not a flag.
    server = _server(harness, monkeypatch)
    body = server.status()
    assert body["running"] is True
    assert body["url"] == "http://127.0.0.1:1420"
    assert body["managed"] is False
    assert body["found"] is False
    assert body["health"] == {"build": "text-image-v1", "issues": []}


def test_status_when_nothing_answers_is_a_state_not_an_error(harness, monkeypatch):
    server = _server(harness, monkeypatch, health=False)
    body = server.status()
    assert body["running"] is False
    assert body["url"] is None
    assert body["error"] is None


def test_start_refuses_without_a_studio_folder(harness, monkeypatch):
    server = _server(harness, monkeypatch, health=False)
    with pytest.raises(Exception) as caught:
        server.start()
    assert "KIRA_STUDIO_DIR" in str(caught.value)
    assert server.status()["managed"] is False


def test_start_refuses_an_external_url_that_is_dark(harness, monkeypatch):
    monkeypatch.setenv("KIRA_STUDIO_URL", "http://127.0.0.1:9")
    server = StudioServer(harness.engine.config, harness.engine.studio, client=_health_client(dead=True))
    with pytest.raises(Exception) as caught:
        server.start()
    assert "KIRA_STUDIO_URL" in str(caught.value)
    assert server.status()["managed"] is False


def test_stop_leaves_a_studio_kira_did_not_start_alone(harness, monkeypatch):
    server = _server(harness, monkeypatch)
    assert server.status()["managed"] is False
    assert server.stop()["running"] is True  # still answering; not killed


@pytest.mark.parametrize("target", ["/chat/", "/api/../../etc/passwd", "/", "/api"])
def test_the_proxy_refuses_paths_outside_the_studio_api(target: str):
    with pytest.raises(StudioRefused):
        StudioServer._split(target)


@pytest.mark.parametrize("target", ["/api/tts/status", "/tts-outputs/a.wav", "/outputs/b.png?x=1"])
def test_the_proxy_accepts_the_published_surface(target: str):
    path, query = StudioServer._split(target)
    assert path == target.split("?")[0]
    assert query == ("x=1" if "?" in target else "")


async def test_the_proxy_forwards_method_body_and_content_type(harness, monkeypatch):
    server = _server(harness, monkeypatch)
    recorder = Recorder()
    server._async = httpx.AsyncClient(transport=httpx.MockTransport(recorder))
    status, content_type, body = await server.proxy(
        "POST",
        "/api/speech/transcribe?model=ggml-base.bin&language=en",
        content_type="audio/wav",
        body=b"RIFFdata",
    )
    assert status == 200
    assert content_type == "application/json"
    wire = recorder.requests[0]
    assert wire.method == "POST"
    assert wire.url.path == "/api/speech/transcribe"
    assert wire.url.params["model"] == "ggml-base.bin"
    assert wire.content == b"RIFFdata"
    assert wire.headers["content-type"] == "audio/wav"


async def test_the_proxy_passes_binary_answers_through(harness, monkeypatch):
    server = _server(harness, monkeypatch)
    server._async = httpx.AsyncClient(
        transport=httpx.MockTransport(Recorder(httpx.Response(200, content=b"RIFF", headers={"content-type": "audio/wav"})))
    )
    status, content_type, body = await server.proxy("GET", "/tts-outputs/heart.wav")
    assert (status, content_type, body) == (200, "audio/wav", b"RIFF")


async def test_the_proxy_refuses_when_the_studio_is_not_running(harness, monkeypatch):
    server = _server(harness, monkeypatch, health=False)
    with pytest.raises(Exception) as caught:
        await server.proxy("GET", "/api/tts/status")
    assert "not running" in str(caught.value)


async def test_the_runtime_route_is_token_only(harness, monkeypatch):
    harness.engine.studio_server = _server(harness, monkeypatch)
    response = await harness.api.get("/v1/kira/studio/app")
    assert response.status_code == 401
    response = await harness.api.get("/v1/kira/studio/app", headers=harness.auth)
    assert response.status_code == 200
    assert response.json()["running"] is True


async def test_starting_the_studio_needs_the_confirm_secret(harness, monkeypatch):
    harness.engine.studio_server = _server(harness, monkeypatch, health=False)
    response = await harness.api.post("/v1/kira/studio/app/start", headers=harness.auth)
    assert response.status_code == 401


async def test_the_proxy_route_carries_json_and_the_token(harness, monkeypatch):
    server = _server(harness, monkeypatch)
    recorder = Recorder(httpx.Response(200, json={"models": [{"filename": "ggml-base.bin"}]}))
    server._async = httpx.AsyncClient(transport=httpx.MockTransport(recorder))
    harness.engine.studio_server = server
    response = await harness.api.get(
        "/v1/kira/studio/proxy", params={"path": "/api/speech/models"}, headers=harness.auth
    )
    assert response.status_code == 200
    assert response.json()["models"][0]["filename"] == "ggml-base.bin"
    assert recorder.requests[0].headers.get("authorization") is None  # the studio gets no Kira token


async def test_a_forwarded_delete_still_needs_the_typed_secret(harness, monkeypatch):
    server = _server(harness, monkeypatch)
    recorder = Recorder()
    server._async = httpx.AsyncClient(transport=httpx.MockTransport(recorder))
    harness.engine.studio_server = server
    refused = await harness.api.post(
        "/v1/kira/studio/proxy", params={"path": "/api/speech/delete-model"}, headers=harness.auth
    )
    assert refused.status_code == 401
    assert recorder.requests == []
    allowed = await harness.api.post(
        "/v1/kira/studio/proxy", params={"path": "/api/speech/delete-model"}, headers=harness.signed, json={"filename": "x.bin"}
    )
    assert allowed.status_code == 200
    assert recorder.requests[0].url.path == "/api/speech/delete-model"


async def test_the_proxy_route_refuses_a_path_outside_the_api(harness, monkeypatch):
    server = _server(harness, monkeypatch)
    server._async = httpx.AsyncClient(transport=httpx.MockTransport(Recorder()))
    harness.engine.studio_server = server
    response = await harness.api.get(
        "/v1/kira/studio/proxy", params={"path": "/chat/index.html"}, headers=harness.auth
    )
    assert response.status_code == 400
