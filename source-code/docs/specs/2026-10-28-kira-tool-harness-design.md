# Kira sub-project 2 — tool harness, permissions, checkpoints, declarative plugins

Date: 2026-10-28
Status: designed under the user's standing "do the full project step by step" mandate; planning next.
Depends on: sub-project 1 (spine), sub-project 9 (control dashboard), sub-project 10 (shell modes).
Sibling slices: desktop shell (3), memory (4), offline model (5), voice (6), avatar (11), remote (12).
Project-level ordering and completion arithmetic: `docs/ROADMAP.md`.

## 1. What this is

Kira's agent loop (`kira-engine/src/kira/loop.py`) already calls tools; the registry holds two
harmless demos (`kira-engine/src/kira/tools.py:70`). This sub-project turns that interface into a
harness an agent can actually be trusted with:

- **Real tools** confined to a workspace directory: list, read, search, write, run a command.
- **A policy per tool** — `allow`, `ask`, `deny` — stored in SQLite, editable from the app, with a
  live approval channel for `ask` while the turn is still streaming.
- **Checkpoints** of every file a write tool is about to change, with diff and restore.
- **Declarative plugins**: HTTP tool definitions in JSON, loaded at startup, carrying no executable
  code — the compliant substitute for Ultron's `self_evolution.py` promised by the shell-modes
  spec §8 (`docs/specs/2026-10-28-kira-shell-modes-design.md:302`).
- **The two spend-accounting findings** from sub-project 9's browser pass that touch this code:
  delete-all re-arming monthly caps, and a provider omitting `usage` under-reporting spend.

It also fills the five Agent work-panel tabs that have said "sub-project 2" since 2026-10-28:
Changes, Terminal, Tests, Problems, Checkpoints (`kira-chat/src/screens/AgentPanel.tsx:34-40`).

## 2. Explicitly not in this spec

| Not here | Why | Lands in |
|---|---|---|
| Network egress as a builtin tool | A generic `fetch_url` is an exfiltration primitive with no allowlist story; declarative HTTP plugins give named, reviewed endpoints instead | plugins below |
| Language-server diagnostics | Needs a process per language; the Problems tab reads failed tool outcomes honestly instead | #7 skills or its own slice |
| Scheduling/prompts when idle (Ultron `scheduling`) | Kira has no scheduler and no background turn | #6 voice / #7 skills |
| Screen, camera, microphone, BLE | Out of the product set (shell spec §8) | never |
| A permission profile (`read_only`/`standard`/`autonomous`) | Per-tool policies cover the same ground with less state; a profile is a second way to say the same thing | reconsider only if per-tool proves tedious |
| Remote/LAN tools | Ground rule: loopback only | #12 |
| Sandboxing the OS | `run_command` runs with the user's own privileges; default policy is `ask`, and the dialog says so | out of scope, stated not implied |

## 3. Donor evidence

Every mechanism below was read from donor source, never recalled, and all of it is reimplemented:

| Claim | Source |
|---|---|
| ALTREX risk vocabulary `LOW/MEDIUM/HIGH/FORBIDDEN`; `run_command` classified from executable+flags, not name; denial surfaces to the model as `ERROR: …` plus a `tool.denied` event | `ALTREX/packages/core/src/security/command-classifier.ts:3-7`, `policy.ts:15-21`, `tools/project-tools.ts:123-151` |
| ALTREX checkpoints: whole-project manifest (`path → sha256/size/mtime`, before/after) outside the project, ignored dirs and protected paths never captured, restore dry-runs then skips files changed since, retention 20, approval blocks the turn and deny/no-UI cancels | `ALTREX/packages/core/src/workspace/checkpoints.ts:12-27,58-59,145-189,211-221`, `security/approvals.ts:56-76`, `renderer/src/v4/Approvals.tsx:42-89` |
| PocketStrike `ToolRisk {safe, external, destructive}` × `ConfirmationPolicy {alwaysAsk, destructiveOnly, autonomous}`; denial does **not** abort, it appends "The user denied permission to run … Do not retry; explain the limitation instead." | `PocketStrike/lib/features/agent/domain/agent_tool.dart:4-44`, `data/agent_engine.dart:135-166` |
| Ultron `TOOL` module shape, startup-only scan of `actions/*.py`, import/validation failures logged and skipped, plugin loader with core-name collision rejection | `Ultron-main/core/action_loader.py:48-93,134-164,167-231`, `core/plugin_loader.py:180-228` |
| MYRAA declarative adapter: `method GET|POST`, `urlTemplate`, parameters with `in: path|query|header|body`, regex substitution + `encodeURIComponent`, unresolved placeholders rejected, secrets only as a credential **name** (never literal), redaction of secret-looking query keys | `MYRAA/src/api_hub/types.ts:77-100`, `adapterExecutor.ts:27-43,114-143,176-184`, `adapterRegistry.ts:79-81` |

What Kira does differently, on purpose:

- **Checkpoint scope is per-file, not whole-project.** AltRex snapshots a project before a task and
  falls back to a temp Git index over its limits. Kira takes a checkpoint when a write tool names
  its target, which is cheap, exact, and honest about what it does not cover (commands).
- **Secrets are Locker references.** MYRAA reads the secret from an environment variable; Kira's
  processes never receive provider or plugin secrets in their environment (see §5.4).
- **The model never sees a policy bypass.** A denied tool returns one sentence and the loop
  continues; the model cannot ask for a second opinion.

## 4. Decisions, with the alternatives they beat

**D1 — Policy is per tool, in SQLite, merged like provider settings.**
Table `tool_policies(tool TEXT PRIMARY KEY, policy TEXT, updated_at REAL)`; effective policy =
override or the tool's declared default. *Alternative:* a JSON file — rejected because the write
gate, validation and backup story already exist for SQLite. *Alternative:* the settings table keyed
`tool:<name>` — rejected because that table's `SETTINGS_KEYS` validation and provider merge assume
provider scoping, and bending it would make `build_view` lie.

**D2 — `ask` is an out-of-band approval that keeps the stream open.**
The SSE stream emits `{"type":"approval", …}`, the loop awaits an `asyncio.Event`, and a
confirm-gated `POST /v1/kira/approvals/{id}` resolves it. *Alternative:* end the turn with
"approval needed" and resubmit — rejected because the model would have to be re-fed the whole
conversation to continue, and the user's typed prompt would be paid for twice. *Alternative:* a
pre-turn checklist — rejected because tool arguments are only known mid-turn.

**D3 — Non-streaming requests cannot ask; they deny with a reason.**
There is no channel to deliver the question on. The model receives
`approval required for "<tool>", but this request is non-streaming and cannot be approved; tell the
user to retry in the chat window`. *Alternative:* block for 120 s hoping another client answers —
rejected because a hung non-stream request looks broken and holds a worker.

**D4 — `run_command` is argv-only, refuses a shell as `argv[0]`, has a minimal environment, a
30 s default timeout, and is never checkpointed.**
`cmd`, `cmd.exe`, `powershell`, `pwsh`, `bash`, `sh`, `zsh`, `wsl` as `argv[0]` are refused: without
that, "argv-only" is decoration. Environment is an allowlist (`PATH`, `PATHEXT`, `SystemRoot`,
`TEMP`, `TMP`, `USERPROFILE`, `HOME`, `LANG`) so a key that leaked into the launcher's environment
cannot leak into a child process. The approval dialog states that commands can change files without
a checkpoint, because they can.

**D5 — The workspace is a directory, defaulting to `data_dir/workspace`.**
Config key `workspace_dir`; relative values resolve against `data_dir`; the directory is created
at engine start. Every path argument resolves with symlinks and must remain under the root.
*Alternative:* a per-session directory — rejected because the agent needs to see what the previous
turn wrote, and the user's mental model is "a folder the agent works in".

**D6 — Plugins are JSON HTTP adapters, scanned once at startup.**
No Python is ever imported from a plugin directory. A malformed file is skipped with a reason that
the Tools screen shows. Adding a plugin requires a restart, stated in the README rather than
papered over with a watcher. This is MYRAA's declarative shape plus Ultron's discovery discipline,
with the Locker replacing env vars.

**D7 — Checkpoints record both states, not just the "before".**
Each file entry stores the blob before the write, its hash, and — finalized right after the tool
runs — the hash after. Restore compares the current hash with the "after" hash and reports the
files that changed since; a force flag overrides. Without an "after" hash, restore would silently
clobber later edits.

**D8 — Spend becomes a ledger, not a projection over history.**
`usage_ledger(month, provider, input_tokens, output_tokens, estimated)` is written in the same
transaction as the assistant row; `monthly_spend()` reads it. A one-time migration (`PRAGMA
user_version` 0→1) backfills from existing messages. Overview, Models and Sessions keep counting
messages, because they describe history; caps read the ledger, because they describe money.

**D9 — An omitted `usage` is estimated and labelled.**
When a provider returns no usage for a step that produced text, the loop estimates
`ceil(chars/4)` per direction, sets `estimated` on the usage, emits one `usage_estimated` chain
record, and the ledger stores the estimate with `estimated=1`. The wire gains
`usage.estimated` (additive).

## 5. The harness

### 5.1 Tools and their defaults

| Tool | Risk | Default policy | Behaviour |
|---|---|---|---|
| `echo`, `now` | `read` | `allow` | unchanged demos |
| `list_dir(path=".")` | `read` | `allow` | names + type + size, 500 entries, hidden files included |
| `read_file(path)` | `read` | `allow` | UTF-8 text, 128 KB cap with a truncation note; refuses NUL bytes as binary |
| `search_text(query, path=".")` | `read` | `allow` | literal search, 200 files / 50 hits / 1 MB scanned, skips binary and `.git` |
| `write_file(path, content)` | `write` | `ask` | 256 KB cap; checkpoint before the write; creates parent dirs |
| `run_command(argv, cwd=".", timeout_s=30)` | `exec` | `ask` | §D4; JSON `{exit_code, stdout, stderr, duration_ms, truncated}` |

Every tool returns a string (the registry's contract). Errors are `error: …` strings, never
exceptions — `ToolRegistry.execute` already guarantees that (`tools.py:55-67`).

`workspace_dir` validation: after creation, `resolve()` must be a directory, must not be the
filesystem root (`resolved != Path(resolved.anchor)`), and must not be `config.data_dir` itself —
the agent may work beside the database but never in the directory holding the database, config and
Locker references.

### 5.2 Paths, caps, and what is deliberately refused

`safe_path(root, raw)`:

1. Reject empty strings and any argument containing `\x00`.
2. `Path(raw)`; relative paths join `root`; `resolve()` (so symlinks are followed before the check).
3. Require `resolved == root` or `root in resolved.parents`; otherwise
   `error: path escapes the workspace`.
4. Return the resolved path.

Caps live in one module (`limits.py`) so a test can assert them rather than rediscover them:
read 128 KB, write 256 KB, search 1 MB / 200 files / 50 hits, list 500, output 8 KB per stream,
argv 64 items with 4096 chars each, timeout 1–120 s, checkpoint blob 8 MB per file, 50 checkpoints
retained, plugin file 64 KB, plugin response 32 KB.

### 5.3 Policy and approvals

Risk→default map: `read → allow`, `write → ask`, `exec → ask`, `network → ask`.
Effective policy = `tool_policies` override, else declared default. `tools_enabled=false` on a
request still disables the whole registry (existing flag, tested in `test_api.py`).

Approval lifecycle:

```
model asks for write_file
  policy=ask → INSERT approvals(status='pending') → chain: tool_approval_requested
  → SSE chunk {"type":"approval", id, tool, arguments, risk}
  → await event (approval_timeout_s, default 120)
  → POST /v1/kira/approvals/{id} {decision} + X-Kira-Confirm
  → allow → checkpoint → execute → chain: tool_executed
  → deny  → tool message "The user denied permission … Do not retry; explain the limitation instead."
            → chain: tool_denied → the step continues with the next call
  → timeout → status expired → treated as deny with reason "approval timed out"
```

At engine start every `pending` row becomes `expired`: a restart has no live waiter, so pretending
otherwise would let the UI show a button that cannot work. `GET /v1/kira/approvals` lists pending
rows (there is at most one per active turn under normal use, but the list is honest).

`POST` decision requires the confirm secret. The secret is the same one the dashboard uses; an
approval is a write to the machine.

### 5.4 Checkpoints

Storage:

```
data_dir/checkpoints/<id>/
    manifest.json          # files: [{path, existed, sha256_before, size, blob, sha256_after}]
    <n>.blob               # raw bytes before the write
```

Row `checkpoints(id, session_id, tool, call_id, scope, files_json, created_at, finalized_at,
restored_at, status)`. `scope` is `files` (a named target) or `files-uncovered` for a restore's own
safety snapshot. `status` ∈ `open | complete | restored | superseded`.

Flow: a `write` tool (policy allow or approved ask) → checkpoint of its `path` argument → execute →
finalize (`sha256_after` for each path, `status=complete`). A write that fails still finalizes, so
restore knows what state the tool left.

Restore (`POST /v1/kira/checkpoints/{id}/restore`, confirm-gated, optional `force`):

1. Compare each path's current hash with `sha256_after`; collect conflicts.
2. If conflicts and not `force` → `409` with `{conflicts: [{path, expected_after, actual}]}`.
3. Take a safety checkpoint of the current state (`tool="restore"`), so a restore is itself undoable.
4. Write each blob back atomically (temp file + `os.replace`); delete files that did not exist.
5. Mark `restored_at`, emit nothing to any stream (this is an out-of-band action).

Diff (`GET /v1/kira/checkpoints/{id}`) returns per file `{path, existed, changed, added, removed,
diff}`; `diff` is `difflib.unified_diff` capped at 200 lines, or `"binary differs"`.

Retention: after a new checkpoint, rows beyond the 50 newest are deleted with their directories;
`restored` rows are pruned with the rest, oldest first.

### 5.5 Declarative plugins

Location `data_dir/plugins/*.json`, scanned in `Engine.__init__`, one log line per file.

```json
{
  "name": "demo_lookup",
  "description": "Look up one demo record by id.",
  "risk": "network",
  "policy": "ask",
  "parameters": {
    "type": "object",
    "properties": {"id": {"type": "string"}},
    "required": ["id"]
  },
  "request": {
    "method": "GET",
    "url": "http://127.0.0.1:8996/demo/{id}",
    "query": {"units": "metric"},
    "headers": {"Accept": "application/json"},
    "timeout_s": 10
  },
  "secret_ref": "plugin/demo",
  "secret_header": "authorization",
  "secret_prefix": "Bearer "
}
```

Rules, each enforced with a test:

- Name `^[a-z][a-z0-9_]{2,39}$`; collisions with builtins or another plugin are skipped.
- `method` GET or POST; `url` must be `http://` or `https://`; `timeout_s` 1–30.
- Every `{placeholder}` must name a declared parameter; every parameter must be scalar; unknown or
  duplicate parameters are rejected at load. Substitution is `quote(value, safe="")`.
- `secret_ref`, when present, is read from the Locker at call time. A missing secret is an error
  outcome, never a call without the header. Secret values never appear in the registry, chain,
  logs or tool output; URL query values are logged with the value redacted when the key looks
  secret-bearing (`key`, `token`, `secret`, `password`, `auth`).
- POST bodies are JSON; 2 MB response cap; non-2xx becomes
  `error: HTTP 404 from demo_lookup`.
- The registry response carries `{file, name, status: loaded|skipped, reason}` — the Tools screen is
  how a user learns a plugin file was rejected without reading a log.

### 5.6 Spend accounting (the two findings)

1. **Caps re-arm after delete-all.** Fix per D8. `clear_sessions()` and `delete_session()` leave
   `usage_ledger` alone; a test deletes every session and asserts the cap still refuses. The
   Sessions screen gains one sentence: "deleting history does not refund the month".
2. **Omitted usage under-reports spend.** Fix per D9, tested with a stub provider that returns text
   and no usage: the ledger records the estimate and the done chunk carries `usage.estimated=true`.

## 6. API surface

All additions; `API_VERSION` and `CONTRACT_VERSION` stay as they are, per the contract's own rule
(`contracts.py:23-30`: a new field, schema or enum value is additive). `CHAIN_EVENTS` grows by
`tool_approval_requested`, `tool_denied`, `checkpoint_created`, `usage_estimated`;
`CHAT_CHUNK_TYPES` grows by `approval`.

| Method | Path | Gate | Returns |
|---|---|---|---|
| GET | `/v1/kira/tools` | token | `{tools: ToolInfo[], plugins: PluginInfo[]}` |
| PUT | `/v1/kira/tools/{name}` | confirm | `{tool: ToolInfo}`; body `{policy: allow\|ask\|deny\|null}` |
| GET | `/v1/kira/checkpoints` | token | `{checkpoints: CheckpointInfo[]}` (`limit`, `session_id` filters) |
| GET | `/v1/kira/checkpoints/{id}` | token | `{checkpoint, files: [diff]}` |
| POST | `/v1/kira/checkpoints/{id}/restore` | confirm | `{restored: [...], conflicts: [...], checkpoint_id}` or 409 |
| GET | `/v1/kira/approvals` | token | `{approvals: ApprovalInfo[]}` (pending only) |
| POST | `/v1/kira/approvals/{id}` | confirm | `{approval: ApprovalInfo}` or 404/409 |

`ChainRecord` gains optional `risk`, `summary`, `duration_ms`, `exit_code`, `kind` (`command` or
`test`), `checkpoint_id`, `approval_id`, `usage_estimated`. `WireUsage` gains `estimated`.
`tool_executed.summary` is the argv joined (command), the path (file tools), or the plugin name —
never arguments that could contain a secret; plugin summaries carry only the name and parameter
*keys*.

Tests classification (`kind: "test"`) is a documented heuristic over `run_command`: `argv` matches
`pytest`, `python -m pytest|unittest`, `npm test`, `npm run test`, `pnpm|yarn test`, `vitest`,
`jest`, `cargo test`, `go test`, `dotnet test`. Anything else is `command`. The Tests tab says
"classified by argv".

## 7. Client surfaces

- **Tools route** (`#/tools`, nav "Tools", both shells): registry table (name, source, risk, policy
  select, "reset" when overridden), plugin list with load status, checkpoints list with file count
  and a Restore button behind the existing confirm dialog (`confirm.tsx`).
- **Approval card** in the chat transcript: tool, risk, a truncated argument preview, Allow / Deny,
  and the confirm-secret field. It appears when the SSE `approval` chunk arrives; the assistant's
  live text stays above it. Denying sends `deny` and the card collapses to "denied".
- **Agent work panel**:
  - Changes — `write_file` records of the current turn, with path and chars; "open checkpoint"
    jumps to the Checkpoints tab.
  - Terminal — `run_command` records with argv, exit code, duration.
  - Tests — the subset classified `kind=test`, with pass/fail from `exit_code`.
  - Problems — failed tool records (`ok=false`, denials, timeouts) with their reason.
  - Checkpoints — the session's checkpoints from `GET /v1/kira/checkpoints?session_id=`, each with a
    Restore button.
  - Agents — the registry list from `GET /v1/kira/tools`, replacing "listed once sub-project 2 adds
    an endpoint".
- Chat shell gets the same approval card inside the transcript; it has no work panel, and this spec
  does not add one.

## 8. Invariants and failure handling

1. A tool can never read or write outside `workspace_dir`; symlink escapes are resolved before the
   check. Tested with a symlink and with `..`.
2. No shell is ever invoked by `run_command`; `argv[0]` allowlist check precedes execution.
3. The Locker is the only source of plugin secrets; a missing secret fails the call, never omits
   auth silently.
4. `X-Kira-Confirm` is never stored client-side (sub-project 9's rule), including in the approval
   card.
5. A `pending` approval from a previous process is `expired` after restart; the UI cannot approve
   a dead turn.
6. Deleting history does not change the month's spend; `monthly_spend` reads the ledger exclusively.
7. Denied tools do not abort the turn; the loop continues and the model is told not to retry.
8. A checkpoint dir that cannot be written aborts the write with
   `error: checkpoint failed: …` — no uncheckpointed write, ever.
9. The contract stays v2, `/v1`, 5 chunk types + `approval`, and the drift gate is regenerated in
   the same commit as any schema edit.

## 9. Testing

Engine (new files, all in `kira-engine/tests/`):

- `test_workspace_tools.py` — caps, escapes (symlink, `..`, absolute), binary refusal, truncation
  notes, `run_command` argv/shell refusal/env allowlist/timeout/exit code, deterministic outputs.
- `test_tool_policy.py` — defaults per risk, overrides, reset, unknown tool, validation, confirm
  gate on PUT, registry listing includes source and effective policy.
- `test_approvals.py` — ask→approval chunk→allow executes; deny appends the sentence and the loop
  continues; timeout; non-stream auto-deny; restart expiry; decision requires confirm; unknown id.
- `test_checkpoints.py` — before-state captured, finalize after hash, restore round trip, conflict
  409, force, safety checkpoint, retention, restore requires confirm, path escape impossible.
- `test_plugins.py` — valid load, every rejection rule, secret from a fake vault, missing secret,
  headers/query/body substitution, response cap, non-2xx, secret redaction in summaries.
- `test_spend_ledger.py` — migration backfill, add_message writes ledger, delete-one and clear-all
  leave it intact, month boundary.
- `test_usage_estimate.py` — provider omits usage → estimate, chain record, wire flag, ledger.
- `test_contract_v2.py` — additive assertions for the new events/chunks/schemas.

Client (Vitest):

- `ToolsScreen.test.tsx` — table renders registry/plugins/checkpoints; policy change goes through
  the confirm dialog; restore shows conflicts.
- `approval.test.tsx` — card renders on the chunk, allow/deny call the client with the secret, deny
  collapses.
- `AgentPanel.test.tsx` — six tabs read real turn data against a stubbed client.
- `App.test.tsx` / `hash-route.test.ts` — six routes, both shells.
- `api.test.ts` — new methods and URLs.

Gates: `npm run check`, `node kira-contracts/check-drift.mjs`, `pytest`; baselines today are
167 chat tests / 18 files and 191 engine tests (+1 skipped); the drift line grows in counts, not
version.

Browser pass (`docs/qa/tool-harness-browser-pass.md`): lab engine + mock provider on :8916/:8996
with a temp workspace; drive a write under `ask` (approve), a denied write, a command, a failing
command (Problems), a test-classified command, a checkpoint restore, a plugin call against the mock
server, and the policy change from `allow` to `deny`; screenshot each.

## 10. Rollback

Drop `tool_policies`, `approvals`, `checkpoints`, `usage_ledger` and their endpoints; delete
`tools.py`'s new handlers and `plugins/` scan; the client's Tools route and approval card are
additive components. The demos `echo`/`now` and the existing SSE chunks are untouched, so reverting
returns exactly sub-project 10's behaviour. The only irreversible part is data: checkpoints and the
usage ledger are new files/tables, and no existing table is rewritten except by the one-way
migration, which only *adds* rows.

## 11. Milestones

| Milestone | Content |
|---|---|
| M13 | Workspace + real tools (`list_dir`, `read_file`, `search_text`, `write_file`, `run_command`) with caps and path safety |
| M14 | Policy storage + registry endpoint + approval broker, SSE chunk, decision endpoint, deny semantics |
| M15 | Checkpoints: capture, finalize, diff, restore, conflicts, retention |
| M16 | Declarative plugins + Tools screen + nav route |
| M17 | Work-panel tabs, approval card, contract regeneration, documentation, browser pass |
| M18 | Spend ledger + usage estimation (the two #13 findings) and the Sessions copy |

M18 is sequenced last because it must not make the harness's tests chase two ledgers at once.
