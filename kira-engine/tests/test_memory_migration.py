from __future__ import annotations

import json
import sqlite3
import time

import pytest

import kira.store as store_module
from kira.errors import ConfigError
from kira.store import Store

# The v1 shape exactly as `Store` used to create it. A migration test that lets `Store` build the
# old tables proves nothing, so this file writes them with raw sqlite3 first.
V1_SCHEMA = """
CREATE TABLE sessions (id TEXT PRIMARY KEY, mode TEXT NOT NULL, created_at REAL NOT NULL);
CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    provider TEXT, model TEXT, finish_reason TEXT,
    status TEXT NOT NULL DEFAULT 'complete',
    tool_calls TEXT NOT NULL DEFAULT '[]',
    usage TEXT NOT NULL DEFAULT '{}',
    chain TEXT NOT NULL DEFAULT '[]',
    created_at REAL NOT NULL
);
CREATE INDEX ix_messages_session ON messages(session_id, id);
"""


def build_v1(path):
    conn = sqlite3.connect(str(path))
    conn.executescript(V1_SCHEMA)
    conn.execute("INSERT INTO sessions VALUES('s1','AUTO',?)", (time.time(),))
    rows = [
        ("user", "we decided the router should fail over", time.time()),
        ("assistant", "the vector database question is settled", time.time()),
        ("tool", "LISTING_CANARY_TOOL_OUTPUT", time.time()),
        ("assistant", "   ", time.time()),
    ]
    for role, content, when in rows:
        conn.execute(
            "INSERT INTO messages(session_id, role, content, created_at) VALUES('s1',?,?,?)",
            (role, content, when),
        )
    conn.execute("PRAGMA user_version=1")
    conn.commit()
    conn.close()


def test_a_v1_database_upgrades_and_indexes_its_history(tmp_path):
    path = tmp_path / "kira.db"
    build_v1(path)
    store = Store(path)
    # A v1 install walks every migration; the number is the latest schema, not memory's rung.
    assert store.conn.execute("PRAGMA user_version").fetchone()[0] == 3

    # The backfill covered user and assistant text, and only that: a tool row and a blank row stay out.
    hits = store.conn.execute(
        "SELECT message_id FROM messages_fts WHERE messages_fts MATCH '\"vector\"'"
    ).fetchall()
    assert len(hits) == 1
    tool = store.conn.execute(
        "SELECT COUNT(*) FROM messages_fts WHERE messages_fts MATCH '\"CANARY\"'"
    ).fetchone()[0]
    assert tool == 0


def test_the_tokenizer_is_recorded_and_is_trigram_on_this_build(tmp_path):
    store = Store(tmp_path / "kira.db")
    value = store.conn.execute("SELECT value FROM meta WHERE key='memory.tokenizer'").fetchone()[0]
    # `meta.value` holds JSON, the same way every other stored setting does.
    assert json.loads(value) == "trigram"


def test_a_build_without_trigram_falls_back_to_unicode61(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "_pick_tokenizer", lambda conn: "unicode61")
    store = Store(tmp_path / "kira.db")
    value = store.conn.execute("SELECT value FROM meta WHERE key='memory.tokenizer'").fetchone()[0]
    assert json.loads(value) == "unicode61"
    store.conn.execute(
        "INSERT INTO memories(id, text, created_at, updated_at) VALUES('m1','a portable note',?,?)",
        (time.time(), time.time()),
    )
    store.conn.commit()
    found = store.conn.execute(
        "SELECT memory_id FROM memory_fts WHERE memory_fts MATCH '\"portable\"'"
    ).fetchall()
    assert len(found) == 1


def test_deleting_a_memory_and_a_session_removes_its_index_rows(tmp_path):
    store = Store(tmp_path / "kira.db")
    now = time.time()
    store.conn.execute(
        "INSERT INTO memories(id, text, created_at, updated_at) VALUES('m1','the user prefers pnpm',?,?)",
        (now, now),
    )
    store.conn.commit()
    store.conn.execute("DELETE FROM memories WHERE id='m1'")
    store.conn.commit()
    assert store.conn.execute("SELECT COUNT(*) FROM memory_fts").fetchone()[0] == 0

    store.create_session("AUTO", "s1")
    store.add_message("s1", "user", "a sentence about pnpm")
    assert store.conn.execute("SELECT COUNT(*) FROM messages_fts").fetchone()[0] == 1
    store.delete_session("s1")
    assert store.conn.execute("SELECT COUNT(*) FROM messages_fts").fetchone()[0] == 0


def test_a_broken_upgrade_names_the_database_and_the_version(tmp_path, monkeypatch):
    path = tmp_path / "kira.db"
    build_v1(path)

    def explode(conn):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(store_module, "_pick_tokenizer", explode)
    with pytest.raises(ConfigError) as caught:
        Store(path)
    assert str(path) in caught.value.message
    assert "schema 2" in caught.value.message and "version 1" in caught.value.message
    # And it left the old database alone rather than half-upgraded.
    conn = sqlite3.connect(str(path))
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
    conn.close()
