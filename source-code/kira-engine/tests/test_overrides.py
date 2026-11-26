from __future__ import annotations

import time
from dataclasses import replace

import pytest

from kira.config import TIERS, Config, ProviderConfig
from kira.errors import ConfigError
from kira.overrides import MAX_PRIORITY, TUNABLE_FIELDS, build_view, enabled_providers, validate_setting
from kira.store import SETTINGS_KEYS, Store


def test_settings_table_roundtrips_a_json_scalar(tmp_path):
    store = Store(tmp_path / "kira.db")
    assert store.settings_map() == {}
    store.set_setting("groq", "enabled", False)
    store.set_setting("groq", "priority", 60)
    assert store.settings_map() == {"groq": {"enabled": "false", "priority": "60"}}
    store.close()


def test_settings_only_accepts_the_four_tunable_keys(tmp_path):
    store = Store(tmp_path / "kira.db")
    assert SETTINGS_KEYS == {"enabled", "priority", "tier", "monthly_cap"}
    try:
        store.set_setting("groq", "base_url", "https://evil")
    except ConfigError as exc:
        assert "base_url" in str(exc)
    else:
        raise AssertionError("base_url must not be writable through settings")
    store.close()


def test_clear_setting_reports_whether_a_row_existed(tmp_path):
    store = Store(tmp_path / "kira.db")
    store.set_setting("groq", "tier", "powerful")
    assert store.clear_setting("groq", "tier") is True
    assert store.clear_setting("groq", "tier") is False
    assert store.settings_map() == {}
    store.close()


def test_settings_map_returns_the_raw_rows_untouched(tmp_path):
    store = Store(tmp_path / "kira.db")
    store.set_setting("groq", "priority", 7)
    # A row a hand-edit could have left behind stays visible: the merge decides what is
    # tunable, and it reports anything it cannot use instead of swallowing it.
    store._conn.execute(  # noqa: SLF001 - deliberately writing underneath the API
        "INSERT INTO settings(provider, key, value, updated_at) VALUES('groq','colour','red',?)",
        (time.time(),),
    )
    store._conn.commit()
    assert store.settings_map() == {"groq": {"colour": "red", "priority": "7"}}
    store.close()


def configs() -> list[ProviderConfig]:
    return [
        ProviderConfig(name="groq", kind="openai_compat", base_url="https://groq.invalid/v1",
                       models=["mini"], tier="fast", key_ref="provider/groq", priority=50),
        ProviderConfig(name="openrouter", kind="openai_compat", base_url="https://or.invalid/v1",
                       models=["max"], tier="powerful", key_ref="provider/openrouter", priority=100),
    ]


def config_of(tmp_path, cap: int | None = None) -> Config:
    return Config(
        data_dir=tmp_path,
        providers=[replace(p, monthly_token_cap=cap) for p in configs()] if cap is not None else configs(),
    )


def test_baseline_applies_when_no_rows_exist(tmp_path):
    store = Store(tmp_path / "kira.db")
    view = build_view(config_of(tmp_path), store)
    groq = view.by_name["groq"]
    assert groq.enabled is True
    assert groq.priority == 50
    assert groq.monthly_cap is None
    assert groq.states["enabled"].to_wire() == {"base": True, "override": None, "effective": True}
    assert view.orphan_settings == []
    store.close()


def test_override_wins_and_stays_visible_alongside_the_baseline(tmp_path):
    store = Store(tmp_path / "kira.db")
    store.set_setting("groq", "priority", 10)
    store.set_setting("groq", "tier", "powerful")
    store.set_setting("groq", "enabled", False)
    store.set_setting("groq", "monthly_cap", 1000000)
    groq = build_view(config_of(tmp_path), store).by_name["groq"]
    assert (groq.priority, groq.tier, groq.enabled, groq.monthly_cap) == (10, "powerful", False, 1000000)
    assert groq.states["tier"].to_wire() == {"base": "fast", "override": "powerful", "effective": "powerful"}
    assert groq.states["monthly_cap"].to_wire() == {"base": None, "override": 1000000, "effective": 1000000}
    store.close()


def test_a_cap_override_of_zero_means_unlimited_not_blocked(tmp_path):
    # 0 is the dashboard's spelling for "no ceiling"; `null` is "drop the override".
    # The two must not be confusable, and only the first is a stored row.
    store = Store(tmp_path / "kira.db")
    store.set_setting("groq", "monthly_cap", 0)
    view = build_view(config_of(tmp_path, cap=2_000), store)
    groq = view.by_name["groq"]
    assert groq.states["monthly_cap"].to_wire() == {"base": 2000, "override": 0, "effective": None}
    assert view.orphan_settings == []
    store.close()


def test_enabled_base_is_true_because_yaml_has_no_enabled_key(tmp_path):
    store = Store(tmp_path / "kira.db")
    groq = build_view(config_of(tmp_path), store).by_name["groq"]
    assert groq.states["enabled"].base is True
    store.close()


def test_a_row_of_the_wrong_type_behaves_as_absent_and_is_reported(tmp_path):
    store = Store(tmp_path / "kira.db")
    store.set_setting("groq", "enabled", 1)        # JSON 1, not a bool
    store.set_setting("groq", "priority", "60")    # JSON string, not an int
    view = build_view(config_of(tmp_path), store)
    groq = view.by_name["groq"]
    assert groq.enabled is True and groq.priority == 50
    assert sorted(view.orphan_settings) == ["groq.enabled", "groq.priority"]
    store.close()


def test_a_key_that_is_not_tunable_is_reported_not_swallowed(tmp_path):
    store = Store(tmp_path / "kira.db")
    # The write boundary refuses this, so it can only arrive from a hand edit or an older build.
    store._conn.execute(  # noqa: SLF001 - deliberately writing underneath the API
        "INSERT INTO settings(provider, key, value, updated_at) VALUES('groq','colour','red',0)"
    )
    store._conn.commit()
    view = build_view(config_of(tmp_path), store)
    assert view.by_name["groq"].priority == 50, "an unusable row changes nothing"
    assert view.orphan_settings == ["groq.colour"]
    store.close()


def test_true_is_not_an_integer_for_priority(tmp_path):
    # bool is a subclass of int in Python; `true` in the database is not priority 1.
    store = Store(tmp_path / "kira.db")
    store.set_setting("groq", "priority", True)
    view = build_view(config_of(tmp_path), store)
    assert view.by_name["groq"].priority == 50
    assert view.orphan_settings == ["groq.priority"]
    store.close()


def test_unparseable_json_is_reported_rather_than_raising(tmp_path):
    store = Store(tmp_path / "kira.db")
    store._conn.execute(  # noqa: SLF001 - deliberately writing underneath the API
        "INSERT INTO settings(provider, key, value, updated_at) VALUES('groq','tier','not json',1.0)"
    )
    store._conn.commit()
    view = build_view(config_of(tmp_path), store)
    assert view.by_name["groq"].tier == "fast"
    assert view.orphan_settings == ["groq.tier"]
    store.close()


def test_a_row_for_a_provider_that_left_the_yaml_is_an_orphan(tmp_path):
    store = Store(tmp_path / "kira.db")
    store.set_setting("deleted_provider", "enabled", False)
    view = build_view(config_of(tmp_path), store)
    assert "deleted_provider" not in view.by_name
    assert view.orphan_settings == ["deleted_provider.enabled"]
    assert store.delete_settings("deleted_provider") == 1
    assert build_view(config_of(tmp_path), store).orphan_settings == []
    store.close()


def test_view_without_a_store_is_the_plain_yaml_baseline(tmp_path):
    view = build_view(config_of(tmp_path), None)
    assert [p.name for p in view.providers] == ["groq", "openrouter"]
    assert all(p.enabled for p in view.providers)
    assert view.orphan_settings == []


def test_enabled_providers_is_what_routing_sees(tmp_path):
    store = Store(tmp_path / "kira.db")
    store.set_setting("groq", "enabled", False)
    store.set_setting("openrouter", "priority", 1)
    view = build_view(config_of(tmp_path), store)
    assert [p.name for p in enabled_providers(view)] == ["openrouter"]
    store.close()


def test_the_write_path_normalises_tier_and_refuses_an_unknown_one(tmp_path):
    assert validate_setting("tier", " Powerful ") == "powerful"
    for bad in ("hyper", "", 7, True):
        with pytest.raises(ConfigError) as exc:
            validate_setting("tier", bad)
    assert "fast" in str(exc.value.message) and "powerful" in str(exc.value.message)


def test_priority_has_the_documented_range_and_a_bool_is_not_an_integer(tmp_path):
    assert validate_setting("priority", 0) == 0
    assert validate_setting("priority", MAX_PRIORITY) == MAX_PRIORITY
    for bad in (-1, MAX_PRIORITY + 1, 12.5, "12", True):
        with pytest.raises(ConfigError):
            validate_setting("priority", bad)


def test_monthly_cap_takes_zero_as_unlimited_and_refuses_the_rest(tmp_path):
    assert validate_setting("monthly_cap", 0) == 0
    assert validate_setting("monthly_cap", 1_000_000) == 1_000_000
    for bad in (-1, 0.5, True, "lots"):
        with pytest.raises(ConfigError):
            validate_setting("monthly_cap", bad)


def test_none_clears_any_field_and_an_unknown_field_is_named(tmp_path):
    for key in TUNABLE_FIELDS:
        assert validate_setting(key, None) is None
    with pytest.raises(ConfigError) as exc:
        validate_setting("colour", "red")
    assert "colour" in exc.value.message
    with pytest.raises(ConfigError) as exc:
        validate_setting("colour", None)
    assert "colour" in exc.value.message, "clearing a field that was never tunable is still a mistake"
