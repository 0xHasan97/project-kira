from __future__ import annotations

import pytest

from kira.errors import ConfigError
from kira.memory import MemoryStore, normalise
from kira.store import Store


@pytest.fixture
def memory(tmp_path):
    return MemoryStore(Store(tmp_path / "kira.db"))


def test_defaults_are_inject_on_capture_explicit_extract_off(memory):
    assert memory.settings() == {
        "inject": True,
        "capture": "explicit",
        "extract": False,
        "tokenizer": "trigram",
    }


def test_settings_round_trip_and_reject_junk(memory):
    written = memory.set_settings({"inject": False, "extract": True, "capture": "off"})
    assert written["inject"] is False and written["extract"] is True and written["capture"] == "off"
    assert memory.settings()["capture"] == "off"
    with pytest.raises(ConfigError):
        memory.set_settings({"capture": "sometimes"})
    with pytest.raises(ConfigError):
        memory.set_settings({"tokenizer": "trigram"})  # read-only observation, not a setting


def test_add_normalises_whitespace_trims_and_reports_a_duplicate(memory):
    item = memory.add("  I prefer   pnpm  ")
    assert item["text"] == "I prefer   pnpm"
    assert item["origin"] == "user" and item["kind"] == "fact" and item["pinned"] is False
    assert memory.find_duplicate("i prefer pnpm.") is not None
    assert normalise("I prefer   pnpm.") == "i prefer pnpm"


def test_add_rejects_blank_kind_and_oversized_text(memory):
    for bad in ("", "   ", "x" * 2001):
        with pytest.raises(ConfigError):
            memory.add(bad)
    with pytest.raises(ConfigError):
        memory.add("fine text", kind="gossip")


def test_update_partial_and_delete(memory):
    item = memory.add("the router fails over", kind="note")
    edited = memory.update(item["id"], {"text": "the router fails over fast", "pinned": True})
    assert edited["text"].endswith("fast") and edited["pinned"] is True and edited["kind"] == "note"
    assert memory.delete(item["id"]) is True
    assert memory.get(item["id"]) is None
    assert memory.delete(item["id"]) is False


def test_pinned_then_recent_ordering_and_mark_used(memory):
    first = memory.add("pinned fact", pinned=True)
    second = memory.add("older fact")
    third = memory.add("newer fact")
    assert [m["id"] for m in memory.pinned(4)] == [first["id"]]
    assert [m["id"] for m in memory.recent(2)] == [third["id"], second["id"]]
    memory.mark_used([second["id"]])
    assert memory.get(second["id"])["use_count"] == 1
    assert memory.get(second["id"])["last_used_at"] is not None


def test_editing_a_fact_moves_its_index_row(memory):
    item = memory.add("the router picks a provider")

    # `search_facts` arrives with Task 3, so this reads the index the trigger owns directly.
    def hits(term):
        return [
            row["memory_id"]
            for row in memory.store.conn.execute(
                "SELECT memory_id FROM memory_fts WHERE memory_fts MATCH ?", (f'"{term}"',)
            )
        ]

    assert hits("provider") == [item["id"]]
    memory.update(item["id"], {"text": "the router picks a model"})
    assert hits("provider") == []
    assert hits("model") == [item["id"]]


def test_export_is_stable_and_carries_a_version(memory):
    memory.add("something worth keeping")
    exported = memory.export()
    assert exported["version"] == 1
    assert set(exported) == {"version", "exported_at", "memories"}
    assert exported["memories"][0]["text"] == "something worth keeping"
