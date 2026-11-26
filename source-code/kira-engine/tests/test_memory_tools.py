from __future__ import annotations

import asyncio
import json

import pytest

from kira.memory import MemoryStore, register_memory_tools
from kira.store import Store
from kira.tools import ToolRegistry


@pytest.fixture
def wired(tmp_path):
    memory = MemoryStore(Store(tmp_path / "kira.db"))
    registry = ToolRegistry()
    register_memory_tools(registry, memory)
    return registry, memory


def run(registry, name, arguments):
    return asyncio.run(registry.execute(name, arguments))


def test_both_tools_are_registered_with_the_documented_defaults(wired):
    registry, _ = wired
    assert registry.get("recall").default_policy == "allow"
    assert registry.get("recall").risk == "read"
    assert registry.get("remember").default_policy == "allow"
    assert registry.get("remember").risk == "write"


def test_remember_stores_a_fact_and_refuses_a_duplicate(wired):
    registry, memory = wired
    first = run(registry, "remember", {"text": "I prefer pnpm", "kind": "preference"})
    assert first.ok and "remembered" in first.content
    stored = memory.list()[0][0]
    assert stored["origin"] == "tool" and stored["kind"] == "preference"
    again = run(registry, "remember", {"text": "i prefer pnpm."})
    assert again.ok and again.content.startswith("already remembered")
    assert memory.list()[1] == 1


def test_remember_needs_text_and_validates_the_kind(wired):
    registry, _ = wired
    assert run(registry, "remember", {}).ok is False
    assert "non-empty" in run(registry, "remember", {}).content
    assert run(registry, "remember", {"text": "x", "kind": "gossip"}).ok is False


def test_recall_searches_both_facts_and_history(wired):
    registry, memory = wired
    memory.add("the user prefers pnpm")
    memory.store.create_session("AUTO", "s1")
    memory.store.add_message("s1", "user", "we talked about pnpm and yarn")
    answer = run(registry, "recall", {"query": "pnpm"})
    assert answer.ok
    assert "the user prefers pnpm" in answer.content
    assert "session s1" in answer.content


def test_recall_says_so_when_it_finds_nothing_and_rejects_an_empty_query(wired):
    registry, _ = wired
    assert run(registry, "recall", {"query": "nothing at all"}).content.startswith("nothing in memory")
    assert run(registry, "recall", {"query": ""}).ok is False


def test_a_recall_limit_is_clamped(wired):
    registry, memory = wired
    for index in range(30):
        memory.add(f"note {index} about tokens")
    answer = run(registry, "recall", {"query": "tokens", "limit": 999})
    assert answer.ok and len(answer.content.splitlines()) <= 40  # 20 facts + 20 history at most


def test_capture_off_removes_remember_and_keeps_recall(harness):
    engine = harness.engine
    assert engine.tools.get("remember") is not None
    engine.memory.set_settings({"capture": "off"})
    engine.sync_memory_tools()
    assert engine.tools.get("remember") is None
    assert engine.tools.get("recall") is not None
    engine.memory.set_settings({"capture": "explicit"})
    engine.sync_memory_tools()
    assert engine.tools.get("remember") is not None


def test_unregister_reports_whether_it_removed_anything(tmp_path):
    registry = ToolRegistry()
    register_memory_tools(registry, MemoryStore(Store(tmp_path / "kira.db")))
    assert registry.unregister("remember") is True
    assert registry.unregister("remember") is False
