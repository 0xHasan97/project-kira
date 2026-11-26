from __future__ import annotations

import httpx

from kira.config import Config
from kira.probe import (
    PROBE_MAX_OUTPUT_TOKENS,
    SAMPLE_LIMIT,
    ProbeResult,
    probe_models,
    probe_provider,
)
from kira.providers.registry import ProviderRegistry
from kira.vault import Vault
from conftest import Scripted, ok, ok_json, openai_text_chunks, provider_configs


def registry_for(tmp_path, scripted: Scripted, *, keyed: bool = True) -> ProviderRegistry:
    config = Config(data_dir=tmp_path, providers=provider_configs())
    vault = Vault("memory")
    if keyed:
        for provider in config.providers:
            vault.set(provider.key_ref, "sekret")
    client = httpx.AsyncClient(transport=scripted.transport, timeout=config.request_timeout_s)
    return ProviderRegistry(config, vault, client)


async def test_probe_models_lists_without_calling_the_chat_endpoint(tmp_path):
    scripted = Scripted()
    scripted.queue("fast1", ok_json({"data": [{"id": "mini"}, {"id": "mini-2"}]}))
    result = await probe_models(registry_for(tmp_path, scripted), "fast_one")
    assert result.ok and result.model_count == 2
    assert result.sample == ["mini", "mini-2"]
    # A list probe that completes would spend the user's money without asking.
    assert result.latency_ms is None
    assert scripted.calls == ["fast1https://fast1.invalid/v1/models"]


async def test_probe_sample_stays_short(tmp_path):
    scripted = Scripted()
    scripted.queue("fast1", ok_json({"data": [{"id": f"m{i}"} for i in range(SAMPLE_LIMIT + 12)]}))
    result = await probe_models(registry_for(tmp_path, scripted), "fast_one")
    assert result.model_count == SAMPLE_LIMIT + 12
    assert len(result.sample) == SAMPLE_LIMIT


async def test_probe_provider_adds_one_capped_completion(tmp_path):
    scripted = Scripted()
    scripted.queue("fast1", ok_json({"data": [{"id": "mini"}]}))
    scripted.queue("fast1", ok(openai_text_chunks("ok")))
    result = await probe_provider(registry_for(tmp_path, scripted), "fast_one")
    assert result.ok and result.model_count == 1
    assert result.latency_ms is not None and result.latency_ms >= 0
    body = scripted.body_for("fast1")
    assert body["max_tokens"] == PROBE_MAX_OUTPUT_TOKENS
    # The probe exercises the model you actually route to, not a catalogue id.
    assert body["model"] == "mini"
    assert len(scripted.calls) == 2


async def test_a_failing_completion_is_reported_not_raised(tmp_path):
    scripted = Scripted()
    scripted.queue("fast1", ok_json({"data": [{"id": "mini"}]}))
    scripted.queue("fast1", httpx.Response(500, json={"error": {"message": "upstream down"}}))
    result = await probe_provider(registry_for(tmp_path, scripted), "fast_one")
    assert not result.ok
    assert "upstream down" in (result.error or "")
    assert result.model_count == 1, "the list half still succeeded; say so"


async def test_a_completion_that_says_nothing_does_not_pass(tmp_path):
    """A reasoning model can spend the entire output budget on hidden thinking and close the
    stream with zero characters. A green Test button for that is a lie about the provider."""
    scripted = Scripted()
    scripted.queue("fast1", ok_json({"data": [{"id": "mini"}]}))
    scripted.queue("fast1", ok(openai_text_chunks("")))
    result = await probe_provider(registry_for(tmp_path, scripted), "fast_one")
    assert not result.ok
    assert "no text" in (result.error or "")
    assert result.model_count == 1, "the catalogue half is still true"


def test_the_probe_budget_clears_a_thinking_models_hidden_output():
    """Measured live on Gemini 3.5 Flash, twice, same prompt. Pass one: 8, 32 and 64 output tokens
    all returned zero characters with `finish_reason=length`, and 128 produced the word. Pass two:
    64 produced a word and 128 came back empty. The hidden-output spend is not a constant, so the
    budget is a hedge rather than a proof — and the constant itself is the contract: dropping it
    back under the measured range turns a green tick into a coin flip."""
    assert PROBE_MAX_OUTPUT_TOKENS >= 256


async def test_a_missing_key_costs_no_http_calls(tmp_path):
    scripted = Scripted()
    result = await probe_provider(registry_for(tmp_path, scripted, keyed=False), "fast_one")
    assert not result.ok and scripted.calls == []
    assert "no key" in (result.error or "") and "provider/fast_one" in (result.error or "")


async def test_an_unknown_provider_is_an_error_not_a_crash(tmp_path):
    scripted = Scripted()
    result = await probe_models(registry_for(tmp_path, scripted), "ghost")
    assert not result.ok and "ghost" in (result.error or "")


def test_the_wire_shape_is_the_documented_one():
    assert set(ProbeResult(provider="p", ok=True).to_wire()) == {
        "provider",
        "ok",
        "model_count",
        "sample",
        "latency_ms",
        "error",
    }
