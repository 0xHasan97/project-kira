from __future__ import annotations

import json

from kira.__main__ import main
from kira.config import load_config, write_sample_config
from kira.store import Store


def seeded(tmp_path) -> Store:
    write_sample_config(tmp_path)
    store = Store(load_config(tmp_path).db_path)
    store.set_setting("groq", "enabled", False)
    # A junk key is exactly what the dashboard cannot write, so seed it the way a typo got there.
    store._conn.execute(  # noqa: SLF001 - deliberately writing underneath the API
        "INSERT INTO settings(provider, key, value, updated_at) VALUES('groq','colour','\"red\"',1.0)"
    )
    store._conn.commit()
    return store


def run(tmp_path, *argv):
    return main(["settings", *argv, "--data-dir", str(tmp_path), "--backend", "memory"])


def test_settings_list_flags_the_orphan_and_prints_no_secrets(tmp_path, capsys):
    seeded(tmp_path)
    assert run(tmp_path, "list") == 0
    rows = json.loads(capsys.readouterr().out)["rows"]
    by_key = {row["key"]: row for row in rows}
    assert by_key["enabled"] == {"provider": "groq", "key": "enabled", "value": "false", "orphan": False}
    assert by_key["colour"]["orphan"] is True
    assert set(by_key["colour"]) == {"provider", "key", "value", "orphan"}


def test_settings_clear_refuses_without_yes_and_takes_the_row_with_it(tmp_path, capsys):
    store = seeded(tmp_path)
    assert run(tmp_path, "clear", "groq", "colour") == 2
    assert store.settings_map()["groq"]["colour"] == '"red"'
    assert "settings clear" in capsys.readouterr().err
    assert run(tmp_path, "clear", "groq", "colour", "--yes") == 0
    assert "colour" not in store.settings_map()["groq"]
    assert "enabled" in store.settings_map()["groq"], "one key cleared is not the row emptied"


def test_settings_clear_without_a_key_removes_every_row_for_that_provider(tmp_path):
    store = seeded(tmp_path)
    store.set_setting("groq", "priority", 5)
    assert run(tmp_path, "clear", "groq", "--yes") == 0
    assert "groq" not in store.settings_map()


def test_settings_clear_of_a_row_that_is_not_there_returns_1(tmp_path, capsys):
    seeded(tmp_path)
    assert run(tmp_path, "clear", "groq", "nosuch", "--yes") == 1
    assert "no settings row" in capsys.readouterr().err
