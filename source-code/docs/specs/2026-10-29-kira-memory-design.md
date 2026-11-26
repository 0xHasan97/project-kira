# Kira sub-project 4 — memory and retrieval

Date: 2026-10-29
Status: **implemented** 2026-10-29 → 2026-10-30 across M19–M22; the plan is
`docs/plans/2026-10-29-kira-memory.md`, the pass record is `docs/qa/memory-browser-pass.md`. The live
memory turn in §11 still waits on the Gemini key's daily quota. The four product choices were answered
by the user on 2026-10-29 (inject + recall tool · explicit capture with opt-in extraction · facts *and*
history · a real `#/memory` screen in both shells).
Depends on: sub-project 2 (tool registry, policies, step spine), sub-project 9 (confirm gate, settings
screen patterns), sub-project 10 (two shells, one route table).
Sibling slices: desktop shell (3), offline model (5), voice (6), avatar (11), remote (12).
Project-level ordering and completion arithmetic: `docs/ROADMAP.md`.

## 1. What this is

Kira forgets everything the moment a session ends. A call is a call the engine does not remember, and
a chat cannot answer "what did we decide about the router last week" even though every word is already
in SQLite. This sub-project gives Kira a memory that is local, inspectable and honest about what it is:

- **Facts** the user or the model chose to keep — a small, editable, forgettable table.
- **Historic recall** over the message rows that already exist, with a ranked lexical index.
- **Injection**: a bounded, labelled block prepended to the turn's system message, selected without a
  model call, so a weak model still gets what Kira knows.
- **A `recall` tool** so the model can search further than the block on its own initiative.
- **A `#/memory` screen** in both shells: search, add, pin, edit, forget, export. Nothing about the
  user is stored where the user cannot see or delete it.

The bundle is one SQLite file, two FTS5 tables and a `meta` row set. No new dependency, no service, no
download, no network.

## 2. Explicitly not in this spec

| Not here | Why | Lands in |
|---|---|---|
| Vector / embedding search | Needs either a local embedding model (a download, consent, ~100 MB) or a BYOK embedding endpoint (a new provider surface). Lexical BM25 is the honest default on a machine with neither, and `search.py` keeps one function to replace later | its own slice, after #5 chooses a local runtime |
| Session summarisation / rolling digests | A model call per session or per N turns, with all the silent-spend problems extraction has — and less inspectable than a fact list | reconsider with #7 skills |
| Cloud sync, multi-device memory | Loopback only; nothing leaves the machine | #12, if at all |
| Auto-extraction on by default | One extra model call per turn on the user's own key. PocketStrike ships exactly this with the toggle on (see §3) and it is the spend pattern the roadmap refuses | setting exists, default **off** |
| Indexing tool output, images, checkpoints | Tool output is the noisiest text in the store and can contain file contents; images have no text; checkpoints are restore data, not knowledge | never, stated |
| A memory browser inside the chat transcript | The screen is the audit surface; the transcript already names `remember` / `recall` in the step spine | never |
| Import | Export is the promise ("your memory is yours"); import is a restore path with merge semantics and its own confirm story | if asked |

## 3. Donor evidence

The two designs this roadmap has cited for unit 4 were read again this session, and the reading
changed the plan: only **one** of them is a retrieval design.

| Claim | Source |
|---|---|
| FTS5 with an own-content virtual table per base table, `UNINDEXED` join column, `porter unicode61` tokenizer, AFTER INSERT/DELETE/UPDATE triggers that mirror each mutation, `bm25()` ranking, backfill on create, and a `LIKE` fallback when the SQLite build has no FTS5 — "retrieval never hard-fails" | laya `engine/laya/db/fts.py:1-20, 90-190, 190-232` (Apache-2.0, inside `laya-main.zip`) |
| A safe MATCH builder: each surviving token quoted (internal quotes doubled) so `*`, `:`, `^`, `AND/OR/NOT` and parentheses from user text cannot raise inside MATCH; stopwords and short tokens dropped; `None` when nothing usable remains so the caller skips FTS rather than issuing an empty match | laya `engine/laya/db/fts.py:51-88` |
| Reciprocal Rank Fusion as the one shared fusion primitive: `score(d) = Σ 1/(k + rank_i(d))`, `k=60`, ids resolved across several id fields so lists dedupe consistently | laya `engine/laya/retrieval.py:1-20, 76-110` (Apache-2.0) |
| Memory as three markdown blobs (USER.md / MEMORY.md / SOUL.md) in app preferences, whole-document injection into the system prompt, append-only `addFact` / `addPreference`, one `autoEvolveEnabled` toggle **defaulting to true**, and a reset-to-defaults button | PocketStrike `lib/features/agent/data/hermes_memory_store.dart:1-180`, `lib/features/settings/ui/memory_settings_screen.dart` |
| No retrieval, no ranking, no budget, no per-fact deletion, no provenance at all in the above — `buildHermesSystemPrompt()` concatenates all three blobs in full on every turn | same file, `:110-150` |
| The user's own assistant has no memory system either: a hand-edited facts file injected as a prefix, plus a LangGraph checkpoint store that is conversation state | `Ai agents/project-Mia/core/memory.py`, `core/agent.py:100-134`; recorded in `docs/ROADMAP.md` §Donor intelligence |

What Kira takes, and what it refuses:

- **Takes** laya's FTS5 shape nearly whole (own-content tables, trigger sync, `bm25()`, quoted MATCH,
  `LIKE` fallback) because it is a proved, dependency-free retrieval layer on the same SQLite that
  Kira already runs — **except its tokenizer**, which is `porter unicode61` and measurably blind to
  CJK (D2 below); Kira uses `trigram`. No line of it is copied; `PROVENANCE.md` gets a row.
- **Takes** PocketStrike's three-way split as a *kind* vocabulary (`fact`, `preference`, `note`) —
  the useful part of USER.md / MEMORY.md / SOUL.md — and its single "auto-evolve" switch as
  `memory.extract`, **inverted to off**.
- **Refuses** whole-blob injection (unbounded tokens, stale facts always present, no way to say which
  memory was used), append-only growth (a wrong fact can only be out-voted, never removed) and an
  auto-evolve default that spends the user's credits without a click.
- **Defers** laya's second half: their ChromaDB vector store and RRF across vector + lexical lists.
  RRF is meaningless with one ranked list, so §2 puts vectors out, and the seam is a single
  `search()` function rather than a hybrid engine with half its inputs faked.

## 4. Decisions, with the alternatives they beat

**D1 — Own-content FTS5 tables, not external-content.** `memory_fts(memory_id UNINDEXED, text,
tokenize='trigram')` and `messages_fts(message_id UNINDEXED, content, tokenize='trigram')`, each with
three triggers. *Alternative:* external-content tables (`content='messages'`)
— rejected: they halve text storage but require the `INSERT INTO fts(fts, rowid, …) VALUES('delete', …)`
dance in every trigger, and that is the classic way to get a silently desynced index. The cost here is
message text stored twice in a local file; the benefit is a `DELETE FROM fts WHERE message_id = old.id`
that cannot be wrong. laya made the same trade (its comment says "own-content") and it is the shape
this repo can test cheaply.

**D2 — `trigram`, chosen after measuring, with a fallback tokenizer for old SQLite builds.** The first
draft of this spec chose `porter unicode61` (laya's tokenizer) on the assumption that `unicode61` splits
CJK per character. Measured on the project's own SQLite 3.49.1, that assumption is **false**: a whole
CJK run is one token, so with `unicode61` or `porter unicode61` the queries `向量数据库`, `数据库` and
`向量` all return **zero** rows against a row that contains `向量数据库很有用` — a 100 % miss, not a
ranking weakness. `trigram` returns the row for `数据库` and `向量数据库`, ranks the document matching
all three English terms above the one matching a single term, and matches inflections by substring
(`decide` finds `decided` without stemming). Its costs, measured: no query shorter than 3 characters,
no Porter semantics, and roughly 3× the index tokens. *Alternative:* a word index **and** a trigram
index fused with RRF — that is laya's real shape, but it doubles the triggers and the merge for a gain
this product does not need yet; the two-index design stays the upgrade path, and `search.py` is the one
place it would change. *Fallback:* `CREATE VIRTUAL TABLE … tokenize='trigram'` raises
`OperationalError` on SQLite older than 3.34; the migration then recreates the table with `unicode61`,
records `meta.memory.tokenizer` so the Memory screen can say which one is live, and the LIKE fallback
(§10) is what keeps CJK from silently vanishing. That is laya's "retrieval never hard-fails" lesson
applied to the tokenizer itself.

**D3 — Selection is deterministic and free.** Pinned memories first, then BM25 matches against the last
user message, then most recently used; dedupe; stop at 12 memories or 1 500 characters. No model call,
no classifier. *Alternative:* an LLM picks relevant memories each turn — a second call per turn, and a
failure mode where memory silently stops working. *Alternative:* inject everything — PocketStrike's
shape, unbounded.

**D4 — One system message, merged, never persisted.** If the request's first message is `system`,
append a blank line and the block to it; otherwise prepend a new system message. The block is
`Known about the user (from your local memory; may be stale — say so if unsure):` followed by one line
per memory. The memory block is **never written to the messages table**, so history export and the
Sessions screen show only what was actually said. *Alternative:* a synthetic user message ("Context: …")
— rejected: it fabricates a turn the user did not take and pollutes `assistant.length === user.length`.

**D5 — `remember` is `allow` by default; `recall` is `read`/`allow`.** Both declare an explicit
`default_policy` on `ToolDef`, so the risk table is untouched. `remember` appends to a local,
user-visible, one-click-forgettable table — an approval prompt on every fact would train the user to
click through prompts, which is worse than the write. A per-tool override can still set `ask` or
`deny` for anyone who wants the gate, and the Tools screen shows both rows like any other tool.
*Alternative:* a new `memory` risk class — rejected: a fifth class with one member, and `policy.py`'s
`RISK_DEFAULTS` would need a UI story for a class that only two tools use.

**D6 — Three booleans in a new `meta` table, not in `settings`.** `memory.inject` (default true),
`memory.capture` (default `explicit`, `off` hides `remember`), `memory.extract` (default false). The
`settings` table is validated by `SETTINGS_KEYS` and merged per provider by `overrides.py`; a global
row there would need a `"*"` provider sentinel and would make `build_view` lie. A two-column `meta(key
TEXT PRIMARY KEY, value TEXT)` table is smaller than the sentinel and does not touch the provider
merge. *Alternative:* `config.yaml` only — rejected: the user asked for a setting, which means a click,
not a file edit.

**D7 — Every write is confirm-gated; reads are not.** `POST`/`PATCH`/`DELETE /v1/kira/memory…` and
`PUT /v1/kira/memory/settings` use the existing `require_confirm` dependency, so the confirm secret is
re-typed exactly as it is for provider writes and history deletes. `GET` (list, search, export,
settings) needs only the bearer token. *Alternative:* trust the bearer token for memory because it is
"only notes" — rejected: a memory row can steer every future answer, which makes it more sensitive than
a provider toggle.

**D8 — Extraction is a labelled purchase, and it fails silently in the only safe direction.** When
`memory.extract` is on, a completed turn with text triggers one router call ("list zero to three durable
facts about the user, one per line, or NONE"), capped at `max_tokens=200`, with no memory block and no
tools. New facts are deduped against existing normalised text, stored with `origin='auto'` and
`tokens_spent`, and the call's usage **is** added to the month ledger. Failure never fails the turn: it
is logged, and nothing is written. *Alternative:* a chain event `memory_extracted` — rejected: it would
describe work that happened after the answer, and it costs a contract event plus a README row for a
fact the Memory screen already shows with its token count.

## 5. Data model and migration

`kira-engine/src/kira/store.py` grows a `_init_schema_version_2()` step, keyed on
`PRAGMA user_version`, which is already the installed mechanism (`version < 1` seeds the ledger today).

```sql
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL DEFAULT 'fact',        -- fact | preference | note
    text TEXT NOT NULL,
    pinned INTEGER NOT NULL DEFAULT 0,
    origin TEXT NOT NULL DEFAULT 'user',      -- user | tool | auto
    session_id TEXT,                          -- when learned in a chat
    tokens_spent INTEGER NOT NULL DEFAULT 0,  -- the extraction call's cost for origin='auto'
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    last_used_at REAL,
    use_count INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_memories_pinned ON memories(pinned, updated_at);

-- tokenizer selected at runtime by _create_fts(); 'trigram' shown, see the note below
CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
    memory_id UNINDEXED, text, tokenize = 'trigram'
);
CREATE TRIGGER IF NOT EXISTS memory_fts_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memory_fts(memory_id, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER IF NOT EXISTS memory_fts_ad AFTER DELETE ON memories BEGIN
    DELETE FROM memory_fts WHERE memory_id = old.id;
END;
CREATE TRIGGER IF NOT EXISTS memory_fts_au AFTER UPDATE OF text ON memories BEGIN
    DELETE FROM memory_fts WHERE memory_id = old.id;
    INSERT INTO memory_fts(memory_id, text) VALUES (new.id, new.text);
END;

CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    message_id UNINDEXED, content, tokenize = 'trigram'
);
-- only what a person would search: user and assistant text, never tool output
CREATE TRIGGER IF NOT EXISTS messages_fts_ai AFTER INSERT ON messages
WHEN new.role IN ('user','assistant') AND length(trim(new.content)) > 0 BEGIN
    INSERT INTO messages_fts(message_id, content) VALUES (new.id, new.content);
END;
CREATE TRIGGER IF NOT EXISTS messages_fts_ad AFTER DELETE ON messages BEGIN
    DELETE FROM messages_fts WHERE message_id = old.id;
END;
CREATE TRIGGER IF NOT EXISTS messages_fts_au AFTER UPDATE OF content ON messages BEGIN
    DELETE FROM messages_fts WHERE message_id = old.id;
    INSERT INTO messages_fts(message_id, content)
    SELECT new.id, new.content
    WHERE new.role IN ('user','assistant') AND length(trim(new.content)) > 0;
END;

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at REAL NOT NULL
);
```

Both virtual tables are created by one helper, `_create_fts(conn, name, column)`, not by the literal
`CREATE` above: it issues the `trigram` statement first, and on `OperationalError` (SQLite < 3.34 has no
trigram tokenizer) retries the same statement with `tokenize = 'unicode61'` and continues. Either way it
writes `meta('memory.tokenizer', 'trigram' | 'unicode61')` — `GET /v1/kira/memory/settings` reports it
and the Memory screen prints it, so a user whose build fell back knows why CJK search is weaker. The
`meta` table is therefore created *before* the two virtual tables. On the fallback path every MATCH
query shorter than the tokenizer can see degrades to the `LIKE` tier (§10) instead of returning nothing.

The migration runs in one transaction: create tables, **backfill both indexes** from existing rows
(`INSERT INTO messages_fts(message_id, content) SELECT id, content FROM messages WHERE role IN
('user','assistant') AND length(trim(content)) > 0`), set `user_version = 2`, commit. A failure rolls
back and re-raises as `ConfigError` naming the database path and the version found, so the engine
refuses to start rather than serve a half-indexed history. `ON DELETE CASCADE` on `sessions` already
deletes messages; the FTS delete trigger fires per row, so no dangling index entries.

## 6. Recall assembly

New module `kira-engine/src/kira/memory.py`:

- `MemoryStore(store)` — CRUD, `search_facts(query, limit)`, `related(text, limit)`,
  `pinned(limit)`, `mark_used(ids)`, `settings()` / `set_settings(...)`, `search_history(query, limit)`.
- `fts_match(text, *, min_len=None, max_terms=8, match_all=False) -> str | None` — the quoted-token
  builder; exported so the tests can hit it with hostile input directly. `min_len` defaults to the live
  tokenizer's floor: 3 for `trigram`, 1 for the `unicode61` fallback (§5). A query whose tokens all fall
  below the floor is not sent to MATCH at all; the caller goes straight to the `LIKE` tier.
- `build_block(store, conversation, budget=1500, max_items=12) -> tuple[str, list[str]]` — the block and
  the ids it used. `""` and `[]` when memory is empty or `inject` is off.
- `inject(messages, block) -> list[Message]` — merge-at-index-0 or append-to-system, never mutating the
  caller's list.
- `snippet_sql` helper for `search_history`: `snippet(messages_fts, 1, '[', ']', '…', 12)`.

Selection order, exactly: pinned (newest first, at most 4) → BM25 matches for the last `user` message
in the conversation (at most 12) → recently used non-pinned (fills the remainder). A memory appears
once. A memory longer than the remaining budget is included only if it fits whole; a memory longer than
the whole budget is truncated at a word boundary and marked with `…`. Nothing is summarised.

Callers: the chat route (both streaming and non-streaming) and `voice/call.py`, each one line:
`messages = inject(messages, block)`. `mark_used(ids)` after a successful response is sent, not before,
so a turn that never reached the user does not inflate the count.

## 7. Tools

| Tool | Schema | Risk / default | Notes |
|---|---|---|---|
| `recall` | `query: string`, `limit?: integer (1-20, default 8)` | `read` / `allow` | Searches facts **and** history; returns dated lines `[2026-10-29] (session 3ad8…) …snippet…`. It searches every session including the current one — a tool handler receives only its arguments (`ToolHandler = Callable[[dict], …]`), and widening that signature to carry a session id would touch every tool for a duplicated line the model can recognise |
| `remember` | `text: string`, `kind?: fact\|preference\|note` | `write` / `allow` (D5) | Returns the stored id and the memory text; a duplicate (same text after normalising: lowercase, whitespace collapsed, trailing punctuation stripped) returns `already remembered` instead of a second row |

`remember` is not registered at all when `memory.capture = off`. Both tools appear in the step spine
(`tool ran remember("…") → ok, 214 chars`), so a turn that writes a memory says so in the transcript.

## 8. API surface (additive; `API_VERSION` 1 and `CONTRACT_VERSION` 2 stay)

| Method | Path | Body / query | Confirm | Returns |
|---|---|---|---|---|
| GET | `/v1/kira/memory` | `query?`, `kind?`, `pinned?`, `limit?` (50, max 200) | no | `{memories: [...], total, settings}` |
| POST | `/v1/kira/memory` | `{text, kind?, pinned?}` | yes | the row |
| PATCH | `/v1/kira/memory/{id}` | `{text?, kind?, pinned?}` | yes | the row, or 404 |
| DELETE | `/v1/kira/memory/{id}` | — | yes | `{deleted: id}`, or 404 |
| GET | `/v1/kira/memory/search` | `q`, `limit?` (20, max 50) | no | `{hits: [{session_id, message_id, role, snippet, created_at}]}` |
| GET | `/v1/kira/memory/export` | — | no | `{version: 1, exported_at, memories: [...]}` |
| GET | `/v1/kira/memory/settings` | — | no | `{inject, capture, extract, tokenizer}` (`tokenizer` read-only) |
| PUT | `/v1/kira/memory/settings` | any subset of the three booleans | yes | the settings |

Every write validates before touching the database: `text` trimmed, non-empty, ≤ 2 000 characters;
`kind` in the enum; `pinned` a bool; unknown keys rejected (the read-only `tokenizer` included — it is
an observation, not a setting). A bad body is **400 `config_error`**, the app's one validation shape
(`_validation_handler` maps FastAPI's 422 to it and names fields only), not a second error dialect. An
empty `q` on search returns an empty list, not an error. An unknown id on PATCH/DELETE is **404
`not_found`**, the shape checkpoints and approvals already return. The README endpoint table gains the
eight rows — `test_docs_match_engine` compares it against the route table and will fail otherwise.

## 9. Client

- `kira-chat/src/api.ts` — eight methods on `KiraClient`, following the existing shape (bearer token,
  `KiraApiError` with `body.code`, confirm header on writes).
- `kira-chat/src/screens/MemoryScreen.tsx` — two tabs.
  *Facts*: search field (debounced 250 ms), list of rows (`kind` chip, text, origin + tokens for
  `auto`, created date, pin toggle, edit, forget), an add form, the three settings toggles, and an
  Export button that downloads `kira-memory-YYYY-MM-DD.json`.
  *History*: search field over `messages_fts`, hits showing role, date, session id and the snippet
  with the match bracketed by the engine.
- `kira-chat/src/hash-route.ts` + the rail: one new route `#/memory`, icon `BrainCircuit`, present in
  both shells like every other screen.
- Styles: reuse `.table`, `.chip`, `.toolbar`; no new tokens.

## 10. Failure modes the engine refuses

- A hostile search string (`"`, `*`, `NEAR(`, `a OR b`, `col:value`, an emoji) must return results or
  an empty list, **never** a 500 — the MATCH builder quotes every token, and a residual `OperationalError`
  is caught and retried as a `LIKE` query, the same two-tier fallback laya uses.
- A CJK query, or any query under 3 characters, must not silently return nothing on a `trigram` build:
  the builder passes it to the `LIKE` tier directly (trigram cannot see a 2-character token), and the
  same is true for everything on a `unicode61` fallback build (§5).
- A memory write while the database is busy returns 503 with the retry hint the store already uses,
  not a partial row.
- Injection with an empty result adds **nothing** (no "you have no memories" preamble, no empty system
  message).
- A turn that fails before the first token does not `mark_used`, and does not extract.
- `memory.extract` on a turn whose provider then fails altogether writes no facts and adds no ledger
  row beyond the turn's own.

## 11. Testing

Engine (`kira-engine/tests/`):

- `test_memory_store.py` — CRUD, dedupe by normalised text, delete removes the FTS row (search for the
  old text finds nothing), update re-indexes, pinned ordering, `mark_used`, export shape, kind
  validation, 2 000-char refusal.
- `test_memory_search.py` — `fts_match` against hostile inputs (assert no exception and a safe
  expression), BM25 ordering (the row containing all terms outranks the one containing one), snippet
  bracketing, `LIKE` fallback when the FTS call raises (monkeypatched), history search excludes
  `tool` rows, empty/stopword-only query returns `[]`, a CJK fact is found by a CJK query (the measured
  D2 case: `向量数据库` against `向量数据库很有用`), and a 2-character query is served by the `LIKE` tier.
- `test_memory_migration.py` — build a v1 database by running the pre-migration schema and inserting
  messages, open it with `Store`, assert `user_version == 2`, both FTS tables answer for the old rows,
  `meta.memory.tokenizer == 'trigram'` on this build, the monkeypatched `OperationalError` path lands on
  `unicode61` and still answers for plain ASCII text, and a deliberately corrupt migration raises
  `ConfigError` naming the path.
- `test_memory_inject.py` — no block when `inject=off` or empty; system merge vs prepend; budget and
  cap; pinned first; mark_used only after a completed turn; the conversation list is not mutated.
- `test_memory_tools.py` — `recall`/`remember` registered with the documented defaults; `remember`
  absent when capture=off; dedupe; a tool-only turn still counts the tool run.
- `test_memory_api.py` — 401 without token; confirm required on POST/PATCH/DELETE/PUT; 404 on an
  unknown id; 400 `config_error` on empty text / bad kind / oversized text / unknown key (including
  `tokenizer` on PUT); export round-trips; search refuses to 500 on hostile `q`; settings read back.
- `test_memory_extract.py` — extract off by default; on, a completed turn writes facts with
  `origin='auto'`, dedupes, adds the call's usage to the ledger, and never fails the turn; a failed
  turn writes nothing.
- `test_docs_match_engine.py` — extended automatically by the new routes; the README rows are the
  implementation's obligation.

Client: `MemoryScreen.test.tsx` (render both tabs, add, edit, forget behind the confirm dialog, pin,
export click, settings toggle, error banner), plus the existing every-route test now rendering eight
routes in both shells.

Live pass (when the key's quota allows): one turn that says "remember that I prefer pnpm", assert the
fact exists in `GET /v1/kira/memory`, start a new session, ask a question that needs it, and assert the
answer used it and that `last_used_at` moved. Record it in `docs/qa/live-app-pass.md` as a new section
rather than a new file.

## 12. Milestones

- **M19 — storage.** Schema v2, triggers, tokenizer probe + `meta.memory.tokenizer`, backfill,
  `memory.py` store + `fts_match`, migration tests.
- **M20 — recall and tools.** `build_block`/`inject`, chat + voice wiring, `recall`/`remember`,
  `mark_used`, tool and injection tests.
- **M21 — API and contract.** Eight routes, validation, confirm gating, contract schemas + TS mirror +
  drift gate, README rows, client methods.
- **M22 — screen, docs and pass.** `#/memory` in both shells, styles, client tests, README/ROADMAP
  sections, a browser pass and (quota permitting) the live memory turn.

## 13. Risks, stated

- **BM25 misses paraphrases.** "my preferred package manager" will not match a fact that says "uses
  pnpm" unless the shared token is there. Pinned memories are the hedge, and §2 puts vectors on the
  roadmap rather than pretending lexical search is semantic.
- **A wrong auto-extracted fact can persist.** Mitigations: off by default, dedupe, `origin='auto'`
  visible with its token cost, one-click forget, and extraction capped at three facts per turn.
- **The injected block is a prompt-injection surface** if a memory contains hostile text — but the
  same is true of anything the user types, and the only writer is the user or the model they are
  already talking to. No tool output is indexable, which removes the realistic vector.
- **Index size grows with history.** Own-content duplicates message text; a multi-year history could
  reach tens of MB, which SQLite handles, and `DELETE` from the Sessions screen prunes both.
- **`remember` writing without an approval prompt is a deliberate asymmetry** with every other write.
  It is documented on the tool, on the Tools screen row and in the README; a per-tool override restores
  the prompt.
