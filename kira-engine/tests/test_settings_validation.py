from __future__ import annotations

import logging

import httpx
from conftest import ok, ok_json, openai_text_chunks
from kira.contracts import API_PREFIX
from kira.errors import ProviderCallError
from kira.overrides import MAX_PRIORITY
from kira.probe import PROBE_MAX_OUTPUT_TOKENS

PROVIDER_CONTROLS = [
    ("put", f"{API_PREFIX}/kira/providers/fast_one/settings", {"priority": 5}),
    ("delete", f"{API_PREFIX}/kira/providers/fast_one/cooldown", None),
    ("post", f"{API_PREFIX}/kira/providers/fast_one/probe", None),
]


async def test_a_provider_control_needs_the_engine_token_not_a_device_token(harness):
    # A paired phone is read-only in practice: re-tuning or probing a provider is a desktop job.
    import hashlib

    harness.store.add_device("phone", hashlib.sha256(b"kd_phone").hexdigest())
    device = {"Authorization": "Bearer kd_phone"}
    for verb, path, body in PROVIDER_CONTROLS:
        resp = await harness.api.request(verb, path, json=body, headers=device)
        assert resp.status_code == 401, f"{verb.upper()} {path} accepted a device token"
        assert "engine token" in resp.json()["error"]["message"]


async def test_a_provider_control_needs_no_confirm_header(harness):
    # The token is the whole gate: no dialog, no second secret to re-type for a toggle or a cap.
    resp = await harness.api.put(
        f"{API_PREFIX}/kira/providers/fast_one/settings", json={"priority": 7}, headers=harness.auth
    )
    assert resp.status_code == 200
    assert harness.store.settings_map() == {"fast_one": {"priority": "7"}}
    assert (await harness.api.delete(f"{API_PREFIX}/kira/providers/fast_one/cooldown", headers=harness.auth)).status_code == 200


async def test_the_bearer_token_is_refused_as_the_confirm_secret(harness):
    # Paste the token into both boxes and every destructive write becomes an open door; say no instead.
    headers = {"Authorization": "Bearer test-engine-token", "X-Kira-Confirm": "test-engine-token"}
    resp = await harness.api.delete(f"{API_PREFIX}/kira/sessions/anything", headers=headers)
    assert resp.status_code == 401
    assert "different value" in resp.json()["error"]["message"]


async def test_a_read_needs_no_confirm(harness):
    for path in (f"{API_PREFIX}/kira/overview", f"{API_PREFIX}/kira/providers", f"{API_PREFIX}/kira/sessions"):
        assert (await harness.api.get(path, headers=harness.auth)).status_code == 200


async def test_a_malformed_body_is_400_and_does_not_echo_the_value(harness):
    resp = await harness.api.post(
        f"{API_PREFIX}/chat/completions",
        json={"messages": [{"role": "user", "content": "hi"}], "max_tokens": "not_a_number_9f3a"},
        headers=harness.auth,
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "config_error"
    assert "not_a_number_9f3a" not in resp.text


async def test_a_valid_settings_write_returns_the_merged_field_states(harness):
    resp = await harness.api.put(
        f"{API_PREFIX}/kira/providers/fast_one/settings",
        json={"priority": 7, "tier": "powerful", "enabled": False},
        headers=harness.signed,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["provider"] == "fast_one"
    assert body["settings"]["priority"] == {"base": 10, "override": 7, "effective": 7}
    assert body["settings"]["tier"] == {"base": "fast", "override": "powerful", "effective": "powerful"}
    assert body["settings"]["enabled"] == {"base": True, "override": False, "effective": False}
    # The router must agree with what the response just promised - one view, no cache to stale out.
    assert harness.engine.view().by_name["fast_one"].priority == 7
    assert harness.engine.view().by_name["fast_one"].enabled is False


async def test_null_clears_only_the_field_it_names(harness):
    harness.store.set_setting("fast_one", "priority", 3)
    harness.store.set_setting("fast_one", "tier", "powerful")
    resp = await harness.api.put(
        f"{API_PREFIX}/kira/providers/fast_one/settings", json={"priority": None}, headers=harness.signed
    )
    assert resp.json()["settings"]["priority"]["override"] is None
    assert resp.json()["settings"]["priority"]["effective"] == 10, "back to the config.yaml baseline"
    assert resp.json()["settings"]["tier"]["override"] == "powerful", "one null must not wipe the row's neighbours"


async def test_a_write_equal_to_the_yaml_baseline_leaves_no_override(harness):
    # The dashboard's controls are round trips — turn a provider off, turn it back on — and every
    # PUT used to store whatever it was sent. The row then read "on — was on" and offered a
    # `clear override` for a setting config.yaml already owned.
    for body in ({"priority": 10}, {"tier": "fast"}, {"enabled": True}, {"monthly_cap": 0}):
        resp = await harness.api.put(
            f"{API_PREFIX}/kira/providers/fast_one/settings", json=body, headers=harness.signed
        )
        assert resp.status_code == 200, body
    assert harness.store.settings_map() == {}, "a value the baseline already states is not an override"
    row = next(
        p
        for p in (await harness.api.get(f"{API_PREFIX}/kira/providers", headers=harness.auth)).json()["providers"]
        if p["name"] == "fast_one"
    )
    assert row["priority"] == {"base": 10, "override": None, "effective": 10}
    assert row["tier"] == {"base": "fast", "override": None, "effective": "fast"}
    assert row["enabled"] == {"base": True, "override": None, "effective": True}
    # `0` is the dashboard's spelling of unlimited and the baseline has no cap at all: same fact,
    # so it must not leave a row behind that makes the next reader subtract one from the other.
    assert row["monthly_cap"] == {"base": None, "override": None, "effective": None}


async def test_off_then_on_again_leaves_the_row_as_it_found_it(harness):
    path = f"{API_PREFIX}/kira/providers/fast_one/settings"
    await harness.api.put(path, json={"enabled": False}, headers=harness.signed)
    assert harness.store.settings_map() == {"fast_one": {"enabled": "false"}}

    resp = await harness.api.put(path, json={"enabled": True}, headers=harness.signed)
    assert resp.json()["settings"]["enabled"] == {"base": True, "override": None, "effective": True}
    assert harness.store.settings_map() == {}, "the switch went back where it started, so must the table"


async def test_an_old_override_is_dropped_when_a_write_lands_on_the_baseline(harness):
    # A row written by an older build, or tuned and then returned by hand, must not outlive the
    # value it no longer changes.
    harness.store.set_setting("fast_one", "priority", 3)
    resp = await harness.api.put(
        f"{API_PREFIX}/kira/providers/fast_one/settings", json={"priority": 10}, headers=harness.signed
    )
    assert resp.json()["settings"]["priority"]["override"] is None
    assert harness.store.settings_map() == {}


async def test_an_empty_body_is_a_200_no_op(harness):
    before = harness.store.settings_map()
    resp = await harness.api.put(f"{API_PREFIX}/kira/providers/fast_one/settings", json={}, headers=harness.signed)
    assert resp.status_code == 200
    assert resp.json()["provider"] == "fast_one"
    assert harness.store.settings_map() == before


async def test_an_out_of_range_value_is_refused_before_anything_is_stored(harness):
    resp = await harness.api.put(
        f"{API_PREFIX}/kira/providers/fast_one/settings",
        json={"enabled": False, "priority": MAX_PRIORITY + 1},
        headers=harness.signed,
    )
    assert resp.status_code == 400
    assert "priority" in resp.json()["error"]["message"]
    assert harness.store.settings_map() == {}, "validate the whole body, then write - never half a write"


async def test_an_unknown_field_is_refused_by_name_and_stores_nothing(harness):
    resp = await harness.api.put(
        f"{API_PREFIX}/kira/providers/fast_one/settings", json={"colour": "red"}, headers=harness.signed
    )
    assert resp.status_code == 400
    assert "colour" in resp.json()["error"]["message"]
    assert harness.store.settings_map() == {}


async def test_an_unknown_provider_is_refused(harness):
    resp = await harness.api.put(f"{API_PREFIX}/kira/providers/nosuch/settings", json={}, headers=harness.signed)
    assert resp.status_code == 400
    resp = await harness.api.put(f"{API_PREFIX}/kira/providers/nosuch/key", json={}, headers=harness.auth)
    assert resp.status_code == 400
    assert (await harness.api.delete(f"{API_PREFIX}/kira/providers/nosuch/cooldown", headers=harness.signed)).status_code == 400


async def test_a_key_write_needs_the_engine_token_not_a_device_token(harness):
    # Keys are the one write a human does while looking at the desktop, so it asks for no typed
    # secret - but a paired phone still must not be able to swap the desktop's credentials.
    import hashlib

    harness.store.add_device("phone", hashlib.sha256(b"kd_phone").hexdigest())
    device = {"Authorization": "Bearer kd_phone"}
    resp = await harness.api.put(f"{API_PREFIX}/kira/providers/fast_one/key", json={"key": "gsk_from_phone"}, headers=device)
    assert resp.status_code == 401
    assert "engine token" in resp.json()["error"]["message"]
    assert harness.vault.get("provider/fast_one") == "key-fast_one", "the phone's key never reached the Locker"
    assert (
        await harness.api.delete(f"{API_PREFIX}/kira/providers/fast_one/key", headers=device)
    ).status_code == 401


async def test_put_key_stores_in_the_vault_and_reports_only_presence(harness):
    resp = await harness.api.put(
        f"{API_PREFIX}/kira/providers/fast_one/key", json={"key": "gsk_super_secret_value"}, headers=harness.auth
    )
    assert resp.status_code == 200
    assert resp.json() == {"provider": "fast_one", "key_ref": "provider/fast_one", "key_present": True}
    assert harness.vault.get("provider/fast_one") == "gsk_super_secret_value", "the Locker got the new value"
    assert "super_secret" not in resp.text, "the response is presence, never the secret"


async def test_delete_key_forgets_it_and_reports_absence(harness):
    # Harness seeds provider/fast_one with "key-fast_one"; deleting must clear that row, not invent one.
    resp = await harness.api.delete(f"{API_PREFIX}/kira/providers/fast_one/key", headers=harness.auth)
    assert resp.json() == {"provider": "fast_one", "key_ref": "provider/fast_one", "key_present": False}
    assert harness.vault.has("provider/fast_one") is False


async def test_an_empty_key_is_refused_without_touching_the_vault(harness):
    before = harness.vault.get("provider/fast_one")
    resp = await harness.api.put(f"{API_PREFIX}/kira/providers/fast_one/key", json={"key": "   "}, headers=harness.auth)
    assert resp.status_code == 400
    assert "key" in resp.json()["error"]["message"]
    assert harness.vault.get("provider/fast_one") == before


async def test_no_response_or_log_record_carries_the_submitted_key(harness, caplog):
    caplog.set_level(logging.DEBUG)
    resp = await harness.api.put(
        f"{API_PREFIX}/kira/providers/fast_one/key", json={"key": "gsk_do_not_leak"}, headers=harness.auth
    )
    providers = await harness.api.get(f"{API_PREFIX}/kira/providers", headers=harness.auth)
    health = await harness.api.get(f"{API_PREFIX}/kira/health", headers=harness.auth)
    assert harness.vault.get("provider/fast_one") == "gsk_do_not_leak", "the write did happen"
    assert "gsk_do_not_leak" not in caplog.text
    for other in (resp, providers, health):
        assert "gsk_do_not_leak" not in other.text


async def test_delete_cooldown_clears_the_timer_and_returns_the_whole_providers_view(harness):
    harness.engine.ledger.record_failure(ProviderCallError("fast_one", "boom", status=503, retryable=True))
    assert harness.engine.ledger.state("fast_one").cooled_until > harness.engine.ledger.clock()
    resp = await harness.api.delete(f"{API_PREFIX}/kira/providers/fast_one/cooldown", headers=harness.signed)
    assert resp.status_code == 200
    assert {"providers", "orphan_settings", "month"} <= set(resp.json()), "amendment 11: one ProvidersResponse"
    row = next(p for p in resp.json()["providers"] if p["name"] == "fast_one")
    assert row["health"]["cooling_s"] == 0
    assert row["health"]["failures"] == 1, "the failure history stays visible"


async def test_a_probe_answers_ok_inline_and_stores_no_conversation(harness):
    harness.script.queue("fast1", ok_json({"data": [{"id": "mini"}]}))
    harness.script.queue("fast1", ok(openai_text_chunks("ok")))
    before = harness.store.session_rows(10)
    resp = await harness.api.post(f"{API_PREFIX}/kira/providers/fast_one/probe", headers=harness.signed)
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"provider", "ok", "model_count", "sample", "latency_ms", "error"}
    assert body["provider"] == "fast_one" and body["ok"] is True and body["model_count"] == 1
    assert body["latency_ms"] is not None
    assert harness.store.session_rows(10) == before, "probe traffic is not a chat"
    assert harness.script.body_for("fast1")["max_tokens"] == PROBE_MAX_OUTPUT_TOKENS


async def test_a_probe_of_a_dead_provider_is_a_200_that_says_no(harness):
    harness.script.queue("fast1", ok_json({"data": [{"id": "mini"}]}))
    harness.script.queue("fast1", httpx.Response(500, json={"error": {"message": "upstream down"}}))
    resp = await harness.api.post(f"{API_PREFIX}/kira/providers/fast_one/probe", headers=harness.signed)
    assert resp.status_code == 200, "a failed diagnostic is data, not an HTTP error"
    assert resp.json()["ok"] is False and "upstream down" in resp.json()["error"]


async def test_a_probe_of_an_unknown_provider_is_a_400(harness):
    resp = await harness.api.post(f"{API_PREFIX}/kira/providers/nosuch/probe", headers=harness.signed)
    assert resp.status_code == 400
    assert harness.script.calls == [], "refusing an unknown name costs the provider nothing"
