# Kira sub-project 4 — memory and retrieval: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Kira a local, inspectable memory: a fact table the user can edit and forget, a ranked
lexical index over the message history that already exists, a bounded block injected into each turn, a
`recall` tool and a `remember` tool, and a `#/memory` screen in both shells.

**Architecture:** One SQLite `memory.py` module over the existing `Store` connection. Two FTS5
own-content tables (`memory_fts`, `messages_fts`) kept in sync by triggers, tokenized `trigram` with a
`unicode61` fallback recorded in a new `meta` table. Selection is deterministic and free (pinned, then
BM25 over the last user message, then recently used); injection merges into the turn's system message
and is never persisted. The API is eight additive routes behind the existing bearer + confirm gate.

**Tech Stack:** Python 3.11 + FastAPI + sqlite3 (stdlib FTS5) in `kira-engine`; React 19 + TypeScript +
Vite + Vitest in `kira-chat`; the hand-authored contract mirror in `kira-contracts`.

**Spec:** `docs/specs/2026-10-29-kira-memory-design.md` — read it first; this plan implements it and
argues from it.

## Global Constraints

- `API_VERSION` stays **1** and `CONTRACT_VERSION` stays **2**. Every change here is additive
  (new paths, new schemas, new fields). A removal or a meaning change is out of scope.
- The engine binds **loopback only**. Nothing in this slice accepts a network address or makes a call
  the user did not configure.
- **No new dependency.** No numpy, no onnxruntime, no embedding model, no download. FTS5 ships inside
  the `sqlite3` module already in the venv (3.49.1 here; `trigram` present).
- Keys, the engine token and the confirm secret live only in the Windows Credential Locker. Never
  print, log or put a secret in a test, a fixture, a URL, a chain record or `localStorage`.
- Every write route needs `X-Kira-Confirm` through the existing `require_confirm` dependency; `GET`
  needs only the bearer token. The client never stores the confirm secret.
- Bad request bodies are **400 `config_error`** (the app's `_validation_handler`). Unknown ids are
  **404 `not_found`**. Do not introduce a second error dialect.
- The injected memory block is **never** written to `messages`, never exported and never shown as a
  turn. It exists for the length of one request.
- Commits: one per task, on branch `feat/memory` off `master`, using
  `git -c user.name="Kira" -c user.email="kira@localhost" commit`. Never `git config`, never push.
  At the end, fast-forward `master` and delete the branch (no remote exists).
- Gates after every task that touches the engine:
  `kira-engine/.venv/Scripts/python.exe -m pytest -q` (must stay green, 367 passing today);
  after every task that touches the client: `cd kira-chat && npm run check` (tsc + vitest + vite build);
  after every contract change: `node kira-contracts/check-drift.mjs`.
- Windows trap, already handled but do not regress: `core.autocrlf=true` makes the drift gate false-fail
  unless it normalises CRLF — it does, in `check-drift.mjs`'s `read()`. Leave that line alone.

---

### Task 1: Schema v2 — memory tables, the tokenizer probe, triggers, backfill

**Files:**
- Modify: `kira-engine/src/kira/store.py:39-147`
- Test: `kira-engine/tests/test_memory_migration.py` (create)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `Store.path: Path`, `Store.conn -> sqlite3.Connection` (read-only property), and on disk a
  `user_version = 2` database with `memories`, `memory_fts`, `messages_fts`, `meta`, their indexes and
  six triggers. `meta('memory.tokenizer')` holds `'trigram'` or `'unicode61'`.
  Module-level `kira.store._pick_tokenizer(conn) -> str` (patchable in tests).

- [ ] **Step 1: Write the failing tests**

```python
# kira-engine/tests/test_memory_migration.py
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
    assert store.conn.execute("PRAGMA user_version").fetchone()[0] == 2

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
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd kira-engine && .venv/Scripts/python.exe -m pytest -q tests/test_memory_migration.py`
Expected: FAIL — `AttributeError: 'Store' object has no attribute 'conn'` / no `meta` table.

- [ ] **Step 3: Implement the schema step**

In `store.py`, keep the v1 block exactly as it is and add below it:

```python
        version = self._conn.execute("PRAGMA user_version").fetchone()[0]
        if version < 1:
            ...  # unchanged ledger seed
            self._conn.execute("PRAGMA user_version=1")
            version = 1
        self._conn.commit()
        if version < 2:
            self._migrate_v2(version)
        self._conn.commit()
```

`__init__` gains `self.path = path` before it opens the connection, and one property:

```python
    @property
    def conn(self) -> sqlite3.Connection:
        """The live connection, for `memory.py`'s FTS5 queries — the only module that needs raw SQL
        this file does not own. Everything else goes through a method."""
        return self._conn
```

The migration, plus the probe it calls (module level, so a test can patch it):

```python
def _pick_tokenizer(conn: sqlite3.Connection) -> str:
    """Which index tokenizer this SQLite build can actually create.

    `trigram` is what makes CJK searchable at all — `unicode61` treats a whole CJK run as one token, so
    every CJK query returns nothing (measured, see the spec). It needs SQLite 3.34+; older builds raise
    at CREATE time, and the honest fallback is `unicode61` plus the LIKE tier in `memory.py`.
    """
    conn.execute("DROP TABLE IF EXISTS _kira_token_probe")
    for candidate in ("trigram", "unicode61"):
        try:
            conn.execute(f"CREATE VIRTUAL TABLE _kira_token_probe USING fts5(x, tokenize='{candidate}')")
        except sqlite3.OperationalError:
            continue
        conn.execute("DROP TABLE _kira_token_probe")
        return candidate
    return "unicode61"
```

```python
    def _migrate_v2(self, found: int) -> None:
        """Facts, both lexical indexes and the settings KV — one transaction, or none of it.

        `executescript` commits any open transaction before it runs, so nothing here uses it: every
        statement goes through `execute` inside one explicit `BEGIN`, and a failure rolls the DDL back
        too, leaving a v1 database the next start retries.
        """
        try:
            self._conn.execute("BEGIN")
            for statement in _MEMORY_DDL:
                self._conn.execute(statement)
            tokenizer = _pick_tokenizer(self._conn)
            for name, column, key in (
                ("memory_fts", "text", "memory_id"),
                ("messages_fts", "content", "message_id"),
            ):
                self._conn.execute(
                    f"CREATE VIRTUAL TABLE IF NOT EXISTS {name} USING fts5("
                    f"{key} UNINDEXED, {column}, tokenize='{tokenizer}')"
                )
            for statement in _MEMORY_TRIGGERS:
                self._conn.execute(statement)
            self._conn.execute(
                "INSERT OR REPLACE INTO meta(key, value, updated_at) VALUES('memory.tokenizer', ?, ?)",
                (json.dumps(tokenizer), time.time()),
            )
            self._conn.execute(
                """INSERT INTO messages_fts(message_id, content)
                   SELECT id, content FROM messages
                   WHERE role IN ('user','assistant') AND length(trim(content)) > 0"""
            )
            self._conn.execute("PRAGMA user_version=2")
            self._conn.commit()
        except sqlite3.Error as exc:
            self._conn.rollback()
            raise ConfigError(
                f"could not upgrade {self.path} to schema 2 from version {found}: {exc}"
            ) from exc
```

The DDL and trigger blocks are tuples of single statements (this is the spec's §5 SQL, with `trigram`
substituted at runtime). Tuples, not one big string, because one statement per `execute` is what keeps
the transaction real:

```python
_MEMORY_DDL = (
    """CREATE TABLE IF NOT EXISTS memories (
        id TEXT PRIMARY KEY,
        kind TEXT NOT NULL DEFAULT 'fact',
        text TEXT NOT NULL,
        pinned INTEGER NOT NULL DEFAULT 0,
        origin TEXT NOT NULL DEFAULT 'user',
        session_id TEXT,
        tokens_spent INTEGER NOT NULL DEFAULT 0,
        created_at REAL NOT NULL,
        updated_at REAL NOT NULL,
        last_used_at REAL,
        use_count INTEGER NOT NULL DEFAULT 0
    )""",
    "CREATE INDEX IF NOT EXISTS ix_memories_pinned ON memories(pinned, updated_at)",
    """CREATE TABLE IF NOT EXISTS meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at REAL NOT NULL
    )""",
)

_MEMORY_TRIGGERS = (
    """CREATE TRIGGER IF NOT EXISTS memory_fts_ai AFTER INSERT ON memories BEGIN
        INSERT INTO memory_fts(memory_id, text) VALUES (new.id, new.text);
    END""",
    """CREATE TRIGGER IF NOT EXISTS memory_fts_ad AFTER DELETE ON memories BEGIN
        DELETE FROM memory_fts WHERE memory_id = old.id;
    END""",
    """CREATE TRIGGER IF NOT EXISTS memory_fts_au AFTER UPDATE OF text ON memories BEGIN
        DELETE FROM memory_fts WHERE memory_id = old.id;
        INSERT INTO memory_fts(memory_id, text) VALUES (new.id, new.text);
    END""",
    """CREATE TRIGGER IF NOT EXISTS messages_fts_ai AFTER INSERT ON messages
    WHEN new.role IN ('user','assistant') AND length(trim(new.content)) > 0 BEGIN
        INSERT INTO messages_fts(message_id, content) VALUES (new.id, new.content);
    END""",
    """CREATE TRIGGER IF NOT EXISTS messages_fts_ad AFTER DELETE ON messages BEGIN
        DELETE FROM messages_fts WHERE message_id = old.id;
    END""",
    """CREATE TRIGGER IF NOT EXISTS messages_fts_au AFTER UPDATE OF content ON messages BEGIN
        DELETE FROM messages_fts WHERE message_id = old.id;
        INSERT INTO messages_fts(message_id, content)
        SELECT new.id, new.content
        WHERE new.role IN ('user','assistant') AND length(trim(new.content)) > 0;
    END""",
)
```

Two facts measured before writing this, which the tests above depend on: `ON DELETE CASCADE` really
does fire the `messages_fts_ad` trigger (foreign keys are `ON` on this connection), and a `WHEN role
IN (...)` trigger really does skip the tool row.

- [ ] **Step 4: Run the tests and the whole engine suite**

Run: `cd kira-engine && .venv/Scripts/python.exe -m pytest -q`
Expected: the five new tests pass; the existing 367 stay green.

- [ ] **Step 5: Commit**

```bash
git checkout -b feat/memory
git add kira-engine/src/kira/store.py kira-engine/tests/test_memory_migration.py
git -c user.name="Kira" -c user.email="kira@localhost" commit -m "memory: schema v2 — facts, two FTS5 indexes, a tokenizer chosen by probing"
```

---

### Task 2: `MemoryStore` — facts, settings, dedupe, export

**Files:**
- Create: `kira-engine/src/kira/memory.py`
- Test: `kira-engine/tests/test_memory_store.py`

**Interfaces:**
- Consumes: `Store.conn`, `Store.path`, `meta`, `memories` (Task 1).
- Produces:
  - `KINDS = ("fact", "preference", "note")`, `CAPTURES = ("off", "explicit")`,
    `DEFAULTS = {"inject": True, "capture": "explicit", "extract": False}`,
    `MAX_TEXT = 2000`.
  - `normalise(text: str) -> str`
  - `class MemoryStore(store: Store)` with `tokenizer`, `settings()`, `set_settings(patch)`,
    `list(query=None, kind=None, pinned=None, limit=50)`, `get(id)`, `add(text, *, kind, pinned, origin,
    session_id, tokens_spent)`, `update(id, patch)`, `delete(id)`, `find_duplicate(text)`,
    `pinned(limit=4)`, `recent(limit=12)`, `mark_used(ids)`, `export()`.
  - A stored row is the wire dict:
    `{id, kind, text, pinned, origin, session_id, tokens_spent, created_at, updated_at, last_used_at, use_count}`
    — `pinned` as `bool`, timestamps as floats, `last_used_at` `None` until first use.

- [ ] **Step 1: Write the failing tests**

```python
# kira-engine/tests/test_memory_store.py
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


def test_export_is_stable_and_carries_a_version(memory):
    memory.add("something worth keeping")
    exported = memory.export()
    assert exported["version"] == 1
    assert set(exported) == {"version", "exported_at", "memories"}
    assert exported["memories"][0]["text"] == "something worth keeping"
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd kira-engine && .venv/Scripts/python.exe -m pytest -q tests/test_memory_store.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'kira.memory'`.

- [ ] **Step 3: Write `memory.py` (facts half)**

```python
from __future__ import annotations

import json
import re
import time
import uuid
from typing import Any

from .errors import ConfigError
from .store import Store

KINDS = ("fact", "preference", "note")
CAPTURES = ("off", "explicit")
DEFAULTS: dict[str, Any] = {"inject": True, "capture": "explicit", "extract": False}
MAX_TEXT = 2000
_ITEM_FIELDS = (
    "id", "kind", "text", "pinned", "origin", "session_id",
    "tokens_spent", "created_at", "updated_at", "last_used_at", "use_count",
)


def normalise(text: str) -> str:
    """What "the same fact" means: case, runs of whitespace and trailing punctuation do not count.

    Deliberately not stemming or reordering — a paraphrase is a new fact, and pretending otherwise
    would silently drop something the user asked to keep.
    """
    collapsed = re.sub(r"\s+", " ", text.strip().lower())
    return collapsed.rstrip(" .!?;:,")


def _item(row: Any) -> dict[str, Any]:
    data = {field: row[field] for field in _ITEM_FIELDS}
    data["pinned"] = bool(data["pinned"])
    return data


def _clean_text(text: Any) -> str:
    if not isinstance(text, str):
        raise ConfigError("memory text must be a string")
    clean = text.strip()
    if not clean:
        raise ConfigError("memory text must not be empty")
    if len(clean) > MAX_TEXT:
        raise ConfigError(f"memory text is limited to {MAX_TEXT} characters, got {len(clean)}")
    return clean


class MemoryStore:
    """Facts the user chose to keep. One table, one index, one owner of the SQL."""

    def __init__(self, store: Store) -> None:
        self.store = store

    @property
    def _conn(self):
        return self.store.conn

    @property
    def tokenizer(self) -> str:
        row = self._conn.execute("SELECT value FROM meta WHERE key='memory.tokenizer'").fetchone()
        return json.loads(row["value"]) if row else "unicode61"

    def settings(self) -> dict[str, Any]:
        stored = {
            row["key"].removeprefix("memory."): json.loads(row["value"])
            for row in self._conn.execute("SELECT key, value FROM meta WHERE key LIKE 'memory.%'")
        }
        return {
            "inject": bool(stored.get("inject", DEFAULTS["inject"])),
            "capture": str(stored.get("capture", DEFAULTS["capture"])),
            "extract": bool(stored.get("extract", DEFAULTS["extract"])),
            "tokenizer": self.tokenizer,
        }

    def set_settings(self, patch: dict[str, Any]) -> dict[str, Any]:
        unknown = set(patch) - set(DEFAULTS)
        if unknown:
            raise ConfigError(
                f"{sorted(unknown)} are not memory settings; the three are {sorted(DEFAULTS)}"
            )
        for key, value in patch.items():
            if key == "capture" and value not in CAPTURES:
                raise ConfigError(f"capture must be one of {list(CAPTURES)}, got {value!r}")
            if key != "capture" and not isinstance(value, bool):
                raise ConfigError(f"{key} must be true or false")
        now = time.time()
        for key, value in patch.items():
            self._conn.execute(
                """INSERT INTO meta(key, value, updated_at) VALUES(?,?,?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
                (f"memory.{key}", json.dumps(value), now),
            )
        self._conn.commit()
        return self.settings()

    def get(self, memory_id: str) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
        return None if row is None else _item(row)

    def add(
        self,
        text: str,
        *,
        kind: str = "fact",
        pinned: bool = False,
        origin: str = "user",
        session_id: str | None = None,
        tokens_spent: int = 0,
    ) -> dict[str, Any]:
        clean = _clean_text(text)
        if kind not in KINDS:
            raise ConfigError(f"kind must be one of {list(KINDS)}, got {kind!r}")
        memory_id = uuid.uuid4().hex[:16]
        now = time.time()
        self._conn.execute(
            """INSERT INTO memories(id, kind, text, pinned, origin, session_id, tokens_spent,
                                    created_at, updated_at)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (memory_id, kind, clean, int(bool(pinned)), origin, session_id, int(tokens_spent), now, now),
        )
        self._conn.commit()
        return self.get(memory_id)

    def update(self, memory_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
        current = self.get(memory_id)
        if current is None:
            return None
        fields: dict[str, Any] = {}
        if "text" in patch:
            fields["text"] = _clean_text(patch["text"])
        if "kind" in patch:
            if patch["kind"] not in KINDS:
                raise ConfigError(f"kind must be one of {list(KINDS)}, got {patch['kind']!r}")
            fields["kind"] = patch["kind"]
        if "pinned" in patch:
            fields["pinned"] = int(bool(patch["pinned"]))
        if not fields:
            return current
        assignments = ", ".join(f"{key}=?" for key in fields)
        self._conn.execute(
            f"UPDATE memories SET {assignments}, updated_at=? WHERE id=?",
            (*fields.values(), time.time(), memory_id),
        )
        self._conn.commit()
        return self.get(memory_id)

    def delete(self, memory_id: str) -> bool:
        cur = self._conn.execute("DELETE FROM memories WHERE id=?", (memory_id,))
        self._conn.commit()
        return cur.rowcount > 0

    def find_duplicate(self, text: str) -> dict[str, Any] | None:
        wanted = normalise(text)
        for row in self._conn.execute("SELECT * FROM memories"):
            if normalise(row["text"]) == wanted:
                return _item(row)
        return None

    def pinned(self, limit: int = 4) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM memories WHERE pinned=1 ORDER BY updated_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [_item(row) for row in rows]

    def recent(self, limit: int = 12) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """SELECT * FROM memories WHERE pinned=0
               ORDER BY COALESCE(last_used_at, updated_at) DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [_item(row) for row in rows]

    def mark_used(self, ids: list[str]) -> None:
        if not ids:
            return
        now = time.time()
        self._conn.executemany(
            "UPDATE memories SET last_used_at=?, use_count=use_count+1 WHERE id=?",
            [(now, memory_id) for memory_id in ids],
        )
        self._conn.commit()

    def export(self) -> dict[str, Any]:
        rows = self._conn.execute("SELECT * FROM memories ORDER BY created_at, id").fetchall()
        return {"version": 1, "exported_at": time.time(), "memories": [_item(row) for row in rows]}
```

- [ ] **Step 4: Run the tests**

Run: `cd kira-engine && .venv/Scripts/python.exe -m pytest -q tests/test_memory_store.py tests/test_memory_migration.py`
Expected: PASS (13 tests).

- [ ] **Step 5: Commit**

```bash
git add kira-engine/src/kira/memory.py kira-engine/tests/test_memory_store.py
git -c user.name="Kira" -c user.email="kira@localhost" commit -m "memory: the fact store — CRUD, dedupe by normalised text, three settings in meta"
```

---

### Task 3: The MATCH builder, fact search, and the LIKE tier

**Files:**
- Modify: `kira-engine/src/kira/memory.py`
- Test: `kira-engine/tests/test_memory_search.py`

**Interfaces:**
- Consumes: `MemoryStore`, `tokenizer` (Tasks 1–2).
- Produces:
  - `fts_match(text, *, min_len=None, max_terms=8, match_all=False) -> str | None`
  - `like_pattern(text) -> str` — `%`-joined, `%`/`_` escaped with `\`.
  - `MemoryStore.search_facts(query, limit=12) -> list[dict]` — row dicts, best first.
  - `MemoryStore.list(*, query=None, kind=None, pinned=None, limit=50) -> tuple[list[dict], int]`
    (rows, total-before-limit).

> **Corrected during execution (commit 442a0c5).** The `list` body below filtered `kind`/`pinned`
> in Python *after* `search_facts(query, limit)` and returned `len(rows)` as `total`. That made the
> count cap at the limit and let a filtered query under-return — four facts matching, the only
> `note` ranked third, `list(query=…, kind="note", limit=2)` came back empty. The shipped code builds
> one alias-qualified `(_filters)` predicate and applies it inside **both** tiers, counting before the
> limit. Two test inputs were also wrong as written: `list`'s query-branch assertions above cannot
> distinguish "filter inside the tier" from "filter after it", and the broken-MATCH test injected
> `'this is not a query'`, which FTS5 *parses* and returns zero rows for, so it never reached the
> `except`. The shipped test injects `'col:value'`, which raises `OperationalError`. Read the shipped
> code for these two, not the snippets below.

- [ ] **Step 1: Write the failing tests**

```python
# kira-engine/tests/test_memory_search.py
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
    assert fts_match("a bb ccc", min_len=3) is None  # everything below the trigram floor


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
    monkeypatch.setattr("kira.memory.fts_match", lambda *a, **k: 'this is not a query')
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
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd kira-engine && .venv/Scripts/python.exe -m pytest -q tests/test_memory_search.py`
Expected: FAIL — `ImportError: cannot import name 'fts_match'`.

- [ ] **Step 3: Implement the builder and both search paths**

```python
_WORD = re.compile(r"[^\W_]+", re.UNICODE)


def fts_match(
    text: str, *, min_len: int | None = None, max_terms: int = 8, match_all: bool = False
) -> str | None:
    """A MATCH expression built only from quoted tokens, or `None` when nothing is usable.

    Every token is wrapped in double quotes with internal quotes doubled, so `*`, `:`, `^`, `NEAR(`,
    `AND/OR/NOT` and parentheses from user text are literal characters to FTS5. A query with no token
    at or above the tokenizer's floor is not sent to MATCH at all — the caller goes to the LIKE tier.
    """
    floor = 3 if min_len is None else min_len  # trigram cannot see a shorter token; unicode61 can
    tokens = [token for token in _WORD.findall(text or "") if len(token) >= floor][:max_terms]
    if not tokens:
        return None
    quoted = [f'"{token.replace(chr(34), chr(34) * 2)}"' for token in tokens]
    return (" AND " if match_all else " OR ").join(quoted)


def like_pattern(text: str) -> str:
    """The second tier: a `LIKE` pattern where the user's own wildcards are escaped."""
    escaped = (text or "").replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    terms = [term for term in escaped.split() if term]
    return "%" + "%".join(terms) + "%" if terms else "%"
```

Inside `MemoryStore`:

```python
    def _floor(self) -> int:
        return 3 if self.tokenizer == "trigram" else 1

    def _fact_rows(self, where: str, params: tuple, limit: int) -> list[dict[str, Any]]:
        return [
            _item(row)
            for row in self._conn.execute(
                f"SELECT m.* FROM memories m WHERE {where} ORDER BY m.pinned DESC, m.updated_at DESC LIMIT ?",
                (*params, limit),
            )
        ]

    def search_facts(self, query: str, limit: int = 12) -> list[dict[str, Any]]:
        """MATCH first for a ranked answer, LIKE when MATCH cannot see the query or finds nothing.

        Two tiers because FTS5 can be blind without failing: on a `unicode61` build a CJK run is one
        token, and a two-character query is below `trigram`'s floor. Returning nothing there would be a
        silent lie; the LIKE tier is slower and unranked, which is the right price for "never empty".
        """
        match = fts_match(query, min_len=self._floor())
        if match:
            try:
                rows = self._conn.execute(
                    """SELECT m.*, bm25(memory_fts) AS score
                       FROM memory_fts JOIN memories m ON m.id = memory_fts.memory_id
                       WHERE memory_fts MATCH ? ORDER BY score LIMIT ?""",
                    (match, limit),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = []
            if rows:
                return [_item(row) for row in rows]
        return self._fact_rows(
            "m.text LIKE ? ESCAPE '\\'", (like_pattern(query),), limit
        )

    def list(
        self,
        *,
        query: str | None = None,
        kind: str | None = None,
        pinned: bool | None = None,
        limit: int = 50,
    ) -> tuple[list[dict[str, Any]], int]:
        if query:
            hits = self.search_facts(query, limit)
            rows = [
                hit for hit in hits
                if (kind is None or hit["kind"] == kind)
                and (pinned is None or hit["pinned"] is pinned)
            ]
            return rows, len(rows)
        clauses, params = [], []
        if kind:
            clauses.append("kind=?")
            params.append(kind)
        if pinned is not None:
            clauses.append("pinned=?")
            params.append(int(pinned))
        where = " AND ".join(clauses) or "1=1"
        total = self._conn.execute(
            f"SELECT COUNT(*) FROM memories WHERE {where}", tuple(params)
        ).fetchone()[0]
        rows = self._fact_rows(where.replace("kind=", "m.kind=").replace("pinned=", "m.pinned="),
                              tuple(params), limit)
        return rows, int(total)
```

`import sqlite3` joins the imports at the top of `memory.py`.

- [ ] **Step 4: Run the tests**

Run: `cd kira-engine && .venv/Scripts/python.exe -m pytest -q tests/test_memory_search.py`
Expected: PASS (13 parametrised + unit cases).

- [ ] **Step 5: Commit**

```bash
git add kira-engine/src/kira/memory.py kira-engine/tests/test_memory_search.py
git -c user.name="Kira" -c user.email="kira@localhost" commit -m "memory: quoted MATCH builder, BM25 fact search, and a LIKE tier that never returns a silent nothing"
```

---

### Task 4: History search with engine-side snippets

**Files:**
- Modify: `kira-engine/src/kira/memory.py`
- Test: `kira-engine/tests/test_memory_history.py`

**Interfaces:**
- Consumes: `messages_fts`, `fts_match`, `like_pattern` (Tasks 1, 3).
- Produces: `MemoryStore.search_history(query, limit=20) -> list[dict]` where a hit is
  `{session_id, message_id, role, snippet, created_at}`.

> **Corrected during execution (commits 9e7d651, 34a839c).** The history tests live in their own
> module, `test_memory_history.py`, not appended to `test_memory_search.py` — one file per concern,
> as Tasks 1–3 already do. The first test as originally written inserted an assistant message that
> did **not** contain the query term and then asserted only `["user"]`, so the "assistant text" half
> of its own name had no teeth. The shipped test makes the assistant row match and asserts
> `sorted(roles) == ["assistant", "user"]`, with per-hit `all(...)` checks replacing the `hits[0]`
> positional ones — which also pins the FTS tier, since a LIKE-fallback snippet carries no
> brackets. Read the shipped file for these.

- [ ] **Step 1: Write the failing tests**

```python
# kira-engine/tests/test_memory_history.py
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
```

- [ ] **Step 2: Run and watch them fail**

Run: `cd kira-engine && .venv/Scripts/python.exe -m pytest -q tests/test_memory_history.py`
Expected: FAIL — `AttributeError: 'MemoryStore' object has no attribute 'search_history'`.

- [ ] **Step 3: Implement**

```python
    def search_history(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        """Ranked hits over the conversation text already in the store. Tool output is never indexed."""
        if not query or not query.strip():
            return []
        match = fts_match(query, min_len=self._floor())
        rows: list[Any] = []
        if match:
            try:
                rows = self._conn.execute(
                    """SELECT snippet(messages_fts, 1, '[', ']', '…', 12) AS snippet,
                              messages_fts.message_id AS message_id,
                              m.session_id, m.role, m.created_at
                       FROM messages_fts
                       JOIN messages m ON m.id = CAST(messages_fts.message_id AS INTEGER)
                       WHERE messages_fts MATCH ?
                       ORDER BY bm25(messages_fts) LIMIT ?""",
                    (match, limit),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = []
        if not rows:
            rows = self._conn.execute(
                """SELECT substr(m.content, 1, 240) AS snippet, m.id AS message_id,
                          m.session_id, m.role, m.created_at
                   FROM messages m
                   WHERE m.role IN ('user','assistant') AND m.content LIKE ? ESCAPE '\\'
                   ORDER BY m.created_at DESC LIMIT ?""",
                (like_pattern(query), limit),
            ).fetchall()
        return [
            {
                "session_id": row["session_id"],
                "message_id": int(row["message_id"]),
                "role": row["role"],
                "snippet": row["snippet"],
                "created_at": float(row["created_at"]),
            }
            for row in rows
        ]
```

- [ ] **Step 4: Run the full engine suite**

Run: `cd kira-engine && .venv/Scripts/python.exe -m pytest -q`
Expected: all green (380-ish passing, 1 skipped).

- [ ] **Step 5: Commit**

```bash
git add kira-engine/src/kira/memory.py kira-engine/tests/test_memory_history.py
git -c user.name="Kira" -c user.email="kira@localhost" commit -m "memory: ranked history search with engine-side snippets, tool output excluded"
```

---

### Task 5: `build_block` and `inject` — deterministic, free, bounded

**Files:**
- Modify: `kira-engine/src/kira/memory.py`
- Test: `kira-engine/tests/test_memory_inject.py`

**Interfaces:**
- Consumes: `MemoryStore.pinned/search_facts/recent/settings` (Tasks 2–3), `kira.types.Message`.
- Produces:
  - `BLOCK_HEADER`, `BLOCK_BUDGET = 1500`, `BLOCK_ITEMS = 12`.
  - `build_block(memory, conversation, *, budget=BLOCK_BUDGET, max_items=BLOCK_ITEMS) -> tuple[str, list[str]]`
  - `inject(messages: list[Message], block: str) -> list[Message]` — a new list, caller's untouched.

> **Corrected after the preflight scan (before execution).** `test_pinned_come_first_then_bm25_then_recent`
> as first drafted asserted `"coffee" not in block`, but the spec's selection order is "pinned → BM25
> matches for the last user message → recently used non-pinned (**fills the remainder**)", so the
> unrelated coffee note is *supposed* to be included. The assertion now checks tier order —
> `block.index("pnpm") < block.index("coffee")` — which is what the test's own name claims and would
> catch a reversed merge.
>
> **Corrected during execution (commit 5f9ed75, corrected before review).** `take()` below truncated
> *any* line that overflowed the remaining room. The spec (§6, selection order) says otherwise: "A
> memory longer than the remaining budget is included only if it fits whole; a memory longer than the
> whole budget is truncated at a word boundary and marked with `…`." The shipped `take()` skips such
> a fact untouched, and truncates only a fact too long to fit even an empty block — at a word
> boundary, adding the ellipsis on top. Two tests below pin both halves.

- [ ] **Step 1: Write the failing tests**

```python
# kira-engine/tests/test_memory_inject.py
from __future__ import annotations

import pytest

from kira.memory import BLOCK_HEADER, MemoryStore, build_block, inject
from kira.store import Store
from kira.types import Message


@pytest.fixture
def memory(tmp_path):
    return MemoryStore(Store(tmp_path / "kira.db"))


# A block shaped like the real one, for the merge tests that care about placement, not content.
BLOCK = BLOCK_HEADER + "\n- [fact] the user is left-handed"


def user(text):
    return [Message(role="user", content=text)]


def test_nothing_in_memory_adds_nothing(memory):
    block, used = build_block(memory, user("hello"))
    assert (block, used) == ("", [])


def test_inject_with_an_empty_block_is_a_copy(memory):
    messages = user("hello")
    out = inject(messages, "")
    assert [m.content for m in out] == ["hello"] and out is not messages


def test_inject_merges_into_an_existing_system_message_and_prepends_one_otherwise():
    merge = inject([Message(role="system", content="be brief"), Message(role="user", content="hi")], BLOCK)
    assert merge[0].role == "system" and merge[0].content.startswith("be brief\n\n")
    assert len(merge) == 2
    prepend = inject([Message(role="user", content="hi")], BLOCK)
    assert prepend[0].role == "system" and prepend[0].content == BLOCK
    assert len(prepend) == 2


def test_pinned_come_first_then_bm25_then_recent(memory):
    pinned = memory.add("the user is left-handed", pinned=True)
    memory.add("the user prefers pnpm for package management")
    memory.add("an unrelated note about coffee")
    block, used = build_block(memory, user("which package manager do I use"))
    assert used[0] == pinned["id"]
    assert "pnpm" in block and BLOCK_HEADER in block
    assert block.index("pnpm") < block.index("coffee")  # BM25 matches rank above the recently-used remainder


def test_the_item_cap_and_the_character_budget_both_hold(memory):
    for index in range(20):
        memory.add(f"fact number {index} " + "x" * 200)
    block, used = build_block(memory, user("fact"), budget=500, max_items=3)
    assert len(used) <= 3 and len(block) <= 500


def test_an_oversized_single_memory_is_truncated_and_marked(memory):
    memory.add("x" * 900, pinned=True)
    block, used = build_block(memory, user("hi"), budget=200)
    assert used and "…" in block and len(block) <= 200


def test_a_memory_that_does_not_fit_whole_is_skipped_not_mangled(memory):
    memory.add("x" * 120, pinned=True)  # longer than what remains once the header is paid for
    small = memory.add("short fact", pinned=True)  # pinned newest-first, so this one is offered first
    block, used = build_block(memory, user("hi"), budget=200)
    assert used == [small["id"]]
    assert "xxxx" not in block and "…" not in block


def test_an_oversized_memory_is_cut_at_a_word_boundary(memory):
    # `"words " * 120`, not `"word " * 120`: at budget 200 the latter's cut lands *on* a space by
    # arithmetic coincidence and passes even against a naive slice.
    memory.add("words " * 120, pinned=True)
    block, used = build_block(memory, user("hi"), budget=200)
    (line,) = block.split("\n", 1)[1:]
    assert used and line.endswith("words…") and len(block) <= 200


def test_inject_is_off_adds_nothing(memory):
    memory.add("a fact")
    memory.set_settings({"inject": False})
    assert build_block(memory, user("fact")) == ("", [])


def test_the_conversation_list_is_not_mutated(memory):
    memory.add("a fact")
    conversation = [Message(role="user", content="fact")]
    before = list(conversation)
    block, _ = build_block(memory, conversation)
    inject(conversation, block)
    assert conversation == before and conversation[0].content == "fact"
```

- [ ] **Step 2: Run and watch them fail**

Run: `cd kira-engine && .venv/Scripts/python.exe -m pytest -q tests/test_memory_inject.py`
Expected: FAIL — `ImportError: cannot import name 'build_block'`.

- [ ] **Step 3: Implement**

```python
BLOCK_HEADER = "Known about the user (from your local memory; may be stale — say so if unsure):"
BLOCK_BUDGET = 1500
BLOCK_ITEMS = 12


def build_block(
    memory: MemoryStore,
    conversation: list[Message],
    *,
    budget: int = BLOCK_BUDGET,
    max_items: int = BLOCK_ITEMS,
) -> tuple[str, list[str]]:
    """The turn's memory block and the ids it used. No model call, no classifier, no surprises.

    Pinned first, then BM25 matches for the last user message, then whatever was used most recently —
    each memory once, inside both the item cap and the character budget. Nothing is summarised: a
    summary would be a second model, and a wrong one is invisible.
    """
    if not memory.settings()["inject"]:
        return "", []
    lines: list[str] = []
    used: list[str] = []
    seen: set[str] = set()
    # The header is part of the block, so it is part of what the budget has to pay for.
    spent = len(BLOCK_HEADER) + 1

    def take(items: list[dict[str, Any]]) -> None:
        nonlocal spent
        for item in items:
            if len(lines) >= max_items:
                return
            if item["id"] in seen:
                continue
            seen.add(item["id"])
            line = f"- [{item['kind']}] {item['text']}"
            room = budget - spent - 1
            if len(line) > room:
                if len(line) <= budget:
                    continue  # it fits whole in an empty block, so it is skipped, never mangled
                if room < 40:
                    continue
                line = line[: room - 1]
                # A word boundary only counts when it keeps most of the slice: space-free text (a
                # CJK run, a pasted URL) has one space and it sits in the `- [fact] ` prefix.
                head = line.rsplit(" ", 1)[0] if " " in line else line
                if len(head) < len(line) - 24:
                    head = line
                line = head.rstrip() + "…"
            lines.append(line)
            used.append(item["id"])
            spent += len(line) + 1

    take(memory.pinned(4))
    if len(lines) < max_items:
        # A vision-only turn has `content == ""`, so the last user message can carry no words at all;
        # falling back to the newest user message that does have text is a better BM25 query than none.
        last_user = next(
            (m.content for m in reversed(conversation) if m.role == "user" and m.content), ""
        )
        if last_user:
            take(memory.search_facts(last_user, BLOCK_ITEMS))
    if len(lines) < max_items:
        take(memory.recent(BLOCK_ITEMS))
    if not lines:
        return "", []
    return f"{BLOCK_HEADER}\n" + "\n".join(lines), used


def inject(messages: list[Message], block: str) -> list[Message]:
    """A new list: the caller's conversation is what gets persisted, and it must stay what was said."""
    out = list(messages)
    if not block:
        return out
    if out and out[0].role == "system":
        first = out[0]
        content = f"{first.content}\n\n{block}" if first.content else block
        out[0] = Message(
            role="system",
            content=content,
            tool_calls=list(first.tool_calls),
            tool_call_id=first.tool_call_id,
            name=first.name,
            images=list(first.images),
        )
    else:
        out.insert(0, Message(role="system", content=block))
    return out
```

- [ ] **Step 4: Run the tests**

Run: `cd kira-engine && .venv/Scripts/python.exe -m pytest -q tests/test_memory_inject.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add kira-engine/src/kira/memory.py kira-engine/tests/test_memory_inject.py
git -c user.name="Kira" -c user.email="kira@localhost" commit -m "memory: a deterministic bounded block and a non-mutating merge into the system message"
```

---

### Task 6: Wire injection into chat and a call; `mark_used` only after a sent turn

**Files:**
- Modify: `kira-engine/src/kira/app.py:152-250, 391-411, 457-600`
- Modify: `kira-engine/src/kira/voice/call.py:236-294`
- Test: `kira-engine/tests/test_memory_inject.py` (append), `kira-engine/tests/test_voice_call.py` (append)

**Interfaces:**
- Consumes: `MemoryStore`, `build_block`, `inject` (Tasks 2, 5).
- Produces: `Engine.memory: MemoryStore`; `app.PreparedTurn(run, session_id, memory_used, user_text)`;
  `build_run(...) -> PreparedTurn`. Every chat turn and every call turn carries the block.

- [ ] **Step 1: Write the failing tests**

```python
# appended to kira-engine/tests/test_memory_inject.py
from kira.app import create_app  # noqa: E402
from kira.config import Config  # noqa: E402
from kira.vault import Vault  # noqa: E402
from conftest import TEST_TOKEN, openai_text_chunks, ok  # noqa: E402


@pytest.mark.anyio
async def test_the_turn_sent_to_the_provider_carries_the_block_and_the_stored_user_row_does_not(
    harness,
):
    harness.engine.memory.add("the user prefers pnpm", pinned=True)
    harness.script.queue("https://fast1.invalid/v1", ok(openai_text_chunks("ok")))

    response = await harness.api.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "which package manager"}]},
        headers=harness.auth,
    )
    assert response.status_code == 200
    sent = harness.script.body_for("fast1")
    assert sent["messages"][0]["role"] == "system"
    assert "the user prefers pnpm" in sent["messages"][0]["content"]

    session_id = response.json()["session_id"]
    stored = harness.store.messages(session_id)
    assert [row["role"] for row in stored] == ["user", "assistant"]
    assert "prefers pnpm" not in str([row["content"] for row in stored])


@pytest.mark.anyio
async def test_a_served_turn_marks_what_it_used_and_a_failed_one_does_not(harness):
    memory = harness.engine.memory
    item = memory.add("the user prefers pnpm", pinned=True)

    harness.script.queue("https://fast1.invalid/v1", ok(openai_text_chunks("ok")))
    ok_turn = await harness.api.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "hi"}]},
        headers=harness.auth,
    )
    assert ok_turn.status_code == 200
    assert memory.get(item["id"])["use_count"] == 1

    harness.script.queue(
        "https://fast1.invalid/v1", httpx.Response(500, json={"error": {"message": "boom"}})
    )
    harness.script.queue(
        "https://fast2.invalid/v1", httpx.Response(500, json={"error": {"message": "boom"}})
    )
    harness.script.queue("https://big.invalid/v1", httpx.Response(500, json={"error": {"message": "boom"}}))
    harness.script.queue("https://ant.invalid", httpx.Response(500, json={"message": "boom"}))
    harness.script.queue("https://gem.invalid", httpx.Response(500, json={"message": "boom"}))
    # `Scripted` answers any unqueued host with a 500, so these queues are belt-and-braces; the turn
    # must fail at every candidate either way.
    failed = await harness.api.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "hi"}]},
        headers=harness.auth,
    )
    assert failed.status_code in (502, 503)
    assert memory.get(item["id"])["use_count"] == 1  # unchanged
```

```python
# appended to kira-engine/tests/test_voice_call.py — the file's own harness, not a new fixture:
# `opened(harness, [])`, speech frames on the socket, `wait_for(socket, "turn_done")`.

def test_a_call_turn_carries_the_memory_block(harness):
    harness.engine.memory.add("the user is learning Spanish", pinned=True)
    harness.script.queue("https://fast1.invalid/v1", ok(openai_text_chunks("hola")))
    harness.engine.voice = Stack(FakeStt(), FakeTts())

    async def scenario():
        socket, call = opened(harness, [])
        task = asyncio.create_task(call.run())
        await wait_for(socket, "ready")
        for frame in speech():
            socket.inbox.put_nowait(frame)
        await wait_for(socket, "turn_done")
        socket.inbox.put_nowait({"type": "close"})
        await asyncio.wait_for(task, 2.0)

    asyncio.run(scenario())
    sent = harness.script.body_for("fast1")
    assert sent["messages"][0]["role"] == "system"  # merged into the call's own system prompt
    assert "learning Spanish" in sent["messages"][0]["content"]
```

> **Corrected after the preflight scan (before execution).** Two defects in this task's text, fixed here.
> (1) The voice test as drafted called `vcall.say("hello")` on a `vcall` fixture that no file defines;
> `test_voice_call.py` drives every scenario through `opened(...)` + socket frames + `wait_for`, which is
> what the test above now does. (2) "Both success paths gain `mark_used`" was too broad: the
> non-streaming route answers 200 with `status == "failed"` when the run produced neither text nor tool
> calls, and counting memory "used" on an answer nobody saw is exactly what the spec's "after a
> successful response is sent" rule forbids. `mark_used` therefore runs only when the same status the
> row is labelled with is not `"failed"`.

- [ ] **Step 2: Run and watch them fail**

Run: `cd kira-engine && .venv/Scripts/python.exe -m pytest -q tests/test_memory_inject.py -k provider`
Expected: FAIL — the first system message is absent from the recorded request body.

- [ ] **Step 3: Implement the wiring**

`app.py`, imports gain `from dataclasses import dataclass` and
`from .memory import MemoryStore, build_block, inject`. Task 7 adds `register_memory_tools` to that
import; this task needs only the store.

In `Engine.__init__`, after `self.workspace` exists and before plugins load:

```python
        self.memory = MemoryStore(self.store)
```

`PreparedTurn` is a module-level dataclass (next to `WireMessage`/`ChatRequest`); `build_run` stays
where it is, nested in `create_app`:

```python
@dataclass
class PreparedTurn:
    """One request, once: the run, the session it belongs to, and what memory went into it."""

    run: AgentRun
    session_id: str
    memory_used: list[str]
    user_text: str
```

```python
    def build_run(body: ChatRequest, *, streaming: bool) -> PreparedTurn:
        plan = engine.router.plan(model=body.model, mode=body.mode, provider=body.provider)
        session_id = engine.store.create_session(plan.mode, body.session_id)
        messages = to_internal(body.messages)
        last_user = next((m for m in reversed(messages) if m.role == "user"), None)
        user_text = last_user.content if last_user is not None else ""
        if last_user is not None and last_user.content:
            engine.store.add_message(session_id, "user", last_user.content)
        block, memory_used = build_block(engine.memory, messages)
        run = AgentRun(
            router=engine.router,
            tools=engine.tools if body.tools_enabled else ToolRegistry(),
            plan=plan,
            messages=inject(messages, block),
            max_steps=cfg.max_agent_steps,
            temperature=body.temperature,
            max_output_tokens=body.max_tokens,
            approvals=engine.approvals if streaming else None,
            checkpoints=engine.checkpoints,
            policies=engine.store.tool_policies(),
            session_id=session_id,
        )
        return PreparedTurn(run, session_id, memory_used, user_text)
```

The one call site becomes:

```python
        turn = build_run(body, streaming=body.stream)
        run, session_id = turn.run, turn.session_id
```

and both success paths gain, after the assistant row is written:

```python
                    assistant_row(session_id, run, run.state.status)
                    if run.state.status != "failed":
                        engine.memory.mark_used(turn.memory_used)
```

(non-streaming: `message_id = assistant_row(...)`, then the same guarded `mark_used` using the `status`
local the row was labelled with). A turn labelled `failed` produced nothing; counting its memories as
used would inflate the count for an answer nobody saw.

`voice/call.py`, in `_turn` after `request_messages` is built:

```python
            block, self.memory_used = build_block(engine.memory, [user])
            request_messages = inject(
                [Message(role="system", content=VOICE_SYSTEM_PROMPT), *self.history[-HISTORY_TURNS:], user],
                block,
            )
```

and after `engine.persist_assistant_row(...)` on the success path:
`engine.memory.mark_used(self.memory_used)`. `VoiceCall.__init__` gains `self.memory_used: list[str] = []`
and imports `build_block, inject` from `..memory`.

- [ ] **Step 4: Run the engine suite plus the client suite (the contract did not change)**

Run: `cd kira-engine && .venv/Scripts/python.exe -m pytest -q`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add kira-engine/src/kira/app.py kira-engine/src/kira/voice/call.py \
        kira-engine/tests/test_memory_inject.py kira-engine/tests/test_voice_call.py
git -c user.name="Kira" -c user.email="kira@localhost" commit -m "memory: every chat and call turn carries a bounded block; usage is counted only after it is served"
```

---

### Task 7: `recall` and `remember` tools, and capture as a live switch

**Files:**
- Modify: `kira-engine/src/kira/tools.py` (add `ToolRegistry.unregister`)
- Modify: `kira-engine/src/kira/memory.py` (add `register_memory_tools`, `register_recall_tool`,
  `register_remember_tool`)
- Modify: `kira-engine/src/kira/app.py` (`Engine.sync_memory_tools`)
- Test: `kira-engine/tests/test_memory_tools.py`

**Interfaces:**
- Consumes: `MemoryStore.search_facts/search_history/find_duplicate/add/settings`, `ToolRegistry`,
  `ToolDef` (Tasks 2–4).
- Produces:
  - `ToolRegistry.unregister(name) -> bool`
  - `register_recall_tool(registry, memory)`, `register_remember_tool(registry, memory)`,
    `register_memory_tools(registry, memory)`
  - `Engine.sync_memory_tools() -> None` — idempotent; `remember` present iff `capture != "off"`.

- [ ] **Step 1: Write the failing tests**

```python
# kira-engine/tests/test_memory_tools.py
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
```

- [ ] **Step 2: Run and watch them fail**

Run: `cd kira-engine && .venv/Scripts/python.exe -m pytest -q tests/test_memory_tools.py`
Expected: FAIL — no `register_memory_tools`.

- [ ] **Step 3: Implement**

`tools.py`, inside `ToolRegistry`:

```python
    def unregister(self, name: str) -> bool:
        """Remove one tool. Used when a setting makes a tool impossible to call, not for plugins."""
        return self._tools.pop(name, None) is not None
```

`memory.py`, whose imports gain `from .tools import ToolDef` (no cycle — `tools.py` imports neither
`memory` nor `app`):

```python
def _limit(value: Any, default: int, low: int, high: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("limit must be an integer")
    return max(low, min(high, value))


def register_recall_tool(registry, memory: MemoryStore) -> None:
    def recall(args: dict) -> str:
        query = args.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a non-empty string")
        limit = _limit(args.get("limit"), 8, 1, 20)
        facts = memory.search_facts(query, limit)
        hits = memory.search_history(query, limit)
        lines = [
            f"[{_day(item['created_at'])}] memory ({item['kind']}) {item['text']}" for item in facts
        ]
        lines += [
            f"[{_day(hit['created_at'])}] {hit['role']} (session {hit['session_id']}) {hit['snippet']}"
            for hit in hits
        ]
        return "\n".join(lines) if lines else "nothing in memory matches that"

    registry.register(
        ToolDef(
            name="recall",
            description=(
                "Search the user's local memory: saved facts and past conversation text. "
                "Every session is searched, including this one."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "words to look for"},
                    "limit": {"type": "integer", "default": 8, "minimum": 1, "maximum": 20},
                },
                "required": ["query"],
            },
            handler=recall,
            risk="read",
            default_policy="allow",
            summary=lambda a: str(a.get("query", ""))[:80],
        )
    )


def register_remember_tool(registry, memory: MemoryStore) -> None:
    def remember(args: dict) -> str:
        if memory.settings()["capture"] == "off":
            raise ValueError("memory capture is off; the user has not enabled remembering")
        text = args.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("text must be a non-empty string")
        kind = args.get("kind", "fact") or "fact"
        if kind not in KINDS:
            raise ValueError(f"kind must be one of {list(KINDS)}")
        existing = memory.find_duplicate(text)
        if existing is not None:
            return f"already remembered: {existing['text']}"
        item = memory.add(text, kind=kind, origin="tool")
        return f"remembered {item['id']}: {item['text']}"

    registry.register(
        ToolDef(
            name="remember",
            description=(
                "Keep one durable fact or preference about the user in local memory. "
                "Visible and forgettable on the Memory screen."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "one sentence worth keeping"},
                    "kind": {"type": "string", "enum": list(KINDS), "default": "fact"},
                },
                "required": ["text"],
            },
            handler=remember,
            risk="write",
            default_policy="allow",
            summary=lambda a: str(a.get("text", ""))[:60],
        )
    )


def register_memory_tools(registry, memory: MemoryStore) -> None:
    register_recall_tool(registry, memory)
    if memory.settings()["capture"] != "off":
        register_remember_tool(registry, memory)


def _day(when: float) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(when))
```

`app.py`, `Engine`:

```python
    def sync_memory_tools(self) -> None:
        """`remember` exists only while capture is on: a model cannot call what it is not told about."""
        if self.memory.settings()["capture"] == "off":
            self.tools.unregister("remember")
        elif self.tools.get("remember") is None:
            register_remember_tool(self.tools, self.memory)
```

`app.py`: the existing `from .memory import MemoryStore, build_block, inject` line from Task 6 gains
`register_memory_tools, register_remember_tool`, and `Engine.__init__` gains the call right after
`self.memory = MemoryStore(self.store)`:

```python
        self.memory = MemoryStore(self.store)
        register_memory_tools(self.tools, self.memory)
```

`register_memory_tools` already skips `remember` when capture is off, so a fresh engine starts in the
right state and `sync_memory_tools` only has to handle a change made at runtime.

- [ ] **Step 4: Run the tests**

Run: `cd kira-engine && .venv/Scripts/python.exe -m pytest -q tests/test_memory_tools.py tests/test_tools_real.py`
Expected: PASS. `test_tools_real.py` still sees exactly its own builtins.

Then the whole engine suite once — `Engine.__init__` now registers two more tools, so every test that
boots a `Harness` sees a longer schema list:

Run: `cd kira-engine && .venv/Scripts/python.exe -m pytest -q`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add kira-engine/src/kira/tools.py kira-engine/src/kira/memory.py kira-engine/src/kira/app.py \
        kira-engine/tests/test_memory_tools.py
git -c user.name="Kira" -c user.email="kira@localhost" commit -m "memory: recall and remember tools, with capture able to remove remember at runtime"
```

---

### Task 8: Opt-in extraction — one capped call, ledgered, never fatal

**Files:**
- Modify: `kira-engine/src/kira/memory.py` (`extract_facts`, `_parse_facts`, `MemoryStore.add_auto`)
- Modify: `kira-engine/src/kira/app.py` (call it on a completed chat turn only)
- Test: `kira-engine/tests/test_memory_extract.py`

**Interfaces:**
- Consumes: `engine.router`, `engine.store.record_usage`, `MemoryStore` (Tasks 2–3).
- Produces:
  - `EXTRACT_PROMPT`, `EXTRACT_MAX_OUTPUT_TOKENS = 200`, `EXTRACT_MAX_FACTS = 3`.
  - `async extract_facts(engine, *, session_id, user_text, answer_text, memory) -> list[dict]`
  - `MemoryStore.add_auto(facts: list[str], *, session_id, tokens_spent) -> list[dict]`

- [ ] **Step 1: Write the failing tests**

```python
# kira-engine/tests/test_memory_extract.py
from __future__ import annotations

import pytest

from conftest import openai_text_chunks, ok


def facts_turn(text: str):
    return ok(openai_text_chunks(text, usage=True))


@pytest.mark.anyio
async def test_extraction_is_off_by_default_and_sends_no_second_call(harness):
    harness.script.queue("https://fast1.invalid/v1", ok(openai_text_chunks("hello")))
    response = await harness.api.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "I prefer pnpm"}]},
        headers=harness.auth,
    )
    assert response.status_code == 200
    assert sum(1 for call in harness.script.calls if "chat/completions" in call) == 1
    assert harness.engine.memory.list()[1] == 0


@pytest.mark.anyio
async def test_extraction_on_writes_labelled_facts_and_ledgers_the_call(harness):
    harness.engine.memory.set_settings({"extract": True})
    harness.script.queue("https://fast1.invalid/v1", ok(openai_text_chunks("hello")))
    harness.script.queue(
        "https://fast1.invalid/v1", facts_turn("I prefer pnpm.\n- Works on Windows.")
    )
    response = await harness.api.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "I prefer pnpm and I am on Windows"}]},
        headers=harness.auth,
    )
    assert response.status_code == 200
    rows, total = harness.engine.memory.list()
    assert total == 2
    assert {row["origin"] for row in rows} == {"auto"}
    assert all(row["tokens_spent"] > 0 for row in rows)
    month = harness.store.usage_for_month()[1]
    assert month["fast_one"] > 22  # the turn's 11+5 plus the extraction's own tokens


@pytest.mark.anyio
async def test_extraction_dedupes_and_caps_at_three(harness):
    harness.engine.memory.set_settings({"extract": True})
    harness.engine.memory.add("I prefer pnpm")
    harness.script.queue("https://fast1.invalid/v1", ok(openai_text_chunks("hello")))
    harness.script.queue(
        "https://fast1.invalid/v1",
        facts_turn("i prefer pnpm.\ndelta\necho\nfoxtrot\ngolf"),
    )
    await harness.api.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "hello"}]},
        headers=harness.auth,
    )
    texts = [row["text"] for row in harness.engine.memory.list(limit=50)[0]]
    assert len(texts) == 4  # the pre-existing one plus three new, never four
    assert "i prefer pnpm." not in texts


@pytest.mark.anyio
async def test_an_extraction_failure_never_fails_the_turn(harness):
    harness.engine.memory.set_settings({"extract": True})
    harness.script.queue("https://fast1.invalid/v1", ok(openai_text_chunks("hello")))
    # No second scripted response: the script answers 500 "no scripted response for fast1".
    response = await harness.api.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "I like tea"}]},
        headers=harness.auth,
    )
    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "hello"
    assert harness.engine.memory.list()[1] == 0


@pytest.mark.anyio
async def test_none_and_short_lines_are_dropped(harness):
    harness.engine.memory.set_settings({"extract": True})
    harness.script.queue("https://fast1.invalid/v1", ok(openai_text_chunks("hello")))
    harness.script.queue("https://fast1.invalid/v1", facts_turn("NONE"))
    await harness.api.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "just chatting"}]},
        headers=harness.auth,
    )
    assert harness.engine.memory.list()[1] == 0


def test_parse_drops_bullets_numbering_and_none():
    from kira.memory import _parse_facts

    assert _parse_facts("NONE") == []
    assert _parse_facts("  - one fact\n2. another fact\n•third fact") == [
        "one fact", "another fact", "third fact",
    ]
    assert _parse_facts("a\nbb\nccc\nddd") == ["ccc", "ddd"]
```

- [ ] **Step 2: Run and watch them fail**

Run: `cd kira-engine && .venv/Scripts/python.exe -m pytest -q tests/test_memory_extract.py`
Expected: FAIL — one request recorded, not two; `_parse_facts` missing.

- [ ] **Step 3: Implement**

```python
EXTRACT_PROMPT = (
    "You maintain a local memory of durable facts about the user. Read one exchange and list zero to "
    "three durable facts, one per line, no numbering, no commentary. A durable fact is a stable "
    "preference, constraint or piece of context — not a question, not a task, not small talk. "
    "If there is nothing durable, reply exactly NONE."
)
EXTRACT_MAX_OUTPUT_TOKENS = 200
EXTRACT_MAX_FACTS = 3


def _parse_facts(raw: str) -> list[str]:
    """Every line that could be a fact, cleaned. The cap belongs after dedupe, in `add_auto`."""
    facts: list[str] = []
    for line in raw.splitlines():
        clean = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", line).strip()
        # Three characters is the floor this task's own boundary test pins (`a`, `bb` out; `ccc` in).
        if not clean or clean.upper() == "NONE" or len(clean) < 3 or len(clean) > 500:
            continue
        facts.append(clean)
    return facts
```

```python
    def add_auto(self, facts: list[str], *, session_id: str | None, tokens_spent: int) -> list[dict]:
        """Dedupe first, then cap: a fact already kept must not eat one of the three new slots."""
        new: list[str] = []
        seen: set[str] = set()
        for fact in facts:
            key = normalise(fact)
            if key in seen or self.find_duplicate(fact) is not None:
                continue
            seen.add(key)
            new.append(fact)
            if len(new) == EXTRACT_MAX_FACTS:
                break
        if not new:
            return []
        share, extra = divmod(int(tokens_spent), len(new))
        added = []
        for index, fact in enumerate(new):
            added.append(
                self.add(
                    fact,
                    origin="auto",
                    session_id=session_id,
                    tokens_spent=share + (extra if index == 0 else 0),
                )
            )
        return added
```

```python
async def extract_facts(
    engine, *, session_id: str, user_text: str, answer_text: str, memory: MemoryStore
) -> list[dict[str, Any]]:
    """One capped call, only when the user turned it on, and never at the turn's expense.

    The call's own usage is added to the month ledger — extraction is a purchase, and a purchase that
    does not show up in the Overview is the silent spend this project keeps refusing.
    """
    try:
        if not memory.settings()["extract"] or not user_text.strip():
            return []
        plan = engine.router.plan()
        request = GenRequest(
            model=plan.choices[0].model,
            messages=[
                Message(role="system", content=EXTRACT_PROMPT),
                Message(role="user", content=f"User: {user_text}\nAssistant: {answer_text}"),
            ],
            temperature=0.0,
            max_output_tokens=EXTRACT_MAX_OUTPUT_TOKENS,
        )
        attempt = AttemptState()
        text: list[str] = []
        usage = Usage()
        async for event in engine.router.events(plan, request, attempt):
            if isinstance(event, Delta):
                text.append(event.text)
            elif isinstance(event, Completed):
                usage = event.usage
        raw = "".join(text)
        # A provider that reports nothing must not become a free record: the same labelled
        # four-chars-per-token estimate the agent loop uses stands in. No text, no estimate.
        if usage.input_tokens + usage.output_tokens == 0 and raw:
            usage = _estimate_usage(request.messages, raw)
        # The call is a purchase whether or not the reply parses to a fact, so the ledger write comes
        # before the early return: a bare NONE still burned tokens, and a month report must say so.
        if attempt.served_by:
            engine.store.record_usage(
                attempt.served_by,
                {
                    "input_tokens": usage.input_tokens,
                    "output_tokens": usage.output_tokens,
                    "estimated": usage.estimated,
                },
            )
        facts = _parse_facts(raw)
        if not facts:
            return []
        return memory.add_auto(
            facts, session_id=session_id, tokens_spent=usage.input_tokens + usage.output_tokens
        )
    except Exception as exc:
        # D8 makes non-fatality unconditional: a provider timeout, a malformed stream or a failed
        # ledger write all end the same way — logged, and the turn already sent stands. Broad on
        # purpose: CancelledError derives from BaseException, so a real disconnect still propagates.
        print(
            f"[kira] memory extraction skipped: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return []
```

`_parse_facts` drops a decorated sentinel, not only the bare word — after the length checks:

```python
        # Models decorate the sentinel: NONE., **NONE**, `NONE` are all the same "nothing".
        if re.fullmatch(r"[\W_]*NONE[\W_]*", clean, re.IGNORECASE):
            continue
```

Imports in `memory.py`: `import sys`, `from .errors import ConfigError`, `from .loop import
_estimate_usage`, `from .router import AttemptState`, `from .types import Completed, Delta,
GenRequest, Message, Usage`.

`app.py` streaming path — the `else:` clause is the only addition to the existing generator, and it
sits after the `done` frame, so the answer is never held back by a second call:

```python
                    assistant_row(session_id, run, run.state.status)
                    yield sse(
                        {
                            "type": "done",
                            "id": completion_id,
                            "session_id": session_id,
                            "provider": run.attempt.served_by,
                            "model": run.attempt.served_model,
                            "finish_reason": run.state.finish_reason,
                            "status": run.state.status,
                            "usage": wire_usage(run.state.usage),
                            "provider_chain": run.attempt.chain,
                        }
                    )
                except (KiraError, ProviderCallError) as exc:
                    assistant_row(session_id, run, "interrupted" if run.state.text else "failed")
                    detail = exc.to_dict()["error"] if isinstance(exc, KiraError) else {
                        "code": exc.code,
                        "message": exc.message,
                        "provider": exc.provider,
                    }
                    yield sse({"type": "error", "error": detail, "provider_chain": run.attempt.chain})
                else:
                    if run.state.text:
                        await extract_facts(
                            engine,
                            session_id=session_id,
                            user_text=turn.user_text,
                            answer_text=run.state.text,
                            memory=engine.memory,
                        )
```

Careful: that `try/except/else` sits inside the async generator; `else` runs only when no exception
was raised. The `done` frame has already been sent, so a slow extraction cannot delay the answer on
screen, and a client that disconnects simply does not get mined.

The non-streaming path, after `message_id = assistant_row(...)`:

```python
        if run.state.text:
            await extract_facts(
                engine,
                session_id=session_id,
                user_text=turn.user_text,
                answer_text=run.state.text,
                memory=engine.memory,
            )
```

A call is **not** mined: it is transcribed speech, noisier than typed text, and the spec keeps the
purchase to the surface the user can see it on (the chat transcript).

**Corrected during execution (commits 539184b, 85e9efd, c951a55).** Three changes, each recorded in
the ledger:

1. `_parse_facts`' floor is `< 3`, not `< 4`. The brief contradicted itself: its own boundary test
   requires three-character `"ccc"`/`"ddd"` to survive, while the snippet dropped anything under
   four. The test is the pinned contract; the snippet now says `< 3`.
2. The `try` now wraps the *whole* body — settings read, the router call, `_parse_facts`, the
   `record_usage` ledger write and `add_auto` — with `except Exception`. Spec D8 says extraction
   failure "never fails the turn", and the narrow catch left a storage error free to 500 a
   non-streaming turn whose answer had already been persisted. `CancelledError` derives from
   `BaseException`, so a client disconnect still propagates. Two tests pin it:
   `test_a_storage_failure_while_writing_facts_never_fails_the_turn` and
   `test_a_ledger_failure_during_extraction_never_fails_the_turn` (the latter raises only on the
   extraction call — a call carrying `when=` is the turn's own assistant-row ledger write, which
   happens before extraction and must keep succeeding for the test to isolate what it names).
3. The broad catch made `httpx`, `KiraError` and `ProviderCallError` unused in `memory.py`; they are
   gone (c951a55).

**Review round (commit 3bbbf03).** The first review found the ledger write sitting *after* the
`if not facts: return []`, so a reply of `NONE` — a real, billed call — never reached the month
report. Fixed: the ledger write now follows the stream and precedes parsing. Two consequences
pinned at the same time: a provider that reports no usage gets the loop's labelled `_estimate_usage`
fallback (never a silent zero-cost record, and never an estimate when there is no text), and the
stderr line names the exception type. `_parse_facts` also drops decorated sentinels. Five tests
were added (15 in the file). Three minors are parked for the final review: the `estimated` flag
itself is unasserted; `NONE (nothing durable)` in prose still survives the sentinel regex; the
estimate runs inside the same broad `except`, so a hypothetical raise there would skip the ledger.

- [ ] **Step 4: Run the tests**

Run: `cd kira-engine && .venv/Scripts/python.exe -m pytest -q tests/test_memory_extract.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add kira-engine/src/kira/memory.py kira-engine/src/kira/app.py kira-engine/tests/test_memory_extract.py
git -c user.name="Kira" -c user.email="kira@localhost" commit -m "memory: opt-in extraction — one capped call, deduped, ledgered, and never able to fail the turn"
```

---

### Task 9: The eight routes — writes first

**Files:**
- Modify: `kira-engine/src/kira/app.py` (models + routes, after the tools routes)
- Modify: `kira-engine/src/kira/contracts.py` (four paths + the schemas they reference)
- Test: `kira-engine/tests/test_memory_api.py`

**Interfaces:**
- Consumes: `MemoryStore` (Tasks 2–3), `require_confirm`, `require_token`.
- Produces routes
  `GET/POST /v1/kira/memory`, `PATCH/DELETE /v1/kira/memory/{memory_id}`,
  `GET /v1/kira/memory/search`, `GET /v1/kira/memory/export`,
  `GET/PUT /v1/kira/memory/settings`.

- [ ] **Step 1: Write the failing tests**

```python
# kira-engine/tests/test_memory_api.py
from __future__ import annotations

import pytest


@pytest.mark.anyio
async def test_memory_reads_need_a_token_and_writes_need_the_confirm_secret(harness):
    assert (await harness.api.get("/v1/kira/memory")).status_code == 401
    assert (await harness.api.post("/v1/kira/memory", json={"text": "x"})).status_code == 401
    unconfirmed = await harness.api.post(
        "/v1/kira/memory", json={"text": "x"}, headers=harness.auth
    )
    assert unconfirmed.status_code == 401
    assert "confirm" in unconfirmed.json()["error"]["message"]


@pytest.mark.anyio
async def test_add_list_patch_and_delete_round_trip(harness):
    created = await harness.api.post(
        "/v1/kira/memory",
        json={"text": "I prefer pnpm", "kind": "preference", "pinned": True},
        headers=harness.signed,
    )
    assert created.status_code == 200
    item = created.json()
    assert item["kind"] == "preference" and item["pinned"] is True

    listed = await harness.api.get("/v1/kira/memory", headers=harness.auth)
    body = listed.json()
    assert body["total"] == 1 and body["memories"][0]["id"] == item["id"]
    assert body["settings"]["tokenizer"] == "trigram"

    patched = await harness.api.patch(
        f"/v1/kira/memory/{item['id']}", json={"text": "I prefer pnpm everywhere"}, headers=harness.signed
    )
    assert patched.status_code == 200 and patched.json()["text"].endswith("everywhere")

    deleted = await harness.api.delete(f"/v1/kira/memory/{item['id']}", headers=harness.signed)
    assert deleted.status_code == 200 and deleted.json() == {"deleted": item["id"]}
    assert (await harness.api.get("/v1/kira/memory", headers=harness.auth)).json()["total"] == 0


@pytest.mark.anyio
async def test_bad_bodies_are_config_error_400_and_unknown_ids_are_404(harness):
    for body in (
        {"text": ""},
        {"text": "   "},
        {"text": "x" * 2001},
        {"text": "fine", "kind": "gossip"},
        {"text": "fine", "surprise": 1},
    ):
        response = await harness.api.post("/v1/kira/memory", json=body, headers=harness.signed)
        assert response.status_code == 400, body
        assert response.json()["error"]["code"] == "config_error"
    missing = await harness.api.patch(
        "/v1/kira/memory/nope", json={"text": "x"}, headers=harness.signed
    )
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "not_found"
    assert (
        await harness.api.delete("/v1/kira/memory/nope", headers=harness.signed)
    ).status_code == 404
```

- [ ] **Step 2: Run and watch them fail**

Run: `cd kira-engine && .venv/Scripts/python.exe -m pytest -q tests/test_memory_api.py`
Expected: FAIL — 404 from the version middleware (`/v1/kira/memory` is not routed yet).

- [ ] **Step 3: Implement the models and the fact routes**

```python
class MemoryWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    kind: str = "fact"
    pinned: bool = False

    @field_validator("text")
    @classmethod
    def _text(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("text must not be empty")
        if len(clean) > MAX_TEXT:
            raise ValueError(f"text is limited to {MAX_TEXT} characters")
        return clean

    @field_validator("kind")
    @classmethod
    def _kind(cls, value: str) -> str:
        if value not in KINDS:
            raise ValueError(f"kind must be one of {list(KINDS)}")
        return value


class MemoryPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str | None = None
    kind: str | None = None
    pinned: bool | None = None

    # Written out rather than borrowed from MemoryWrite: a shared classmethod validator fights the
    # decorator in pydantic v2, and four duplicated lines are cheaper than a framework trick.
    @field_validator("text")
    @classmethod
    def _text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        clean = value.strip()
        if not clean:
            raise ValueError("text must not be empty")
        if len(clean) > MAX_TEXT:
            raise ValueError(f"text is limited to {MAX_TEXT} characters")
        return clean

    @field_validator("kind")
    @classmethod
    def _kind(cls, value: str | None) -> str | None:
        if value is not None and value not in KINDS:
            raise ValueError(f"kind must be one of {list(KINDS)}")
        return value
```

Both `ValueError`s inside a validator become a 400 `config_error` through `_validation_handler`; the
extra field becomes one too. The 404s are `JSONResponse`s like the existing checkpoint/approval ones,
so each route returns early instead:

```python
    def not_found() -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"error": {"code": "not_found", "message": "unknown memory", "status": 404,
                               "retryable": False}},
        )

    @app.get(f"{API_PREFIX}/kira/memory", dependencies=[auth])
    async def memory_list(
        query: str | None = None,
        kind: str | None = None,
        pinned: bool | None = None,
        limit: int = 50,
    ) -> dict:
        rows, total = engine.memory.list(
            query=query, kind=kind, pinned=pinned, limit=max(1, min(200, limit))
        )
        return {"memories": rows, "total": total, "settings": engine.memory.settings()}

    @app.post(f"{API_PREFIX}/kira/memory", dependencies=[auth, confirm])
    async def memory_add(body: MemoryWrite) -> dict:
        return engine.memory.add(body.text, kind=body.kind, pinned=body.pinned)

    @app.patch(f"{API_PREFIX}/kira/memory/{{memory_id}}", dependencies=[auth, confirm])
    async def memory_patch(memory_id: str, body: MemoryPatch) -> Any:
        patch = body.model_dump(exclude_none=True)
        item = engine.memory.update(memory_id, patch)
        return not_found() if item is None else item

    @app.delete(f"{API_PREFIX}/kira/memory/{{memory_id}}", dependencies=[auth, confirm])
    async def memory_delete(memory_id: str) -> Any:
        return {"deleted": memory_id} if engine.memory.delete(memory_id) else not_found()
```

Imports: `ConfigDict` from pydantic; `KINDS` and `MAX_TEXT` join the `.memory` import.

Read carefully: Starlette walks routes in declaration order and prefers a full path+method match to an
earlier path-only one, so a same-method literal must be declared **before** `{memory_id}`. This design
has no `GET /kira/memory/{memory_id}`, so today's `PATCH`/`DELETE` cannot swallow `/search` and
`/export` — keep the literals first anyway: the day a single-fact `GET` is added, a search that
silently answered `404 unknown memory` is exactly the failure this note exists to prevent.

**The contract is part of this task, not Task 11.** `tests/test_versioning.py` requires every `/v1`
route to appear in `OPENAPI["paths"]`, so a route that lands without its contract leaves the suite
red for two tasks. The path entries below are the exact text Task 11 lists; take them from there and
add the six schemas they reference (`MemoryItem`, `MemoryList`, `MemoryWrite`, `MemoryPatch`,
`MemorySettings`, `MemoryDeleted`) in the same commit. Task 10 does the same for its four routes and
its four schemas; Task 11 then adds the TS mirror, the client methods, the fake-engine routes and the
regenerated artifacts against a contract that is already complete.

- [ ] **Step 4: Add the four fact rows to the README endpoint table**

`test_docs_match_engine` compares the table against the live route table in both directions, so the
rows land with the routes, not three tasks later. The table carries the method and path inside the
first cell's backticks; put these next to the tools rows, in the same voice:

```markdown
| `GET /v1/kira/memory` | bearer | saved facts with their kind, origin, pin and use count, plus the three switches and the tokenizer in use |
| `POST /v1/kira/memory` | bearer + confirm | keep one fact (`text` ≤ 2 000 chars, `kind` one of `fact` / `preference` / `note`) |
| `PATCH /v1/kira/memory/{id}` | bearer + confirm | edit text, kind or pin; an unknown id is 404 |
| `DELETE /v1/kira/memory/{id}` | bearer + confirm | forget one fact — the index row goes with it |
```

- [ ] **Step 5: Run the full engine suite**

Run: `cd kira-engine && .venv/Scripts/python.exe -m pytest -q`
Expected: all green, including `test_docs_match_engine`. (The token test in `test_memory_api.py` reads
`settings.tokenizer` from the list response, so it is green once the route answers.)

- [ ] **Step 6: Commit**

```bash
git add kira-engine/src/kira/app.py kira-engine/src/kira/contracts.py \
        kira-engine/tests/test_memory_api.py README.md
git -c user.name="Kira" -c user.email="kira@localhost" commit -m "memory: the fact routes — confirm-gated writes, 400 for bad bodies, 404 for unknown ids"
```

**Corrected during execution (commits dcdf4a2, 7280c7f).** The implementer hit the scan's missed
row: the versioning gate compares every registered `/v1` route against `OPENAPI["paths"]` in both
directions, so the plan's "contract in Task 11" left the suite red from Task 9 through Task 10 — the
same defect the README ruling fixed. The six schemas and both path entries now land here (7280c7f),
`contracts.py` is in the commit list, and Task 11 is re-scoped to the mirror, the client and the
regenerated artifacts. Full suite after the contract landed: 450 passed, 1 skipped.

**Review round (commits 0a6debd, f01549a).** The reviewer kept spec compliance at PASS and asked for
six tightenings, all shipped: `_memory_write()` (mirroring `_approval_write`/`_checkpoint_restore`)
publishes `404 not_found - no memory has ever had that id` on both `{memory_id}` ops; the GET `kind`
filter is validated against its published enum through `ConfigError`; `MemoryWrite`/`MemoryPatch`
carry `additionalProperties: false` and `limit` carries `minimum: 1, maximum: 200`, matching
`extra="forbid"` and `max(1, min(200, limit))`; the round trip proves `{"pinned": false}` really
unpins (read back through the list route, not echoed) and that `{}` is a byte-identical no-op; the
tokenizer assertion reads `engine.memory.tokenizer` instead of hardcoding `"trigram"`; and the
duplicated text validator's comment now names the exact wording difference from `_clean_text` and why
it never reaches the wire. Two rulings came out of it: the tools `PUT` has the same missing-404 gap
and is deliberately not touched (it predates this unit), and a blank `?kind=` means "no filter" —
normalised before the enum check, because every neighbouring read route treats empty as absent and
Task 12's filter row sends an empty selection on first paint. Non-blank values off the enum still 400;
the engine does not trim a half-spelled kind for the client. Suite: 451 passed, 1 skipped.

---

### Task 10: search, export, settings — and the live `remember` switch

**Files:**
- Modify: `kira-engine/src/kira/app.py`
- Modify: `kira-engine/src/kira/contracts.py` (four paths + the schemas they reference)
- Test: `kira-engine/tests/test_memory_api.py` (append)

**Interfaces:**
- Consumes: `search_history`, `export`, `settings`, `set_settings` (Tasks 2, 4), `Engine.sync_memory_tools`
  (Task 7).
- Produces: `GET /v1/kira/memory/search`, `GET /v1/kira/memory/export`,
  `GET /v1/kira/memory/settings`, `PUT /v1/kira/memory/settings` (confirm-gated).

- [ ] **Step 1: Write the failing tests**

```python
# appended to kira-engine/tests/test_memory_api.py

@pytest.mark.anyio
async def test_search_never_500s_on_hostile_input(harness):
    harness.store.create_session("AUTO", "s1")
    harness.store.add_message("s1", "user", "a sentence about eggs")
    for query in ['"', "*", "NEAR(", "a OR b", "col:value", "' OR 1=1 --", "🚀"]:
        response = await harness.api.get("/v1/kira/memory/search", params={"q": query}, headers=harness.auth)
        assert response.status_code == 200, query
        assert isinstance(response.json()["hits"], list)
    hits = await harness.api.get("/v1/kira/memory/search", params={"q": "eggs"}, headers=harness.auth)
    hits = await harness.api.get("/v1/kira/memory/search", params={"q": "eggs"}, headers=harness.auth)
    (hit,) = hits.json()["hits"]
    # NOT `.startswith("a sentence")`: FTS5's snippet() centres the window on the match and elides the
    # head with `…`, so under this build's trigram tokenizer the honest answer is `…nce about [eggs]`.
    # The bracket is the guarantee Task 4's own history test pins, so that is what this asserts.
    assert hit["role"] == "user" and hit["session_id"] == "s1" and "[eggs]" in hit["snippet"]


@pytest.mark.anyio
async def test_an_empty_query_is_an_empty_list_not_an_error(harness):
    response = await harness.api.get("/v1/kira/memory/search", params={"q": ""}, headers=harness.auth)
    assert response.status_code == 200 and response.json() == {"hits": []}


@pytest.mark.anyio
async def test_export_round_trips_and_settings_read_back(harness):
    harness.engine.memory.add("a keepable fact")
    exported = await harness.api.get("/v1/kira/memory/export", headers=harness.auth)
    body = exported.json()
    assert body["version"] == 1 and body["memories"][0]["text"] == "a keepable fact"

    settings = await harness.api.get("/v1/kira/memory/settings", headers=harness.auth)
    assert settings.json() == {
        "inject": True, "capture": "explicit", "extract": False, "tokenizer": "trigram",
    }


@pytest.mark.anyio
async def test_settings_writes_are_gated_validated_and_flip_the_remember_tool(harness):
    assert (
        await harness.api.put("/v1/kira/memory/settings", json={"inject": False}, headers=harness.auth)
    ).status_code == 401
    off = await harness.api.put(
        "/v1/kira/memory/settings", json={"capture": "off"}, headers=harness.signed
    )
    assert off.status_code == 200 and off.json()["capture"] == "off"
    assert harness.engine.tools.get("remember") is None
    back = await harness.api.put(
        "/v1/kira/memory/settings", json={"capture": "explicit"}, headers=harness.signed
    )
    assert back.status_code == 200 and harness.engine.tools.get("remember") is not None

    for body in ({"capture": "sometimes"}, {"tokenizer": "trigram"}, {"inject": "yes"}):
        response = await harness.api.put("/v1/kira/memory/settings", json=body, headers=harness.signed)
        assert response.status_code == 400, body
```

- [ ] **Step 2: Run and watch them fail**

Run: `cd kira-engine && .venv/Scripts/python.exe -m pytest -q tests/test_memory_api.py -k "search or export or settings"`
Expected: FAIL — 404 for the three read paths.

- [ ] **Step 3: Implement**

```python
class MemorySettingsPatch(BaseModel):
    # Strict on purpose: pydantic's lax mode reads the string "yes" as `True`, so `{"inject": "yes"}`
    # would quietly become a real write. A JSON body that spells a boolean as prose is a 400 here.
    model_config = ConfigDict(extra="forbid", strict=True)

    inject: bool | None = None
    capture: str | None = None
    extract: bool | None = None

    @field_validator("capture")
    @classmethod
    def _capture(cls, value: str | None) -> str | None:
        if value is not None and value not in CAPTURES:
            raise ValueError(f"capture must be one of {list(CAPTURES)}")
        return value
```

```python
    @app.get(f"{API_PREFIX}/kira/memory/search", dependencies=[auth])
    async def memory_search(q: str = "", limit: int = 20) -> dict:
        hits = engine.memory.search_history(q, max(1, min(50, limit)))
        return {"hits": hits}

    @app.get(f"{API_PREFIX}/kira/memory/export", dependencies=[auth])
    async def memory_export() -> dict:
        return engine.memory.export()

    @app.get(f"{API_PREFIX}/kira/memory/settings", dependencies=[auth])
    async def memory_settings() -> dict:
        return engine.memory.settings()

    @app.put(f"{API_PREFIX}/kira/memory/settings", dependencies=[auth, confirm])
    async def memory_settings_put(body: MemorySettingsPatch) -> dict:
        written = engine.memory.set_settings(body.model_dump(exclude_none=True))
        engine.sync_memory_tools()
        return written
```

Keep these four literals above `memory_patch`/`memory_delete`. Today the methods differ, so `/search`
cannot be swallowed by a PATCH-only `{memory_id}` — but Starlette matches in declaration order, and
the day a `GET /kira/memory/{memory_id}` exists, a search that answered `404 unknown memory` is the
failure this ordering prevents. No new test is needed for it.

The contract is this task's job too, exactly as in Task 9: add the four paths (`/search`, `/export`,
and `/settings` for both verbs) and their schemas (`MemorySearch`, `MemoryHit`, `MemoryExport`,
`MemorySettingsPatch`; `MemorySettings` already exists) from Task 11's Step 3 text, in the same
commit, or `tests/test_versioning.py` stays red until Task 11.

Two contract-text items Task 9's review parked for the file this task already edits — both are
description-only, no behaviour changes:
- the `GET /kira/memory` `kind` param publishes an enum but never says that a blank value means "no
  filter" while a non-blank value off the enum is a 400. Say it in that param's `description`.
- `limit` publishes `minimum: 1, maximum: 200` and the route *clamps* to them rather than rejecting.
  Say "values outside 1..200 are clamped, not refused" so a client reading the contract is not
  surprised by a 200 for `?limit=5000`.

- [ ] **Step 4: Add the four read rows to the README endpoint table**

```markdown
| `GET /v1/kira/memory/search` | bearer | ranked snippets over conversation text (`?q=`, `?limit=`); tool output is never indexed |
| `GET /v1/kira/memory/export` | bearer | every fact as JSON, for a backup you own |
| `GET /v1/kira/memory/settings` | bearer | `inject`, `capture`, `extract`, and which FTS tokenizer this build gave you |
| `PUT /v1/kira/memory/settings` | bearer + confirm | set any subset; `capture: "off"` also removes the `remember` tool |
```

- [ ] **Step 5: Run the full engine suite**

Run: `cd kira-engine && .venv/Scripts/python.exe -m pytest -q`
Expected: all green, `test_docs_match_engine` included — the table grew with the routes.

- [ ] **Step 6: Commit**

```bash
git add kira-engine/src/kira/app.py kira-engine/src/kira/contracts.py \
        kira-engine/tests/test_memory_api.py README.md
git -c user.name="Kira" -c user.email="kira@localhost" commit -m "memory: search, export and settings routes; capture flips the remember tool on the spot"
```

**Corrected during execution (preflight, before Task 10 ran).** Two defects fixed in the text: the
settings patch model is `strict=True` because pydantic's lax mode reads `{"inject": "yes"}` as `True`,
so the brief's own 400 case would have returned 200; and the contract additions move here from Task
11 for the same gate reason as Task 9. The route-order note was rewritten: the old text claimed a
PATCH-only `{memory_id}` would swallow `GET /search`, which it cannot.

---

### Task 11: Contract, TS mirror, drift gate, README rows, client methods

**Files:**
- Modify: `kira-engine/src/kira/contracts.py` (schemas + paths)
- Modify: `kira-engine/tests/test_contract_v2.py`
- Modify: `kira-contracts/types.ts`, `kira-contracts/openapi.json`, `kira-contracts/contract.json`,
  `kira-contracts/VERSION` (regenerated by the CLI)
- Modify: `README.md` (endpoint table + a Memory section)
- Modify: `kira-chat/src/api.ts`, `kira-chat/src/api.test.ts`

**Interfaces:**
- Consumes: the eight routes (Tasks 9–10).
- Produces the ten schemas `MemoryItem`, `MemoryList`, `MemoryWrite`, `MemoryPatch`, `MemorySearch`,
  `MemoryHit`, `MemoryExport`, `MemorySettings`, `MemorySettingsPatch`, `MemoryDeleted`, and eight
  `KiraClient` methods:
  `memories(query?, kind?, pinned?, limit?)`, `memorySearch(q, limit=20)`, `memorySettings()`,
  `exportMemory()`, `addMemory(text, kind, secret)`, `updateMemory(id, patch, secret)`,
  `deleteMemory(id, secret)`, `putMemorySettings(patch, secret)`.

- [ ] **Step 1: Write the failing tests**

```python
# appended to kira-engine/tests/test_contract_v2.py
MEMORY_PATHS = [
    ("get", f"{API_PREFIX}/kira/memory"),
    ("post", f"{API_PREFIX}/kira/memory"),
    ("patch", f"{API_PREFIX}/kira/memory/{{memory_id}}"),
    ("delete", f"{API_PREFIX}/kira/memory/{{memory_id}}"),
    ("get", f"{API_PREFIX}/kira/memory/search"),
    ("get", f"{API_PREFIX}/kira/memory/export"),
    ("get", f"{API_PREFIX}/kira/memory/settings"),
    ("put", f"{API_PREFIX}/kira/memory/settings"),
]


def test_memory_paths_are_published_and_the_writes_carry_the_confirm_header():
    for method, path in MEMORY_PATHS:
        assert method in OPENAPI["paths"][path], f"{method} {path} is not published"
    for method, path in MEMORY_PATHS:
        if method == "get":
            continue
        params = [p.get("$ref", "") for p in OPENAPI["paths"][path][method]["parameters"]]
        assert "#/components/parameters/Confirm" in params, f"{method} {path} is not confirm-gated"


def test_memory_schemas_are_additive_only():
    assert CONTRACT_VERSION == 2
    for name in ("MemoryItem", "MemoryList", "MemorySettings", "MemorySearch", "MemoryExport"):
        assert name in SCHEMAS
```

```python
# appended to kira-engine/tests/test_memory_api.py — Task 10's review found `/search`'s published
# `maximum: 50` unverified: widening `min(50, limit)` to `min(5000, limit)` kept all eight API tests
# green. This is the one assertion that makes the published bound true, and it belongs here because
# this task is the one that mirrors the contract on both sides of the wire.
@pytest.mark.anyio
async def test_the_search_limit_bound_the_contract_publishes_is_the_bound_the_route_keeps(harness):
    harness.store.create_session("AUTO", "s1")
    for i in range(3):
        harness.store.add_message("s1", "user", f"note {i} about eggs")
    for limit in (0, -1, 9999):
        response = await harness.api.get(
            "/v1/kira/memory/search", params={"q": "eggs", "limit": limit}, headers=harness.auth
        )
        assert response.status_code == 200, limit
        assert len(response.json()["hits"]) <= 50
```

```ts
// appended to kira-chat/src/api.test.ts — add FAKE_CONFIRM to the existing fake-engine import.
it("builds the memory query strings and sends the confirm header only on writes", async () => {
  const engine = fakeEngine();
  const client = new KiraClient({ baseUrl: "http://127.0.0.1:8901", token: "t", fetch: engine.fetch });
  await client.memories("pnpm", "preference", true, 10);
  await client.addMemory("I prefer pnpm", "preference", FAKE_CONFIRM);
  await client.putMemorySettings({ capture: "off" }, FAKE_CONFIRM);
  expect(engine.calls[0].url).toBe(`${API_PREFIX}/kira/memory?query=pnpm&kind=preference&pinned=true&limit=10`);
  expect(engine.calls[0].headers["X-Kira-Confirm"]).toBeUndefined();
  expect(engine.calls[1].method).toBe("POST");
  expect(engine.calls[1].headers["X-Kira-Confirm"]).toBe(FAKE_CONFIRM);
  expect(engine.calls[1].body).toBe(JSON.stringify({ text: "I prefer pnpm", kind: "preference" }));
  expect(engine.calls[2].body).toBe(JSON.stringify({ capture: "off" }));
});
```

- [ ] **Step 2: Run and watch them fail**

Run: `cd kira-engine && .venv/Scripts/python.exe -m pytest -q tests/test_contract_v2.py`
Expected: the two Python tests PASS — since the Task 9 ruling, every path and schema lands with the
route that serves it, so `contracts.py` is already complete; these two tests are the full-surface
guard. The TS test in `api.test.ts` is the red one: `KiraClient` has no `memories` method yet.

- [ ] **Step 3: Mirror what the contract already publishes**

**Do not re-add the block below.** Tasks 9 and 10 already put these schemas and paths in
`contracts.py`; the text is kept here as the reference the TypeScript mirror must match, and as the
place to check when a name disagrees. The work in this step is `kira-contracts/*` (regenerated from
`contracts.py` by the CLI) and `kira-chat/src/api.ts`.

In `contracts.py`, inside `OPENAPI["components"]["schemas"]`:

```python
            "MemoryItem": {
                "type": "object",
                "required": ["id", "kind", "text", "pinned", "origin", "created_at", "updated_at", "use_count"],
                "properties": {
                    "id": {"type": "string"},
                    "kind": {"type": "string", "enum": ["fact", "preference", "note"]},
                    "text": {"type": "string"},
                    "pinned": {"type": "boolean"},
                    "origin": {"type": "string", "enum": ["user", "tool", "auto"]},
                    "session_id": {"type": "string", "nullable": True},
                    "tokens_spent": {"type": "integer", "description": "the extraction call's share, origin=auto"},
                    "created_at": {"type": "number"},
                    "updated_at": {"type": "number"},
                    "last_used_at": {"type": "number", "nullable": True},
                    "use_count": {"type": "integer"},
                },
            },
            "MemoryList": {
                "type": "object",
                "required": ["memories", "total", "settings"],
                "properties": {
                    "memories": {"type": "array", "items": {"$ref": "#/components/schemas/MemoryItem"}},
                    "total": {"type": "integer"},
                    "settings": {"$ref": "#/components/schemas/MemorySettings"},
                },
            },
            "MemoryWrite": {
                "type": "object",
                "required": ["text"],
                "properties": {
                    "text": {"type": "string", "maxLength": 2000},
                    "kind": {"type": "string", "enum": ["fact", "preference", "note"]},
                    "pinned": {"type": "boolean"},
                },
            },
            "MemoryPatch": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "maxLength": 2000},
                    "kind": {"type": "string", "enum": ["fact", "preference", "note"]},
                    "pinned": {"type": "boolean"},
                },
            },
            "MemoryHit": {
                "type": "object",
                "required": ["session_id", "message_id", "role", "snippet", "created_at"],
                "properties": {
                    "session_id": {"type": "string"},
                    "message_id": {"type": "integer"},
                    "role": {"type": "string", "enum": ["user", "assistant"]},
                    "snippet": {"type": "string", "description": "the engine brackets the match with [ ]"},
                    "created_at": {"type": "number"},
                },
            },
            "MemorySearch": {
                "type": "object",
                "required": ["hits"],
                "properties": {"hits": {"type": "array", "items": {"$ref": "#/components/schemas/MemoryHit"}}},
            },
            "MemoryExport": {
                "type": "object",
                "required": ["version", "exported_at", "memories"],
                "properties": {
                    "version": {"type": "integer", "description": "export format, not the API version"},
                    "exported_at": {"type": "number"},
                    "memories": {"type": "array", "items": {"$ref": "#/components/schemas/MemoryItem"}},
                },
            },
            "MemorySettings": {
                "type": "object",
                "required": ["inject", "capture", "extract", "tokenizer"],
                "properties": {
                    "inject": {"type": "boolean"},
                    "capture": {"type": "string", "enum": ["off", "explicit"]},
                    "extract": {"type": "boolean"},
                    "tokenizer": {
                        "type": "string",
                        "enum": ["trigram", "unicode61"],
                        "description": "read-only: which index tokenizer this SQLite build gave us",
                    },
                },
            },
            "MemorySettingsPatch": {
                "type": "object",
                "properties": {
                    "inject": {"type": "boolean"},
                    "capture": {"type": "string", "enum": ["off", "explicit"]},
                    "extract": {"type": "boolean"},
                },
            },
            "MemoryDeleted": {
                "type": "object",
                "required": ["deleted"],
                "properties": {"deleted": {"type": "string"}},
            },
```

And in `paths`, before the tools entries:

```python
        f"{API_PREFIX}/kira/memory": {
            "get": _read(
                "Facts, newest first; `query` searches them",
                "MemoryList",
                [
                    {"name": "query", "in": "query", "schema": {"type": "string"}},
                    {"name": "kind", "in": "query", "schema": {"type": "string", "enum": ["fact", "preference", "note"]}},
                    {"name": "pinned", "in": "query", "schema": {"type": "boolean"}},
                    {"name": "limit", "in": "query", "schema": {"type": "integer", "default": 50}},
                ],
            ),
            "post": _write("Keep one fact", "MemoryItem", [], "MemoryWrite"),
        },
        f"{API_PREFIX}/kira/memory/{{memory_id}}": {
            "patch": _write(
                "Edit text, kind or pin",
                "MemoryItem",
                [{"name": "memory_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                "MemoryPatch",
            ),
            "delete": _write(
                "Forget one fact",
                "MemoryDeleted",
                [{"name": "memory_id", "in": "path", "required": True, "schema": {"type": "string"}}],
            ),
        },
        f"{API_PREFIX}/kira/memory/search": {
            "get": _read(
                "Ranked snippets over saved conversation text",
                "MemorySearch",
                [
                    {"name": "q", "in": "query", "schema": {"type": "string"}},
                    {"name": "limit", "in": "query", "schema": {"type": "integer", "default": 20}},
                ],
            )
        },
        f"{API_PREFIX}/kira/memory/export": {"get": _read("Every fact, as JSON", "MemoryExport")},
        f"{API_PREFIX}/kira/memory/settings": {
            "get": _read("The three switches plus the tokenizer in use", "MemorySettings"),
            "put": _write("Set any subset of the three switches", "MemorySettings", [], "MemorySettingsPatch"),
        },
```

The fake engine learns the same routes **in this task**, because the TypeScript test above talks to it
and its whole point is to 404 anything it does not speak. In `fake-engine.ts`, add the options:

```ts
  memory?: unknown;
  memorySearch?: unknown;
  memorySettings?: unknown;
  memoryError?: boolean;
```

exported fixtures next to the others:

```ts
export function memoryFixture() {
  return {
    memories: [
      { id: "m1", kind: "preference", text: "I prefer pnpm", pinned: true, origin: "user",
        session_id: null, tokens_spent: 0, created_at: 1, updated_at: 2, last_used_at: null, use_count: 3 },
      { id: "m2", kind: "fact", text: "works on Windows", pinned: false, origin: "auto",
        session_id: "sess-9", tokens_spent: 42, created_at: 3, updated_at: 3, last_used_at: 4, use_count: 1 },
    ],
    total: 2,
    settings: { inject: true, capture: "explicit", extract: false, tokenizer: "trigram" },
  };
}

export function memoryHitsFixture() {
  return {
    hits: [
      { session_id: "sess-9", message_id: 12, role: "user", snippet: "we talked about the [vector] database", created_at: 5 },
    ],
  };
}
```

A mutable settings object beside `let release` (the screen reads its switches from the list response,
so a `PUT` that did not move it would leave the screen showing the old state and the test would be
testing nothing):

```ts
  let memorySettings = options.memorySettings ?? memoryFixture().settings;
```

and the routes, placed before the `/chat/completions` branch. Literal paths come before the
`{memory_id}` matcher:

```ts
    if (at("/kira/memory") && method === "GET") {
      if (options.memoryError) {
        return json({ error: { code: "internal_error", message: "the index is not open", status: 500, retryable: false } }, 500);
      }
      return json({ ...(options.memory ?? memoryFixture()), settings: memorySettings });
    }
    if (at("/kira/memory") && method === "POST") {
      if (confirmHeader !== wanted) return refused;
      const body = JSON.parse(String(init.body ?? "{}")) as { text: string; kind?: string };
      return json({ ...memoryFixture().memories[0], id: "m3", text: body.text, kind: body.kind ?? "fact", origin: "user" });
    }
    if (at("/kira/memory/search") && method === "GET") return json(options.memorySearch ?? memoryHitsFixture());
    if (at("/kira/memory/settings") && method === "GET") return json(memorySettings);
    if (at("/kira/memory/settings") && method === "PUT") {
      if (confirmHeader !== wanted) return refused;
      const body = JSON.parse(String(init.body ?? "{}")) as Partial<typeof memorySettings>;
      memorySettings = { ...memorySettings, ...body };
      return json(memorySettings);
    }
    if (at("/kira/memory/export") && method === "GET")
      return json({ version: 1, exported_at: 6, memories: (options.memory ?? memoryFixture()).memories });
    const memoryItem = url.pathname.match(new RegExp(`^${API_PREFIX}/kira/memory/([^/]+)$`));
    if (memoryItem && (method === "PATCH" || method === "DELETE")) {
      if (confirmHeader !== wanted) return refused;
      if (memoryItem[1] === "gone") {
        return json({ error: { code: "not_found", message: "unknown memory", status: 404, retryable: false } }, 404);
      }
      if (method === "DELETE") return json({ deleted: memoryItem[1] });
      return json({ ...memoryFixture().memories[0], id: memoryItem[1], ...JSON.parse(String(init.body ?? "{}")) });
    }
```

- [ ] **Step 4: Regenerate the contract and mirror it**

```bash
cd kira-engine && .venv/Scripts/python.exe -m kira contracts --out ../kira-contracts
cd .. && node kira-contracts/check-drift.mjs
```

Expected now: FAIL listing ten missing interfaces in `types.ts`. Add each one, with **exactly** the
property names above:

```ts
export type MemoryKind = "fact" | "preference" | "note";
export type MemoryOrigin = "user" | "tool" | "auto";
export type MemoryCapture = "off" | "explicit";

export interface MemoryItem {
  id: string;
  kind: MemoryKind;
  text: string;
  pinned: boolean;
  origin: MemoryOrigin;
  session_id?: string | null;
  tokens_spent?: number;
  created_at: number;
  updated_at: number;
  last_used_at?: number | null;
  use_count: number;
}

export interface MemorySettings {
  inject: boolean;
  capture: MemoryCapture;
  extract: boolean;
  /** read-only: trigram on SQLite 3.34+, unicode61 on older builds */
  tokenizer: "trigram" | "unicode61";
}

export interface MemoryList {
  memories: MemoryItem[];
  total: number;
  settings: MemorySettings;
}

export interface MemoryWrite {
  text: string;
  kind?: MemoryKind;
  pinned?: boolean;
}

export interface MemoryPatch {
  text?: string;
  kind?: MemoryKind;
  pinned?: boolean;
}

export interface MemoryHit {
  session_id: string;
  message_id: number;
  role: "user" | "assistant";
  snippet: string;
  created_at: number;
}

export interface MemorySearch {
  hits: MemoryHit[];
}

export interface MemoryExport {
  version: number;
  exported_at: number;
  memories: MemoryItem[];
}

export interface MemorySettingsPatch {
  inject?: boolean;
  capture?: MemoryCapture;
  extract?: boolean;
}

export interface MemoryDeleted {
  deleted: string;
}
```

Re-run the gate: `node kira-contracts/check-drift.mjs` → `kira-contracts OK — v2, 66 schemas, 6 chunk
types, 16 chain events`.

- [ ] **Step 5: Add the Memory section to the README**

The eight endpoint rows are already in the table from Tasks 9–10. What is missing is the prose that
explains them. Put a short section after "Tools and permissions":

```markdown
## Memory

Kira keeps two kinds of memory, both local and both visible on `#/memory`.

**Facts** are rows you (or the model, via `remember`) chose to keep. They are injected into every
turn as a bounded block — pinned first, then BM25 matches for your last message, then recently used,
12 items or 1 500 characters at most. The block is **never** stored as a message: the Sessions screen
shows only what was said. `remember` is `allow` by default (one click on the Tools screen restores the
prompt); `capture: off` removes it from the model's tool list entirely.

**History** is the conversation already in SQLite, indexed in FTS5 and searchable from the same
screen. Only `user` and `assistant` text is indexed — never tool output, never an image.

The index tokenizer is chosen by probing the installed SQLite: `trigram` on 3.34+, which is the only
one of the two that can match CJK (a `unicode61` build treats a whole CJK run as one token and returns
nothing for `向量数据库`). `GET /v1/kira/memory/settings` says which one is live. Either way a query
that MATCH cannot see falls through to a `LIKE` tier, so a search is slow before it is ever empty.

Extraction (`extract`, default off) is one capped 200-token call after a completed chat turn, labelled
`origin: auto` with the tokens it spent, deduped, and added to the month's ledger. It never fails a turn.
```

- [ ] **Step 6: Add the client methods**

In `api.ts`, after `tools()`:

```ts
  memories(query?: string, kind?: MemoryKind, pinned?: boolean, limit = 50): Promise<MemoryList> {
    // Built in this order so the wire URL is stable enough to assert on, and so a filter that is
    // absent reads as absent rather than as "false".
    const params = new URLSearchParams();
    if (query) params.set("query", query);
    if (kind) params.set("kind", kind);
    if (pinned !== undefined) params.set("pinned", String(pinned));
    params.set("limit", String(limit));
    return this.request<MemoryList>(`${API_PREFIX}/kira/memory?${params}`);
  }

  memorySearch(q: string, limit = 20): Promise<MemorySearch> {
    return this.request<MemorySearch>(
      `${API_PREFIX}/kira/memory/search?${new URLSearchParams({ q, limit: String(limit) })}`,
    );
  }

  memorySettings(): Promise<MemorySettings> {
    return this.request<MemorySettings>(`${API_PREFIX}/kira/memory/settings`);
  }

  exportMemory(): Promise<MemoryExport> {
    return this.request<MemoryExport>(`${API_PREFIX}/kira/memory/export`);
  }

  addMemory(text: string, kind: MemoryKind, secret: string): Promise<MemoryItem> {
    return this.write(`${API_PREFIX}/kira/memory`, "POST", secret, { text, kind });
  }

  updateMemory(id: string, patch: MemoryPatch, secret: string): Promise<MemoryItem> {
    return this.write(`${API_PREFIX}/kira/memory/${encodeURIComponent(id)}`, "PATCH", secret, patch);
  }

  deleteMemory(id: string, secret: string): Promise<MemoryDeleted> {
    return this.write(`${API_PREFIX}/kira/memory/${encodeURIComponent(id)}`, "DELETE", secret);
  }

  putMemorySettings(patch: MemorySettingsPatch, secret: string): Promise<MemorySettings> {
    return this.write(`${API_PREFIX}/kira/memory/settings`, "PUT", secret, patch);
  }
```

Imports gain the ten type names.

- [ ] **Step 7: Run every gate**

```bash
cd kira-engine && .venv/Scripts/python.exe -m pytest -q
cd ../kira-chat && npm run check
cd .. && node kira-contracts/check-drift.mjs
```

Expected: engine green (README test now passes), client 26 files green with the new `api.test.ts` case,
drift `v2, 66 schemas, 6 chunk types, 16 chain events`.

- [ ] **Step 8: Commit**

```bash
git add kira-engine/src/kira/contracts.py kira-engine/tests/test_contract_v2.py \
        kira-contracts/ README.md kira-chat/src/api.ts kira-chat/src/api.test.ts
git -c user.name="Kira" -c user.email="kira@localhost" commit -m "memory: publish eight routes in contract v2, mirror the types, document them, and add the client methods"
```

**Corrected during execution (commit 26ed715).** Six small divergences between this text and what
actually works, each reproduced before it was accepted:

- Step 1's clamp test cannot fail as written: three fixture rows sit under both 50 and 5 000, so
  `len(hits) <= 50` stays green with the clamp widened. The shipped test seeds 60 rows and pins the
  page sizes `(0→1, -1→1, 9999→50)`; it fails against `min(5000, …)`, against a dropped `max(1, …)`,
  and proves the brief's own version passes under the regression it was meant to catch.
- Step 6's "imports gain the ten type names" is nine: `MemoryWrite`, `MemoryHit`, `MemoryOrigin` and
  `MemoryCapture` are unused by the eight methods, and `noUnusedLocals` + `verbatimModuleSyntax`
  reject unused type imports. All thirteen are exported from `kira-contracts/types.ts` for Task 12.
- The fake engine's export branch needs a narrow cast: `memory?: unknown` collapses to `{}` under
  `tsc`, so `(options.memory ?? memoryFixture()).memories` is a TS2339. The shipped line reads it
  through a cast and answers `list.memories ?? []`; the fake's answers are unchanged.
- Step 8's staging list is short of this task's own work — it omits `kira-chat/src/fake-engine.ts`
  (Step 3's routes) and `kira-engine/tests/test_memory_api.py` (Step 1's clamp test). Both shipped.
- Step 7's "client 26 files" is 25 files / 217 tests; the new case joined the existing `api.test.ts`.
  `contracts.py` was passed to `git add` but is unmodified — Step 3's "do not re-add" held, and the
  reviewer confirmed the regenerated artifacts are byte-identical to the CLI's output.
- The README prose shipped as "the `#/memory` screen that shows them is the next build", which is the
  honest wording until Task 12. `docs/ROADMAP.md:14`'s test counts are stale and Task 13 rewrites them.

The reviewer also mapped the drift gate's real reach: it checks interface *names* and three enum
lists, so a renamed property fails it while a made-optional field or an invented enum member does
not; and the fake's `{memory_id}` matcher answers writes to literal names, so Task 12's tests must
not depend on that shape.

---

### Task 12: `#/memory` in both shells

**Files:**
- Create: `kira-chat/src/screens/MemoryScreen.tsx`, `kira-chat/src/screens/MemoryScreen.test.tsx`
- Modify: `kira-chat/src/hash-route.ts`, `kira-chat/src/App.tsx`, `kira-chat/src/App.test.tsx`,
  `kira-chat/src/fake-engine.ts`, `kira-chat/src/confirm.tsx` (only if a phrase is wanted — see below)
- Modify: `kira-chat/src/styles.css` (only if a class is genuinely missing)

**Interfaces:**
- Consumes: the eight client methods (Task 11), `useAsync`, `useWrite`, `useConfirm`.
- Produces: route `#/memory`; `MemoryScreen({ client, connected })`; fake-engine memory routes.

- [ ] **Step 1: Write the failing tests**

```tsx
// kira-chat/src/screens/MemoryScreen.test.tsx
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { KiraClient } from "../api.ts";
import { ConfirmProvider } from "../confirm.tsx";
import { FAKE_CONFIRM, fakeEngine } from "../fake-engine.ts";
import { MemoryScreen } from "./MemoryScreen.tsx";

function mount(engine: ReturnType<typeof fakeEngine>) {
  const client = new KiraClient({ baseUrl: "http://127.0.0.1:8901", token: "t", fetch: engine.fetch });
  render(
    <ConfirmProvider>
      <MemoryScreen client={client} connected />
    </ConfirmProvider>,
  );
}

async function signIn() {
  // The one confirm dialog every screen shares: its label and its submit button's name, verbatim.
  fireEvent.change(await screen.findByLabelText(/confirm secret/i), { target: { value: FAKE_CONFIRM } });
  fireEvent.click(screen.getByRole("button", { name: /confirm write/i }));
}

beforeEach(() => localStorage.clear());

describe("MemoryScreen", () => {
  it("lists facts with their kind, origin and pin state", async () => {
    mount(fakeEngine());
    expect(await screen.findByText("I prefer pnpm")).toBeTruthy();
    expect(screen.getAllByText("preference").length).toBeGreaterThan(0); // the chip and the kind menu
    expect(screen.getByText(/auto · 42 tokens/)).toBeTruthy();
    expect(screen.getByLabelText("search facts")).toBeTruthy();
  });

  it("adds a fact after the confirm secret is typed", async () => {
    const engine = fakeEngine();
    mount(engine);
    await screen.findByText("I prefer pnpm");
    fireEvent.change(screen.getByLabelText("new fact"), { target: { value: "I am on Windows" } });
    fireEvent.click(screen.getByRole("button", { name: "keep" }));
    await signIn();
    await waitFor(() =>
      expect(engine.calls.some((call) => call.method === "POST" && call.url === "/v1/kira/memory")).toBe(true),
    );
    const post = engine.calls.find((call) => call.method === "POST")!;
    expect(post.headers["X-Kira-Confirm"]).toBe(FAKE_CONFIRM);
    expect(post.body).toBe(JSON.stringify({ text: "I am on Windows", kind: "fact" }));
  });

  it("forgets one fact behind a danger confirm and re-reads the list", async () => {
    const engine = fakeEngine();
    mount(engine);
    await screen.findByText("I prefer pnpm");
    fireEvent.click(screen.getByRole("button", { name: /forget m1/ }));
    await signIn();
    await waitFor(() => expect(engine.calls.some((call) => call.method === "DELETE")).toBe(true));
  });

  it("switches to history and shows bracketed snippets", async () => {
    mount(fakeEngine());
    fireEvent.click(screen.getByRole("tab", { name: "history" }));
    fireEvent.change(screen.getByLabelText("search history"), { target: { value: "vector" } });
    expect(await screen.findByText(/\[vector\]/)).toBeTruthy();
    expect(screen.getByText(/session sess-9/)).toBeTruthy();
  });

  it("turns capture off through the switch and says what that removes", async () => {
    const engine = fakeEngine();
    mount(engine);
    await screen.findByText("I prefer pnpm");
    fireEvent.click(screen.getByLabelText("capture"));
    await signIn();
    await waitFor(() =>
      expect(
        engine.calls.some((call) => call.method === "PUT" && call.url === "/v1/kira/memory/settings"),
      ).toBe(true),
    );
    expect(await screen.findByText(/remember is hidden from the model/i)).toBeTruthy();
  });

  it("names the tokenizer when it is not trigram", async () => {
    mount(
      fakeEngine({
        memorySettings: { inject: true, capture: "explicit", extract: false, tokenizer: "unicode61" },
      }),
    );
    expect(await screen.findByText("unicode61")).toBeTruthy();
    expect(screen.getByText(/CJK/)).toBeTruthy();
  });

  it("shows the engine's refusal instead of an empty table", async () => {
    mount(fakeEngine({ memoryError: true }));
    expect((await screen.findByRole("alert")).textContent).toContain("cannot read memory");
  });
});
```

- [ ] **Step 2: Run and watch them fail**

Run: `cd kira-chat && npx vitest run src/screens/MemoryScreen.test.tsx`
Expected: FAIL — cannot resolve `./MemoryScreen.tsx`.

- [ ] **Step 3: Point the screen at the fixtures Task 11 already gave the fake**

`memoryFixture()`, `memoryHitsFixture()` and the eight routes (with their mutable settings object) were
added in Task 11, because the `KiraClient` test needed them. Nothing new goes in `fake-engine.ts` here
beyond a repair: if the Step 1 tests fail on a missing route or a list response whose `settings` never
move, the Task 11 block was added in an order that lets the `{memory_id}` matcher win — literal paths
first, `{memory_id}` last — and the fix belongs in that file, not in the screen.

- [ ] **Step 4: Write the screen**

```tsx
import { useState } from "react";
import type { KiraClient } from "../api.ts";
import type { MemoryHit, MemoryItem, MemoryKind, MemorySearch, MemorySettings, MemorySettingsPatch } from "../contracts.ts";
import { useAsync } from "../useAsync.ts";
import { useWrite } from "../useWrite.ts";

const KINDS: MemoryKind[] = ["fact", "preference", "note"];
const EMPTY = {
  memories: [] as MemoryItem[],
  total: 0,
  settings: { inject: true, capture: "explicit", extract: false, tokenizer: "trigram" } as MemorySettings,
};
const EMPTY_HITS: MemorySearch = { hits: [] as MemoryHit[] };

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function stamp(seconds: number): string {
  return new Date(seconds * 1000).toLocaleDateString("en-GB");
}

export function MemoryScreen({ client, connected }: { client: KiraClient; connected: boolean }) {
  const [tab, setTab] = useState<"facts" | "history">("facts");
  const [query, setQuery] = useState("");
  const [historyQuery, setHistoryQuery] = useState("");
  const [draft, setDraft] = useState("");
  const [kind, setKind] = useState<MemoryKind>("fact");
  const [editing, setEditing] = useState<{ id: string; text: string } | null>(null);

  const facts = useAsync(
    () => (connected ? client.memories(query || undefined) : Promise.resolve(EMPTY)),
    [connected, query],
  );
  const hits = useAsync(
    () => (connected && historyQuery ? client.memorySearch(historyQuery) : Promise.resolve(EMPTY_HITS)),
    [connected, historyQuery],
  );
  const { busy, note, run } = useWrite(() => {
    facts.refresh();
    hits.refresh();
  });

  const settings = facts.kind === "ready" ? facts.data.settings : EMPTY.settings;

  function keep() {
    const text = draft.trim();
    if (!text) return;
    void run("keep this fact", "It will be injected into future turns until you forget it.", false, async (secret) => {
      await client.addMemory(text, kind, secret);
      setDraft("");
    });
  }

  function forget(item: MemoryItem) {
    void run(`forget "${item.text.slice(0, 60)}"`, "This cannot be undone; export first if unsure.", true, (secret) =>
      client.deleteMemory(item.id, secret),
    );
  }

  function togglePin(item: MemoryItem) {
    void run(
      item.pinned ? "unpin this fact" : "pin this fact",
      "Pinned facts are the first ones injected into every turn.",
      false,
      (secret) => client.updateMemory(item.id, { pinned: !item.pinned }, secret),
    );
  }

  function saveEdit() {
    if (!editing) return;
    void run("save this edit", "The indexed text changes with it.", false, async (secret) => {
      await client.updateMemory(editing.id, { text: editing.text }, secret);
      setEditing(null);
    });
  }

  function switchSetting(key: "inject" | "capture" | "extract", value: boolean) {
    // Written as literals, not a computed key: `{ [key]: value }` widens to an index signature and
    // stops being the patch the client's type promises.
    const patch: MemorySettingsPatch =
      key === "capture" ? { capture: value ? "explicit" : "off" } : key === "inject" ? { inject: value } : { extract: value };
    void run(`set ${key}`, "This changes what every future turn carries.", false, (secret) =>
      client.putMemorySettings(patch, secret),
    );
  }

  function exportAll() {
    void client.exportMemory().then((data) => {
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `kira-memory-${new Date().toISOString().slice(0, 10)}.json`;
      link.click();
      URL.revokeObjectURL(url);
    });
  }

  return (
    <section className="screen" aria-label="memory">
      <h2>Memory</h2>
      {note && <p className="error">{note}</p>}
      <div className="toolbar" role="tablist">
        <button role="tab" aria-selected={tab === "facts"} onClick={() => setTab("facts")}>facts</button>
        <button role="tab" aria-selected={tab === "history"} onClick={() => setTab("history")}>history</button>
        <button type="button" onClick={exportAll}>export</button>
      </div>

      {tab === "facts" && (
        <>
          <div className="toolbar">
            <input
              aria-label="search facts"
              placeholder="search facts"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
            <input
              aria-label="new fact"
              placeholder="something worth keeping"
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
            />
            <select aria-label="kind" value={kind} onChange={(event) => setKind(event.target.value as MemoryKind)}>
              {KINDS.map((option) => <option key={option} value={option}>{option}</option>)}
            </select>
            <button type="button" disabled={busy || !draft.trim()} onClick={keep}>keep</button>
          </div>

          {facts.kind === "loading" ? <p className="muted">reading memory…</p> : null}
          {facts.kind === "error" ? <p className="error" role="alert">cannot read memory: {messageOf(facts.error)}</p> : null}
          {facts.kind === "ready" && (
            <table className="grid">
              <thead><tr><th>fact</th><th>kind</th><th>origin</th><th>used</th><th /></tr></thead>
              <tbody>
                {facts.data.memories.map((item) => (
                  <tr key={item.id}>
                    <td>
                      {editing?.id === item.id ? (
                        <input
                          aria-label={`edit ${item.id}`}
                          value={editing.text}
                          onChange={(event) => setEditing({ id: item.id, text: event.target.value })}
                        />
                      ) : (
                        <div>{item.text}</div>
                      )}
                      <div className="muted small">{stamp(item.created_at)}</div>
                    </td>
                    <td><span className="chip">{item.kind}</span></td>
                    <td className="muted">
                      {item.origin}
                      {item.origin === "auto" ? ` · ${item.tokens_spent} tokens` : ""}
                    </td>
                    <td className="muted">{item.use_count}×</td>
                    <td>
                      <button type="button" disabled={busy} onClick={() => togglePin(item)}>
                        {item.pinned ? "unpin" : "pin"}
                      </button>
                      {editing?.id === item.id ? (
                        <>
                          <button type="button" disabled={busy} onClick={saveEdit}>save</button>
                          <button type="button" onClick={() => setEditing(null)}>cancel</button>
                        </>
                      ) : (
                        <button type="button" disabled={busy} onClick={() => setEditing({ id: item.id, text: item.text })}>
                          edit
                        </button>
                      )}
                      <button type="button" disabled={busy} onClick={() => forget(item)}>
                        {`forget ${item.id}`}
                      </button>
                    </td>
                  </tr>
                ))}
                {facts.data.memories.length === 0 && (
                  <tr><td colSpan={5} className="empty">
                    nothing kept yet — say "remember that …" in chat, or type a fact above.
                  </td></tr>
                )}
              </tbody>
            </table>
          )}

          <div className="toolbar">
            <label>
              <input type="checkbox" aria-label="inject" checked={settings.inject} disabled={busy}
                     onChange={(event) => switchSetting("inject", event.target.checked)} />
              inject into every turn
            </label>
            <label>
              <input type="checkbox" aria-label="capture" checked={settings.capture !== "off"} disabled={busy}
                     onChange={(event) => switchSetting("capture", event.target.checked)} />
              let the model keep facts
            </label>
            <label>
              <input type="checkbox" aria-label="extract" checked={settings.extract} disabled={busy}
                     onChange={(event) => switchSetting("extract", event.target.checked)} />
              extract after each turn (one extra call)
            </label>
          </div>
          {settings.capture === "off" ? (
            <p className="muted small">remember is hidden from the model while capture is off.</p>
          ) : null}
          {settings.tokenizer !== "trigram" ? (
            <p className="muted small">
              this build fell back to the <strong>{settings.tokenizer}</strong> tokenizer — CJK search is
              served by the slower LIKE tier.
            </p>
          ) : null}
        </>
      )}

      {tab === "history" && (
        <>
          <div className="toolbar">
            <input
              aria-label="search history"
              placeholder="search past conversations"
              value={historyQuery}
              onChange={(event) => setHistoryQuery(event.target.value)}
            />
          </div>
          {hits.kind === "error" ? <p className="error" role="alert">cannot search history: {messageOf(hits.error)}</p> : null}
          {hits.kind === "ready" && hits.data.hits.length === 0 ? (
            <p className="empty">no stored message matches that yet.</p>
          ) : null}
          {hits.kind === "ready" && hits.data.hits.length > 0 && (
            <ul className="work-list">
              {hits.data.hits.map((hit) => (
                <li key={`${hit.session_id}-${hit.message_id}`}>
                  <span className="muted small">{hit.role} · session {hit.session_id} · {stamp(hit.created_at)}</span>
                  <div>{hit.snippet}</div>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  );
}
```

The test's `getByLabelText(/confirm secret/i)` and `getByRole("button", { name: /confirm write/i })`
match the dialog that ships today: `confirm.tsx` labels its input **"Confirm secret"** and its submit
button **"confirm write"**. One dialog serves every screen, so if that ever changes, change the test to
the dialog's new names — never the dialog to the test.

- [ ] **Step 5: Wire the route**

```ts
// hash-route.ts:1 — the one line that grows
export const ROUTES = ["chat", "call", "overview", "providers", "models", "sessions", "tools", "memory"] as const;
```

```tsx
// App.tsx:24 — add BrainCircuit to the existing lucide import, keeping it alphabetical
import { Activity, BrainCircuit, Cpu, History, LogOut, MessageSquare, PanelLeftClose, PanelLeftOpen, Phone, RefreshCw, Server, Wrench } from "lucide-react";
```

```tsx
// App.tsx:31 — one entry, at the end
const NAV_ICONS = {
  chat: MessageSquare,
  call: Phone,
  overview: Activity,
  providers: Server,
  models: Cpu,
  sessions: History,
  tools: Wrench,
  memory: BrainCircuit,
} as const;
```

```tsx
// App.tsx:45 — same, at the end
const NAV_LABELS: Record<Route, string> = {
  chat: "Chat",
  call: "Call",
  overview: "Overview",
  providers: "Providers",
  models: "Models",
  sessions: "Sessions",
  tools: "Tools",
  memory: "Memory",
};
```

```tsx
// App.tsx:13 — the screen import, after CallScreen
import { MemoryScreen } from "./screens/MemoryScreen.tsx";
```

```tsx
// App.tsx:278 — a new branch after the Tools branch; Sessions stays the fallback
          ) : route === "tools" ? (
            <ToolsScreen client={client} connected={connected} />
          ) : route === "memory" ? (
            <MemoryScreen client={client} connected={connected} />
          ) : (
            <SessionsScreen client={client} focusId={focusSession} onChanged={voidRefresh} />
          )}
```

`tsc` enforces both records once `ROUTES` grows: `NAV_ICONS[route]` and the `Record<Route, string>`
type both fail to compile until `memory` is present in each.

- [ ] **Step 6: Extend the every-route test**

In `App.test.tsx:253`, add `"memory"` to the array and one assertion beside the others:

```tsx
        if (route === "memory") expect(await screen.findByRole("heading", { name: "Memory" })).toBeTruthy();
```

- [ ] **Step 7: Run the client gate**

Run: `cd kira-chat && npm run check`
Expected: tsc clean, 27 files / ~223 tests, vite build green.

- [ ] **Step 8: Commit**

```bash
git add kira-chat/src/screens/MemoryScreen.tsx kira-chat/src/screens/MemoryScreen.test.tsx \
        kira-chat/src/hash-route.ts kira-chat/src/App.tsx kira-chat/src/App.test.tsx \
        kira-chat/src/fake-engine.ts
git -c user.name="Kira" -c user.email="kira@localhost" commit -m "memory: a real #/memory screen in both shells — facts, history, three switches, export"
```

**Corrected during execution (commits 7137aef, 778a797).** Four divergences.

1. **The brief's class names do not exist.** `styles.css` has no `.toolbar`, no `.chip` and no bare
   `.grid` selector; the first red run failed on module resolution, so no test ever depended on them.
   The screen ships with the house classes — `table.grid`, `.badge`, `.cell-actions`, `.filters`,
   `.switches`, `.segmented`, `.muted .small`, `.empty`, `.work-list` — and `styles.css` gained
   exactly three rules: a `.filters`/`.switches` wrapping row, a `.segmented button[aria-selected]`
   active state (the existing rule only knew `aria-checked`), and `.screen-head .segmented` sizing.
   The Step 8 staging list omitted `styles.css`; it was staged.
2. **The counts were an estimate.** The gate is 26 files / 224 tests, not 27 / ~223: Task 11's
   README said 25 / 217, and this screen adds one file and seven tests.
3. **`fake-engine.ts` needed no repair.** Literal memory paths are declared before the `{memory_id}`
   matcher and that matcher only answers PATCH/DELETE, so every screen test and the every-route test
   reached the intended branch on the first try.
4. **Two review tightenings, committed separately (778a797).** The forget test now pins
   `DELETE /v1/kira/memory/m1` rather than any DELETE — a mutant that forgets `m2` passes the old
   assertion and fails the new one. And the three switches render only once the list has been read:
   on a failed read the screen used to render `EMPTY.settings`, three checkboxes claiming to know the
   engine's state. The same test now asserts `inject` is absent while the alert is up; removing the
   `facts.kind === "ready"` guard fails it. Both mutants were run and reverted.

---

### Task 13: Docs, every gate, a browser pass, and the merge

**Files:**
- Modify: `README.md` (counts, and the Memory section's numbers if they moved)
- Modify: `docs/ROADMAP.md` (unit 4 done, completion arithmetic, milestone list)
- Modify: `PROVENANCE.md` (the memory row)
- Create: `docs/qa/memory-browser-pass.md`
- Modify: `docs/specs/2026-10-29-kira-memory-design.md` (only the status line, if anything changed)

**Interfaces:**
- Consumes: everything above.
- Produces: a green tree, an honest QA record, and `master` fast-forwarded.

- [ ] **Step 1: Add the provenance row**

```markdown
| Memory and retrieval (`memory.py`, the v2 schema in `store.py`, `screens/MemoryScreen.tsx`) | laya `db/fts.py` (own-content FTS5 tables, trigger sync, `bm25()`, quoted MATCH builder, LIKE fallback) and `retrieval.py` (RRF, deferred); PocketStrike `hermes_memory_store.dart` (the fact/preference/note split, and its auto-evolve switch, inverted to off) | Apache-2.0 / none | no — SQL and behaviour written here; their tokenizer was measured and rejected |
```

- [ ] **Step 2: Run the three gates and copy their exact output into the QA file**

```bash
cd kira-engine && .venv/Scripts/python.exe -m pytest -q
cd ../kira-chat && npm run check
cd .. && node kira-contracts/check-drift.mjs
```

Record the real numbers. Do not invent them; if a count surprises you, find out why before writing it.

- [ ] **Step 3: The browser pass**

Against the real engine (`kira-engine/tools/kira_lab.py` plus `tools/mock_openai.py` — the sandbox pair
from `docs/qa/dashboard-browser-pass.md`, so nothing is spent) and the built `kira-chat/dist` at
`/chat/`:

1. `#/memory` renders in **Chat** and in **Agent**; the rail entry is reachable by keyboard.
2. Keep a fact → confirm dialog → row appears; the row survives a reload.
3. Pin it → it moves to the top of the injected block (prove it by asking the mock provider a question
   and reading the recorded request body the mock logs).
4. Edit the text; forget it; both re-read from the engine, not from local state.
5. Search history for a word that exists only in a `tool` row → **no hit**; for a word in a user row →
   a hit with `[brackets]`.
6. `capture: off` → the Tools screen no longer lists `remember`, and `GET /v1/kira/models`-adjacent
   tool schemas do not carry it either.
7. Export downloads a file whose `version` is 1 and whose rows match what the screen shows.
8. `localStorage` still holds exactly `kira.base`, `kira.shell`, `kira.token`.
9. Zero uncaught exceptions in the console for the whole run.

Write each check, what you observed, and any defect with its guard-test name. Findings that are real
defects get fixed test-first **in that pass**, the way the shell-modes pass did.

- [ ] **Step 4: Update ROADMAP and README counts**

Unit 4 becomes done with M19–M22; recompute the delivered-milestones fraction from the file, do not
guess. Add the one honest limitation this slice has: lexical search misses paraphrases, and the
Memory screen is where that shows.

- [ ] **Step 5: Merge**

```bash
git checkout master
git merge --ff-only feat/memory
git branch -d feat/memory
git log --oneline -14
```

- [ ] **Step 6: Commit the docs and the pass record**

```bash
git add README.md docs/ROADMAP.md PROVENANCE.md docs/qa/memory-browser-pass.md
git -c user.name="Kira" -c user.email="kira@localhost" commit -m "docs: sub-project 4 complete — gates, browser pass, provenance, roadmap arithmetic"
```

---

**Corrected during execution (docs `0a449c7`, merged `5c0e552..0a449c7`).** Five divergences.

1. **Steps 5 and 6 ran in the other order.** Committing the docs on `feat/memory` and *then*
   fast-forwarding is the only order in which the docs live in the branch's own linear history; the
   plan's order would have left them as a commit on `master` that the branch never contained. The merge
   was still `--ff-only`, and the end state is the same tree.
2. **The README's opening paragraph was two sub-projects stale.** It still said this tree carries only
   sub-project 1 and sub-project 9 and that "tool execution … memory … are still later sub-projects",
   and the tree listing called `kira-chat/` "the chat and the five-screen dashboard". Both were
   corrected while the counts were being touched; a shipped feature list that stops at unit 9 is a
   worse lie than a wrong test count.
3. **The counts were re-measured after the docs edits, not carried over.** `458 passed, 1 skipped`,
   `Test Files 26 passed (26)`, `Tests 224 passed (224)`, drift `v2, 66 schemas, 6 chunk types, 16
   chain events` — identical to Step 2, which is the point of running them twice. The final
   whole-branch review then found one more defect and added one test (see §6 below), so the tree closes
   at **225** client tests, and both docs were corrected to say so.
4. **The spec's status line said "Planning next."** It now says implemented, names the plan and the pass
   record, and keeps the one thing still outstanding visible: the live memory turn in §11 waits on the
   Gemini key's daily quota.
5. **The browser pass could not follow Step 3 literally in two places**, and both are written down in
   `docs/qa/memory-browser-pass.md` instead of being papered over: the mock provider keeps no request
   log (injection was proved by `use_count`/`last_used_at` and by running `build_block` against the live
   SQLite), and the export is a Blob plus a synthetic anchor click (intercepted at
   `URL.createObjectURL`). A third observation is not a defect and was left as the engine behaves: the
   history tab's "no stored message matches that yet." is shown before the first keystroke, because an
   empty query is an empty result.
6. **The whole-branch review found one defect the browser pass could not see: a failed export was
   silent.** `exportAll` chained `.then()` with no `.catch()`, so an engine that refused the export
   produced an unhandled rejection and no message on screen — a backup that did not happen and did not
   say so. The browser pass could not catch it because the export there succeeded. Fixed test-first:
   the fake engine gained `exportError`, the new test asserts `cannot export memory: …` in an alert,
   and the red run was the unhandled `KiraApiError` itself. Client tests go 224 → 225.

---

## Self-review notes (what to watch for while executing)

- **Route order is load-bearing.** `/kira/memory/{memory_id}` declared before `/search` swallows it and
  the search route 404s. The API tests fail loudly if this regresses; keep the literal paths first.
- **`mark_used` belongs after a sent answer.** Both failure paths return before the call site; if you
  move it, `test_a_served_turn_marks_what_it_used_and_a_failed_one_does_not` catches you.
- **`ToolRegistry.schemas()` is what the model sees.** `unregister` must remove the tool from *both*
  `get()` and `schemas()` — it does, because both read `self._tools`.
- **The block is never persisted.** The stored user row is written *before* injection, from the
  original text; the assistant row comes from `run.state.text`. Nothing else may touch `messages`.
- **Drift counts.** Ten new schemas take the gate from 56 to 66; no new chain event, so it stays 16.
  If the count moves another way, a schema was added and not mirrored (or the reverse).
- **Windows line endings.** `check-drift.mjs` normalises CRLF on read; a fresh clone without
  `core.autocrlf=false` will look broken if that line is ever "cleaned up".
