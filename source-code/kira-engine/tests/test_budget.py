from __future__ import annotations

import time
from datetime import datetime, timezone

import httpx
import pytest

from kira.errors import AllProvidersExhausted, BudgetExhausted
from kira.loop import AgentRun
from kira.router import AttemptState, Note
from kira.store import Store, month_bounds
from kira.tools import ToolDef, ToolOutcome, ToolRegistry
from kira.types import GenRequest, Message
from conftest import ok, openai_text_chunks, openai_tool_chunks

USER = {"role": "user", "content": "hi"}

FAST_TIER = ("fast_one", "fast_two", "gem")


def req(model: str | None = None) -> GenRequest:
    return GenRequest(model=model or "mini", messages=[Message(role="user", content="q")])


async def drain(router, plan, request, state) -> list:
    events = []
    async for event in router.events(plan, request, state):
        events.append(event)
    return events


def spend(store: Store, provider: str, tokens: int, *, at: float | None = None) -> None:
    """One assistant row costing `tokens`. Raw SQL because `add_message` always stamps
    `time.time()`, and 'last month does not count' needs a timestamp in last month. The
    ledger is charged explicitly for the same reason the gate reads it: the cap never
    looks at the message rows, so a fixture that only inserts one buys nothing."""
    when = time.time() if at is None else at
    sid = store.create_session("AUTO")
    store._conn.execute(  # noqa: SLF001 - the gate is proved against timestamps a test controls
        """INSERT INTO messages(session_id, role, content, provider, model, status,
                                tool_calls, usage, chain, created_at)
           VALUES(?,'assistant','a',?,'mini','complete','[]',?,'[]',?)""",
        (sid, provider, f'{{"input_tokens": {tokens}, "output_tokens": 0}}', when),
    )
    store.record_usage(provider, {"input_tokens": tokens, "output_tokens": 0}, when=when)
    store._conn.commit()


def month() -> str:
    # Never a literal: the tests must hold whenever they run, including on the first of a month.
    return month_bounds()[0]


async def test_a_provider_exactly_at_its_cap_is_skipped_with_a_budget_note(harness):
    harness.store.set_setting("fast_one", "monthly_cap", 1000)
    spend(harness.store, "fast_one", 1000)
    plan = harness.engine.router.plan()
    assert "fast_one" not in {c.provider for c in plan.choices}
    assert [(n["provider"], n["reason"]) for n in plan.notes if n["event"] == "skipped_budget"] == [
        ("fast_one", f"used 1,000 of 1,000 tokens in {month()}")
    ]


async def test_an_agent_step_does_not_repeat_the_plan_notes(harness):
    # The loop calls router.events() once per step with the same plan, and events() replayed
    # `plan.notes` at the top of every call: one capped provider became two "over budget" chips on
    # a tool turn, and the stored chain counted the same skip twice.
    harness.store.set_setting("fast_one", "monthly_cap", 100)
    spend(harness.store, "fast_one", 100)
    harness.script.queue("fast2", ok(openai_tool_chunks("echo", "{}")))
    harness.script.queue("fast2", ok(openai_text_chunks("done")))

    tools = ToolRegistry()
    tools.register(ToolDef("echo", "repeat", {}, lambda args: ToolOutcome(ok=True, content="ok", summary="echo")))
    run = AgentRun(
        router=harness.engine.router,
        tools=tools,
        plan=harness.engine.router.plan(),
        messages=[Message(role="user", content="q")],
        policies={"echo": "allow"},
    )
    events = [event async for event in run.events()]

    notes = [event.record for event in events if isinstance(event, Note)]
    assert [note["event"] for note in notes].count("skipped_budget") == 1
    assert [record["event"] for record in run.attempt.chain].count("skipped_budget") == 1
    assert run.state.steps == 2, "the turn really did take two steps"


async def test_one_token_under_the_cap_routes(harness):
    harness.store.set_setting("fast_one", "monthly_cap", 1000)
    spend(harness.store, "fast_one", 999)
    plan = harness.engine.router.plan()
    assert plan.choices[0].provider == "fast_one" and plan.notes == []


async def test_no_cap_means_no_ceiling(harness):
    # Rule 1: the harness config has no `monthly_token_cap` and no override row, so 5M tokens is a
    # number the router reads and ignores. An unlimited provider is `cap is None`, never a big int.
    spend(harness.store, "fast_one", 5_000_000)
    plan = harness.engine.router.plan()
    assert plan.choices[0].provider == "fast_one" and plan.notes == []


async def test_the_budget_note_reaches_the_chain_the_client_draws(harness):
    harness.store.set_setting("fast_one", "monthly_cap", 500)
    spend(harness.store, "fast_one", 500)
    harness.script.queue("fast2", ok(openai_text_chunks("yo")))
    state = AttemptState()
    await drain(harness.engine.router, harness.engine.router.plan(), req(), state)
    assert state.served_by == "fast_two"
    assert [c["event"] for c in state.chain] == ["skipped_budget", "attempt", "served"]
    assert [c["provider"] for c in state.chain] == ["fast_one", "fast_two", "fast_two"]


async def test_a_cooled_and_capped_provider_reports_the_cap(harness):
    # Amendment 7: two facts about one provider, and only one of them is actionable.
    harness.script.queue("fast1", httpx.Response(503, json={"error": {"message": "down"}}))
    harness.script.queue("fast2", ok(openai_text_chunks("back")))
    await drain(harness.engine.router, harness.engine.router.plan(), req(), AttemptState())
    harness.store.set_setting("fast_one", "monthly_cap", 100)
    spend(harness.store, "fast_one", 100)
    events = {n["event"] for n in harness.engine.router.plan().notes if n["provider"] == "fast_one"}
    assert events == {"skipped_budget"}, "the ledger does not get to explain a provider the cap stood down"


async def test_a_disabled_provider_is_gone_before_the_cap_is_asked(harness):
    harness.store.set_setting("fast_one", "enabled", False)
    harness.store.set_setting("fast_one", "monthly_cap", 10)
    spend(harness.store, "fast_one", 10)
    plan = harness.engine.router.plan()
    assert all(n["provider"] != "fast_one" for n in plan.notes), "it was already dropped; the cap is not why"


async def test_every_candidate_over_cap_is_a_budget_refusal(harness):
    for name in FAST_TIER:
        harness.store.set_setting(name, "monthly_cap", 200)
        spend(harness.store, name, 200)
    with pytest.raises(BudgetExhausted) as excinfo:
        harness.engine.router.plan(mode="FAST")
    assert excinfo.value.status == 429 and excinfo.value.retryable is False
    assert {n["provider"] for n in excinfo.value.chain} == set(FAST_TIER)


async def test_a_list_emptied_before_the_gate_is_not_blamed_on_the_cap(harness):
    # Amendment 7's other half. The caps are set so this test also fails if someone moves the budget
    # loop in front of the key filter: there these providers never reach it, so `budget_exhausted`
    # would be a lie about money when the truth is a missing key.
    for name in FAST_TIER:
        harness.vault.delete(f"provider/{name}")
        harness.store.set_setting(name, "monthly_cap", 1)
    with pytest.raises(AllProvidersExhausted) as excinfo:
        harness.engine.router.plan(mode="FAST")
    assert all(n["event"] != "skipped_budget" for n in excinfo.value.chain)


async def test_custom_mode_refuses_an_over_cap_provider_instead_of_answering_from_another(harness):
    harness.store.set_setting("big", "monthly_cap", 50)
    spend(harness.store, "big", 50)
    with pytest.raises(BudgetExhausted, match="big"):
        harness.engine.router.plan(mode="CUSTOM", provider="big")


async def test_the_gate_reads_spend_live_between_two_turns(harness):
    harness.store.set_setting("fast_one", "monthly_cap", 1000)
    spend(harness.store, "fast_one", 900)
    assert harness.engine.router.plan().choices[0].provider == "fast_one"
    spend(harness.store, "fast_one", 100)
    with pytest.raises(BudgetExhausted):
        harness.engine.router.plan(mode="CUSTOM", provider="fast_one")


async def test_last_months_spend_does_not_count_against_this_month(harness):
    _, start, _ = month_bounds()
    harness.store.set_setting("fast_one", "monthly_cap", 100)
    spend(harness.store, "fast_one", 5000, at=start - 3600)
    plan = harness.engine.router.plan()
    assert plan.choices[0].provider == "fast_one" and plan.notes == []


async def test_a_turn_that_never_finished_still_counts_against_the_cap(harness):
    # Derived, not accumulated: the tokens were billed whether or not the answer arrived, so an
    # interrupted turn is spend. A gate that counted only `complete` rows overspends on purpose.
    harness.store.set_setting("fast_one", "monthly_cap", 100)
    sid = harness.store.create_session("AUTO")
    harness.store.add_message(
        sid, "assistant", "partial", provider="fast_one", model="mini",
        status="interrupted", usage={"input_tokens": 60, "output_tokens": 40},
    )
    with pytest.raises(BudgetExhausted):
        harness.engine.router.plan(mode="CUSTOM", provider="fast_one")


async def test_mixed_causes_end_in_exhaustion_with_both_notes_visible(harness, monkeypatch):
    # Two over cap, one cooling: the budget alone did not empty the list, so the honest error is
    # `providers_exhausted` - and its chain has to carry both reasons or the owner is guessing.
    # The cooldown is 5 s in production, and the four commits below can outlast that on a machine
    # busy with an installer: then `cooling` silently expires and the test proves nothing. Its
    # length is not what this test is about, so make it outlive any plausible delay.
    monkeypatch.setattr("kira.net.BASE_COOLDOWN_S", 300.0)
    harness.script.queue("fast2", httpx.Response(503, json={"error": {"message": "down"}}))
    with pytest.raises(AllProvidersExhausted):
        # The attempt loop ends in exhaustion; all this line wants is the cooldown it records.
        await drain(harness.engine.router, harness.engine.router.plan(mode="CUSTOM", provider="fast_two"), req(), AttemptState())
    for name in ("fast_one", "gem"):
        harness.store.set_setting(name, "monthly_cap", 100)
        spend(harness.store, name, 100)
    with pytest.raises(AllProvidersExhausted) as excinfo:
        harness.engine.router.plan(mode="FAST")
    assert {n["event"] for n in excinfo.value.chain} == {"skipped_budget", "skipped_cooling"}
    assert {n["provider"] for n in excinfo.value.chain if n["event"] == "skipped_budget"} == {"fast_one", "gem"}


async def test_the_api_answers_a_budget_refusal_with_429_and_the_chain(harness):
    for name in FAST_TIER:
        harness.store.set_setting(name, "monthly_cap", 10)
        spend(harness.store, name, 10)
    resp = await harness.api.post(
        "/v1/chat/completions", headers=harness.auth, json={"messages": [USER], "mode": "FAST"}
    )
    assert resp.status_code == 429
    body = resp.json()["error"]
    assert body["code"] == "budget_exhausted"
    assert body["status"] == 429 and body["retryable"] is False
    assert {r["provider"] for r in body["provider_chain"]} == set(FAST_TIER)
    assert {r["event"] for r in body["provider_chain"]} == {"skipped_budget"}


async def test_a_streaming_request_refused_on_budget_is_plain_json(harness):
    # `build_run` plans before the SSE opens, so a refusal is an ordinary error body - which is
    # exactly what `KiraClient.stream` turns into a `KiraApiError` (Task 14), not a broken stream.
    for name in FAST_TIER:
        harness.store.set_setting(name, "monthly_cap", 10)
        spend(harness.store, name, 10)
    resp = await harness.api.post(
        "/v1/chat/completions",
        headers=harness.auth,
        json={"messages": [USER], "mode": "FAST", "stream": True},
    )
    assert resp.status_code == 429
    assert "text/event-stream" not in resp.headers.get("content-type", "")
    assert resp.json()["error"]["code"] == "budget_exhausted"


async def test_a_refused_turn_stores_nothing(harness):
    for name in FAST_TIER:
        harness.store.set_setting(name, "monthly_cap", 10)
        spend(harness.store, name, 10)
    # `spend()` files a session per row, so an empty store is not the claim. The claim is that the
    # refused turn adds nothing: `build_run` plans before `create_session`, so no session and no
    # user message survives a budget refusal.
    before = {row["id"] for row in harness.store.session_rows()}
    resp = await harness.api.post(
        "/v1/chat/completions", headers=harness.auth, json={"messages": [USER], "mode": "FAST"}
    )
    assert resp.status_code == 429
    assert {row["id"] for row in harness.store.session_rows()} == before, (
        "the cap stops the turn before the question is filed"
    )


async def test_a_refusal_is_recorded_where_no_turn_could_store_it(harness):
    for name in FAST_TIER:
        harness.store.set_setting(name, "monthly_cap", 10)
        spend(harness.store, name, 10)
    resp = await harness.api.post(
        "/v1/chat/completions", headers=harness.auth, json={"messages": [USER], "mode": "FAST"}
    )
    assert resp.status_code == 429
    body = (await harness.api.get("/v1/kira/overview", headers=harness.auth)).json()
    refusals = body["refusals"]
    assert refusals["count"] == 1
    assert refusals["by_code"] == [{"code": "budget_exhausted", "count": 1}]
    assert refusals["recent"][0]["code"] == "budget_exhausted"
    assert refusals["recent"][0]["mode"] == "FAST"
    assert "over the monthly cap" in refusals["recent"][0]["message"]
    assert body["turns"] == len(FAST_TIER), "the fixture's three rows and nothing from the refusal"


async def test_a_served_turn_does_not_enter_the_refusal_ledger(harness):
    harness.script.queue("fast1", ok(openai_text_chunks("served")))
    resp = await harness.api.post(
        "/v1/chat/completions", headers=harness.auth, json={"messages": [USER], "mode": "FAST"}
    )
    assert resp.status_code == 200
    body = (await harness.api.get("/v1/kira/overview", headers=harness.auth)).json()
    assert body["refusals"] == {"count": 0, "by_code": [], "recent": []}


async def test_clearing_the_history_does_not_erase_the_refusals(harness):
    for name in FAST_TIER:
        harness.store.set_setting(name, "monthly_cap", 10)
        spend(harness.store, name, 10)
    await harness.api.post(
        "/v1/chat/completions", headers=harness.auth, json={"messages": [USER], "mode": "FAST"}
    )
    harness.store.clear_sessions()
    body = (await harness.api.get("/v1/kira/overview", headers=harness.auth)).json()
    assert body["turns"] == 0
    assert body["refusals"]["count"] == 1, "a refusal is not a session, so deleting sessions cannot undo it"


async def test_a_refusal_counts_in_the_month_it_happened(harness):
    _, start, _ = month_bounds()
    harness.store.record_refusal(
        "all_providers_exhausted",
        "mode AUTO: nothing left to ask",
        mode="AUTO",
        model=None,
        at=start - 60,
    )
    this_month = (await harness.api.get("/v1/kira/overview", headers=harness.auth)).json()
    assert this_month["refusals"]["count"] == 0
    previous = datetime.fromtimestamp(start - 60, timezone.utc).strftime("%Y-%m")
    last_month = (await harness.api.get(f"/v1/kira/overview?month={previous}", headers=harness.auth)).json()
    assert last_month["refusals"]["count"] == 1
