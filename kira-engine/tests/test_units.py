from __future__ import annotations

import re
from pathlib import Path

import pytest

from kira.config import Config, ProviderConfig, load_config, resolve_data_dir, write_sample_config
from kira.errors import ConfigError
from kira.net import HealthLedger
from kira.store import Store, month_bounds
from kira.vault import Vault, ENGINE_TOKEN_REF
from conftest import provider_configs


def test_provider_config_rejects_unknown_kind():
    with pytest.raises(ConfigError):
        ProviderConfig(name="x", kind="mistral", base_url="https://a.invalid", models=["m"])


def test_provider_config_requires_models():
    with pytest.raises(ConfigError, match="no models"):
        ProviderConfig(name="x", kind="gemini", base_url="https://a.invalid", models=[])


def test_provider_config_requires_http_base_url():
    with pytest.raises(ConfigError, match="http"):
        ProviderConfig(name="x", kind="gemini", base_url="a.invalid", models=["m"])


def test_config_refuses_non_loopback_host(tmp_path):
    with pytest.raises(ConfigError, match="loopback"):
        Config(data_dir=tmp_path, host="0.0.0.0", providers=provider_configs())


def test_config_refuses_duplicate_provider_names(tmp_path):
    dup = provider_configs() + [provider_configs()[0]]
    with pytest.raises(ConfigError, match="unique"):
        Config(data_dir=tmp_path, providers=dup)


def test_config_rejects_unknown_mode(tmp_path):
    with pytest.raises(ConfigError, match="default_mode"):
        Config(data_dir=tmp_path, default_mode="CHEAP", providers=provider_configs())


def test_sample_config_roundtrips_through_loader(tmp_path):
    path = write_sample_config(tmp_path)
    cfg = load_config(tmp_path)
    assert path.exists()
    assert [p.name for p in cfg.providers] == ["openrouter", "groq", "anthropic", "gemini"]
    assert cfg.by_name["anthropic"].kind == "anthropic"
    assert cfg.by_name["groq"].tier == "fast"
    assert cfg.by_name["openrouter"].base_url == "https://openrouter.ai/api/v1"
    assert cfg.supports_model("llama-3.3-70b-versatile")
    assert not cfg.supports_model("does-not-exist")


def test_load_config_without_file_yields_no_providers(tmp_path):
    cfg = load_config(tmp_path)
    assert cfg.providers == []
    assert (tmp_path / "logs").exists()


def test_vault_memory_stores_and_lists_presence():
    vault = Vault("memory")
    assert vault.get("provider/x") is None
    vault.set("provider/x", "secret")
    assert vault.get("provider/x") == "secret"
    assert vault.has("provider/x")
    vault.delete("provider/x")
    assert not vault.has("provider/x")


def test_engine_token_created_once():
    vault = Vault("memory")
    token, created = vault.get_or_create_engine_token()
    assert created and len(token) > 20
    again, created_again = vault.get_or_create_engine_token()
    assert not created_again and again == token
    assert vault.get(ENGINE_TOKEN_REF) == token


def test_store_roundtrips_messages_with_chain(tmp_path):
    store = Store(tmp_path / "kira.db")
    sid = store.create_session("AUTO")
    store.add_message(sid, "user", "hello")
    store.add_message(
        sid,
        "assistant",
        "hi",
        provider="fast_one",
        model="mini",
        finish_reason="stop",
        usage={"input_tokens": 3, "output_tokens": 2},
        chain=[{"provider": "fast_one", "event": "served"}],
    )
    rows = store.messages(sid)
    assert [r["role"] for r in rows] == ["user", "assistant"]
    assert rows[1]["provider"] == "fast_one"
    assert rows[1]["chain"][0]["event"] == "served"
    assert rows[1]["usage"]["output_tokens"] == 2
    assert store.list_sessions()[0]["id"] == sid
    store.close()


def test_ledger_backs_off_and_clears_on_success(tmp_path):
    store = Store(tmp_path / "kira.db")
    ledger = HealthLedger(store=store)
    from kira.errors import ProviderCallError

    first = ProviderCallError("p", "boom", status=503, retryable=True, code="provider_5xx")
    record = ledger.record_failure(first)
    assert record["cooldown_s"] == 5.0
    ledger.record_failure(first)
    assert ledger.state("p").cooled_until > 0
    eligible, skipped = ledger.available(["p", "q"])
    assert eligible == ["q"]
    assert skipped[0]["event"] == "skipped_cooling"

    ledger.record_success("p")
    assert ledger.available(["p"])[0] == ["p"]
    reloaded = HealthLedger(store=store)
    assert reloaded.state("p").successes == 1
    store.close()


def test_non_retryable_failure_does_not_cool_provider():
    from kira.errors import ProviderCallError

    ledger = HealthLedger()
    ledger.record_failure(ProviderCallError("p", "bad request", status=400, retryable=False))
    assert ledger.state("p").cooled_until == 0
    assert ledger.available(["p"])[0] == ["p"]


def _kira_error_classes(cls):
    yield cls
    for sub in cls.__subclasses__():
        yield sub
        yield from _kira_error_classes(sub)


def test_contract_publishes_every_kira_error_code():
    from kira import errors
    from kira.contracts import ERROR_CODES, PROVIDER_CODES

    documented = set(ERROR_CODES) | set(PROVIDER_CODES)
    emitted = {cls.code for cls in _kira_error_classes(errors.KiraError)}
    assert emitted <= documented
    assert set(ERROR_CODES) == emitted
    assert {errors.BAD_STREAM, errors.RATE_LIMITED, errors.PROVIDER_4XX, errors.PROVIDER_5XX} <= set(PROVIDER_CODES)


def test_provider_error_default_code_is_documented():
    from kira.contracts import PROVIDER_CODES
    from kira.errors import ProviderCallError

    assert ProviderCallError("p", "boom").code in PROVIDER_CODES


def test_default_data_dir_keeps_the_chat_bundle_a_sibling(tmp_path, monkeypatch):
    monkeypatch.delenv("KIRA_DATA_DIR", raising=False)
    data = resolve_data_dir()
    assert data.name == ".kira-data"
    assert (data.parent / "kira-chat").is_dir()
    assert (data.parent / "kira-engine").is_dir()


def test_settings_table_appears_on_an_existing_database(tmp_path):
    path = tmp_path / "kira.db"
    first = Store(path)
    first.create_session("AUTO")
    first.close()

    second = Store(path)  # reopening a v1 database must not lose or refuse the new table
    second.set_setting("groq", "tier", "fast")
    assert second.settings_map() == {"groq": {"tier": '"fast"'}}
    assert [s["id"] for s in second.list_sessions()]  # the pre-existing row is still there
    second.close()


def test_sample_config_leaves_the_cap_absent(tmp_path):
    write_sample_config(tmp_path)
    assert load_config(tmp_path).by_name["groq"].monthly_token_cap is None


def test_yaml_cap_is_read_and_validated(tmp_path):
    stanza = (
        "providers:\n  - name: groq\n    kind: openai_compat\n    base_url: https://g.invalid\n"
        "    models: [mini]\n"
    )
    (tmp_path / "config.yaml").write_text(stanza + "    monthly_token_cap: 1000000\n", encoding="utf-8")
    assert load_config(tmp_path).by_name["groq"].monthly_token_cap == 1000000

    for bad in ("-5", "true", '"many"', "0"):
        (tmp_path / "config.yaml").write_text(stanza + f"    monthly_token_cap: {bad}\n", encoding="utf-8")
        if bad == "0":
            # 0 is the "no ceiling" spelling, so it lands on None rather than a zero-cap provider.
            assert load_config(tmp_path).by_name["groq"].monthly_token_cap is None
        else:
            with pytest.raises(ConfigError, match="monthly_token_cap"):
                load_config(tmp_path)


def test_an_over_cap_provider_is_stood_down_with_a_published_event_name(harness):
    # Task 15's own file proves the arithmetic; this proves the *name*: the event the router writes is
    # one of the events the contract publishes, so a rename cannot leave the client falling through to
    # `LABELS[record.event] ?? record.event` while every budget test still passes.
    from kira.contracts import CHAIN_EVENTS

    harness.store.set_setting("fast_one", "monthly_cap", 1_000)
    harness.engine.router.spend_source = lambda: (month_bounds()[0], {"fast_one": 1_000})
    notes = [n for n in harness.engine.router.plan(mode="FAST").notes if n["provider"] == "fast_one"]
    assert [n["event"] for n in notes] == ["skipped_budget"]
    assert {n["event"] for n in notes} <= set(CHAIN_EVENTS)


def test_every_published_chain_event_has_a_label_in_the_chat_bundle(monkeypatch):
    # An unlabelled event still renders — as a chip of snake_case jargon. This is the only check that
    # catches that before a human sees it.
    from kira.contracts import CHAIN_EVENTS

    monkeypatch.delenv("KIRA_DATA_DIR", raising=False)
    trace = resolve_data_dir().parent / "kira-chat" / "src" / "components" / "ChainTrace.tsx"
    assert trace.is_file(), f"the chat bundle must sit beside the engine: {trace}"
    block = trace.read_text(encoding="utf-8").split("const LABELS: Record<string, string> = {", 1)[1]
    block = block.split("};", 1)[0]
    labelled = set(re.findall(r"^  (\w+):", block, re.MULTILINE))
    assert labelled == set(CHAIN_EVENTS)


def test_a_frozen_build_keeps_its_data_under_local_appdata(monkeypatch, tmp_path):
    # An installed copy usually sits in Program Files, where nothing may write; the repo
    # default (<checkout>/.kira-data) would either fail or land inside the install folder.
    import sys

    monkeypatch.delenv("KIRA_DATA_DIR", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    assert resolve_data_dir() == tmp_path / "Local" / "Kira"


def test_a_frozen_build_without_local_appdata_falls_back_to_home(monkeypatch, tmp_path):
    import sys

    monkeypatch.delenv("KIRA_DATA_DIR", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    assert resolve_data_dir() == tmp_path / "AppData" / "Local" / "Kira"
