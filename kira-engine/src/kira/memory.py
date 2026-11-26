from __future__ import annotations

import json
import re
import sqlite3
import sys
import time
import uuid
from typing import Any

from .errors import ConfigError
from .loop import _estimate_usage
from .router import AttemptState
from .store import Store
from .tools import ToolDef
from .types import Completed, Delta, GenRequest, Message, Usage

KINDS = ("fact", "preference", "note")
CAPTURES = ("off", "explicit")
DEFAULTS: dict[str, Any] = {"inject": True, "capture": "explicit", "extract": False}
MAX_TEXT = 2000
BLOCK_HEADER = "Known about the user (from your local memory; may be stale — say so if unsure):"
BLOCK_BUDGET = 1500
BLOCK_ITEMS = 12
EXTRACT_PROMPT = (
    "You maintain a local memory of durable facts about the user. Read one exchange and list zero to "
    "three durable facts, one per line, no numbering, no commentary. A durable fact is a stable "
    "preference, constraint or piece of context — not a question, not a task, not small talk. "
    "If there is nothing durable, reply exactly NONE."
)
EXTRACT_MAX_OUTPUT_TOKENS = 200
EXTRACT_MAX_FACTS = 3
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


def _parse_facts(raw: str) -> list[str]:
    """Every line that could be a fact, cleaned. The cap belongs after dedupe, in `add_auto`."""
    facts: list[str] = []
    for line in raw.splitlines():
        clean = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", line).strip()
        # Three characters is the floor the brief's boundary test pins (`a`, `bb` out; `ccc` in).
        if not clean or clean.upper() == "NONE" or len(clean) < 3 or len(clean) > 500:
            continue
        # Models decorate the sentinel: NONE., **NONE**, `NONE` are all the same "nothing".
        if re.fullmatch(r"[\W_]*NONE[\W_]*", clean, re.IGNORECASE):
            continue
        facts.append(clean)
    return facts


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

    def add_auto(
        self, facts: list[str], *, session_id: str | None, tokens_spent: int
    ) -> list[dict[str, Any]]:
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
        # `rowid` is the tiebreak: on Windows `time.time()` ticks every 15.6 ms, so two facts added
        # in the same breath share an `updated_at` and the newest would otherwise sort arbitrarily.
        rows = self._conn.execute(
            "SELECT * FROM memories WHERE pinned=1 ORDER BY updated_at DESC, rowid DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [_item(row) for row in rows]

    def recent(self, limit: int = 12) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """SELECT * FROM memories WHERE pinned=0
               ORDER BY COALESCE(last_used_at, updated_at) DESC, rowid DESC LIMIT ?""",
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

    def _floor(self) -> int:
        return 3 if self.tokenizer == "trigram" else 1

    def _filters(self, kind: str | None, pinned: bool | None) -> tuple[str, tuple]:
        """The `kind`/`pinned` predicate, already qualified for the `m` alias, and its parameters."""
        clauses: list[str] = []
        params: list[Any] = []
        if kind:
            clauses.append("m.kind=?")
            params.append(kind)
        if pinned is not None:
            clauses.append("m.pinned=?")
            params.append(int(pinned))
        return " AND ".join(clauses), tuple(params)

    @staticmethod
    def _tail(extra: str) -> str:
        """How a filter clause attaches to a tier that already has a `WHERE`."""
        return f" AND {extra}" if extra else ""

    def _fact_rows(self, where: str, params: tuple, limit: int) -> list[dict[str, Any]]:
        # `rowid` tiebreaks for the same reason it does in `pinned`: one Windows clock tick covers
        # several facts, and the newest of those should still come first.
        return [
            _item(row)
            for row in self._conn.execute(
                f"SELECT m.* FROM memories m WHERE {where} "
                "ORDER BY m.pinned DESC, m.updated_at DESC, m.rowid DESC LIMIT ?",
                (*params, limit),
            )
        ]

    def _count(self, where: str, params: tuple) -> int:
        """How many facts a predicate matches, regardless of the page's limit."""
        return int(
            self._conn.execute(
                f"SELECT COUNT(*) FROM memories m WHERE {where}", params
            ).fetchone()[0]
        )

    def _match_rows(
        self, query: str, limit: int, extra: str, extra_params: tuple
    ) -> list[dict[str, Any]] | None:
        """Ranked MATCH rows, or `None` when there is nothing to match or MATCH refused the query."""
        match = fts_match(query, min_len=self._floor())
        if not match:
            return None
        try:
            return [
                _item(row)
                for row in self._conn.execute(
                    f"""SELECT m.*, bm25(memory_fts) AS score
                        FROM memory_fts JOIN memories m ON m.id = memory_fts.memory_id
                        WHERE memory_fts MATCH ?{self._tail(extra)} ORDER BY score LIMIT ?""",
                    (match, *extra_params, limit),
                ).fetchall()
            ]
        except sqlite3.OperationalError:
            return None

    def _match_total(self, query: str, extra: str, extra_params: tuple) -> int:
        """The MATCH tier's size before the limit, over the expression and filter that made the page."""
        match = fts_match(query, min_len=self._floor())
        if not match:  # unreachable from a page that MATCH produced; keeps the helper total
            return 0
        return int(
            self._conn.execute(
                f"""SELECT COUNT(*) FROM memory_fts JOIN memories m ON m.id = memory_fts.memory_id
                    WHERE memory_fts MATCH ?{self._tail(extra)}""",
                (match, *extra_params),
            ).fetchone()[0]
        )

    def _like_rows(
        self, query: str, limit: int, extra: str, extra_params: tuple
    ) -> list[dict[str, Any]]:
        where = "m.text LIKE ? ESCAPE '\\'" + self._tail(extra)
        return self._fact_rows(where, (like_pattern(query), *extra_params), limit)

    def _like_total(self, query: str, extra: str, extra_params: tuple) -> int:
        where = "m.text LIKE ? ESCAPE '\\'" + self._tail(extra)
        return self._count(where, (like_pattern(query), *extra_params))

    def search_facts(self, query: str, limit: int = 12) -> list[dict[str, Any]]:
        """MATCH first for a ranked answer, LIKE when MATCH cannot see the query or finds nothing.

        Two tiers because FTS5 can be blind without failing: on a `unicode61` build a CJK run is one
        token, and a two-character query is below `trigram`'s floor. Returning nothing there would be a
        silent lie; the LIKE tier is slower and unranked, which is the right price for "never empty".
        """
        rows = self._match_rows(query, limit, "", ())
        if rows:
            return rows
        return self._like_rows(query, limit, "", ())

    def search_history(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        """Ranked hits over the conversation text already in the store. Tool output is never indexed."""
        if not query or not query.strip():
            return []
        match = fts_match(query, min_len=self._floor())
        # A score tie is broken newest-first: identical text scores identically, and one Windows
        # clock tick covers several messages, so leaving the order to SQLite would be luck.
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
                       ORDER BY bm25(messages_fts), m.created_at DESC, m.id DESC LIMIT ?""",
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
                   ORDER BY m.created_at DESC, m.id DESC LIMIT ?""",
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

    def list(
        self,
        *,
        query: str | None = None,
        kind: str | None = None,
        pinned: bool | None = None,
        limit: int = 50,
    ) -> tuple[list[dict[str, Any]], int]:
        """A page of facts and how many the predicate matches before that page's limit."""
        where, params = self._filters(kind, pinned)
        if query:
            rows = self._match_rows(query, limit, where, params)
            if rows:
                return rows, self._match_total(query, where, params)
            return self._like_rows(query, limit, where, params), self._like_total(
                query, where, params
            )
        return self._fact_rows(where or "1=1", params, limit), self._count(
            where or "1=1", params
        )

    def export(self) -> dict[str, Any]:
        # Insertion order, so the document reads chronologically even when the clock is coarse.
        rows = self._conn.execute("SELECT * FROM memories ORDER BY created_at, rowid").fetchall()
        return {"version": 1, "exported_at": time.time(), "memories": [_item(row) for row in rows]}


def build_block(
    memory: MemoryStore,
    conversation: list[Message],
    *,
    budget: int = BLOCK_BUDGET,
    max_items: int = BLOCK_ITEMS,
) -> tuple[str, list[str]]:
    """The turn's memory block and the ids it used. No model call, no classifier, no surprises.

    Pinned first, then BM25 matches for the last user message, then whatever was used most recently —
    each memory once, inside both the item cap and the character budget. A fact too long for what is
    left of the budget is left out whole; only a fact longer than the whole budget is cut, at a word
    boundary, and marked `…`. Nothing is summarised: a summary would be a second model, and a wrong
    one is invisible.
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
