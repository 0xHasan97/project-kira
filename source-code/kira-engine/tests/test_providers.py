from __future__ import annotations

import httpx
import pytest

from kira.config import Config, ProviderConfig
from kira.errors import ConfigError, ProviderCallError
from kira.providers.anthropic import Anthropic
from kira.providers.gemini import Gemini
from kira.providers.openai_compat import OpenAICompat
from kira.providers.registry import ProviderRegistry
from kira.types import Completed, Delta, GenRequest, Message, ToolCall, ToolCallEvent
from kira.vault import Vault
from conftest import Scripted, ok, ok_json, openai_text_chunks, openai_tool_chunks


async def collect(provider, req: GenRequest) -> list:
    return [event async for event in provider.stream(req)]


def make(cls, host: str, script: Scripted):
    return cls(
        name=host,
        base_url=f"https://{host}.invalid/v1" if cls is OpenAICompat else f"https://{host}.invalid",
        client=httpx.AsyncClient(transport=script.transport),
        api_key="k",
    )


REQ = GenRequest(model="m", messages=[Message(role="user", content="hi")])


async def test_openai_streams_text_and_usage():
    script = Scripted()
    script.queue("fast1", ok(openai_text_chunks("hey")))
    events = await collect(make(OpenAICompat, "fast1", script), REQ)
    assert "".join(e.text for e in events if isinstance(e, Delta)) == "hey"
    done = [e for e in events if isinstance(e, Completed)][0]
    assert done.finish_reason == "stop"
    assert (done.usage.input_tokens, done.usage.output_tokens) == (11, 3)
    assert "/v1/chat/completions" in script.calls[0]


async def test_openai_reassembles_streamed_tool_arguments():
    script = Scripted()
    script.queue("fast1", ok(openai_tool_chunks("echo", '{"text":"ping"}')))
    events = await collect(make(OpenAICompat, "fast1", script), REQ)
    call = [e for e in events if isinstance(e, ToolCallEvent)][0].call
    assert (call.name, call.arguments, call.id) == ("echo", {"text": "ping"}, "call_1")
    done = [e for e in events if isinstance(e, Completed)][0]
    assert done.finish_reason == "tool_calls"


async def test_openai_sends_tools_and_wire_messages():
    script = Scripted()
    script.queue("fast1", ok(openai_text_chunks("x")))
    req = GenRequest(
        model="m",
        messages=[
            Message(role="system", content="be terse"),
            Message(role="user", content="time?"),
            Message(role="assistant", content="", tool_calls=[ToolCall(id="c1", name="now", arguments={})]),
            Message(role="tool", content="12:00", tool_call_id="c1", name="now"),
        ],
        tools=[{"type": "function", "function": {"name": "now", "description": "d", "parameters": {"type": "object"}}}],
        max_output_tokens=64,
    )
    await collect(make(OpenAICompat, "fast1", script), req)
    body = script.body_for("fast1")
    assert body["stream"] is True and body["max_tokens"] == 64
    assert body["tool_choice"] == "auto" and len(body["tools"]) == 1
    assert body["messages"][0] == {"role": "system", "content": "be terse"}
    assert body["messages"][3] == {"role": "tool", "tool_call_id": "c1", "content": "12:00"}


@pytest.mark.parametrize(
    "status,expected_retryable",
    [(429, True), (503, True), (401, True), (403, True), (400, False), (404, False)],
)
async def test_openai_status_codes_classify_failover_eligibility(status, expected_retryable):
    """401/403 are the two 4xx that are not our bug: the provider looked at the credentials, not at
    the body. Measured with a deliberately bad key against every provider kind the product ships —
    Groq `401 invalid_api_key`, Anthropic `401 authentication_error`, OpenRouter `401 User not found`
    — so under the old "every 4xx is a mapping bug" rule one expired key ended the chat. A 400 keeps
    its old meaning."""
    script = Scripted()
    script.queue("fast1", httpx.Response(status, json={"error": {"message": "nope"}}))
    with pytest.raises(ProviderCallError) as excinfo:
        await collect(make(OpenAICompat, "fast1", script), REQ)
    assert excinfo.value.retryable is expected_retryable
    assert excinfo.value.status == status


async def test_anthropic_payload_translation_and_stream():
    script = Scripted()
    events = [
        {"type": "message_start", "message": {"usage": {"input_tokens": 7}}},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "hel"}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "lo"}},
        {"type": "content_block_stop", "index": 0},
        {"type": "content_block_start", "index": 1, "content_block": {"type": "tool_use", "id": "tu_1", "name": "echo"}},
        {
            "type": "content_block_delta",
            "index": 1,
            "delta": {"type": "input_json_delta", "partial_json": '{"text":"ok"}'},
        },
        {"type": "content_block_stop", "index": 1},
        {"type": "message_delta", "delta": {"stop_reason": "tool_use"}, "usage": {"output_tokens": 4}},
        {"type": "message_stop"},
    ]
    script.queue("ant", ok([e for e in events]))
    req = GenRequest(
        model="claude-mock",
        messages=[
            Message(role="system", content="rules"),
            Message(role="user", content="q"),
            Message(role="assistant", content="a", tool_calls=[ToolCall(id="tu_0", name="echo", arguments={"text": "1"})]),
            Message(role="tool", content="result", tool_call_id="tu_0", name="echo"),
        ],
        tools=[{"type": "function", "function": {"name": "echo", "description": "d", "parameters": {"type": "object"}}}],
    )
    received = await collect(make(Anthropic, "ant", script), req)
    assert "".join(e.text for e in received if isinstance(e, Delta)) == "hello"
    call = [e for e in received if isinstance(e, ToolCallEvent)][0].call
    assert (call.id, call.name, call.arguments) == ("tu_1", "echo", {"text": "ok"})
    done = [e for e in received if isinstance(e, Completed)][0]
    assert done.finish_reason == "tool_calls" and (done.usage.input_tokens, done.usage.output_tokens) == (7, 4)

    body = script.body_for("ant")
    assert body["system"] == "rules"
    assert body["max_tokens"] == 4096
    assert body["messages"][0]["role"] == "user"
    # assistant tool_use and the tool result must be separate alternating turns
    roles = [m["role"] for m in body["messages"]]
    assert roles == ["user", "assistant", "user"]
    assert body["messages"][2]["content"][0]["type"] == "tool_result"
    assert body["tools"][0]["input_schema"] == {"type": "object"}


async def test_anthropic_error_event_raises():
    script = Scripted()
    script.queue("ant", ok([{"type": "error", "error": {"type": "overloaded_error", "message": "busy"}}]))
    with pytest.raises(ProviderCallError) as excinfo:
        await collect(make(Anthropic, "ant", script), REQ)
    assert excinfo.value.code == "overloaded_error"


async def test_gemini_payload_and_stream():
    script = Scripted()
    chunks = [
        {
            "candidates": [
                {"content": {"parts": [{"text": "yo"}], "role": "model"}, "finishReason": None},
                {"usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 1}},
            ]
        },
        {
            "candidates": [
                {
                    "content": {
                        "parts": [{"functionCall": {"name": "now", "args": {}}}],
                        "role": "model",
                    },
                    "finishReason": "STOP",
                }
            ]
        },
    ]
    script.queue("gem", ok(chunks))
    req = GenRequest(
        model="gemini-mock",
        messages=[
            Message(role="system", content="persona"),
            Message(role="user", content="time"),
            Message(role="assistant", content="", tool_calls=[ToolCall(id="g1", name="now", arguments={})]),
            Message(role="tool", content="12:00", tool_call_id="g1", name="now"),
        ],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "now",
                    "description": "clock",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
    )
    received = await collect(make(Gemini, "gem", script), req)
    assert [e.text for e in received if isinstance(e, Delta)] == ["yo"]
    call = [e for e in received if isinstance(e, ToolCallEvent)][0].call
    assert call.name == "now" and call.id.startswith("gemini_call_")
    assert [e for e in received if isinstance(e, Completed)][0].finish_reason == "tool_calls"

    body = script.body_for("gem")
    assert body["systemInstruction"]["parts"][0]["text"] == "persona"
    assert [c["role"] for c in body["contents"]] == ["user", "model", "user"]
    assert body["contents"][2]["parts"][0]["functionResponse"]["name"] == "now"
    assert body["tools"][0]["functionDeclarations"][0]["name"] == "now"
    assert "streamGenerateContent" in script.calls[0] and "alt=sse" in script.calls[0]


async def test_gemini_captures_the_thought_signature_it_is_asked_to_return():
    """A thinking model signs every functionCall, and the signature is not part of the call.

    Measured live 2026-10-29 against `gemini-3.5-flash`: the part arrives as
    `{"functionCall": {"args", "id", "name"}, "thoughtSignature": "<504 chars of base64>"}`. Google
    rejects a replayed functionCall without it — see the companion test below — so the provider has to
    hold onto it even though nothing in our tool contract, the UI or the model's own arguments uses it.
    """
    script = Scripted()
    script.queue(
        "gem",
        ok([{"candidates": [{"content": {"parts": [{"functionCall": {"name": "now", "args": {}}, "thoughtSignature": "SIG-ABC"}]}, "finishReason": "STOP"}]}]),
    )
    received = await collect(make(Gemini, "gem", script), REQ)
    call = [e for e in received if isinstance(e, ToolCallEvent)][0].call
    assert call.signature == "SIG-ABC"


async def test_gemini_puts_the_thought_signature_back_on_the_function_call():
    """Replay without the signature and the whole agent turn dies — measured, not theorised.

    Same conversation, sent twice: as we used to build it, Google answers
    `400 Function call is missing a thought_signature in functionCall parts. This is required for tools
    to work correctly`; with `thoughtSignature` pasted back onto that part it answers 200 and the model
    says "OK". The signature belongs to the *part*, not to the functionCall object.
    """
    script = Scripted()
    script.queue("gem", ok([{"candidates": [{"content": {"parts": [{"text": "12:00"}]}, "finishReason": "STOP"}]}]))
    req = GenRequest(
        model="gemini-mock",
        messages=[
            Message(role="user", content="time"),
            Message(role="assistant", content="", tool_calls=[ToolCall(id="g1", name="now", arguments={}, signature="SIG-ABC")]),
            Message(role="tool", content="12:00", tool_call_id="g1", name="now"),
        ],
        tools=REQ.tools,
    )
    await collect(make(Gemini, "gem", script), req)
    model_turn = [c for c in script.body_for("gem")["contents"] if c["role"] == "model"][0]
    assert model_turn["parts"][0]["functionCall"]["name"] == "now"
    assert model_turn["parts"][0]["thoughtSignature"] == "SIG-ABC"


async def test_gemini_surfaces_error_chunk():
    script = Scripted()
    script.queue("gem", ok([{"error": {"status": "RESOURCE_EXHAUSTED", "message": "quota"}}]))
    with pytest.raises(ProviderCallError) as excinfo:
        await collect(make(Gemini, "gem", script), REQ)
    assert excinfo.value.code == "RESOURCE_EXHAUSTED"


async def test_list_models_per_provider():
    script = Scripted()
    script.queue("fast1", ok_json({"data": [{"id": "mini"}, {"id": "max"}]}))
    script.queue("ant", ok_json({"data": [{"id": "claude-mock"}]}))
    script.queue("gem", ok_json({"models": [{"name": "models/gemini-mock"}]}))
    assert await make(OpenAICompat, "fast1", script).list_models() == ["mini", "max"]
    assert await make(Anthropic, "ant", script).list_models() == ["claude-mock"]
    assert await make(Gemini, "gem", script).list_models() == ["gemini-mock"]


async def test_a_server_with_no_models_yet_lists_nothing_instead_of_crashing():
    # Ollama answers `{"object": "list", "data": null}` until its first model is pulled, and
    # `.get("data", [])` hands back that None: the probe crashed on a fresh install instead of
    # reporting an empty catalogue.
    script = Scripted()
    script.queue("fast1", ok_json({"object": "list", "data": None}))
    assert await make(OpenAICompat, "fast1", script).list_models() == []


def registry_for(tmp_path, providers: list[ProviderConfig], script: Scripted) -> ProviderRegistry:
    return ProviderRegistry(
        Config(data_dir=tmp_path, providers=providers),
        Vault("memory"),
        httpx.AsyncClient(transport=script.transport),
    )


async def test_a_provider_that_declares_no_key_needs_none(tmp_path):
    """A local OpenAI-compatible server answers on loopback with no credential at all.

    Measured in the sandboxed browser pass against a stanza with an empty `key_ref`: `plan()` let it
    through — its key filter only skips providers that declare a ref — and then `build()` died with
    `skipped_config` telling the user to run `kira-engine keys set ` with an empty ref. The two rules
    have to agree, or the offline provider this contract advertises can never be reached.
    """
    local = ProviderConfig(
        name="local", kind="openai_compat", base_url="https://local.invalid/v1", models=["llama3"], priority=10
    )
    script = Scripted()
    script.queue("local", ok(openai_text_chunks("served")))
    registry = registry_for(tmp_path, [local], script)

    assert registry.key_for("local") is None
    events = await collect(registry.build("local"), REQ)
    assert "".join(event.text for event in events if isinstance(event, Delta)) == "served"


async def test_a_declared_key_ref_is_still_required(tmp_path):
    needs = ProviderConfig(
        name="needs",
        kind="openai_compat",
        base_url="https://needs.invalid/v1",
        models=["m"],
        key_ref="provider/needs",
        priority=10,
    )
    with pytest.raises(ConfigError) as excinfo:
        registry_for(tmp_path, [needs], Scripted()).build("needs")
    assert "provider/needs" in str(excinfo.value)


def test_no_authorization_header_when_no_key_is_needed():
    """A blank bearer is not the same as no bearer: a strict local server can reject the former."""
    provider = OpenAICompat(name="local", base_url="https://local.invalid/v1", client=httpx.AsyncClient(), api_key="")
    assert "Authorization" not in provider._headers()
    assert provider._headers()["Accept"] == "text/event-stream"
