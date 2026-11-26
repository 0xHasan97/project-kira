from __future__ import annotations

import re

import pytest

from kira.errors import ConfigError  # noqa: F401 - imported for the type of what must NOT escape
from kira.memory import MemoryStore, fts_match, like_pattern
from kira.store import Store


@pytest.fixture
def memory(tmp_path):
    return MemoryStore(Store(tmp_path / "kira.db"))


HOSTILE = ['"', "*", "NEAR(", "a OR b", "col:value", "🚀", "'; DROP TABLE memories; --", "^^^"]

# Nothing but quoted tokens and the builder's own AND/OR between them: no user-supplied operator,
# colon, star, caret or parenthesis survives into the expression FTS5 parses.
QUOTED_ONLY = re.compile(r'^"(?:[^"]|"")*"(?: (?:OR|AND) "(?:[^"]|"")*")*$')


@pytest.mark.parametrize("query", HOSTILE)
def test_the_match_builder_quotes_hostile_input_or_returns_none(query):
    built = fts_match(query, min_len=3)
    assert built is None or QUOTED_ONLY.match(built), built


def test_tokens_are_quoted_and_internal_quotes_are_doubled():
    assert fts_match('say "hi"', min_len=3) == '"say"'
    assert fts_match("alpha beta", min_len=3, match_all=True) == '"alpha" AND "beta"'
    assert fts_match("a bb cc", min_len=3) is None  # everything below the trigram floor


def test_like_pattern_escapes_its_wildcards():
    assert like_pattern("50%_off") == r"%50\%\_off%"


def test_bm25_ranks_the_row_matching_every_term_first(memory):
    memory.add("the router decides the provider and fails over")
    memory.add("a short note about routers")
    hits = memory.search_facts("router provider failover", 5)
    assert hits[0]["text"].startswith("the router decides")
    assert len(hits) == 2


def test_a_cjk_query_finds_a_cjk_fact(memory):
    memory.add("向量数据库很有用")
    hits = memory.search_facts("向量数据库", 5)
    assert [hit["text"] for hit in hits] == ["向量数据库很有用"]


def test_a_two_character_query_is_served_by_the_like_tier(memory):
    memory.add("we use pnpm here")
    assert [hit["text"] for hit in memory.search_facts("pn", 5)] == ["we use pnpm here"]


def test_an_empty_result_falls_through_to_like(memory, monkeypatch):
    memory.add("nothing in the index says that word")
    # Simulate a tokenizer that cannot see the term at all: MATCH finds nothing, LIKE still can.
    monkeypatch.setattr("kira.memory.fts_match", lambda *a, **k: '"invisible"')
    assert memory.search_facts("invisible", 5) == []
    monkeypatch.setattr("kira.memory.fts_match", lambda *a, **k: '"says"')
    assert memory.search_facts("says", 5)[0]["text"].startswith("nothing in the index")


def test_a_broken_match_expression_is_retried_as_like(memory, monkeypatch):
    memory.add("a row about eggs")
    # `col:value` is a column filter, and `memory_fts` has no `col`: FTS5 raises, not just misses.
    monkeypatch.setattr("kira.memory.fts_match", lambda *a, **k: "col:value")
    assert [hit["text"] for hit in memory.search_facts("eggs", 5)] == ["a row about eggs"]


def test_list_filters_by_kind_and_pinned_and_reports_the_total(memory):
    memory.add("one", kind="preference", pinned=True)
    memory.add("two", kind="note")
    rows, total = memory.list(kind="note")
    assert total == 1 and rows[0]["text"] == "two"
    rows, total = memory.list(pinned=True)
    assert total == 1 and rows[0]["text"] == "one"
    rows, total = memory.list(query="on")
    assert total == 1 and rows[0]["text"] == "one"


def test_list_breaks_a_shared_timestamp_by_insertion_order(memory):
    first = memory.add("first of the same tick")
    second = memory.add("second of the same tick")
    # Force the tie the Windows clock makes on its own, so the rule is pinned rather than hoped for.
    memory.store.conn.execute("UPDATE memories SET updated_at=1.0")
    memory.store.conn.commit()
    rows, _ = memory.list()
    assert [row["id"] for row in rows] == [second["id"], first["id"]]


def test_list_reports_the_total_before_the_limit(memory):
    memory.add("the router picks a provider")
    memory.add("the router fails over")
    memory.add("a note about the router")
    rows, total = memory.list(query="router", limit=1)
    assert len(rows) == 1
    assert total == 3  # three match, one is shown: the count is not the page size


def test_a_filtered_query_still_finds_a_row_that_ranks_beyond_the_limit(memory):
    # bm25 needs a corpus before it separates documents, and none of these match the query.
    for index in range(8):
        memory.add(f"unrelated distractor fact number {index} about tea and weather")
    memory.add("kubernetes kubernetes kubernetes")
    memory.add("kubernetes kubernetes in every deployment")
    memory.add("kubernetes only in this shorter note", kind="note")  # ranks third of the four
    memory.add(
        "kubernetes and then a fairly long tail of words that pad this row out so it ranks last"
    )
    page, _ = memory.list(query="kubernetes", limit=2)
    assert [row["kind"] for row in page] == ["fact", "fact"]  # the note really is past the limit
    rows, total = memory.list(query="kubernetes", kind="note", limit=2)
    assert [row["text"] for row in rows] == ["kubernetes only in this shorter note"]
    assert total == 1
