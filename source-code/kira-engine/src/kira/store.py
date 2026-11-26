from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import ConfigError

SETTINGS_KEYS = frozenset({"enabled", "priority", "tier", "monthly_cap"})
_MONTH_RE = re.compile(r"^(?P<year>\d{4})-(?P<month>0[1-9]|1[0-2])$")


def month_bounds(month: str | None = None) -> tuple[str, float, float]:
    """Half-open UTC window for "YYYY-MM"; `None` means the current calendar month."""
    now = datetime.now(timezone.utc)
    label = month if month is not None else f"{now.year:04d}-{now.month:02d}"
    match = _MONTH_RE.match(label)
    if not match:
        raise ConfigError(f"month must look like YYYY-MM, got '{label}'")
    year, number = int(match.group("year")), int(match.group("month"))
    start = datetime(year, number, 1, tzinfo=timezone.utc).timestamp()
    end = datetime(year + (number == 12), (number % 12) + 1, 1, tzinfo=timezone.utc).timestamp()
    return label, start, end


def _failure_reason(chain: list[dict]) -> str:
    """The newest thing the chain blames, so the Overview list is actionable at a glance."""
    for record in reversed(chain):
        if record.get("event") in ("failed", "aborted_mid_stream", "skipped_budget", "skipped_config"):
            return str(record.get("reason") or record.get("event"))
    return str(chain[-1].get("event")) if chain else ""


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

_DEVICES_DDL = (
    """CREATE TABLE IF NOT EXISTS devices (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        token_hash TEXT NOT NULL UNIQUE,
        created_at REAL NOT NULL,
        last_seen_at REAL NOT NULL,
        revoked_at REAL
    )""",
    "CREATE INDEX IF NOT EXISTS ix_devices_active ON devices(revoked_at)",
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


class Store:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        # One connection per thread, because FastAPI runs a sync route in a threadpool and a
        # single sqlite3.Connection used by two threads at once raises `InterfaceError` — measured
        # when a paired phone's first screen fired two reads in parallel. WAL lets the readers run
        # beside the one writer and `busy_timeout` makes a writer wait instead of failing.
        # `check_same_thread=False` stays only so `close()` may be called from any thread.
        self._local = threading.local()
        self._live: list[sqlite3.Connection] = []
        self._live_lock = threading.Lock()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), check_same_thread=False, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        with self._live_lock:
            self._live.append(conn)
        return conn

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                mode TEXT NOT NULL,
                created_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                role TEXT NOT NULL,
                content TEXT NOT NULL DEFAULT '',
                provider TEXT,
                model TEXT,
                finish_reason TEXT,
                status TEXT NOT NULL DEFAULT 'complete',
                tool_calls TEXT NOT NULL DEFAULT '[]',
                usage TEXT NOT NULL DEFAULT '{}',
                chain TEXT NOT NULL DEFAULT '[]',
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS ix_messages_session ON messages(session_id, id);

            CREATE TABLE IF NOT EXISTS provider_health (
                provider TEXT PRIMARY KEY,
                failures INTEGER NOT NULL DEFAULT 0,
                successes INTEGER NOT NULL DEFAULT 0,
                cooled_until REAL NOT NULL DEFAULT 0,
                last_reason TEXT NOT NULL DEFAULT '',
                updated_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS settings (
                provider TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                updated_at REAL NOT NULL,
                PRIMARY KEY (provider, key)
            );

            CREATE TABLE IF NOT EXISTS tool_policies (
                tool TEXT PRIMARY KEY,
                policy TEXT NOT NULL,
                updated_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS approvals (
                id TEXT PRIMARY KEY,
                session_id TEXT,
                tool TEXT NOT NULL,
                arguments TEXT NOT NULL DEFAULT '{}',
                risk TEXT NOT NULL,
                status TEXT NOT NULL,
                reason TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL,
                expires_at REAL NOT NULL,
                decided_at REAL
            );

            CREATE TABLE IF NOT EXISTS checkpoints (
                id TEXT PRIMARY KEY,
                session_id TEXT,
                tool TEXT NOT NULL,
                call_id TEXT NOT NULL DEFAULT '',
                scope TEXT NOT NULL DEFAULT 'files',
                files TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL,
                created_at REAL NOT NULL,
                finalized_at REAL,
                restored_at REAL
            );

            CREATE TABLE IF NOT EXISTS usage_ledger (
                month TEXT NOT NULL,
                provider TEXT NOT NULL,
                input_tokens INTEGER NOT NULL DEFAULT 0,
                output_tokens INTEGER NOT NULL DEFAULT 0,
                estimated INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (month, provider)
            );

            CREATE TABLE IF NOT EXISTS refusals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL,
                message TEXT NOT NULL,
                mode TEXT,
                model TEXT,
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS ix_refusals_created ON refusals(created_at);
            """
        )
        version = self._conn.execute("PRAGMA user_version").fetchone()[0]
        if version < 1:
            # Installs that predate the ledger keep their spend: the message rows are still
            # billed history, and the ledger starts as their sum rather than at zero.
            self._conn.execute(
                """INSERT OR IGNORE INTO usage_ledger(month, provider, input_tokens, output_tokens, estimated)
                   SELECT strftime('%Y-%m', created_at, 'unixepoch') AS month, provider,
                          COALESCE(SUM(json_extract(usage,'$.input_tokens')), 0),
                          COALESCE(SUM(json_extract(usage,'$.output_tokens')), 0),
                          COALESCE(MAX(json_extract(usage,'$.estimated')), 0)
                   FROM messages
                   WHERE role='assistant' AND provider IS NOT NULL
                   GROUP BY month, provider"""
            )
            self._conn.execute("PRAGMA user_version=1")
            version = 1
        self._conn.commit()
        if version < 2:
            self._migrate_v2(version)
            version = 2
        self._conn.commit()
        if version < 3:
            self._migrate_v3(version)
        self._conn.commit()

    @property
    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = self._connect()
            self._local.conn = conn
        return conn

    @property
    def conn(self) -> sqlite3.Connection:
        """This thread's live connection, for `memory.py`'s FTS5 queries — the only module that
        needs raw SQL this file does not own. Everything else goes through a method."""
        return self._conn

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

    def _migrate_v3(self, found: int) -> None:
        """The devices a phone pairs as — added, never rewritten, so old rows survive.

        Same transaction shape as `_migrate_v2`: a failure leaves the database at v2 and the
        next start retries instead of serving a half-created table.
        """
        try:
            self._conn.execute("BEGIN")
            for statement in _DEVICES_DDL:
                self._conn.execute(statement)
            self._conn.execute("PRAGMA user_version=3")
            self._conn.commit()
        except sqlite3.Error as exc:
            self._conn.rollback()
            raise ConfigError(
                f"could not upgrade {self.path} to schema 3 from version {found}: {exc}"
            ) from exc

    def add_device(self, name: str, token_hash: str) -> dict[str, Any]:
        """Register a paired device. Only the hash is stored; the token is the caller's to hand back."""
        device_id = uuid.uuid4().hex[:16]
        now = time.time()
        self._conn.execute(
            "INSERT INTO devices(id, name, token_hash, created_at, last_seen_at) VALUES(?,?,?,?,?)",
            (device_id, name, token_hash, now, now),
        )
        self._conn.commit()
        return {"id": device_id, "name": name, "created_at": now, "last_seen_at": now}

    def device_by_token_hash(self, token_hash: str) -> dict[str, Any] | None:
        """The live device behind a presented token, or None — revoked rows never authenticate."""
        row = self._conn.execute(
            """SELECT id, name, created_at, last_seen_at FROM devices
               WHERE token_hash=? AND revoked_at IS NULL""",
            (token_hash,),
        ).fetchone()
        return dict(row) if row else None

    def touch_device(self, device_id: str) -> None:
        self._conn.execute("UPDATE devices SET last_seen_at=? WHERE id=?", (time.time(), device_id))
        self._conn.commit()

    def list_devices(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """SELECT id, name, created_at, last_seen_at FROM devices
               WHERE revoked_at IS NULL ORDER BY created_at"""
        ).fetchall()
        return [dict(row) for row in rows]

    def revoke_device(self, device_id: str) -> bool:
        """False for an id that is unknown or already revoked — the caller decides 404 vs. gone."""
        cursor = self._conn.execute(
            "UPDATE devices SET revoked_at=? WHERE id=? AND revoked_at IS NULL",
            (time.time(), device_id),
        )
        self._conn.commit()
        return bool(cursor.rowcount)

    @staticmethod
    def new_session_id() -> str:
        return uuid.uuid4().hex[:16]

    def create_session(self, mode: str, session_id: str | None = None) -> str:
        sid = session_id or self.new_session_id()
        self._conn.execute(
            "INSERT OR IGNORE INTO sessions(id, mode, created_at) VALUES(?,?,?)",
            (sid, mode, time.time()),
        )
        self._conn.commit()
        return sid

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str = "",
        *,
        provider: str | None = None,
        model: str | None = None,
        finish_reason: str | None = None,
        status: str = "complete",
        tool_calls: list[dict] | None = None,
        usage: dict | None = None,
        chain: list[dict] | None = None,
    ) -> int:
        created = time.time()
        # Charged before the row lands: a crash between the two overcounts the month, which
        # over-spends a cap instead of quietly refunding it.
        if role == "assistant" and provider:
            self.record_usage(provider, usage or {}, when=created)
        cur = self._conn.execute(
            """INSERT INTO messages(session_id, role, content, provider, model, finish_reason,
                                      status, tool_calls, usage, chain, created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (
                session_id,
                role,
                content,
                provider,
                model,
                finish_reason,
                status,
                json.dumps(tool_calls or []),
                json.dumps(usage or {}),
                json.dumps(chain or []),
                created,
            ),
        )
        self._conn.commit()
        return int(cur.lastrowid or 0)

    def record_usage(self, provider: str, usage: dict, *, when: float | None = None) -> None:
        month = datetime.fromtimestamp(when or time.time(), timezone.utc).strftime("%Y-%m")
        record = usage or {}
        self._conn.execute(
            """INSERT INTO usage_ledger(month, provider, input_tokens, output_tokens, estimated)
               VALUES(?,?,?,?,?)
               ON CONFLICT(month, provider) DO UPDATE SET
                 input_tokens=input_tokens+excluded.input_tokens,
                 output_tokens=output_tokens+excluded.output_tokens,
                 estimated=MAX(estimated, excluded.estimated)""",
            (
                month,
                provider,
                int(record.get("input_tokens", 0)),
                int(record.get("output_tokens", 0)),
                int(bool(record.get("estimated", False))),
            ),
        )
        self._conn.commit()

    def messages(self, session_id: str, limit: int = 200) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM messages WHERE session_id=? ORDER BY id DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
        out = []
        for row in reversed(rows):
            d = dict(row)
            d["tool_calls"] = json.loads(d["tool_calls"])
            d["usage"] = json.loads(d["usage"])
            d["chain"] = json.loads(d["chain"])
            out.append(d)
        return out

    def list_sessions(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT id, mode, created_at FROM sessions ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def settings_map(self) -> dict[str, dict[str, str]]:
        rows = self._conn.execute(
            "SELECT provider, key, value FROM settings ORDER BY provider, key"
        ).fetchall()
        out: dict[str, dict[str, str]] = {}
        for row in rows:
            out.setdefault(row["provider"], {})[row["key"]] = row["value"]
        return out

    def set_setting(self, provider: str, key: str, value: object) -> None:
        if key not in SETTINGS_KEYS:
            raise ConfigError(f"'{key}' is not a tunable setting; settings holds {sorted(SETTINGS_KEYS)}")
        self._conn.execute(
            """INSERT INTO settings(provider, key, value, updated_at) VALUES(?,?,?,?)
               ON CONFLICT(provider, key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
            (provider, key, json.dumps(value), time.time()),
        )
        self._conn.commit()

    def clear_setting(self, provider: str, key: str) -> bool:
        cur = self._conn.execute("DELETE FROM settings WHERE provider=? AND key=?", (provider, key))
        self._conn.commit()
        return cur.rowcount > 0

    def delete_settings(self, provider: str) -> int:
        cur = self._conn.execute("DELETE FROM settings WHERE provider=?", (provider,))
        self._conn.commit()
        return int(cur.rowcount or 0)

    def tool_policies(self) -> dict[str, str]:
        rows = self._conn.execute("SELECT tool, policy FROM tool_policies ORDER BY tool").fetchall()
        return {row["tool"]: row["policy"] for row in rows}

    def set_tool_policy(self, tool: str, policy: str | None) -> str | None:
        from .policy import validate_policy  # local import: policy imports tools, not store

        if policy is None:
            self._conn.execute("DELETE FROM tool_policies WHERE tool=?", (tool,))
            self._conn.commit()
            return None
        value = validate_policy(policy)
        self._conn.execute(
            """INSERT INTO tool_policies(tool, policy, updated_at) VALUES(?,?,?)
               ON CONFLICT(tool) DO UPDATE SET policy=excluded.policy, updated_at=excluded.updated_at""",
            (tool, value, time.time()),
        )
        self._conn.commit()
        return value

    def add_approval(self, session_id: str | None, tool: str, arguments: dict, risk: str, expires_at: float) -> dict[str, Any]:
        approval_id = uuid.uuid4().hex[:16]
        self._conn.execute(
            """INSERT INTO approvals(id, session_id, tool, arguments, risk, status, created_at, expires_at)
               VALUES(?,?,?,?,?,'pending',?,?)""",
            (approval_id, session_id, tool, json.dumps(arguments), risk, time.time(), expires_at),
        )
        self._conn.commit()
        return self.get_approval(approval_id)

    def get_approval(self, approval_id: str) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT * FROM approvals WHERE id=?", (approval_id,)).fetchone()
        return None if row is None else self._approval_row(row)

    @staticmethod
    def _approval_row(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["arguments"] = json.loads(data["arguments"])
        return data

    def pending_approvals(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM approvals WHERE status='pending' ORDER BY created_at"
        ).fetchall()
        return [self._approval_row(row) for row in rows]

    def decide_approval(self, approval_id: str, decision: str, reason: str = "") -> dict[str, Any] | None:
        status = "allowed" if decision == "allow" else "denied"
        # A deny without a stated reason still needs one: the loop quotes it back to the model,
        # and an empty string turns that sentence into "The user denied permission to run "x". ."
        if status == "denied" and not reason:
            reason = "the user denied this call"
        cur = self._conn.execute(
            """UPDATE approvals SET status=?, reason=?, decided_at=?
               WHERE id=? AND status='pending'""",
            (status, reason, time.time(), approval_id),
        )
        self._conn.commit()
        return self.get_approval(approval_id) if cur.rowcount else None

    def expire_pending_approvals(self) -> int:
        cur = self._conn.execute(
            """UPDATE approvals SET status='expired', reason='the engine restarted', decided_at=?
               WHERE status='pending'""",
            (time.time(),),
        )
        self._conn.commit()
        return int(cur.rowcount or 0)

    @staticmethod
    def _checkpoint_row(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["files"] = json.loads(data["files"])
        return data

    def add_checkpoint(
        self, *, session_id: str | None, tool: str, call_id: str, scope: str, files: list[dict]
    ) -> dict[str, Any]:
        checkpoint_id = uuid.uuid4().hex[:16]
        self._conn.execute(
            """INSERT INTO checkpoints(id, session_id, tool, call_id, scope, files, status, created_at)
               VALUES(?,?,?,?,?,?, 'open', ?)""",
            (checkpoint_id, session_id, tool, call_id, scope, json.dumps(files), time.time()),
        )
        self._conn.commit()
        return self.get_checkpoint(checkpoint_id)

    def get_checkpoint(self, checkpoint_id: str) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT * FROM checkpoints WHERE id=?", (checkpoint_id,)).fetchone()
        return None if row is None else self._checkpoint_row(row)

    def finalize_checkpoint(self, checkpoint_id: str, files: list[dict]) -> dict[str, Any] | None:
        self._conn.execute(
            "UPDATE checkpoints SET files=?, status='complete', finalized_at=? WHERE id=?",
            (json.dumps(files), time.time(), checkpoint_id),
        )
        self._conn.commit()
        return self.get_checkpoint(checkpoint_id)

    def mark_checkpoint_restored(self, checkpoint_id: str) -> None:
        self._conn.execute(
            "UPDATE checkpoints SET status='restored', restored_at=? WHERE id=?",
            (time.time(), checkpoint_id),
        )
        self._conn.commit()

    def list_checkpoints(self, limit: int = 20, session_id: str | None = None) -> list[dict[str, Any]]:
        if session_id:
            rows = self._conn.execute(
                "SELECT * FROM checkpoints WHERE session_id=? ORDER BY created_at DESC, rowid DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM checkpoints ORDER BY created_at DESC, rowid DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._checkpoint_row(row) for row in rows]

    def prune_checkpoints(self, keep: int) -> list[str]:
        rows = self._conn.execute(
            "SELECT id FROM checkpoints ORDER BY created_at DESC, rowid DESC LIMIT -1 OFFSET ?", (keep,)
        ).fetchall()
        ids = [row["id"] for row in rows]
        if ids:
            self._conn.executemany("DELETE FROM checkpoints WHERE id=?", [(value,) for value in ids])
            self._conn.commit()
        return ids

    def monthly_spend(self, month_start: float, month_end: float) -> dict[str, int]:
        """Money outlives history: the ledger is charged as turns are written, so deleting
        sessions cannot refund a month. A partial generation was still billed, so
        interrupted and failed turns are in it too."""
        month = datetime.fromtimestamp(month_start, timezone.utc).strftime("%Y-%m")
        rows = self._conn.execute(
            "SELECT provider, input_tokens + output_tokens AS tokens FROM usage_ledger WHERE month=?",
            (month,),
        ).fetchall()
        return {row["provider"]: int(row["tokens"] or 0) for row in rows}

    def usage_for_month(self, month: str | None = None) -> tuple[str, dict[str, int]]:
        label, start, end = month_bounds(month)
        return label, self.monthly_spend(start, end)

    def record_refusal(
        self, code: str, message: str, *, mode: str | None = None, model: str | None = None, at: float | None = None
    ) -> None:
        """A plan-time refusal raises before `create_session`, so there is no row it could call its
        own. This ledger is the only place the engine can say a turn was asked for and never began."""
        self._conn.execute(
            "INSERT INTO refusals(code, message, mode, model, created_at) VALUES(?,?,?,?,?)",
            (code, message, mode, model, time.time() if at is None else at),
        )
        self._conn.commit()

    def refusal_summary(self, month_start: float, month_end: float, *, recent: int = 5) -> dict[str, Any]:
        window = (month_start, month_end)
        count = int(
            self._conn.execute(
                "SELECT COUNT(*) FROM refusals WHERE created_at >= ? AND created_at < ?", window
            ).fetchone()[0]
        )
        by_code = [
            {"code": row["code"], "count": int(row["n"])}
            for row in self._conn.execute(
                """SELECT code, COUNT(*) AS n FROM refusals
                   WHERE created_at >= ? AND created_at < ?
                   GROUP BY code ORDER BY n DESC, code""",
                window,
            )
        ]
        recent_rows = [
            {
                "code": row["code"],
                "message": row["message"],
                "mode": row["mode"],
                "model": row["model"],
                "created_at": float(row["created_at"]),
            }
            for row in self._conn.execute(
                """SELECT code, message, mode, model, created_at FROM refusals
                   WHERE created_at >= ? AND created_at < ?
                   ORDER BY created_at DESC, id DESC LIMIT ?""",
                (*window, int(recent)),
            )
        ]
        return {"count": count, "by_code": by_code, "recent": recent_rows}

    def overview(self, month_start: float, month_end: float) -> dict[str, Any]:
        # The label comes from the window itself, so a caller can never hand `overview`
        # a start and a string that name different months.
        month_label = datetime.fromtimestamp(month_start, timezone.utc).strftime("%Y-%m")
        window = (month_start, month_end)
        totals = self._conn.execute(
            """SELECT COUNT(*) AS turns,
                      COALESCE(SUM(json_extract(usage,'$.input_tokens')), 0) AS tokens_in,
                      COALESCE(SUM(json_extract(usage,'$.output_tokens')), 0) AS tokens_out,
                      SUM(status = 'interrupted') AS interrupted,
                      SUM(status = 'failed') AS failed
               FROM messages
               WHERE role = 'assistant' AND created_at >= ? AND created_at < ?""",
            window,
        ).fetchone()
        turns = int(totals["turns"])
        interrupted = int(totals["interrupted"] or 0)
        failed = int(totals["failed"] or 0)

        by_provider = [
            {"provider": r["provider"], "turns": int(r["turns"]), "tokens": int(r["tokens"] or 0)}
            for r in self._conn.execute(
                """SELECT provider, COUNT(*) AS turns,
                          SUM(COALESCE(json_extract(usage,'$.input_tokens'), 0)
                            + COALESCE(json_extract(usage,'$.output_tokens'), 0)) AS tokens
                   FROM messages
                   WHERE role = 'assistant' AND provider IS NOT NULL AND created_at >= ? AND created_at < ?
                   GROUP BY provider ORDER BY provider""",
                window,
            )
        ]
        by_model = [
            {"provider": r["provider"], "model": r["model"], "turns": int(r["turns"]), "tokens": int(r["tokens"] or 0)}
            for r in self._conn.execute(
                """SELECT provider, model, COUNT(*) AS turns,
                          SUM(COALESCE(json_extract(usage,'$.input_tokens'), 0)
                            + COALESCE(json_extract(usage,'$.output_tokens'), 0)) AS tokens
                   FROM messages
                   WHERE role = 'assistant' AND provider IS NOT NULL AND created_at >= ? AND created_at < ?
                   GROUP BY provider, model ORDER BY tokens DESC, provider, model""",
                window,
            )
        ]
        daily = [
            {"date": r["day"], "turns": int(r["turns"]), "tokens": int(r["tokens"] or 0)}
            for r in self._conn.execute(
                """SELECT date(created_at, 'unixepoch') AS day, COUNT(*) AS turns,
                          SUM(COALESCE(json_extract(usage,'$.input_tokens'), 0)
                            + COALESCE(json_extract(usage,'$.output_tokens'), 0)) AS tokens
                   FROM messages
                   WHERE role = 'assistant' AND created_at >= ? AND created_at < ?
                   GROUP BY day ORDER BY day""",
                window,
            )
        ]
        issues = []
        for row in self._conn.execute(
            """SELECT id, session_id, provider, model, status, created_at, chain
               FROM messages
               WHERE role = 'assistant' AND status IN ('interrupted','failed')
                 AND created_at >= ? AND created_at < ?
               ORDER BY created_at DESC, id DESC LIMIT 10""",
            window,
        ).fetchall():
            issues.append(
                {
                    "id": int(row["id"]),
                    "session_id": row["session_id"],
                    "provider": row["provider"],
                    "model": row["model"],
                    "status": row["status"],
                    "created_at": float(row["created_at"]),
                    "reason": _failure_reason(json.loads(row["chain"])),
                }
            )
        return {
            "month": month_label,
            "turns": turns,
            "tokens": {"input": int(totals["tokens_in"] or 0), "output": int(totals["tokens_out"] or 0)},
            # "no data" and "0% healthy" are different messages, so null is not 0.
            "success_rate": None if not turns else round((turns - interrupted - failed) / turns, 3),
            "interrupted": interrupted,
            "failed": failed,
            "by_provider": by_provider,
            "by_model": by_model,
            "daily": daily,
            "recent_issues": issues,
            "refusals": self.refusal_summary(month_start, month_end),
        }

    def session_rows(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """SELECT s.id, s.mode, s.created_at,
                      (SELECT COUNT(*) FROM messages m WHERE m.session_id = s.id) AS message_count,
                      (SELECT COALESCE(SUM(COALESCE(json_extract(m.usage,'$.input_tokens'), 0)
                                         + COALESCE(json_extract(m.usage,'$.output_tokens'), 0)), 0)
                         FROM messages m WHERE m.session_id = s.id) AS tokens,
                      (SELECT MAX(m.created_at) FROM messages m WHERE m.session_id = s.id) AS last_used_at
               FROM sessions s
               ORDER BY COALESCE(last_used_at, s.created_at) DESC, s.id DESC
               LIMIT ?""",
            (min(int(limit), 500),),
        ).fetchall()
        return [dict(row) for row in rows]

    def delete_session(self, session_id: str) -> tuple[int, int]:
        messages = self._conn.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id = ?", (session_id,)
        ).fetchone()[0]
        cur = self._conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        self._conn.commit()
        return int(cur.rowcount or 0), int(messages)

    def clear_sessions(self) -> tuple[int, int]:
        sessions = self._conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        messages = self._conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        # One statement pair, in child-first order, so a crash cannot leave orphans behind.
        self._conn.execute("DELETE FROM messages")
        self._conn.execute("DELETE FROM sessions")
        self._conn.commit()
        return int(sessions), int(messages)

    def upsert_health(
        self, provider: str, *, failures: int, successes: int, cooled_until: float, last_reason: str
    ) -> None:
        self._conn.execute(
            """INSERT INTO provider_health(provider, failures, successes, cooled_until, last_reason, updated_at)
               VALUES(?,?,?,?,?,?)
               ON CONFLICT(provider) DO UPDATE SET
                 failures=excluded.failures, successes=excluded.successes,
                 cooled_until=excluded.cooled_until, last_reason=excluded.last_reason,
                 updated_at=excluded.updated_at""",
            (provider, failures, successes, cooled_until, last_reason, time.time()),
        )
        self._conn.commit()

    def load_health(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self._conn.execute("SELECT * FROM provider_health").fetchall()]

    def close(self) -> None:
        with self._live_lock:
            conns, self._live = self._live, []
        for conn in conns:
            conn.close()
        self._local = threading.local()
