from __future__ import annotations

import pytest

from kira.memory import MemoryStore
from kira.store import Store


@pytest.fixture
def memory(tmp_path):
    return MemoryStore(Store(tmp_path / "kira.db"))


def test_history_search_finds_user_and_assistant_text_but_never_tool_output(memory):
    store = memory.store
    store.create_session("AUTO", "s1")
    store.add_message("s1", "user", "what did we decide about the vector database")
    store.add_message("s1", "assistant", "we settled on a vector index after all")
    store.add_message("s1", "tool", "TOOL_ONLY_CANARY vector")
    hits = memory.search_history("vector", 10)
    assert sorted(hit["role"] for hit in hits) == ["assistant", "user"]
    assert all(hit["session_id"] == "s1" for hit in hits)
    assert all("[" in hit["snippet"] for hit in hits)  # the engine brackets the match, the UI does not re-find it


def test_history_search_is_best_first_across_sessions(memory):
    store = memory.store
    store.create_session("AUTO", "s1")
    store.create_session("AUTO", "s2")
    store.add_message("s1", "user", "router")
    store.add_message("s2", "user", "the router picks a provider and the router fails over")
    hits = memory.search_history("router provider failover", 10)
    assert hits[0]["session_id"] == "s2"


def test_history_search_returns_nothing_for_an_empty_query(memory):
    memory.store.create_session("AUTO", "s1")
    memory.store.add_message("s1", "user", "anything")
    assert memory.search_history("", 10) == []
    assert memory.search_history("   ", 10) == []


def test_a_broken_match_expression_is_retried_as_like_without_tool_output(memory, monkeypatch):
    store = memory.store
    store.create_session("AUTO", "s1")
    store.add_message("s1", "user", "a message about eggs")
    store.add_message("s1", "tool", "TOOL_ONLY_CANARY eggs")
    # `col:value` is a column filter, and `messages_fts` has no `col`: FTS5 raises, not just misses.
    monkeypatch.setattr("kira.memory.fts_match", lambda *a, **k: "col:value")
    hits = memory.search_history("eggs", 10)
    assert [hit["role"] for hit in hits] == ["user"]
    assert hits[0]["snippet"] == "a message about eggs"


def test_history_search_breaks_a_score_tie_newest_first(memory):
    store = memory.store
    store.create_session("AUTO", "s1")
    store.create_session("AUTO", "s2")
    first = store.add_message("s1", "user", "router")
    second = store.add_message("s2", "user", "router")
    # Identical text scores identically; one clock tick can also hand them the same timestamp.
    store.conn.execute("UPDATE messages SET created_at=1.0")
    store.conn.commit()
    hits = memory.search_history("router", 10)
    assert [hit["message_id"] for hit in hits] == [second, first]


def test_a_history_hit_has_the_documented_shape(memory):
    memory.store.create_session("AUTO", "s1")
    message_id = memory.store.add_message("s1", "user", "the vector database")
    (hit,) = memory.search_history("vector", 10)
    assert set(hit) == {"session_id", "message_id", "role", "snippet", "created_at"}
    assert hit["message_id"] == message_id
    assert isinstance(hit["created_at"], float)
