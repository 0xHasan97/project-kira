from __future__ import annotations

import json
from pathlib import Path

import httpx
from fastapi.routing import APIRoute

from conftest import ok, openai_text_chunks
from kira.contracts import API_PREFIX, API_VERSION, CONTRACT_VERSION, OPENAPI

USER = {"role": "user", "content": "hi"}

# Every operation the contract publishes that the engine does not register yet. Task 12 and Task 13
# registered all seven, so this is empty: anything appearing here later means a path was documented with
# no code behind it — which used to be invisible, because nothing compared the contract to the route table.
UNIMPLEMENTED: set[tuple[str, str]] = set()

#: Registered under the namespace but deliberately absent from the contract document.
SERVED_BUT_UNDOCUMENTED = {f"{API_PREFIX}/openapi.json"}


def _chat_body(path: str) -> dict:
    return {"messages": [USER], "model": "mini", "stream": True}


async def test_the_namespace_and_the_revision_are_two_different_numbers(harness):
    body = (await harness.api.get("/healthz")).json()
    assert API_PREFIX == f"/v{API_VERSION}"
    assert body["api_version"] == API_VERSION, "healthz is how a caller finds the namespace"
    assert body["contract_version"] == CONTRACT_VERSION
    assert body["api_version"] != body["contract_version"], "the two versions must not be conflated"


async def test_a_version_this_engine_does_not_serve_is_rejected_before_credentials(harness):
    # No Authorization at all: the rejection must not need, or reveal, anything about the token.
    resp = await harness.api.get("/v9/models")
    assert resp.status_code == 404
    error = resp.json()["error"]
    assert error["code"] == "unsupported_version"
    assert API_PREFIX in error["message"] and "/v9" in error["message"]
    assert error["retryable"] is False, "retrying a namespace that does not exist never helps"


async def test_a_wrong_version_post_is_rejected_without_dialling_a_provider(harness):
    resp = await harness.api.post(f"/v{API_VERSION + 8}/chat/completions", json=_chat_body("/v9"))
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "unsupported_version"
    assert harness.script.calls == [], "a rejected request must never reach a provider"


async def test_a_path_that_only_looks_like_a_namespace_is_not_one(harness):
    # The matcher is anchored on a whole segment, so `/v1x` is just an unknown route.
    resp = await harness.api.get("/v1x/models")
    assert resp.status_code == 404
    assert "unsupported_version" not in resp.text


async def test_the_bare_prefix_and_a_trailing_slash_do_what_starlette_actually_does(harness):
    bare = await harness.api.get(API_PREFIX)
    assert bare.status_code == 404, "the namespace alone is not a resource"
    assert bare.headers["x-kira-contract-version"] == str(CONTRACT_VERSION)

    slashed = await harness.api.get(f"{API_PREFIX}/models/")
    assert slashed.status_code == 307
    assert slashed.headers["location"].endswith(f"{API_PREFIX}/models")
    followed = await harness.api.get(f"{API_PREFIX}/models/", headers=harness.auth, follow_redirects=True)
    assert followed.status_code == 200


async def test_every_response_under_the_namespace_carries_the_revision(harness):
    for path in (f"{API_PREFIX}/models", f"{API_PREFIX}/kira/overview", f"{API_PREFIX}/kira/health"):
        resp = await harness.api.get(path, headers=harness.auth)
        assert resp.headers["x-kira-contract-version"] == str(CONTRACT_VERSION), path
    assert (await harness.api.get("/healthz")).headers.get("x-kira-contract-version") is None, (
        "healthz answers outside the namespace, so it cannot pre-judge its own version"
    )


async def test_a_streamed_turn_keeps_every_frame_and_the_header(harness):
    # The version gate is ASGI middleware wrapping `send`, so a StreamingResponse must survive it
    # intact: header on the start message, every `data:` frame still in order.
    harness.script.queue("fast1", ok(openai_text_chunks("hi")))
    resp = await harness.api.post(
        f"{API_PREFIX}/chat/completions", headers=harness.auth, json={**_chat_body(""), "stream": True}
    )
    assert resp.status_code == 200
    assert resp.headers["x-kira-contract-version"] == str(CONTRACT_VERSION)
    assert resp.headers["x-kira-session-id"], "the session header still belongs to the stream"
    events = [
        json.loads(line[len("data: ") :])
        for block in resp.text.strip().split("\n\n")
        for line in block.split("\n")
        if line.startswith("data: ")
    ]
    assert "".join(e.get("text", "") for e in events if e["type"] == "delta") == "hi"
    assert events[-1]["type"] == "done"


async def test_there_is_only_one_openapi_document(harness):
    contract = await harness.api.get(f"{API_PREFIX}/openapi.json")
    alias = await harness.api.get("/openapi.json")
    assert contract.json() == OPENAPI
    assert alias.json() == OPENAPI, "/openapi.json must not be a second opinion on the surface"
    assert alias.json()["info"]["version"] == str(CONTRACT_VERSION)
    # The generated Swagger/Redoc pages went with it: their assets come from a CDN and they described a
    # different API than the one the contract publishes.
    assert (await harness.api.get("/docs")).status_code == 404
    assert (await harness.api.get("/redoc")).status_code == 404


async def test_the_contract_and_the_route_table_agree_in_both_directions(harness):
    registered = {
        (method.lower(), route.path)
        for route in harness.app.routes
        if isinstance(route, APIRoute)
        for method in route.methods
        if method not in {"HEAD", "OPTIONS"}
    }
    documented = {(method, path) for path, spec in OPENAPI["paths"].items() for method in spec}

    assert documented - registered == UNIMPLEMENTED
    under_namespace = {path for _, path in registered if path.startswith(API_PREFIX)}
    assert under_namespace - {path for _, path in documented} == SERVED_BUT_UNDOCUMENTED


def test_the_front_end_never_types_the_namespace_by_hand():
    # A literal `/v1` in the client is a second source of truth: it survives a namespace change as a 404.
    client_dir = Path(__file__).parents[2] / "kira-chat" / "src"
    for name in ("api.ts", "fake-engine.ts"):
        text = (client_dir / name).read_text(encoding="utf-8")
        assert '"/v' not in text, f"{name} hardcodes a version namespace"
        assert "API_PREFIX" in text, f"{name} does not use the published namespace"
