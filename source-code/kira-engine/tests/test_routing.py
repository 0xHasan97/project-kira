from __future__ import annotations

import httpx
import pytest

from kira.errors import AllProvidersExhausted, ConfigError, ProviderCallError
from kira.router import AttemptState, Note
from kira.types import Completed, Delta, GenRequest, Message
from conftest import ok, openai_text_chunks, openai_tool_chunks


def req(model: str | None = None) -> GenRequest:
    return GenRequest(model=model or "mini", messages=[Message(role="user", content="q")])


async def drain(router, plan, request, state):
    events = []
    async for event in router.events(plan, request, state):
        events.append(event)
    return events


def chain_of(state: AttemptState) -> list[dict]:
    return state.chain


async def test_auto_prefers_lowest_priority_number(harness):
    harness.script.queue("fast1", ok(openai_text_chunks("yo")))
    plan = harness.engine.router.plan()
    state = AttemptState()
    await drain(harness.engine.router, plan, req(), state)
    assert state.served_by == "fast_one"
    assert [c["event"] for c in chain_of(state)] == ["attempt", "served"]


async def test_fast_mode_excludes_powerful_tier(harness):
    plan = harness.engine.router.plan(mode="FAST")
    assert {c.provider for c in plan.choices} == {"fast_one", "fast_two", "gem"}


async def test_powerful_mode_excludes_fast_tier(harness):
    plan = harness.engine.router.plan(mode="POWERFUL")
    assert {c.provider for c in plan.choices} == {"big", "ant"}


async def test_custom_requires_provider(harness):
    with pytest.raises(ConfigError, match="requires a 'provider'"):
        harness.engine.router.plan(mode="CUSTOM")
    plan = harness.engine.router.plan(mode="CUSTOM", provider="gem")
    assert [(c.provider, c.model) for c in plan.choices] == [("gem", "gemini-mock")]


async def test_unknown_model_is_rejected_before_any_call(harness):
    with pytest.raises(ConfigError, match="offers model"):
        harness.engine.router.plan(model="gpt-9")
    assert harness.script.calls == []


async def test_retryable_failure_fails_over_and_cools_the_broken_provider(harness):
    harness.script.queue("fast1", httpx.Response(503, json={"error": {"message": "down"}}))
    harness.script.queue("fast2", ok(openai_text_chunks("back")))
    state = AttemptState()
    await drain(harness.engine.router, harness.engine.router.plan(), req(), state)
    assert state.served_by == "fast_two"
    events = [c["event"] for c in chain_of(state)]
    assert events == ["attempt", "failed", "attempt", "served"]
    failed = chain_of(state)[1]
    assert failed["provider"] == "fast_one" and failed["cooldown_s"] == 5.0

    # the cooled provider is skipped, visibly, on the next request
    second = harness.engine.router.plan()
    assert "fast_one" not in {c.provider for c in second.choices}
    cooling = [n for n in second.notes if n["event"] == "skipped_cooling"]
    assert [n["provider"] for n in cooling] == ["fast_one"]
    assert cooling[0]["retry_in_s"] > 0


async def test_non_retryable_failure_does_not_fail_over(harness):
    harness.script.queue("fast1", httpx.Response(400, json={"error": {"message": "bad schema"}}))
    state = AttemptState()
    with pytest.raises(ProviderCallError) as excinfo:
        await drain(harness.engine.router, harness.engine.router.plan(), req(), state)
    assert excinfo.value.retryable is False
    assert "fast2" not in "".join(harness.script.calls)


async def test_every_provider_failing_raises_exhausted(harness):
    for host in ("fast1", "fast2", "big", "ant", "gem"):
        harness.script.queue(host, httpx.Response(503, json={"error": {"message": "down"}}))
    state = AttemptState()
    with pytest.raises(AllProvidersExhausted) as excinfo:
        await drain(harness.engine.router, harness.engine.router.plan(model="mini"), req("mini"), state)
    assert len([c for c in excinfo.value.chain if c["event"] == "failed"]) == 5


async def test_a_pinned_model_nobody_can_answer_names_the_model_and_the_reason(harness):
    """"Every provider was filtered out" is a fact the caller cannot act on.

    Measured live 2026-10-29: the chat client defaulted its picker to an unkeyed provider's model and the
    screen read `providers_exhausted: mode AUTO: every provider was filtered out before the request`, while
    the whole story was one empty vault ref — and the model being held was not even named.

    FAST is the lane that still means "this model only", so it is the lane that still has to explain itself.
    """
    harness.vault.delete("provider/fast_one")
    harness.vault.delete("provider/fast_two")
    with pytest.raises(AllProvidersExhausted) as excinfo:
        harness.engine.router.plan(model="mini", mode="FAST")
    message = str(excinfo.value)
    assert "'mini'" in message, message
    assert "provider/fast_one" in message, message


async def test_auto_holds_a_pinned_provider_first(harness):
    plan = harness.engine.router.plan(model="max")
    assert [(c.provider, c.model) for c in plan.choices] == [
        ("big", "max"),
        ("fast_one", "mini"),
        ("fast_two", "mini"),
        ("ant", "claude-mock"),
        ("gem", "gemini-mock"),
    ]


async def test_auto_falls_over_to_another_provider_rather_than_failing(harness):
    """A model named in AUTO is a preference, not a wall.

    The picker could only ever name a model, so pinning one made cross-provider failover unreachable: when
    the provider carrying that id was down or out of budget the whole turn died, though three others were
    idle. AUTO is the "you decide" lane, so the others stay in line behind it.
    """
    for host in ("fast1", "fast2"):
        harness.script.queue(host, httpx.Response(503, json={"error": {"message": "down"}}))
    harness.script.queue("big", ok(openai_text_chunks("back")))
    state = AttemptState()
    await drain(harness.engine.router, harness.engine.router.plan(model="mini"), req("mini"), state)
    assert state.served_by == "big"
    assert state.served_model == "max"
    assert [c["event"] for c in chain_of(state)] == [
        "attempt",
        "failed",
        "attempt",
        "failed",
        "attempt",
        "served",
    ]
    assert [c.get("model") for c in chain_of(state) if c["event"] == "attempt"] == ["mini", "mini", "max"]


async def test_auto_still_refuses_a_model_no_provider_carries(harness):
    """A typo must not quietly become a different model; a preference is not a wildcard."""
    with pytest.raises(ConfigError, match="offers model"):
        harness.engine.router.plan(model="mini-too", mode="AUTO")
    assert harness.script.calls == []


async def test_a_lane_that_means_this_model_only_still_says_no(harness):
    with pytest.raises(ConfigError, match="offers model"):
        harness.engine.router.plan(model="max", mode="FAST")
    with pytest.raises(ConfigError, match="offers model"):
        harness.engine.router.plan(model="mini", mode="CUSTOM", provider="gem")


async def test_the_answer_that_fell_back_says_which_model_it_used(harness):
    harness.script.queue("fast1", httpx.Response(503, json={"error": {"message": "down"}}))
    harness.script.queue("fast2", httpx.Response(503, json={"error": {"message": "down"}}))
    harness.script.queue("big", ok(openai_text_chunks("hi")))
    state = AttemptState()
    await drain(harness.engine.router, harness.engine.router.plan(model="mini"), req("mini"), state)
    served = [c for c in chain_of(state) if c["event"] == "served"][-1]
    assert served["provider"] == "big" and served["model"] == "max"


async def test_missing_key_skips_provider_without_hiding_it(harness):
    harness.vault.delete("provider/fast_one")
    harness.script.queue("fast2", ok(openai_text_chunks("x")))
    plan = harness.engine.router.plan()
    assert [n["event"] for n in plan.notes] == ["skipped_missing_key"]
    state = AttemptState()
    await drain(harness.engine.router, plan, req(), state)
    assert state.served_by == "fast_two"


async def test_mid_stream_failure_does_not_fail_over_after_text(harness):
    # The client already saw "hi"; restarting on another provider would show it two answers.
    body = (
        b'data: {"choices":[{"index":0,"delta":{"content":"hi"}}]}\n\n'
        b"data: this-is-not-json\n\n"
    )
    harness.script.queue(
        "fast1", httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})
    )
    plan = harness.engine.router.plan(model="mini")
    state = AttemptState()
    seen = []
    with pytest.raises(ProviderCallError):
        async for event in harness.engine.router.events(plan, req("mini"), state):
            seen.append(event)
    assert [e.text for e in seen if isinstance(e, Delta)] == ["hi"]
    assert state.chain[-1]["event"] == "aborted_mid_stream"
    assert "fast2.invalid" not in "".join(harness.script.calls)
    assert state.failed is True

async def test_a_disabled_provider_is_absent_from_every_mode(harness):
    harness.store.set_setting("fast_one", "enabled", False)
    harness.script.queue("fast2", ok(openai_text_chunks("x")))
    assert "fast_one" not in {c.provider for c in harness.engine.router.plan().choices}
    assert "fast_one" not in {c.provider for c in harness.engine.router.plan(mode="FAST").choices}
    assert "fast_one" not in {c.provider for c in harness.engine.router.plan(model="mini").choices}


async def test_disabling_the_only_tier_member_reports_the_tier_honestly(harness):
    harness.store.set_setting("big", "enabled", False)
    harness.store.set_setting("ant", "enabled", False)
    with pytest.raises(ConfigError, match="no provider configured with tier 'powerful'"):
        harness.engine.router.plan(mode="POWERFUL")


async def test_custom_refuses_a_disabled_provider_by_name(harness):
    harness.store.set_setting("gem", "enabled", False)
    with pytest.raises(ConfigError, match="gem.* disabled"):
        harness.engine.router.plan(mode="CUSTOM", provider="gem")
    # An unknown provider keeps its own, different message: the advice differs.
    with pytest.raises(ConfigError, match="unknown provider 'nope'"):
        harness.engine.router.plan(mode="CUSTOM", provider="nope")


async def test_a_disabled_provider_can_be_switched_back_on(harness):
    harness.store.set_setting("fast_one", "enabled", False)
    assert "fast_one" not in {c.provider for c in harness.engine.router.plan().choices}
    harness.store.clear_setting("fast_one", "enabled")
    assert "fast_one" in {c.provider for c in harness.engine.router.plan().choices}


async def test_an_override_changes_priority_ordering_live(harness):
    harness.script.queue("fast2", ok(openai_text_chunks("yo")))
    harness.store.set_setting("fast_two", "priority", 1)
    state = AttemptState()
    await drain(harness.engine.router, harness.engine.router.plan(), req(), state)
    assert state.served_by == "fast_two"
    assert "fast2.invalid" in harness.script.calls[0]


async def test_a_dead_key_fails_over_instead_of_stranding_the_turn(harness):
    """401/403 are the provider saying *your credentials are wrong*, not us sending a bad body —
    measured against Groq, Anthropic and OpenRouter with a deliberately bad key each. Under the old
    rule, "every 4xx is our mapping bug, do not fail over", one dead key was an error screen even
    though a configured, working provider was waiting behind it. A 400 keeps its old meaning."""
    harness.script.queue("fast1", httpx.Response(401, json={"error": {"message": "invalid key"}}))
    harness.script.queue("fast2", ok(openai_text_chunks("back")))
    state = AttemptState()
    await drain(harness.engine.router, harness.engine.router.plan(), req(), state)
    assert state.served_by == "fast_two"
    assert [c["event"] for c in chain_of(state)] == ["attempt", "failed", "attempt", "served"]

    harness.script.queue("fast1", httpx.Response(403, json={"error": {"message": "forbidden"}}))
    harness.script.queue("fast2", ok(openai_text_chunks("again")))
    second = AttemptState()
    await drain(harness.engine.router, harness.engine.router.plan(), req(), second)
    assert second.served_by == "fast_two"


async def test_an_answer_of_nothing_fails_over_instead_of_being_served(harness):
    """A reasoning model whose whole budget goes to hidden thinking completes with
    `finish_reason=length` and zero characters. The live Gemini probe did exactly that at
    16 output tokens, and the router called it `served`: the user got an empty bubble and the
    chain said someone had answered. Nothing arrived, so the next provider gets the turn."""
    harness.script.queue("fast1", ok(openai_text_chunks("")))
    harness.script.queue("fast2", ok(openai_text_chunks("here")))
    state = AttemptState()
    events = await drain(harness.engine.router, harness.engine.router.plan(), req(), state)
    assert state.served_by == "fast_two"
    assert [c["event"] for c in chain_of(state)] == ["attempt", "empty_answer", "attempt", "served"]
    empty = chain_of(state)[1]
    assert empty["provider"] == "fast_one" and empty["reason"] == "completed with no text"
    assert "".join(event.text for event in events if isinstance(event, Delta)) == "here"


async def test_a_tool_call_turn_is_not_an_empty_answer(harness):
    """The agent loop's normal shape: a step that says nothing and calls a tool. If the router
    mistook that for an empty answer it would fail over mid-turn and run the tools twice."""
    harness.script.queue("fast1", ok(openai_tool_chunks("list_files", "{}")))
    state = AttemptState()
    events = await drain(harness.engine.router, harness.engine.router.plan(), req(), state)
    assert state.served_by == "fast_one"
    assert [c["event"] for c in chain_of(state)] == ["attempt", "served"]
    assert any(event.__class__.__name__ == "ToolCallEvent" for event in events)


async def test_every_provider_answering_nothing_is_exhaustion(harness):
    """Three empty completions is not three successes. The client must see the error, not an
    empty assistant row it will read as the model choosing silence."""
    for host in ("fast1", "fast2", "gem"):
        harness.script.queue(host, ok(openai_text_chunks("")))
    state = AttemptState()
    with pytest.raises(AllProvidersExhausted, match="answered with nothing"):
        await drain(harness.engine.router, harness.engine.router.plan(mode="FAST"), req(), state)
    assert [c["event"] for c in chain_of(state)] == ["attempt", "empty_answer"] * 3
