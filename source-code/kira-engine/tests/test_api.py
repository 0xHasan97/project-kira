from __future__ import annotations

import json

import httpx
import pytest

from kira.config import ProviderConfig
from kira.contracts import API_VERSION, CONTRACT_VERSION
from conftest import Harness, ok, ok_json, openai_text_chunks, openai_tool_chunks

USER = {"role": "user", "content": "hi"}


def parse_sse(text: str) -> list[dict]:
    events = []
    for block in text.strip().split("\n\n"):
        for line in block.split("\n"):
            if line.startswith("data: "):
                events.append(json.loads(line[len("data: ") :]))
    return events


async def test_healthz_needs_no_token(harness):
    resp = await harness.api.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["api_version"] == API_VERSION, "healthz is how a caller finds the namespace it must use"
    assert body["contract_version"] == CONTRACT_VERSION
    assert body["providers_configured"] == 5


async def test_endpoints_reject_missing_and_wrong_tokens(harness):
    unauth = await harness.api.get("/v1/models")
    assert unauth.status_code == 401
    assert unauth.json()["error"]["code"] == "unauthorized"
    wrong = await harness.api.get("/v1/models", headers={"Authorization": "Bearer nope"})
    assert wrong.status_code == 401


async def test_models_lists_configured_models_with_owners(harness):
    resp = await harness.api.get("/v1/models", headers=harness.auth)
    data = resp.json()["data"]
    assert {m["id"] for m in data} == {"mini", "max", "claude-mock", "gemini-mock"}
    assert {m["provider"] for m in data} == {"fast_one", "fast_two", "big", "ant", "gem"}


async def test_the_model_catalogue_says_which_rows_can_answer(harness):
    """A picker needs to know which rows will reply, not only which rows exist.

    Measured on the real machine 2026-10-29: four providers configured, one keyed. The catalogue is
    priority-ordered, so `data[0]` was groq's model; the chat client defaulted its model select there,
    and every fresh browser turn died as `503 providers_exhausted` with one `skipped_missing_key` note
    while the same prompt posted without a model streamed an answer from Gemini.
    """
    harness.vault.delete("provider/fast_one")
    harness.vault.delete("provider/fast_two")
    data = (await harness.api.get("/v1/models", headers=harness.auth)).json()["data"]
    assert {(row["provider"], row["key_present"]) for row in data} == {
        ("fast_one", False),
        ("fast_two", False),
        ("big", True),
        ("ant", True),
        ("gem", True),
    }


async def test_a_keyless_provider_is_reported_as_needing_no_key(tmp_path):
    """`key_present: false` is only a call to action when a key is wanted in the first place.

    Measured in the sandboxed browser pass against a loopback provider: its stanza declares no
    `key_ref`, so the catalogue row and the Providers badge both read "no key" — the wording tells you
    to go store a credential the endpoint never asks for. Unit 5 ships an offline model on exactly that
    shape, so the API has to separate "no key needed" from "key missing".
    """
    providers = [
        ProviderConfig(
            name="big", kind="openai_compat", base_url="https://big.invalid/v1",
            models=["max"], tier="powerful", key_ref="provider/big", priority=120,
        ),
        ProviderConfig(
            name="local", kind="openai_compat", base_url="https://local.invalid/v1",
            models=["llama3"], priority=5,
        ),
    ]
    harness = Harness(tmp_path, providers=providers)

    rows = {row["provider"]: row for row in (await harness.api.get("/v1/models", headers=harness.auth)).json()["data"]}
    assert (rows["local"]["needs_key"], rows["local"]["key_present"]) == (False, False)
    assert (rows["big"]["needs_key"], rows["big"]["key_present"]) == (True, True)

    dashboard = {row["name"]: row for row in (await harness.api.get("/v1/kira/providers", headers=harness.auth)).json()["providers"]}
    assert (dashboard["local"]["needs_key"], dashboard["local"]["key_present"]) == (False, False)
    assert dashboard["local"]["key_ref"] == ""

    health = (await harness.api.get("/v1/kira/health", headers=harness.auth)).json()
    assert {row["name"]: row["needs_key"] for row in health["configured"]} == {"big": True, "local": False}


async def test_a_keyless_loopback_provider_serves_a_whole_turn(tmp_path):
    """Not a reporting nicety: before this, the request died as `skipped_config`.

    The router's key filter deliberately leaves a stanza with no `key_ref` alone, so the turn was
    planned, then the registry refused to build it and told the user to store a key under an empty ref.
    """
    harness = Harness(
        tmp_path,
        providers=[
            ProviderConfig(
                name="local", kind="openai_compat", base_url="https://local.invalid/v1", models=["llama3"], priority=5
            )
        ],
    )
    harness.script.queue("local", ok(openai_text_chunks("served offline")))
    body = (
        await harness.api.post("/v1/chat/completions", headers=harness.auth, json={"messages": [USER], "model": "llama3"})
    ).json()
    assert body["choices"][0]["message"]["content"] == "served offline"
    assert body["provider_chain"][-1]["event"] == "served"


async def test_a_gemini_tool_turn_replays_the_call_with_its_thought_signature(harness):
    """The whole turn, not the mapping: this is where the signature could have been dropped.

    Measured live 2026-10-29 with `gemini-3.5-flash`: the first answer is a signed `functionCall`, and
    the follow-up request that carries it back unsigned is refused with
    `400 Function call is missing a thought_signature in functionCall parts`, so every real Gemini tool
    turn ended as an empty assistant row. The loop, the request builder and the provider all have to
    keep the signature; only an end-to-end turn proves all three.
    """
    harness.script.queue(
        "gem",
        ok([{"candidates": [{"content": {"parts": [{"functionCall": {"name": "now", "args": {}}, "thoughtSignature": "SIG-1"}]}, "finishReason": "STOP"}]}]),
    )
    harness.script.queue(
        "gem",
        ok([{"candidates": [{"content": {"parts": [{"text": "the time is noon"}]}, "finishReason": "STOP"}]}]),
    )
    body = (
        await harness.api.post(
            "/v1/chat/completions",
            headers=harness.auth,
            json={"messages": [{"role": "user", "content": "what time is it?"}], "model": "gemini-mock"},
        )
    ).json()
    assert body["choices"][0]["message"]["content"] == "the time is noon", json.dumps(body)[:400]

    second_request = [payload for name, payload in harness.script.bodies if name == "gem"][1]
    model_turn = [c for c in second_request["contents"] if c["role"] == "model"][0]
    assert model_turn["parts"][0]["functionCall"]["name"] == "now"
    assert model_turn["parts"][0]["thoughtSignature"] == "SIG-1"


async def test_a_turn_that_ends_on_a_provider_error_writes_one_row_and_does_not_claim_success(harness):
    """One turn, one history row — and a row that died says it died.

    Measured live: the Gemini 400 above left session `ba9534f7484d43b6` holding two assistant rows one
    millisecond apart, the first `failed` and the second `complete`, both with no text. The non-streaming
    branch wrote the failure row, swallowed the error because only `KiraError` re-raised, then fell
    through to the success path — which counts "has tool calls" as a served answer. Overview read both
    rows, so the month's turn count and success rate were both wrong, and the caller got HTTP 200 with an
    empty message.
    """
    harness.script.queue("fast1", ok(openai_tool_chunks("now", "{}")))
    harness.script.queue("fast1", httpx.Response(400, json={"error": {"message": "missing thought signature"}}))
    resp = await harness.api.post(
        "/v1/chat/completions", headers=harness.auth, json={"messages": [USER], "model": "mini"}
    )
    assert resp.status_code == 502, resp.text
    assert resp.json()["error"]["provider"] == "fast_one"
    assert resp.json()["error"]["provider_chain"][-1]["event"] == "failed"

    messages = harness.store.messages(harness.store.session_rows()[0]["id"])
    assistant = [m for m in messages if m["role"] == "assistant"]
    assert len(assistant) == 1, json.dumps(assistant)[:400]
    assert assistant[0]["status"] == "failed"


async def test_models_live_probe_reports_the_truth_per_provider(harness):
    for host in ("fast1", "fast2", "big", "ant"):
        harness.script.queue(host, ok_json({"data": [{"id": "x"}]}))
    harness.script.queue("gem", ok_json({"models": [{"name": "models/gemini-mock"}]}))
    resp = await harness.api.get("/v1/models?live=true", headers=harness.auth)
    live = {row["provider"]: row for row in resp.json()["live"]}
    assert all(row["ok"] for row in live.values()), live
    assert live["gem"]["sample"] == ["gemini-mock"]


async def test_non_stream_completion_persists_provider_chain(harness):
    harness.script.queue("fast1", ok(openai_text_chunks("hi")))
    resp = await harness.api.post(
        "/v1/chat/completions", headers=harness.auth, json={"messages": [USER], "model": "mini"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["choices"][0]["message"]["content"] == "hi"
    assert body["provider"] == "fast_one"
    assert body["usage"] == {"prompt_tokens": 11, "completion_tokens": 2, "estimated": False}
    assert resp.headers["x-kira-provider"] == "fast_one"
    assert body["provider_chain"][-1]["event"] == "served"

    messages = await harness.api.get(
        f"/v1/kira/sessions/{body['session_id']}/messages", headers=harness.auth
    )
    rows = messages.json()["messages"]
    assert [r["role"] for r in rows] == ["user", "assistant"]
    assert rows[1]["provider"] == "fast_one" and rows[1]["status"] == "complete"


async def test_stream_completion_emits_typed_sse_events(harness):
    harness.script.queue("fast1", ok(openai_text_chunks("abc")))
    resp = await harness.api.post(
        "/v1/chat/completions", headers=harness.auth, json={"messages": [USER], "model": "mini", "stream": True}
    )
    assert resp.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(resp.text)
    kinds = [e["type"] for e in events]
    assert kinds.count("delta") == 3
    assert "chain" in kinds and kinds[-1] == "done"
    done = events[-1]
    assert done["provider"] == "fast_one" and done["status"] == "complete"
    assert [r["record"]["event"] for r in events if r["type"] == "chain"] == ["attempt", "served"]


async def test_tool_round_trip_executes_locally_then_resumes(harness):
    harness.script.queue("fast1", ok(openai_tool_chunks("echo", '{"text":"pong"}')))
    harness.script.queue("fast1", ok(openai_text_chunks("tool said pong")))
    resp = await harness.api.post(
        "/v1/chat/completions", headers=harness.auth, json={"messages": [USER], "model": "mini"}
    )
    body = resp.json()
    assert body["choices"][0]["message"]["content"] == "tool said pong"
    events = [c["event"] for c in body["provider_chain"]]
    assert events == ["attempt", "served", "tool_executed", "attempt", "served"]
    tool_record = body["provider_chain"][2]
    assert tool_record["tool"] == "echo" and tool_record["ok"] is True

    second_request = [payload for host, payload in harness.script.bodies if host == "fast1"][1]
    roles = [m["role"] for m in second_request["messages"]]
    assert roles == ["user", "assistant", "tool"]
    assert second_request["messages"][2]["content"] == "pong"


async def test_tools_can_be_disabled_per_request(harness):
    harness.script.queue("fast1", ok(openai_text_chunks("plain")))
    resp = await harness.api.post(
        "/v1/chat/completions",
        headers=harness.auth,
        json={"messages": [USER], "model": "mini", "tools_enabled": False},
    )
    assert resp.json()["choices"][0]["message"]["content"] == "plain"
    sent = harness.script.bodies[0][1]
    assert "tools" not in sent


async def test_exhausted_providers_return_503_with_the_chain(harness):
    resp = await harness.api.post(
        "/v1/chat/completions",
        headers=harness.auth,
        json={"messages": [USER], "model": "claude-mock", "mode": "CUSTOM", "provider": "ant"},
    )
    assert resp.status_code == 503
    error = resp.json()["error"]
    assert error["code"] == "providers_exhausted"
    events = [c["event"] for c in error["provider_chain"]]
    assert events == ["attempt", "failed"]


async def test_mid_stream_failure_is_reported_and_partial_is_saved(harness):
    body = (
        b'data: {"choices":[{"index":0,"delta":{"content":"half"}}]}\n\n'
        b"data: broken-json\n\n"
    )
    harness.script.queue("fast1", httpx.Response(200, content=body, headers={"content-type": "text/event-stream"}))
    resp = await harness.api.post(
        "/v1/chat/completions", headers=harness.auth, json={"messages": [USER], "model": "mini", "stream": True}
    )
    events = parse_sse(resp.text)
    deltas = [e for e in events if e["type"] == "delta"]
    assert deltas == [{"type": "delta", "text": "half"}]
    assert events[-1]["type"] == "error"
    assert events[-1]["error"]["code"] == "bad_stream"

    session_id = resp.headers["x-kira-session-id"]
    rows = (await harness.api.get(f"/v1/kira/sessions/{session_id}/messages", headers=harness.auth)).json()["messages"]
    assistant = [r for r in rows if r["role"] == "assistant"][0]
    assert assistant["status"] == "interrupted" and assistant["content"] == "half"


async def test_health_reports_cooldowns(harness):
    harness.script.queue("fast1", httpx.Response(503, json={"error": {"message": "down"}}))
    harness.script.queue("fast2", ok(openai_text_chunks("x")))
    await harness.api.post("/v1/chat/completions", headers=harness.auth, json={"messages": [USER], "model": "mini"})
    snapshot = (await harness.api.get("/v1/kira/health", headers=harness.auth)).json()
    assert snapshot["providers"]["fast_one"]["failures"] == 1
    assert snapshot["providers"]["fast_two"]["successes"] == 1
    assert {p["name"] for p in snapshot["configured"] if not p["key_present"]} == set()


async def test_validation_errors_are_a_contract_400_naming_the_field(harness):
    # Task 12 replaced FastAPI's default 422 with the documented 400 shape: the 422 body echoes the
    # submitted value under `input`, which is unacceptable for a body that can carry a provider key.
    empty = await harness.api.post("/v1/chat/completions", headers=harness.auth, json={"messages": []})
    assert empty.status_code == 400
    assert empty.json()["error"]["code"] == "config_error"
    assert "messages" in empty.json()["error"]["message"]
    badmode = await harness.api.post(
        "/v1/chat/completions", headers=harness.auth, json={"messages": [USER], "mode": "CHEAPEST"}
    )
    assert badmode.status_code == 400
    assert "mode" in badmode.json()["error"]["message"]


async def test_unknown_provider_mode_returns_400(harness):
    resp = await harness.api.post(
        "/v1/chat/completions", headers=harness.auth, json={"messages": [USER], "model": "nope"}
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "config_error"


async def test_contract_version_matches_exported_artifacts(tmp_path, harness):
    from kira.contracts import export_contracts

    path = export_contracts(tmp_path / "kira-contracts")
    assert path.exists()
    assert (tmp_path / "kira-contracts" / "VERSION").read_text(encoding="utf-8").strip() == str(CONTRACT_VERSION)
    spec = json.loads(path.read_text(encoding="utf-8"))
    assert set(spec["paths"]) >= {"/v1/chat/completions", "/v1/models", "/healthz"}


def _schema(name: str) -> dict:
    from kira.contracts import OPENAPI

    return OPENAPI["components"]["schemas"][name]


def _items(schema_name: str, field: str) -> dict:
    """Array item schema, following the one-hop `$ref` v2 uses for named rows."""
    items = _schema(schema_name)["properties"][field]["items"]
    if "$ref" in items:
        return _schema(items["$ref"].rsplit("/", 1)[-1])
    return items


async def test_shipped_bodies_match_the_documented_required_fields(harness):
    """The published OpenAPI is checked against what the app actually returns."""
    from kira.contracts import WIRE_USAGE_FIELDS

    healthz = (await harness.api.get("/healthz")).json()
    assert set(healthz) >= set(_schema("HealthzResponse")["required"])

    models = (await harness.api.get("/v1/models", headers=harness.auth)).json()
    assert set(models["data"][0]) >= set(_schema("ModelInfo")["required"])

    harness.script.queue("fast1", ok(openai_text_chunks("hello")))
    body = (
        await harness.api.post("/v1/chat/completions", headers=harness.auth, json={"messages": [USER], "model": "mini"})
    ).json()
    assert set(body) >= set(_schema("ChatCompletion")["required"])
    assert set(WIRE_USAGE_FIELDS) <= set(body["usage"])
    # `estimated` is the one additive extra: documented in the schema, optional to a reader.
    assert set(body["usage"]) - set(WIRE_USAGE_FIELDS) == {"estimated"}
    for record in body["provider_chain"]:
        assert "event" in record

    # The ledger only reports providers it has actually served or lost.
    snapshot = (await harness.api.get("/v1/kira/health", headers=harness.auth)).json()
    assert set(snapshot["providers"]["fast_one"]) >= set(_schema("ProviderState")["required"])
    assert set(snapshot["configured"][0]) >= set(_schema("ConfiguredProvider")["required"])

    message_schema = _items("MessagesResponse", "messages")
    rows = (
        await harness.api.get(f"/v1/kira/sessions/{body['session_id']}/messages", headers=harness.auth)
    ).json()
    for row in rows["messages"]:
        assert set(row) >= set(message_schema["required"])
        assert row["status"] in message_schema["properties"]["status"]["enum"]


async def test_stream_done_chunk_shares_the_completion_usage_shape(harness):
    from kira.contracts import CHAT_CHUNK_TYPES, WIRE_USAGE_FIELDS

    harness.script.queue("fast1", ok(openai_text_chunks("hey")))
    resp = await harness.api.post(
        "/v1/chat/completions",
        headers=harness.auth,
        json={"messages": [USER], "model": "mini", "stream": True},
    )
    events = parse_sse(resp.text)
    assert {e["type"] for e in events} <= set(CHAT_CHUNK_TYPES)
    done = events[-1]
    assert set(done) <= set(_schema("ChatChunk")["properties"])
    assert set(WIRE_USAGE_FIELDS) <= set(done["usage"])
    assert set(done["usage"]) - set(WIRE_USAGE_FIELDS) == {"estimated"}
    assert done["status"] == "complete"


async def test_error_chunk_fields_are_documented(harness):
    from kira.contracts import CHAT_CHUNK_TYPES

    # Both providers offering "mini" throttle, so the turn dies as providers_exhausted.
    def throttled() -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": "rate limited"}})

    harness.script.queue("fast1", throttled())
    harness.script.queue("fast2", throttled())
    resp = await harness.api.post(
        "/v1/chat/completions",
        headers=harness.auth,
        json={"messages": [USER], "model": "mini", "stream": True},
    )
    events = parse_sse(resp.text)
    assert {e["type"] for e in events} <= set(CHAT_CHUNK_TYPES)
    error = events[-1]
    assert error["type"] == "error"
    assert set(error) <= set(_schema("ChatChunk")["properties"])
    assert error["error"]["code"] == "providers_exhausted"
    assert set(error["error"]) >= {"code", "message", "status", "retryable"}

async def test_models_and_health_reflect_effective_tier_and_priority(harness):
    harness.store.set_setting("big", "enabled", False)
    harness.store.set_setting("fast_one", "tier", "powerful")
    harness.store.set_setting("fast_one", "priority", 7)

    models = (await harness.api.get("/v1/models", headers=harness.auth)).json()["data"]
    assert {m["id"] for m in models} == {"mini", "gemini-mock", "claude-mock"}
    assert not any(m["provider"] == "big" for m in models), "a disabled provider must not be selectable"

    snapshot = (await harness.api.get("/v1/kira/health", headers=harness.auth)).json()["configured"]
    rows = {row["name"]: row for row in snapshot}
    assert rows["fast_one"]["tier"] == "powerful" and rows["fast_one"]["priority"] == 7
    assert "big" in rows, "health lists what exists so you can switch it back on"


async def test_a_disabled_provider_still_answers_custom_with_a_400(harness):
    harness.store.set_setting("ant", "enabled", False)
    resp = await harness.api.post(
        "/v1/chat/completions",
        headers=harness.auth,
        json={"messages": [USER], "mode": "CUSTOM", "provider": "ant"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "config_error"
    assert "disabled" in resp.json()["error"]["message"]
