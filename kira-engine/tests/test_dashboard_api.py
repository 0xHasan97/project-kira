from __future__ import annotations

from kira.store import month_bounds


def providers_by_name(body: dict) -> dict:
    return {row["name"]: row for row in body["providers"]}


async def test_providers_reports_base_override_and_effective(harness):
    harness.store.set_setting("fast_one", "priority", 5)
    harness.store.set_setting("fast_one", "tier", "powerful")
    resp = await harness.api.get("/v1/kira/providers", headers=harness.auth)
    assert resp.status_code == 200
    row = providers_by_name(resp.json())["fast_one"]
    assert row["priority"] == {"base": 10, "override": 5, "effective": 5}
    assert row["tier"] == {"base": "fast", "override": "powerful", "effective": "powerful"}
    assert row["enabled"] == {"base": True, "override": None, "effective": True}
    assert row["monthly_cap"] == {"base": None, "override": None, "effective": None}
    assert row["key_ref"] == "provider/fast_one"
    assert row["key_present"] is True
    assert "key-fast_one" not in resp.text, "the ref is published, the value never is"


async def test_providers_names_orphans_rather_than_hiding_them(harness):
    harness.store.set_setting("ghost", "enabled", False)
    # set_setting refuses a non-tunable key on purpose, so a junk row can only arrive the way
    # it would in real life: a hand edit or an older build.
    harness.store._conn.execute(  # noqa: SLF001 - deliberately writing underneath the API
        "INSERT INTO settings(provider, key, value, updated_at) VALUES('fast_one','nonsense','1',0)"
    )
    harness.store._conn.commit()
    resp = await harness.api.get("/v1/kira/providers", headers=harness.auth)
    assert sorted(resp.json()["orphan_settings"]) == ["fast_one.nonsense", "ghost.enabled"]


async def test_providers_carries_month_spend_and_health(harness):
    resp = await harness.api.get("/v1/kira/providers", headers=harness.auth)
    body = resp.json()
    assert body["month"] == month_bounds()[0]
    row = providers_by_name(body)["fast_one"]
    assert row["spend_this_month"] == 0
    assert row["health"] == {"failures": 0, "successes": 0, "cooling_s": 0.0, "last_reason": ""}


async def test_overview_defaults_to_this_month_and_uses_published_names(harness):
    resp = await harness.api.get("/v1/kira/overview", headers=harness.auth)
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {
        "month", "turns", "tokens", "success_rate", "interrupted", "failed",
        "by_provider", "by_model", "daily", "budgets", "recent_issues", "refusals",
    }
    assert body["turns"] == 0 and body["success_rate"] is None
    assert body["tokens"] == {"input": 0, "output": 0}
    assert body["refusals"] == {"count": 0, "by_code": [], "recent": []}


async def test_overview_rejects_a_junk_month_with_the_documented_error(harness):
    resp = await harness.api.get("/v1/kira/overview?month=nope", headers=harness.auth)
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "config_error"


async def test_overview_budgets_include_disabled_providers(harness):
    harness.store.set_setting("fast_one", "monthly_cap", 100)
    harness.store.set_setting("fast_two", "enabled", False)
    resp = await harness.api.get("/v1/kira/overview", headers=harness.auth)
    budgets = {b["provider"]: b for b in resp.json()["budgets"]}
    assert budgets["fast_one"] == {"provider": "fast_one", "cap": 100, "used": 0, "remaining": 100}
    assert budgets["fast_two"]["cap"] is None and budgets["fast_two"]["remaining"] is None
    assert budgets["big"]["cap"] is None, "no cap in yaml means unlimited, not missing"


async def test_sessions_now_carry_counts(harness):
    sid = harness.store.create_session("AUTO", "sess-9")
    harness.store.add_message(sid, "assistant", "a", provider="fast_one", model="mini",
                              usage={"input_tokens": 4, "output_tokens": 3})
    resp = await harness.api.get("/v1/kira/sessions?limit=5", headers=harness.auth)
    row = resp.json()["sessions"][0]
    assert row["id"] == "sess-9"
    assert row["message_count"] == 1
    assert row["tokens"] == 7
    assert row["last_used_at"] is not None


async def test_reads_need_the_token_and_no_confirm(harness):
    for path in ("/v1/kira/overview", "/v1/kira/providers", "/v1/kira/sessions"):
        assert (await harness.api.get(path)).status_code == 401
        ok = await harness.api.get(path, headers=harness.auth)
        assert ok.status_code == 200, path
