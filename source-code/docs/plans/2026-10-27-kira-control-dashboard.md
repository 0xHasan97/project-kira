# Kira Control Dashboard (sub-project 9) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the single owner of one Kira install a browser control surface — spend per provider, key add/forget, enable/tier/priority tuning, router-enforced monthly token caps, and history deletion — as tabs beside the chat that already exists.

**Architecture:** The engine keeps owning truth. A SQLite `settings` table holds four tunable fields per provider as JSON scalars, merged per request over a read-only `config.yaml` baseline; the router, `/v1/models` and the dashboard all read that one merged view, so a toggle cannot disagree with a route. Reads need the bearer token; writes additionally need a **separate** `engine/confirm` Locker secret sent as `X-Kira-Confirm` and re-typed per write. Monthly spend is derived from the `messages` table, never accumulated. The UI is one React bundle, a hash route, five screens, no new dependencies.

**Tech Stack:** Python 3.12, FastAPI, SQLite (WAL), `keyring` (Windows Credential Locker), pytest + pytest-asyncio (`asyncio_mode=auto`), `httpx.MockTransport` fake providers. TypeScript, React 19, Vite 8, vitest + jsdom. Contracts-first: engine-generated `openapi.json` / `contract.json` / `VERSION` checked against a hand-written TS mirror by `kira-contracts/check-drift.mjs`.

**Spec:** `Kira/docs/specs/2026-10-27-kira-control-dashboard-design.md` (approved 2026-10-27). Read it before Task 1. This plan argues from it and records every place planning had to amend it, below.

## Global Constraints

- BYOK and local only. **No free-tier endpoint aggregation, no remote model-catalogue feed, no non-chat modalities.** Do not add a `LOCAL` router mode — offline inference is sub-project 5.
- Provider keys and the confirm secret live in the Windows Credential Locker via `Vault` (the confirm secret only for the engine; in the browser it only ever lives inside one dialog). Never write either to disk, to `engine.log`, to a response body, to a URL, or to `localStorage`. The engine bearer token is the one secret the browser holds, in `localStorage`, so a reload stays one click — see amendment 24.
- The engine binds loopback only (`127.0.0.1`); `Config.__post_init__` enforces it. Do not widen it.
- `config.yaml` is never rewritten by the dashboard. `name`, `kind`, `base_url`, `models` stay YAML-only; the dashboard shows them and points at the file.
- No new runtime dependencies in either package. Charts are inline SVG; styles extend `kira-chat/src/styles.css`.
- Never run the donor folders' installer `.exe` files. Reimplement, do not copy; anything studied from `Source code/freellmapi-main.zip` is UX reference only and stays recorded in `Kira/PROVENANCE.md`.
- **No git repository exists in `Kira/` yet**, and `git init` requires the user's explicit approval. Each task therefore ends with a **Checkpoint** step: run the given commands and confirm the given output. If the user has approved git before execution starts, also run the task's `git add`/`git commit` line at the checkpoint; the messages are supplied so history stays uniform.
- Commands run from these directories: engine → `Kira/kira-engine`, chat → `Kira/kira-chat`, contract gate → `Kira`. Shell is Git Bash on Windows. The engine venv interpreter is `kira-engine/.venv/Scripts/python.exe` (plain `python -m pytest` has no pytest installed).
- `Kira/.kira-data` must stay free of test residue; engine tests use `tmp_path` and `Vault("memory")`.

## Spec amendments found while planning

Each of these is a decision the spec left implicit or slightly wrong. They are part of the approved design now; do not re-litigate them mid-task, and do re-read them at review time.

1. **`OverviewResponse` gains `recent_issues`.** The Overview spec asks for "a list of the most recent `interrupted`/`failed` turns linking straight to their session transcript", but no published field carried it. `recent_issues` is that field: `[{id, session_id, status, provider, model, created_at, reason}]`, newest first, at most 10 rows, same month window as everything else.
2. **`FieldState` is four named schemas, not one generic.** OpenAPI has no generics, and the drift gate requires a `types.ts` interface for every schema name. They are `FieldStateBool`, `FieldStateInt`, `FieldStateStr`, `FieldStateCap`, each `{base, override, effective}`.
3. **Four usage row types become named schemas** — `ProviderUsage`, `ModelUsage`, `DailyUsage`, `BudgetRow` — because the Models screen consumes `by_model` too, and the drift gate only inspects top-level schemas, so inline item objects would be unprotected.
4. **The CLI keeps a list-only probe.** Spec line 63-64 says `models` switches to `probe.py`. It does: `probe_models()` (list_models only). The dashboard's Test button calls `probe_provider()` (list_models **plus** one 8-token completion). `--live` catalogue listing must not silently spend credits; only a clicked Test does.
5. **`confirm.ts` is `confirm.tsx`** — it renders a dialog, so it contains JSX. Everything the spec says about it still holds.
6. **`HealthResponse.configured` reports effective tier/priority**, not YAML values, so the chat sidebar and the Providers screen cannot disagree. Schema unchanged, no new field.
7. **A provider that is both over cap and cooling is reported over cap** (budget checked before the ledger filter, per spec). A candidate list emptied *before* the budget check (e.g. every provider missing a key) stays `providers_exhausted`; `budget_exhausted` requires at least one candidate to have reached the budget check and every one of those to have been dropped there.
8. **Disabling a provider in `CUSTOM` mode is a `config_error` naming it as disabled**, not the existing `unknown provider` message — the two are different facts and the user can only act on the accurate one.

Nine more amendments and six more findings came out of planning the later milestones. They are **argued in
full at the task that discovered them** — the lines below are the index, not the summary, and a task's own
text wins if the two ever seem to disagree:

| # | Decision | Argued in |
| --- | --- | --- |
| 9 | `LiveProbe` and `ProbeResponse` become one schema; `count` is renamed `model_count` | Task 8 |
| 10 | `SessionRow`, `MessageRow`, `RecentIssue`, `ProviderSettings` become named top-level schemas so the drift gate can see them | Task 8 |
| 11 | `DELETE /v1/kira/providers/{name}/cooldown` returns the whole `ProvidersResponse` | Task 8 |
| 12 | The `skipped_budget` chip label ships with the contract, not with the budget gate | Task 8 |
| 13 | A refused confirm is `unauthorized` 401, a malformed body is `config_error` 400, and a 422 body is sanitized because it echoes the submitted value | Task 8 |
| 14 | A 401 from a write re-opens the dialog instead of leaving a bare error in a table cell — so `useWrite`/`run` loops, and every pass needs a fresh keystroke | Task 14 |
| 15 | A 429 refusal must carry its chain to the client and point at the screen that raises the cap; the "exactly N tokens left" promise is banned | Task 16 |
| 16 | A `by_model` row with no configured row is shown and marked `no longer configured`, never dropped | Task 17 |
| 17 | The Models table states the `config.yaml` rule **once** above the table instead of per row, and has no editable cell at all | Task 17 |
| 18 | `ConfirmRequest` gains `phrase?: string`: clear-all needs typed words, and those words stop at the dialog | Task 18 |
| 19 | Amendment 14's re-ask loop is extracted into `useWrite` rather than copied into a second screen | Task 18 |
| 20 | "README matches the engine" becomes a test, because a section nobody can check is not an acceptance criterion | Task 19 |
| 21 | The documented client gate is `npm run check`, not `npm test` — the weaker gate hides the failures that matter | Task 19 |
| 22 | The live pass gets checked-in dev tools (`tools/mock_openai.py`, `tools/kira_lab.py`) instead of running against your install, your credits and your Locker | Task 20 |
| 23 | The `Router.events()` note repetition is recorded as observed behaviour, not fixed inside a proof | Task 20 |
| 24 | The security rule is narrowed to what the code does: provider keys and the confirm secret never reach web storage; the loopback bearer token deliberately does, so reloads stay one click | Global Constraints, Task 19 |
| 25 | `App.test.tsx`'s `beforeEach` also resets `window.location.hash` — jsdom carries it across tests, and the route test writes it, so the default-route test failed on its predecessor's hash | Task 2, found by running Step 2 |
| 26 | The placeholder assertion matches the literal `"Dashboard is arriving in M9."`, not `/dashboard is arriving in M9/` — a regex matcher is case-sensitive and the rendered sentence starts with a capital | Task 2, found by running Step 2 |
| 27 | `set_setting(provider, key, value)` takes a **Python object** and stores `json.dumps(value)`; a test that wants the stored text `"fast"` passes `"fast"`, not `'"fast"'` | Task 3, found by running Step 5 |
| 28 | `load_config` validates while reading, so the bad-YAML loop calls it **inside** `pytest.raises` — the plan's `loaded = load_config(...)` binding raised out of the block and failed a test for the right reason | Task 4, found while writing Step 3 |
| 29 | `Scripted.calls` entries are `host + url`, not a bare URL, so call assertions use `in` (the convention every earlier routing test already follows) | Task 5, found by running Step 5 |
| 30 | Store tests seed timestamps **inside the month they aggregate** and pin an empty session's `created_at`: `create_session`/`add_message` stamp the real clock, so a `1.0` seed is January 1970 and an unseeded sibling outranks the busy session | Task 6, found by running Step 4 |
| 31 | `ProbeResult.to_wire()` renames the CLI's `count` to `model_count`, so `LiveProbe.count` in `kira-contracts/types.ts` is stale from this task until Task 8 folds it into `ProbeResponse`; nothing reads `live` in the client yet, and the drift gate only counts declared schemas, so the gate stays green in between. Step 5 also needs `from .probe import probe_models` in `app.py` and the now-unused `ProviderCallError` dropped from `__main__.py:12` | Task 7, found by running Steps 5-6 |
| 32 | `test_api.py`'s required-fields check read `MessagesResponse.properties.messages.items` **inline**; v2 makes it a `$ref`, so the test needs a one-hop `_items()` resolver before Step 6 can pass. Nothing in Task 8 predicted that a consumer of the old inline shape already existed | Task 8, found by running Step 6 |
| 33 | Three v2 follow-ons the task text missed: `api.test.ts:14` asserted `contract_version` is literally `1` (now the imported `CONTRACT_VERSION`); the Step 10 budget fixture put `skipped_budget` only in streamed `chain` chunks, but `turn.ts:49` lets a non-empty `done.provider_chain` **replace** them, so the record must be in both; and the published totals are 39 schemas over 13 paths (the task said 32 and 12 — 32 predates the four `FieldState` splits and 12 forgot `/healthz`) | Task 8, found by running Steps 7 and 11 |

| 34 | `/v1/kira/sessions` loses its `min(limit, 200)` boundary clamp because `store.session_rows()` clamps to 500 inside the store — the guard moves, it does not disappear | Task 9, found by running Step 4 |
| 35 | Step 1's fourth `useAsync` test cannot detect staleness as written: the rerender starts a second request and the shared `release` handle is reassigned by its executor, so `release(1)` resolves the **current** call and the hook correctly shows `ready`. Keep one resolver per call and release the first (stale) one, then the second, and the guard is actually exercised | Task 10, found by running Step 4 |
| 36 | Step 9's assertions name strings the Step 6 fixture never produces: `was 100` cannot render because a `was …` line appears only for an **overridden** field and openrouter's priority has no override (assert `was 50` from groq's tuned priority and `was on` from openrouter's tuned `enabled`, plus that `was 100` is absent), and the tokens card reads `16,800` not `12,800` because the fixture's split is `12000 + 4800` | Task 10, found by running Step 11 |
| 37 | Step 9's empty-month half cannot work as written: `KiraClient` binds `fetch` at construction (`api.ts:29`), so a second `connectedTo(empty)` on a mounted app still talks to the first engine. Unmount, re-stub, re-render — which is also what a month rollover looks like to a user who reloads the page | Task 10, found while writing Step 9 |
| 38 | Step 10's `.bar`, `.bar-used`, `.bar-label` collide with the app header's existing `.bar` rule (`styles.css:157`, `display:flex`), which would have crushed the top strip to `height: 1.15rem; overflow:hidden`. The budget bar is `.budget-bar / .budget-used / .budget-label / .budget-high / .budget-over / .budget-unlimited`, and `.screen` gained `overflow-x: auto` because the eight-column table made the **page** scroll sideways (measured at 531px: `document.scrollWidth` 843 vs `clientWidth` 516; after the fix the table scrolls inside its own section) | Task 10, found by reading the stylesheet then measuring in a browser |
| 39 | Step 12's hand-check command is `kira-engine serve`, not `run` — and `serve` **ignores** `--backend`: `cmd_serve` calls `create_app(config)` with no vault, so `Engine.__init__` builds `Vault()` = keyring and the "memory" run minted a real Locker `engine/token` (deleted after the check; `keys list` shows every ref `present: false`). Do the check against a throwaway `--data-dir` sibling of `.kira-data` so the user's data dir stays clean — and it must be a *sibling*, because `chat_dist_dir()` is `data_dir.parent / kira-chat / dist`. Task 11 owns the `serve --backend` fix, since it already edits `__main__.py` | Task 10, found by running Step 12 |
| 40 | The live check caught a contract lie: `store.overview()` groups a failed turn into `by_model` with `model: null` (no model was ever reached), but `ModelUsage.model` was `string` in `contracts.py` and `types.ts`. It is now `["string","null"]` / `string \| null`, the Overview names it `no model reached`, and the fixture carries such a row so a test covers the branch. Dropping the row instead would have made the table add up to less than the stat card above it | Task 10, found by reading a real engine response |
| 41 | Step 8's `serve --backend` fix (promised to this task by item 39) is a behavioural bug, not a cosmetic one: `cmd_serve` called `create_app(config)` with no vault, so `KIRA_VAULT=memory` was ignored and a memory run wrote both engine secrets to the Locker. It now passes `Vault(args.backend)`, and a test monkeypatches `uvicorn.run` to assert `app.state.engine.vault.backend == "memory"` and `host == "127.0.0.1"` | Task 11, found while doing item 39's hand-check |
| 42 | Step 9's predicted counts are one out: 125 passing at Step 9, not 124, because of item 41's serve regression test. Step 5's 122 was exact | Task 11, found by running the step |
| 44 | The contract ran ahead of the engine and nothing could see it: Task 8 documented seven write operations (settings PUT, key PUT/DELETE, cooldown DELETE, probe POST, one-session DELETE, all-sessions DELETE) that no decorator implements, and `check-drift.mjs` never compared `paths` against the route table. `test_versioning.py` now asserts the documented-but-unregistered set **equals** an explicit `UNIMPLEMENTED` whitelist, so Task 12 has to empty it and a future path documented with no code behind it fails the suite | Task 11.5, found while making the drift gate notice a renamed prefix |
| 45 | The version gate is a pure ASGI class, not `@app.middleware("http")`. Two traps decided it: an exception raised inside a `BaseHTTPMiddleware` never reaches `@app.exception_handler` (those live in `ExceptionMiddleware`, which nests *under* user middleware), and its anyio task group mangles a cancelled stream — which is what a chat **stop** is. So the rejection writes its own `JSONResponse` and the header is set on `http.response.start`; the streamed test asserts every frame **and** the header survive | Task 11.5, design |
| 46 | `api.ts`'s `asError` read the body twice (`response.json()` then `response.text()`), and a second read of a consumed stream always throws — so a shaped JSON 404 from a renamed route or a wrong namespace reached the user as "HTTP 404 with a non-JSON body". Now one read, `JSON.parse` in a try, and `empty_response` carries the actual text when the JSON has no `error` | Task 11.5, found while writing the wrong-namespace client test |
| 47 | Step 3 of the versioning plan said `app.openapi_schema = OPENAPI` and keep `/docs` + `/redoc`. Neither holds: FastAPI invalidates `app.openapi_schema` whenever a route is added, and Swagger/Redoc fetch their JavaScript from a CDN, which a loopback-only offline-first engine cannot promise. The generated document is switched off (`openapi_url=None`, `docs_url=None`, `redoc_url=None`), the contract is served at `{API_PREFIX}/openapi.json` with an `/openapi.json` alias returning the identical bytes, and the app's own version string became `CONTRACT_VERSION` instead of a third number (`0.1.0`) | Task 11.5, found while wiring the one-document rule |
| 48 | The cooldown test in Task 12 looked up its row as `p["provider"] == "fast_one"`, but the published `ProviderView` names that field `name` (`contracts.py:436-444`), and the read endpoint Task 9 froze that shape already returns `name`. The schema won — the same rule Task 12 Step 10 states for the drift gate ("if the gate complains, the schema is the one to trust"); the test now reads `p["name"]` | Task 12, found by running the step's test |
| 49 | Task 12's 422→400 sanitizer is global, not dashboard-scoped: it rewrites **every** request-validation failure, including the chat route Task 1 shipped and its `test_validation_errors_are_422_not_silent`. That test is now `test_validation_errors_are_a_contract_400_naming_the_field` — same two bodies (empty `messages`, junk `mode`), plus assertions on the code and on the field name the new message carries. Task 11.5's "Not exercised, and why" named the old 422 body as a bug left alone; this closes it | Task 12, Step 4's blast radius |
| 50 | `body: dict[str, Any]` makes the plan's `isinstance(body, dict)` guard unreachable over HTTP — FastAPI rejects a JSON array or `null` first, and the sanitizer answers `malformed request body; check body`. The guard stays (it is the only thing standing between a loosened annotation and a `.items()` crash on `Any`) and the live pass proves which branch a real `[]` takes | Task 12, found while hand-checking Step 11 |
| 51 | Step 10's expected `147 passed, 1 skipped` predates Task 11.5, which added `test_versioning.py` (10 tests). The true figures for this task are 158 passed, 1 skipped engine-side (+23: 4 validator + 19 endpoint), 42 chat tests, drift gate green — README's count line moved 135 → 158 in the same commit | Task 12, found by running the suite |
| 52 | Task 13 made item 44's whitelist empty, which is the state it was built to reach: every operation the contract publishes now has a decorator behind it, so `documented - registered == set()` is the assertion that will catch the *next* time someone documents a path first. `UNIMPLEMENTED` stays in the file as a typed empty set rather than being deleted — the gate without the list is the same as no gate | Task 13, M10's write surface complete |
| 53 | Step 6's `158 passed, 1 skipped` is the number Task 12 finished on, not the number Task 13 ends on: +7 delete tests +4 CLI tests makes 169 passed, 1 skipped. Recorded here because the plan's own arithmetic chains task to task and each link drifts | Task 13, found by running the suite |
| 54 | Steps 5 and 6 spell the namespace by hand (`/v1/kira/providers/...`) in `api.ts` and `fake-engine.ts` - the only two files item 44's `test_the_front_end_never_types_the_namespace_by_hand` reads. A backtick template satisfies the gate's letter (`"/v` needs a double quote) while breaking its purpose, so both files interpolate `API_PREFIX`. The path literals stay in the test files, where pinning the wire shape is the point of the assertion | Task 14, found while wiring the write methods |
| 55 | Step 7's first test asserts `/was 100/` - the exact assertion amendment 36 proved cannot render, because a `was ...` line appears only for an overridden field and openrouter's priority base 100 has no override. It reappeared in a brand-new file, so it is corrected the same way: assert `was 50` (groq's tuned priority) and that `was 100` is absent | Task 14, found by running Step 7 |
| 56 | Step 7's cap test drives `openrouter`, whose `monthly_cap` override is `null`, so the button it clicks (`clear override openrouter`) is `disabled` by the row's own rule and the `monthly_cap: null` write is never sent. Both halves moved to `groq`, the provider that does have a cap override, which is the only row where `set cap` and `clear override` are both meaningful | Task 14, found by running Step 7 |
| 57 | A successful write calls `refresh()`, and `useAsync` returns the screen to `loading`, which unmounts every row - so the probe answer Step 8 deliberately keeps as component state is discarded by the re-read the same click triggered. `run` gained a `reread` flag and the probe passes `false`, because `probe.py` commits no row and touches no ledger: a re-read can only learn what it already knows. Every other write still re-reads, and a test that clicks twice after one must re-find its control with `findByRole` | Task 14, found by running Step 7's probe test |
| 58 | Step 10 names three things the stylesheet does not have: `--line-strong` (the token is `--line`), `.small`, and `.sr`. Each was substituted or dropped rather than added - this task must not mint a fourth spelling of a colour, and a visually-hidden span inside a cell that already sets `aria-label` says the same word twice | Task 14, Step 10's own check |
| 59 | Step 1's fourth test ends `expect(...).toBeTruthy(), "the first dialog is still open";` - the comma operator evaluates the string and discards it, so it is a second expression, not an assertion message. Now a plain assertion | Task 14, found while transcribing the test |
| 60 | Step 5 defines `SettingPatch` field by field, which is the published `SettingsRequest` (`kira-contracts/types.ts:323-329`) spelled a second time in the client. It is an alias now, so the contract stays the one source of the four fields and their `null` meaning | Task 14, Step 5 |
| 61 | Step 11's `158 passed, 1 skipped` is Task 12's figure; Task 13 took the engine to 169. This task touches no engine code, so 169 passed, 1 skipped is the checkpoint, and chat went 42 to 58 (5 dialog + 4 api + 7 screen) | Task 14, found by running both suites |
| 62 | Step 6's `174 passed, 1 skipped (158 after Task 14 plus these 16)` carries Task 12's figure again as if it were Task 14's. Task 14 changed no engine file, so the baseline stayed 169 and the correct checkpoint is **185 passed, 1 skipped** - which is what the suite printed, with no pre-existing routing expectation moving | Task 15, found by running the suite |
| 63 | Step 1's last test asserts `harness.store.session_rows() == []`, but its own `spend()` helper files a session per row (the `messages.session_id` FK demands one), so the store is non-empty before the request is even sent and the assertion could never pass. The clause it carries is "a refused turn stores nothing", which `build_run` does honour - it plans before `create_session`. The test now snapshots the session ids, asserts the 429, and asserts the id set is unchanged, so it still fails if a refusal is ever filed | Task 15, found by running Step 2 |
| 64 | The `**Files:**` list anchors `app.py:21` for the errors import and `app.py:144-149` for the `KiraError` handler; after Task 11.5's middleware, Task 12's decorators and this task's `Router(...)` they are at `:24` and `:235-242`. Both were found by name, not by number - the numbers are corrected here so the next reader does not edit the `ProviderCallError` handler believing it is the exhaustion one | Task 15, Step 3's anchors |
| 65 | Step 1's second test waits for `/providers_exhausted: every provider was filtered out/`, which cannot render: `KiraApiError.message` is `` `${body.code}: ${body.message}` `` and the fixture's message already begins `mode auto:`, so the line on screen is `providers_exhausted: mode auto: every provider was filtered out…`. The sibling test in the same step gets the prefix right, so the guard test failed as a fifth failure in Step 2 instead of passing as one of the two early greens. Regex extended; the assertion's purpose - no cap link for a non-money refusal - is unchanged | Task 16, found by running Step 2 |
| 66 | Step 5's snippet spells the bar markup `bar` / `bar-over` / `bar-high` / `bar-used` / `bar-label`, but Task 10 shipped `budget-bar` / `budget-over` / `budget-high` / `budget-used` / `budget-label`, and `.bar` is already the app header's class (`styles.css:163`, used by `<header className="bar">`). Taking the snippet literally would have restyled the top bar, so the replacement keeps the shipped selectors and mints nothing | Task 16, Step 5 against the real file |
| 67 | The counts drift again: `App.test.tsx` holds 12 tests coming in, not Step 1's 9 (Task 14's screen rewrite added shell-level cases), so Step 8's `13 passed` is 16 and chat ends the task at 64. The engine likewise: Task 15 closed at 185 (amendment 62), so Step 11's `176` is 187 passed, 1 skipped | Task 16, found by running both suites |
| 68 | Step 4 computes `retired` from `view.by_model` against the configured keys. `ModelUsage.model` is nullable (`kira-contracts/types.ts:259`, "null for a turn that failed before any model answered it"), so a null row never matches a config name and the snippet would label it `no longer configured` — contradicting this task's own test 1. The rows joined and scanned are now `named`, with `model` narrowed to `string`; a turn that never reached a model belongs to Overview's failure counts, not to a model row | Task 17, Step 4 against the contract |
| 69 | The test file needs two local typings the snippet assumed away: `overviewFixture()` answers `unknown` (the fake's options are `unknown`), so `{ ...overviewFixture(), by_model: [] }` fails TS2698, and an inline models literal widens `tier` to `string` against `ModelInfo` (TS2322 — `Tier` is the union the engine publishes). A named `OVERVIEW` plus `const MODELS: ModelInfo[]` fixes both inside this file and leaves `fake-engine.ts` alone, which is right: it is not in this task's `**Files:**` and other suites read those fixtures | Task 17, found by `npm run check` |
| 70 | Step 8's clicking could not be done with the browser driver as written: `fill` left the connect form's React state empty (DOM value set, `onChange` never seen) and `click` did not reach the app's handlers, so Connect stayed on the gate and "use in chat" looked dead. The pass seeded `kira.base` and `kira.token` — the same two keys `connect()` writes (amendment 24) — and drove the button in-page with `btn.click()`. The screen then showed all 5 `config.yaml` models with matching tiers, `0` turns and `0` tokens on a fresh data dir, one button per row and no editable cell; the second row's button set the model select to `gemini-2.5-flash · gemini · fast` and the hash to `#/chat`. Worth knowing before Task 20: that pass needs the same seeding | Task 17, found by running Step 8 |
| 71 | Step 8's last claim — send one message on a keyed provider and watch the row gain a turn — is not made here. The hand-proof engine ran `Vault("memory")` against a throwaway data dir, so no Locker key exists, and a keyless turn is refused before it is filed; that stores nothing, which is Task 15's own rule working, not a gap in this screen. The mock-provider lab in Task 20 is where a row gains a turn in a browser. Counts again: App went 16 to 17, so chat ends Task 17 at 71, not Step 7's 70 | Task 17, found by running Steps 7 and 8 |

| 72 | Step 1 says the hook's `run` is "the same five-argument shape with the fifth optional", but its snippet swaps the fifth slot's meaning: `ProvidersScreen.Row.run` used it for amendment 57's `reread`, and `RunOptions` as written carries only `phrase` while `refresh()` became unconditional. So the probe's trailing `false,` no longer typechecks against `RunOptions`, and the probe answer would be discarded by the re-read its own click triggered — the exact regression amendment 57 exists to prevent. `RunOptions` gained `reread?: boolean` (default `true`) and the probe call site now passes `{ reread: false }`; `ProvidersScreen.test.tsx` still passes unmodified, which is the proof Gap 19 asked for | Task 18, found by reading Step 1 against the shipped `Row` |
| 73 | Step 2 gates the phrase with a `disabled` submit button only, and a disabled button does not stop a form submitted by a keystroke: Enter in the secret box reaches `submit()` with the words empty, so clear-all was one keystroke away from ignoring Gap 18. `submit()` re-checks the phrase and answers `type DELETE ALL exactly, or cancel`; `confirm.test.tsx` has a third test ("holds the words even when the form is submitted by a keystroke"), so it ends at 8, not Step 2's 7 | Task 18, found by writing Step 2's tests |
| 74 | Step 4's transcript block has an unreachable branch: `transcript.kind === "ready" && transcript.data === null` inside the `open !== null` case, but the `useAsync` function returns `Promise.resolve(null)` only when `open === null` — the outer condition already ruled that out. The ready state therefore always carries an array, and the empty message is rendered by the `messages.length === 0` case alone. The dead conditional was dropped rather than shipped as decoration | Task 18, found by reading Step 4 against `useAsync` |
| 75 | Step 10's scratch recipe does not produce the `never` it tells the walker to expect. `store.py`'s `session_rows` computes `last_used_at` as `MAX(messages.created_at)`, so a session with one message reports that message's timestamp; `never` is `NULL`, which only a session with no rows at all can yield. The seed needed a third `create_session()` with no `add_message` — the walk then showed messages `2 / 1 / 0` and `never` on the third row, which is also the same row the transcript's empty message is about | Task 18, found by running Step 10 |
| 76 | The hand proof caught a defect the tests did not: deleting a session whose transcript was open left the panel mounted, printing "the engine has no rows for `<id>`: it was created and never answered" about a session that had been answered and had just been deleted. Both delete paths now close the panel first — `setOpen((current) => current === row.id ? null : current)` for one, `setOpen(null)` for clear-all — and an eighth test asserts the `transcript <id>` region is gone after the delete, so `SessionsScreen.test.tsx` ends at 8, not 7 | Task 18, found by running Step 10 |
| 77 | After `npm run check` rebuilt `dist/`, `#/sessions` still served the old bundle and printed "Sessions screen arrives in M12." Rebuilding is not enough for a browser pass; the page needs a cache-bypassing reload (`navigate_page` with `ignoreCache`), on top of amendment 70's `localStorage` seeding and in-page clicks. Task 20 should assume both | Task 18, found by running Step 10 |
| 78 | Counts and one dead style. Step 9's `15 passed` for App is stale twice over: Task 17 left 17 (amendment 71), Step 7's loop replaces the placeholder test for net zero and the trouble-link test adds one, so App ends at 18; Step 11's engine `176` has been 187 since Task 16; chat totals 87 (`useWrite` 4, confirm 8, SessionsScreen 8, App 18). `styles.css` also lost `.screen-empty`, the class the `COMING_SOON` placeholders styled — Step 6 deleted the map that used it and no other screen references it | Task 18, found by running Steps 9 and 11 |

| 79 | Step 1's predicted failure contents are right on two of the four checks and wrong on two: the route check did name nine undocumented rows and the event check did report `missing: {'skipped_budget'}`, but the verb check reported only `['keys rm', 'token', 'models']` (`settings list` and `settings clear` were already in the old `Run it by hand` block) and the tunable check only `['enabled', 'tier', 'monthly_cap']` (`priority` was already backticked in the routing list). Still `4 failed`, still the same four tests | Task 19, found by running Step 1 |
| 80 | The tree block drops `kira-engine/tools/`. That directory does not exist yet — `mock_openai.py` and `kira_lab.py` are Task 20's product — and this task's own rule for `docs/qa/` ("documenting a directory that does not exist yet is the kind of drift the new test cannot catch, because no code owns it") applies exactly the same way to `tools/`. Task 20 adds both lines, since it creates both directories | Task 19, found by `ls kira-engine` |
| 81 | Step 3's storage bullet and Step 13's expectation both say `grep -rn "localStorage" kira-chat/src/` returns only `App.tsx`'s lines, "three lines". It returns eight: five in `App.tsx` and three in `App.test.tsx`, which seeds the same two keys and clears them. The claim the README makes is the one that survives the grep — every hit is `kira.base` or `kira.token`, no third key, no other module — and the sentence now says so, naming both files | Task 19, found by running Step 13's greps |
| 82 | Step 7 quotes three UI strings that the shipped screens do not print. Overview's empty month is `nothing spent in 2026-10 yet — the month is empty, not broken.`, not "no turns recorded for 2026-10"; Providers has no "Set key" button (the row shows `no key` beside an input labelled `new key <provider>` and a `forget key <provider>` button) and no "reset to baseline" control (`clear override <provider>`, which sends the explicit `null` the endpoint table already describes). The section was written from `grep`s of the screens rather than from the plan's paraphrases, because a README that quotes a label that is not on screen is the drift this task exists to stop | Task 19, found by checking Step 7 against `OverviewScreen.tsx:108` and `ProvidersScreen.tsx:116-155` |
| 83 | Step 5's seventeen rows went in as written except that two parentheticals from the old table stayed: `/healthz` still names both `api_version` and `contract_version`, and `/v1/openapi.json` still notes that `GET /openapi.json` is the same document. Both are true of the route table, the comparison only reads column one, and deleting an accurate sentence to match a snippet is the wrong direction | Task 19, Step 5 |
| 84 | Counts, twice more. Step 1's `176 passed` baseline has been 187 since Task 16, so the suite ends Task 19 at **191 passed, 1 skipped**, not 180; the client line was pasted from the run as instructed (11 files, 87 tests). Step 12's expected `engine is up at http://127.0.0.1:8913` actually prints `…:8913 (api /v1, contract v2)` — the launcher's own `_healthz_versions` suffix, predating this task — and the `stopping engine...` farewell was **not** observed: the run was killed as a background task, not interrupted, so only the child's exit was provable (nothing left listening on 8913). The `screens:` line, in order and present under `--no-browser`, is what Step 11's change was checked for | Task 19, found by running Steps 9 and 12 |
| 85 | Step 13's last instruction — read the finished README against the running lab and cross out any sentence you cannot point at on screen — is deferred to Task 20 rather than done here, because the lab it reads against is that task's `kira_lab.py`. What could be checked without it was: every README claim about endpoints, verbs, events and tunable fields is now machine-checked, and the three storage greps were run | Task 19, Step 13 |

| 86 | The pass runs one turn ahead of the plan's arithmetic from Step 3 onward, because Step 3's out-of-band `curl` turn is *stored* — the engine files it like any other turn. Overview and Providers read `450` where Steps 4-6 predict `300`, so the `spend + 1` cap was typed as **451** rather than 301 and the chip read `used 600 of 451 tokens in 2026-10` instead of `used 450 of 301`. Same shape, same rule (amendment 15's one turn of slack), every number one turn higher. Steps 7-9 were then re-run on a fresh process with cap `151` over spend `150`, which produced exactly the planned pair — `used 300 of 151` on the chip and `300 / 151 · at cap` on the bar — so the mechanism is proven and only the first run's count started high | Task 20, found by running Steps 3-6 and re-running 7-9 |
| 87 | The DOM reads in Steps 5 and 9 return null while another screen is showing: the screens are conditionally rendered, so `[aria-label="priority mock_two"]` does not exist on `#/chat`. Navigate first, then query. Amendment 70's seeding recipe assumed one screen was always on page | Task 20, found by running Step 5 |
| 88 | Two render shapes no "read the screen" instruction mentions. The sidebar prints a session id with no separator (`856f1798AUTO`), so a regex expecting a space matches nothing. Overview's daily series is an SVG — `svg.spark`, `aria-label="daily tokens, peak 450"`, one polyline point at `0.0,2.00` for a one-day month — so a text dump of the screen skips it entirely | Task 20, found by reading Steps 4 and 9 |
| 89 | Step 8's chain is written in engine event names (`attempt mock_two`, `tool_executed echo`, `served mock_two`); the UI localises them. On screen: `mock_one / over budget / used 150 of 1 tokens in 2026-10` → `mock_two / trying / mini` → `mock_two / answered / mini` → `kira / tool ran / echo("call_lab_1") → ok, 15 chars` → the same `over budget` line again → `trying` → `answered`, with the footer `2 served · 0 failed · 2 skipped · 1 tool runs`. The repeat is the finding; the record quotes the screen, not the event names | Task 20, Step 8 against the shipped `ChainTrace` labels |
| 90 | Step 8 could not pass until the lab's own mock was corrected: `tool_call_chunks()` ended its stream with `finish_reason: tool_calls` and **no `usage`**, so the first completion of a tool turn billed 0 and one user turn cost 150 where the plan says 300. The engine was innocent — `loop.py:59` accumulates with `+=` — so the fix went into `tools/mock_openai.py` (that chunk now carries `USAGE`), and the re-run read `200↑ / 100↓` with `mock_two` at 0 → 300. Two things this records: this task's "adds no engine or client code" line does not cover a defect found in the task's own instrument, and the product risk the accident exposed — a provider that omits `usage` on a step makes that month's spend and the cap meter read low, silently, because the engine stores what it is handed | Task 20, found by measuring Step 8 against Providers |
| 91 | Step 9's `never` row (amendment 75's seeded empty session) is unreachable from a browser. A session gets its first message inside the request that created it, and the refusal path raises before `create_session`, so every stored session has a timestamp; all six rows printed a real date. The unit tests keep ownership of that state | Task 20, found by running Step 9's session read |
| 92 | Six sessions for eight turns. `sessionId` is React state, so Step 4's address-bar refresh — and any round trip through another screen — opens a new one. The plan's "count them before you judge it" resolved as a finding about the connect flow, not about `#/sessions` | Task 20, Step 9 |
| 93 | `delete every session` re-arms every cap. `spend_this_month` is derived from stored turns, so `mock_one` went 600 → 0 while its override (`451`, later `151`) stayed in the settings table and the health ledger (`7✓ 0✗`) survived too. Self-consistent — the meter counts what is stored — but it means the audit trail and the budget meter are the same rows, and wiping one resets the other without saying so. Recorded in the pass's Findings for the spec, not fixed mid-pass | Task 20, Step 9's clear-all |
| 94 | Step 10's second lab (no `--data-dir`) printed `data …\kira-lab-8j4orlq_ (temp, deleted on exit)` and then **kept** `config.yaml kira.db kira.db-shm kira.db-wal logs` when the harness killed it — `atexit` does not run on a killed process. The interrupt path was verified separately with the same `atexit(shutil.rmtree, …)` wiring and a propagated `KeyboardInterrupt`: gone. The README now says the temp directory is removed "when you stop it with Ctrl+C" instead of promising deletion on any exit | Task 20, found by running Step 10's temp-dir case |
| 95 | Step 11's two deferred tree lines went in differently. `kira-engine/tools/` became an indented `  tools/` sub-line under `kira-engine/` — a top-level entry of that width pushes the comment column — and `docs/qa/` is the plain line the plan wrote. Step 12's `.kira-data` still held exactly `config.yaml` and `logs/`, with no `kira.db`, which is the proof Steps 3-11 never touched the real data dir | Task 20, Steps 11 and 12 |
| 96 | Counts and greps, as ever. Step 12's `180 passed, 1 skipped` has been **191 passed, 1 skipped** since Task 19 (amendment 84); the client stayed at 87 across 11 files, which is the point of a pass that mints no code. `grep -rn "127.0.0.1" kira-engine/tools/` also matches `tools/__pycache__/*.pyc`, so the honest claim is "every source socket in `tools/` binds loopback and `0.0.0.0` appears nowhere". `rm -rf /tmp/kira-lab` is `%TEMP%\kira-lab` on this machine | Task 20, Step 12 |

| 97 | Verifying the merged result caught a Windows-only defect in the gate itself. `core.autocrlf=true` materialises `kira-contracts/*` with CRLF on checkout, and `tsBlock()`'s `type X = …` pattern ends at `\n\n` — which `\r\n\r\n` never contains — so `node kira-contracts/check-drift.mjs` failed with `types.ts has no 'ChatChunk' for openapi schema ChatChunk` on a tree byte-identical to the one it had just passed. The interface and class patterns survive by accident (they end at `\n}`, and CRLF contains `\n`). `read()` in the gate now normalises CRLF, proven by re-running it against the CRLF working copy; `test_docs_match_engine.py` was never at risk because Python's line splitting accepts CRLF. A `.gitattributes` pinning `eol=lf` is the broader fix and is deliberately not added here: it rewrites every working copy on the next checkout, which is a decision rather than a repair | Task 20's merge verification, found by running the checkpoint on master |

Items 18-97 are numbered in the same sequence because they are the same kind of thing: the spec was silent or
uncheckable, and the plan decided. None of them widens the design. Item 24 narrows one instead — the spec's
"never `localStorage`" clause was written as if no web storage existed, and the chat app that already ships
uses it for the base URL and the bearer token (Task 14 Step 12). The owner chose the token-in-storage
behaviour over a re-paste-every-reload app; the plan records that choice rather than pretending the grep
will find nothing.

## File Structure

Created:

| Path | Responsibility |
| --- | --- |
| `kira-engine/src/kira/overrides.py` | Merge `settings` rows over `ProviderConfig`; `EffectiveProvider`, `FieldState`, `MergedView`, orphan reporting |
| `kira-engine/src/kira/probe.py` | `probe_models()` and `probe_provider()`; the only place a live provider call is timed |
| `kira-chat/src/hash-route.ts` | `currentRoute()`, `navigate()`, `onRoute()` over `location.hash` |
| `kira-chat/src/screens/ChatScreen.tsx` | Today's chat, moved whole |
| `kira-chat/src/screens/OverviewScreen.tsx` | Month, stat cards, budget bars, sparkline, top models, recent issues |
| `kira-chat/src/screens/ProvidersScreen.tsx` | Per-provider tuning, key, health, probe |
| `kira-chat/src/screens/ModelsScreen.tsx` | Configured models, tier, month usage, "use in chat" |
| `kira-chat/src/screens/SessionsScreen.tsx` | Session table, transcript, delete one, clear all |
| `kira-chat/src/confirm.tsx` | `ConfirmProvider`, `useConfirm()`, the dialog; holds the secret only while a write is in flight |
| `kira-chat/src/useAsync.ts` | Tiny loading/error/data hook every screen uses, so "explicit states" is one implementation |
| `kira-chat/src/useWrite.ts` | The one implementation of "commit, and re-ask if the secret was refused" that both write screens share (Gap 19) |
| `kira-engine/tests/` | New suites named in the spec, plus `test_contract_v2.py`, `test_confirm_secret.py`, `test_session_deletes.py`, `test_budget.py` |
| `kira-engine/tests/test_docs_match_engine.py` | README against the route table, the event list, the CLI verbs and the tunable fields (Gap 20) |
| `kira-engine/tools/mock_openai.py` | Scripted loopback provider with fixed usage, for the browser pass only (Gap 22) |
| `kira-engine/tools/kira_lab.py` | Mock + scratch engine + memory vault in one command, nothing real at stake (Gap 22) |
| `docs/qa/dashboard-browser-pass.md` | The record Task 20 fills in from the screen |

Modified:

| Path | What changes |
| --- | --- |
| `kira-engine/src/kira/store.py` | `settings` table + CRUD, `month_bounds()`, `monthly_spend()`, `overview()`, `session_rows()`, `delete_session()`, `clear_sessions()` |
| `kira-engine/src/kira/config.py` | `ProviderConfig.monthly_token_cap`, `_provider_from` reads it, `SAMPLE_CONFIG` gains a commented example |
| `kira-engine/src/kira/router.py` | `Router` takes `view`/`store`; plan() drops disabled providers, then budget, then cooldown |
| `kira-engine/src/kira/errors.py` | `BudgetExhausted` (429, not retryable, carries `chain`) |
| `kira-engine/src/kira/net.py` | `HealthLedger.view(name)`, `clear_cooldown(name)` |
| `kira-engine/src/kira/vault.py` | `ENGINE_CONFIRM_REF`, `get_or_create_confirm()`, shared `_get_or_create()` |
| `kira-engine/src/kira/app.py` | Merged view in `/v1/models` + `/v1/kira/health`, `require_confirm`, `providers_payload()`, a 422→400 body sanitizer, `/v1/kira/*` read and write endpoints, chain-carrying error handler, `Engine.confirm` |
| `kira-engine/src/kira/contracts.py` | `CONTRACT_VERSION = 2`, `skipped_budget`, `budget_exhausted`, new schemas + paths |
| `kira-engine/src/kira/__main__.py` | `token` prints the confirm secret on stderr; `keys list` reports its presence; `models` uses `probe_models`; new `settings list` / `settings clear` |
| `kira-contracts/contract.ts`, `types.ts` | Mirror v2 |
| `kira-chat/src/App.tsx` | Becomes the shell: gate, bar, nav rail, route switch, version guard using `CONTRACT_VERSION` |
| `kira-chat/src/api.ts` | Read + write methods; writes send `X-Kira-Confirm` |
| `kira-chat/src/components/ChainTrace.tsx` | `skipped_budget` label "over budget", tone `warn` |
| `kira-chat/src/fake-engine.ts` | v2 defaults, new routes, strict write assertions |
| `kira-chat/src/styles.css` | Nav rail, screens, cards, bars, sparkline, dialog |
| `run_kira.py`, `README.md`, `PROVENANCE.md` | Confirm secret surfaced; dashboard documented; the studied-not-copied rows added |

**Checkpoint convention:** each task lists the exact commands and the exact expected output. Never mark a task done on reasoning alone — this is the project's standing rule (see `Kira/README.md` "Checks").

---

# M8 — Shell and routing (client only)

M8 changes no engine code. Its acceptance is that chat behaves exactly as before while living behind a route.

## Task 1: Hash route

**Files:**
- Create: `kira-chat/src/hash-route.ts`
- Create: `kira-chat/src/hash-route.test.ts`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `type Route = "chat" | "overview" | "providers" | "models" | "sessions"`
  - `const ROUTES: readonly Route[]` (order is the nav rail order)
  - `currentRoute(): Route` — never throws; anything unparseable is `"chat"`
  - `navigate(route: Route): void` — sets `location.hash` and notifies subscribers when the value did not change
  - `onRoute(fn: (route: Route) => void): () => void` — returns an unsubscribe function

- [ ] **Step 1: Write the failing tests**

Create `kira-chat/src/hash-route.test.ts`:

```ts
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { currentRoute, navigate, onRoute, ROUTES, type Route } from "./hash-route.ts";

beforeEach(() => {
  window.location.hash = "";
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("hash-route", () => {
  it("treats an empty or unknown hash as chat", () => {
    window.location.hash = "";
    expect(currentRoute()).toBe("chat");
    window.location.hash = "#/nonsense";
    expect(currentRoute()).toBe("chat");
  });

  it("reads every documented route", () => {
    for (const route of ROUTES) {
      window.location.hash = `#/${route}`;
      expect(currentRoute()).toBe(route);
    }
  });

  it("notifies subscribers on hashchange and stops after unsubscribe", () => {
    const seen: Route[] = [];
    const off = onRoute((route) => seen.push(route));
    window.location.hash = "#/providers";
    window.dispatchEvent(new HashChangeEvent("hashchange"));
    expect(seen).toEqual(["providers"]);
    off();
    window.location.hash = "#/models";
    window.dispatchEvent(new HashChangeEvent("hashchange"));
    expect(seen).toEqual(["providers"]);
  });

  it("navigate() fires the subscriber even when the hash already matches", () => {
    window.location.hash = "#/sessions";
    const seen: Route[] = [];
    onRoute((route) => seen.push(route));
    navigate("sessions");
    expect(seen).toEqual(["sessions"]);
  });
});
```

No `dispatchEvent` in that last test, and that is deliberate: the only `hashchange` these tests get is the
one they dispatch themselves (jsdom does not deliver one in the same tick when a test writes
`location.hash`), so a manual dispatch after `navigate()` notifies twice and the assertion would be testing
the test. What the line does prove is the module's same-route branch — delete it from `hash-route.ts` and
`seen` is `[]`.

- [ ] **Step 2: Run them to watch them fail**

Run: `cd kira-chat && npm run test -- hash-route`
Expected: FAIL — `Failed to resolve import "./hash-route.ts"`.

- [ ] **Step 3: Write the module**

Create `kira-chat/src/hash-route.ts`:

```ts
export const ROUTES = ["chat", "overview", "providers", "models", "sessions"] as const;
export type Route = (typeof ROUTES)[number];

const DEFAULT_ROUTE: Route = "chat";

function parse(hash: string): Route {
  const name = hash.replace(/^#\//, "").split("?")[0];
  return (ROUTES as readonly string[]).includes(name) ? (name as Route) : DEFAULT_ROUTE;
}

export function currentRoute(): Route {
  return parse(window.location.hash);
}

type Listener = (route: Route) => void;
const listeners = new Set<Listener>();

export function onRoute(fn: Listener): () => void {
  listeners.add(fn);
  if (listeners.size === 1) {
    window.addEventListener("hashchange", notify);
  }
  return () => {
    listeners.delete(fn);
    if (listeners.size === 0) {
      window.removeEventListener("hashchange", notify);
    }
  };
}

function notify() {
  const route = currentRoute();
  for (const fn of listeners) fn(route);
}

export function navigate(route: Route): void {
  const wanted = `#/${route}`;
  if (window.location.hash === wanted) {
    // Same route: no hashchange event will come, but the caller still wants a refresh.
    for (const fn of listeners) fn(route);
    return;
  }
  window.location.hash = wanted;
}
```

- [ ] **Step 4: Run them to watch them pass**

Run: `cd kira-chat && npm run test -- hash-route`
Expected: PASS — 4 tests.

- [ ] **Step 5: Checkpoint**

Run: `cd kira-chat && npm run typecheck && npm run test`
Expected: `tsc --noEmit` silent; `Test Files 5 passed` (4 on disk + this one), tests `27 passed` (23
existing + 4 new).

If git is initialised: `git add kira-chat/src/hash-route.ts kira-chat/src/hash-route.test.ts && git commit -m "feat(chat): hash route for the dashboard shell"`.

## Task 2: Shell, nav rail, ChatScreen extraction

**Files:**
- Create: `kira-chat/src/screens/ChatScreen.tsx` (from `App.tsx` lines 12-37, 76-146, 169-302)
- Modify: `kira-chat/src/App.tsx` (whole file becomes the shell)
- Modify: `kira-chat/src/styles.css` (after the `/* shell */` block at line 101)
- Modify: `kira-chat/src/App.test.tsx` (unchanged assertions, plus one new test)

**Interfaces:**
- Consumes: `Route`, `currentRoute()`, `navigate()`, `onRoute()` from Task 1; `KiraClient` from `api.ts`.
- Produces:
  - `App()` — default export, renders the gate when no token, else the shell.
  - `ChatScreen(props: ChatScreenProps)` — named export from `screens/ChatScreen.tsx`.
  - `interface ChatScreenProps { client: KiraClient; models: ModelInfo[]; model: string; setModel(m: string): void; mode: Mode; setMode(m: Mode): void; connected: boolean; route: Route }`
  - `interface ScreenProps { client: KiraClient }` — every later screen takes the client, nothing else. Re-declared per screen as `{ client: KiraClient; onUseModel(model: string): void }` where needed (Models, Overview).

The split is deliberate: the shell owns *connection* (token, base, healthz, model catalogue, mode, model, route); chat owns *its own* conversation, sessions and provider sidebar and fetches them itself. That keeps `refresh()` in the shell two calls instead of four, and means a dashboard screen never waits on chat state.

- [ ] **Step 1: Write the failing test**

Append to `kira-chat/src/App.test.tsx` inside the `describe("App")` block:

```tsx
  it("routes to the providers screen and back to chat on refresh", async () => {
    const engine = fakeEngine({ models: MODELS, health: HEALTH });
    connectedTo(engine);
    window.location.hash = "#/providers";
    render(<App />);

    expect(await screen.findByText("Dashboard is arriving in M9.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Chat" }));
    expect(window.location.hash).toBe("#/chat");
    expect(await screen.findByLabelText("message")).toBeTruthy();
  });

  it("keeps chat as the default route", async () => {
    const engine = fakeEngine({ models: MODELS, health: HEALTH });
    connectedTo(engine);
    render(<App />);
    expect(window.location.hash).toBe("");
    expect(await screen.findByLabelText("message")).toBeTruthy();
  });
```

Note: `connectedTo()` in this file already stubs `fetch` and sets `localStorage`; `#/providers` is a placeholder panel until Task 11 gives it real content. The placeholder text is the literal string `Dashboard is arriving in M9.` — one place, so the later task replaces both the copy and the assertion.

Also add one line to the `beforeEach` that already sits above the `describe("App")` block (amendment 25):

```tsx
beforeEach(() => {
  localStorage.clear();
  // jsdom keeps window.location across tests, and the route tests below write it.
  window.location.hash = "";
});
```

Without it the second test fails on the first one's hash, and the failure looks like a routing bug in code
that does not exist yet.

- [ ] **Step 2: Run it to watch it fail**

Run: `cd kira-chat && npm run test -- App`
Expected: FAIL — `Unable to find role "button" and name "Chat"` (nav rail does not exist yet), and the four existing chat tests still pass, which is the point of Step 4's order.

- [ ] **Step 3: Move chat into its own screen**

Create `kira-chat/src/screens/ChatScreen.tsx` by moving, from `App.tsx`, these verbatim blocks: the `Entry` interface, the `entries`/`sessionId`/`sessions`/`prompt`/`busy`/`live`/`abortRef`/`nextId` state, `send()`, `stop()`, `openSession()`, the `cooling` derivation, the `<aside className="side">` element and the `<section className="thread">` element, and `messageOf()`. Import `KiraClient`, `ChainTrace`, `applyChunk`/`chainSummary`/`emptyTurn`/`Turn` as before. Its body:

```tsx
export interface ChatScreenProps {
  client: KiraClient;
  models: ModelInfo[];
  model: string;
  setModel(model: string): void;
  mode: Mode;
  setMode(mode: Mode): void;
  connected: boolean;
  route: Route;
}

export function ChatScreen({ client, models, model, setModel, mode, setMode, connected, route }: ChatScreenProps) {
  // ...the moved state and handlers, unchanged...
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [sessions, setSessions] = useState<SessionRow[]>([]);

  useEffect(() => {
    // Chat only re-reads the engine when it is actually on screen.
    if (route !== "chat") return;
    void Promise.all([client.health(), client.sessions()])
      .then(([snapshot, rows]) => {
        setHealth(snapshot);
        setSessions(rows.sessions);
      })
      .catch(() => undefined);
  }, [client, route]);

  if (route !== "chat") {
    return null;
  }
  return <div className="body">{/* the moved <aside> and <section>, verbatim */}</div>;
}
```

Two changes to the moved code, both required by the split:

1. `send()`'s `finally` block keeps its `Promise.all([client.health(), client.sessions()])` refresh exactly as written today.
2. The `mode`/`model` `<select>` elements leave this file — the shell's bar keeps them, because they belong to the connection, not to chat. Chat's composer hint line keeps `{models.length} models · {mode}`.

- [ ] **Step 4: Rewrite the shell**

`kira-chat/src/App.tsx` becomes:

```tsx
import { useCallback, useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { KiraClient } from "./api.ts";
import { CONTRACT_VERSION, MODES } from "./contracts.ts";
import type { ModelInfo, Mode } from "./contracts.ts";
import { currentRoute, navigate, onRoute, ROUTES } from "./hash-route.ts";
import type { Route } from "./hash-route.ts";
import { ChatScreen } from "./screens/ChatScreen.tsx";

const TOKEN_KEY = "kira.token";
const BASE_KEY = "kira.base";

const NAV_LABELS: Record<Route, string> = {
  chat: "Chat",
  overview: "Overview",
  providers: "Providers",
  models: "Models",
  sessions: "Sessions",
};

export default function App() {
  const [base, setBase] = useState(() => localStorage.getItem(BASE_KEY) ?? "");
  const [token, setToken] = useState(() => localStorage.getItem(TOKEN_KEY) ?? "");
  const [draftToken, setDraftToken] = useState("");
  const [connected, setConnected] = useState(false);
  const [connectError, setConnectError] = useState<string | null>(null);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [model, setModel] = useState("");
  const [mode, setMode] = useState<Mode>("AUTO");
  const [route, setRoute] = useState<Route>(() => currentRoute());

  const client = useMemo(() => new KiraClient({ baseUrl: base, token }), [base, token]);

  useEffect(() => onRoute(setRoute), []);

  const refresh = useCallback(async () => {
    try {
      const probe = await client.healthz();
      if (probe.contract_version !== CONTRACT_VERSION) {
        setConnectError(`engine speaks contract v${probe.contract_version}, this client speaks v${CONTRACT_VERSION}`);
        return;
      }
      setConnected(true);
      setConnectError(null);
      const catalogue = await client.models();
      setModels(catalogue.data);
      if (catalogue.data.length && !catalogue.data.some((m) => m.id === model)) setModel(catalogue.data[0].id);
    } catch (error) {
      setConnected(false);
      setConnectError(messageOf(error));
    }
  }, [client, model]);

  useEffect(() => {
    if (token) void refresh();
  }, [token, refresh]);

  // ...the gate JSX, verbatim from today's lines 148-167...

  return (
    <div className="app">
      <nav className="rail" aria-label="Kira sections">
        <div className="rail-brand">
          <span className={`dot ${connected ? "on" : "off"}`} />
          <strong>Kira</strong>
        </div>
        {ROUTES.map((item) => (
          <button
            key={item}
            type="button"
            className={item === route ? "rail-active" : ""}
            aria-current={item === route ? "page" : undefined}
            onClick={() => navigate(item)}
          >
            {NAV_LABELS[item]}
          </button>
        ))}
        <span className="spacer" />
        <button type="button" onClick={() => void refresh()}>
          refresh
        </button>
        <button
          type="button"
          onClick={() => {
            localStorage.removeItem(TOKEN_KEY);
            setToken("");
            setConnected(false);
          }}
        >
          disconnect
        </button>
      </nav>
      <div className="pane">
        <header className="bar">
          <select name="routing_mode" value={mode} onChange={(e) => setMode(e.target.value as Mode)} aria-label="routing mode">
            {MODES.map((m) => (
              <option key={m} value={m}>{m}</option>
            ))}
          </select>
          <select name="model" value={model} onChange={(e) => setModel(e.target.value)} aria-label="model">
            {models.length === 0 && <option value="">no models configured</option>}
            {models.map((m) => (
              <option key={`${m.provider}-${m.id}`} value={m.id}>{m.id} · {m.provider} · {m.tier}</option>
            ))}
          </select>
          <span className="spacer" />
          <span className="muted mono">v{CONTRACT_VERSION}</span>
        </header>
        {route === "chat" ? (
          <ChatScreen client={client} models={models} model={model} setModel={setModel} mode={mode} setMode={setMode} connected={connected} route={route} />
        ) : (
          <section className="screen-empty">
            <p className="muted">Dashboard is arriving in M9.</p>
          </section>
        )}
      </div>
    </div>
  );
}

function messageOf(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error);
}
```

The `dot on|off` indicator moves into the rail; `cooling.length > 0` warning leaves the shell for ChatScreen's sidebar, where the `health` state now lives. Nothing else about chat's visible behaviour changes.

- [ ] **Step 5: Add the shell styles**

Insert into `kira-chat/src/styles.css` immediately after the `/* shell */` comment on line 101, before `.shell`:

```css
/* dashboard shell */
.app {
  display: grid;
  grid-template-columns: 11rem 1fr;
  min-height: 100vh;
}
.rail {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  padding: 0.9rem 0.7rem;
  background: var(--panel);
  border-right: 1px solid var(--line);
}
.rail-brand {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-family: var(--display);
  margin-bottom: 0.8rem;
}
.rail button {
  text-align: left;
  background: transparent;
  border: 1px solid transparent;
}
.rail button.rail-active {
  background: var(--panel-2);
  border-color: var(--line);
  color: var(--accent);
}
.pane {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.screen-empty {
  padding: 2rem;
}
@media (max-width: 60rem) {
  .app {
    grid-template-columns: 1fr;
    grid-template-rows: auto 1fr;
  }
  .rail {
    flex-direction: row;
    flex-wrap: wrap;
    border-right: 0;
    border-bottom: 1px solid var(--line);
  }
}
```

- [ ] **Step 6: Checkpoint**

Run: `cd kira-chat && npm run check`
Expected: `tsc --noEmit` silent; `Test Files` all passed, tests `29 passed` (23 existing + 4 hash-route + 2 new App); `vite build` succeeds. Then `node kira-contracts/check-drift.mjs` from `Kira/` — expected `kira-contracts OK — v1, 18 schemas, 5 chunk types, 8 chain events` (M8 touches no contract).

If git is initialised: `git add kira-chat/src && git commit -m "feat(chat): dashboard shell with hash routing"`.

**M8 acceptance (from the spec):** chat behaves exactly as before, `#/chat` survives refresh, all existing chat tests pass. Verify by hand later in Task 20's browser pass; the four moved tests are the machine-checkable part now.

---

# M9 — Merged settings, probe, contract v2, read endpoints, read-only screens

M9 ends with a dashboard that shows the truth and can be *proven* to drive routing by inserting an override row with `store.set_setting()` by hand — before any write endpoint exists.

## Task 3: The `settings` table

**Files:**
- Modify: `kira-engine/src/kira/store.py` (schema at `:20-55`, methods after `list_sessions` at `:123`)
- Modify: `kira-engine/tests/test_units.py` (append)
- Create: `kira-engine/tests/test_overrides.py` (starts here, grows in Task 4)

**Interfaces:**
- Consumes: nothing new.
- Produces, on `Store`:
  - `SETTINGS_KEYS: frozenset[str]` = `{"enabled", "priority", "tier", "monthly_cap"}` — module-level in `store.py`
  - `settings_map() -> dict[str, dict[str, str]]` — provider → key → raw JSON text, **every row it finds**, including keys outside `SETTINGS_KEYS`; the filter that hides junk lives in `build_view` (Task 4) so the dashboard can report orphans
  - `set_setting(provider: str, key: str, value: object) -> None` — validates the key, stores `json.dumps(value)`. Callers pass Python values (amendment 27): `set_setting("groq", "tier", "fast")` writes the column text `"fast"`, and `set_setting("groq", "priority", 60)` writes `60`. Passing already-quoted JSON double-encodes it.
  - `clear_setting(provider: str, key: str) -> bool` — `False` when no row existed
  - `delete_settings(provider: str) -> int` — every row for one provider (used by the orphan prune)
  - `month_bounds(month: str | None = None) -> tuple[str, float, float]` — module-level function, `(label, start, end)` UTC epoch seconds, half-open

- [ ] **Step 1: Write the failing tests**

Create `kira-engine/tests/test_overrides.py`:

```python
from __future__ import annotations

import time

from kira.store import SETTINGS_KEYS, Store


def test_settings_table_roundtrips_a_json_scalar(tmp_path):
    store = Store(tmp_path / "kira.db")
    assert store.settings_map() == {}
    store.set_setting("groq", "enabled", False)
    store.set_setting("groq", "priority", 60)
    assert store.settings_map() == {"groq": {"enabled": "false", "priority": "60"}}
    store.close()


def test_settings_only_accepts_the_four_tunable_keys(tmp_path):
    from kira.errors import ConfigError

    store = Store(tmp_path / "kira.db")
    assert SETTINGS_KEYS == {"enabled", "priority", "tier", "monthly_cap"}
    try:
        store.set_setting("groq", "base_url", "https://evil")
    except ConfigError as exc:
        assert "base_url" in str(exc)
    else:
        raise AssertionError("base_url must not be writable through settings")
    store.close()


def test_clear_setting_reports_whether_a_row_existed(tmp_path):
    store = Store(tmp_path / "kira.db")
    store.set_setting("groq", "tier", "powerful")
    assert store.clear_setting("groq", "tier") is True
    assert store.clear_setting("groq", "tier") is False
    assert store.settings_map() == {}
    store.close()


def test_settings_map_returns_the_raw_rows_untouched(tmp_path):
    store = Store(tmp_path / "kira.db")
    store.set_setting("groq", "priority", 7)
    # A row a hand-edit could have left behind stays visible: the merge decides what is
    # tunable, and it reports anything it cannot use instead of swallowing it.
    store._conn.execute(  # noqa: SLF001 - deliberately writing underneath the API
        "INSERT INTO settings(provider, key, value, updated_at) VALUES('groq','colour','red',?)",
        (time.time(),),
    )
    store._conn.commit()
    assert store.settings_map() == {"groq": {"colour": "red", "priority": "7"}}
    store.close()
```

- [ ] **Step 2: Run them to watch them fail**

Run: `cd kira-engine && .venv/Scripts/python.exe -m pytest -q tests/test_overrides.py`
Expected: FAIL — `ModuleNotFoundError`/`AttributeError: 'Store' object has no attribute 'settings_map'`.

- [ ] **Step 3: Add the table and the methods**

In `store.py`, add the import `import re` at the top, then the table inside the existing `executescript` string in `_init_schema`, after the `provider_health` statement:

```sql
            CREATE TABLE IF NOT EXISTS settings (
                provider TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                updated_at REAL NOT NULL,
                PRIMARY KEY (provider, key)
            );
```

At module level, above `class Store`:

```python
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
```

Add `import re`, `from datetime import datetime, timezone` and `from .errors import ConfigError` to `store.py`'s imports (`store.py` currently imports only `json`, `sqlite3`, `time`, `uuid`, `Path`, `Any`) — this is the first time `store` needs the other three, and it keeps one error vocabulary at the boundary the API calls. `datetime` is imported once at module level because Task 6's `overview()` needs it too; a function-local import would just be a second place to keep in sync.

Methods on `Store`, inserted after `list_sessions()`:

```python
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
```

- [ ] **Step 4: Run them to watch them pass**

Run: `cd kira-engine && .venv/Scripts/python.exe -m pytest -q tests/test_overrides.py`
Expected: PASS — 4 tests.

- [ ] **Step 5: Prove an existing database migrates**

`_init_schema` runs `CREATE TABLE IF NOT EXISTS` on every open, so an old `kira.db` gains the table on next start. Assert that rather than assume it — append to `tests/test_units.py`:

```python
def test_settings_table_appears_on_an_existing_database(tmp_path):
    path = tmp_path / "kira.db"
    first = Store(path)
    first.create_session("AUTO")
    first.close()

    second = Store(path)  # reopening a v1 database must not lose or refuse the new table
    second.set_setting("groq", "tier", "fast")
    assert second.settings_map() == {"groq": {"tier": '"fast"'}}
    assert [s["id"] for s in second.list_sessions()]  # the pre-existing row is still there
    second.close()
```

Run: `cd kira-engine && .venv/Scripts/python.exe -m pytest -q tests/test_units.py`
Expected: PASS — 17 tests, up from 16.

- [ ] **Step 6: Checkpoint**

Run: `cd kira-engine && .venv/Scripts/python.exe -m pytest -q`
Expected: `60 passed, 1 skipped` (55 existing + 5 new; the live-provider suite stays skipped without `KIRA_LIVE=1`).

If git is initialised: `git add kira-engine/src/kira/store.py kira-engine/tests && git commit -m "feat(engine): settings override table"`

---

## Task 4: `monthly_token_cap` + `overrides.py` — one merged view for router, API and dashboard

**Files:**
- Modify: `kira-engine/src/kira/config.py` (`ProviderConfig` at `:19-37`, `_provider_from` at `:90-102`, `SAMPLE_CONFIG` at `:127-173`)
- Create: `kira-engine/src/kira/overrides.py`
- Modify: `kira-engine/tests/test_overrides.py` (append)
- Modify: `kira-engine/tests/test_units.py` (append)

**Interfaces:**
- Consumes: `Config`, `ProviderConfig`, `TIERS` from `config.py`; `Store.settings_map()`; `ConfigError`.
- Produces:
  - `ProviderConfig.monthly_token_cap: int | None` — the YAML baseline for a cap; `None` means unlimited
  - `FieldState(base, override, effective)` with `to_wire() -> dict`
  - `EffectiveProvider` — dataclass whose scalars the router reads are named exactly as on `ProviderConfig` (`name`, `kind`, `base_url`, `models`, `key_ref`, `priority`, `tier`), plus `enabled: bool`, `monthly_cap: int | None`, `base: ProviderConfig`, and `states: dict[str, FieldState]` keyed by `enabled`/`priority`/`tier`/`monthly_cap`
  - `MergedView(providers: list[EffectiveProvider], by_name: dict[str, EffectiveProvider], orphan_settings: list[str])`
  - `build_view(config: Config, store: Store | None = None) -> MergedView`
  - `enabled_providers(view: MergedView) -> list[EffectiveProvider]` — priority-then-name sorted

The merge checks **types only**, never ranges: a range check belongs at the write boundary (Task 13), and a row that is the right type but a hand-edited oddity must still behave predictably rather than silently reverting.

- [ ] **Step 1: Write the failing tests**

Append to `kira-engine/tests/test_overrides.py`:

```python
from kira.config import Config, ProviderConfig
from kira.overrides import build_view, enabled_providers


def configs() -> list[ProviderConfig]:
    return [
        ProviderConfig(name="groq", kind="openai_compat", base_url="https://groq.invalid/v1",
                       models=["mini"], tier="fast", key_ref="provider/groq", priority=50),
        ProviderConfig(name="openrouter", kind="openai_compat", base_url="https://or.invalid/v1",
                       models=["max"], tier="powerful", key_ref="provider/openrouter", priority=100),
    ]


def config_of(tmp_path) -> Config:
    return Config(data_dir=tmp_path, providers=configs())


def test_baseline_applies_when_no_rows_exist(tmp_path):
    store = Store(tmp_path / "kira.db")
    view = build_view(config_of(tmp_path), store)
    groq = view.by_name["groq"]
    assert groq.enabled is True
    assert groq.priority == 50
    assert groq.monthly_cap is None
    assert groq.states["enabled"].to_wire() == {"base": True, "override": None, "effective": True}
    assert view.orphan_settings == []
    store.close()


def test_override_wins_and_stays_visible_alongside_the_baseline(tmp_path):
    store = Store(tmp_path / "kira.db")
    store.set_setting("groq", "priority", 10)
    store.set_setting("groq", "tier", "powerful")
    store.set_setting("groq", "enabled", False)
    store.set_setting("groq", "monthly_cap", 1000000)
    groq = build_view(config_of(tmp_path), store).by_name["groq"]
    assert (groq.priority, groq.tier, groq.enabled, groq.monthly_cap) == (10, "powerful", False, 1000000)
    assert groq.states["tier"].to_wire() == {"base": "fast", "override": "powerful", "effective": "powerful"}
    assert groq.states["monthly_cap"].to_wire() == {"base": None, "override": 1000000, "effective": 1000000}
    store.close()


def test_a_cap_override_of_zero_means_unlimited_not_blocked(tmp_path):
    # 0 is the dashboard's spelling for "no ceiling"; `null` is "drop the override".
    # The two must not be confusable, and only the first is a stored row.
    store = Store(tmp_path / "kira.db")
    store.set_setting("groq", "monthly_cap", 0)
    view = build_view(config_of(tmp_path, cap=2_000), store)
    groq = view.by_name["groq"]
    assert groq.states["monthly_cap"].to_wire() == {"base": 2000, "override": 0, "effective": None}
    assert view.orphan_settings == []
    store.close()


def test_enabled_base_is_true_because_yaml_has_no_enabled_key(tmp_path):
    store = Store(tmp_path / "kira.db")
    groq = build_view(config_of(tmp_path), store).by_name["groq"]
    assert groq.states["enabled"].base is True
    store.close()


def test_a_row_of_the_wrong_type_behaves_as_absent_and_is_reported(tmp_path):
    store = Store(tmp_path / "kira.db")
    store.set_setting("groq", "enabled", 1)        # JSON 1, not a bool
    store.set_setting("groq", "priority", "60")  # JSON string, not an int
    view = build_view(config_of(tmp_path), store)
    groq = view.by_name["groq"]
    assert groq.enabled is True and groq.priority == 50
    assert sorted(view.orphan_settings) == ["groq.enabled", "groq.priority"]
    store.close()


def test_a_key_that_is_not_tunable_is_reported_not_swallowed(tmp_path):
    store = Store(tmp_path / "kira.db")
    # The write boundary refuses this, so it can only arrive from a hand edit or an older build.
    store._conn.execute(  # noqa: SLF001 - deliberately writing underneath the API
        "INSERT INTO settings(provider, key, value, updated_at) VALUES('groq','colour','red',0)"
    )
    store._conn.commit()
    view = build_view(config_of(tmp_path), store)
    assert view.by_name["groq"].priority == 50, "an unusable row changes nothing"
    assert view.orphan_settings == ["groq.colour"]
    store.close()


def test_true_is_not_an_integer_for_priority(tmp_path):
    # bool is a subclass of int in Python; `true` in the database is not priority 1.
    store = Store(tmp_path / "kira.db")
    store.set_setting("groq", "priority", True)
    view = build_view(config_of(tmp_path), store)
    assert view.by_name["groq"].priority == 50
    assert view.orphan_settings == ["groq.priority"]
    store.close()


def test_unparseable_json_is_reported_rather_than_raising(tmp_path):
    store = Store(tmp_path / "kira.db")
    store._conn.execute(  # noqa: SLF001 - deliberately writing underneath the API
        "INSERT INTO settings(provider, key, value, updated_at) VALUES('groq','tier','not json',1.0)"
    )
    store._conn.commit()
    view = build_view(config_of(tmp_path), store)
    assert view.by_name["groq"].tier == "fast"
    assert view.orphan_settings == ["groq.tier"]
    store.close()


def test_a_row_for_a_provider_that_left_the_yaml_is_an_orphan(tmp_path):
    store = Store(tmp_path / "kira.db")
    store.set_setting("deleted_provider", "enabled", False)
    view = build_view(config_of(tmp_path), store)
    assert "deleted_provider" not in view.by_name
    assert view.orphan_settings == ["deleted_provider.enabled"]
    assert store.delete_settings("deleted_provider") == 1
    assert build_view(config_of(tmp_path), store).orphan_settings == []
    store.close()


def test_view_without_a_store_is_the_plain_yaml_baseline(tmp_path):
    view = build_view(config_of(tmp_path), None)
    assert [p.name for p in view.providers] == ["groq", "openrouter"]
    assert all(p.enabled for p in view.providers)
    assert view.orphan_settings == []


def test_enabled_providers_is_what_routing_sees(tmp_path):
    store = Store(tmp_path / "kira.db")
    store.set_setting("groq", "enabled", False)
    store.set_setting("openrouter", "priority", 1)
    view = build_view(config_of(tmp_path), store)
    assert [p.name for p in enabled_providers(view)] == ["openrouter"]
    store.close()
```

`config_of()` in the zero-cap test takes a `cap` keyword. Change its definition in this same block to:

```python
def config_of(tmp_path, cap: int | None = None) -> Config:
    return Config(
        data_dir=tmp_path,
        providers=[replace(p, monthly_token_cap=cap) for p in configs()] if cap is not None else configs(),
    )
```

and add `from dataclasses import replace` to the imports at the top of `tests/test_overrides.py`.

- [ ] **Step 2: Run them to watch them fail**

Run: `cd kira-engine && .venv/Scripts/python.exe -m pytest -q tests/test_overrides.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'kira.overrides'`.

- [ ] **Step 3: Add the YAML baseline field the merge reads**

In `config.py`, give `ProviderConfig` a new last field after `priority: int = 100`:

```python
    monthly_token_cap: int | None = None
```

Add the validation at the end of `ProviderConfig.__post_init__`:

```python
        cap = self.monthly_token_cap
        if cap is not None and (isinstance(cap, bool) or not isinstance(cap, int) or cap <= 0):
            raise ConfigError(f"provider '{self.name}' monthly_token_cap must be a positive integer")
```

In `_provider_from`, add to the returned kwargs:

```python
        monthly_token_cap=_optional_positive_int(raw.get("monthly_token_cap")),
```

and put that helper immediately above `_provider_from`, so `0` and an absent key both land on `None` rather than smuggling a zero-cap provider into memory:

```python
def _optional_positive_int(value: Any) -> int | None:
    if value is None or value == 0:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"monthly_token_cap must be an integer, got {value!r}")
    if value < 0:
        raise ConfigError(f"monthly_token_cap must be positive, got {value}")
    return int(value)
```

Add the commented example to `SAMPLE_CONFIG` inside the `groq` stanza, after its `models` list and before the blank line that separates stanzas:

```yaml
    # Optional ceiling for this provider, tokens per calendar month. The router
    # stands the provider down once the month's derived spend reaches it.
    # Absent (or 0) means unlimited. Set it from the dashboard instead of here
    # unless you want it as the baseline every override resets to.
    # monthly_token_cap: 1000000
```

Append to `kira-engine/tests/test_units.py`:

```python
def test_sample_config_leaves_the_cap_absent(tmp_path):
    write_sample_config(tmp_path)
    assert load_config(tmp_path).by_name["groq"].monthly_token_cap is None


def test_yaml_cap_is_read_and_validated(tmp_path):
    stanza = (
        "providers:\n  - name: groq\n    kind: openai_compat\n    base_url: https://g.invalid\n"
        "    models: [mini]\n"
    )
    (tmp_path / "config.yaml").write_text(stanza + "    monthly_token_cap: 1000000\n", encoding="utf-8")
    assert load_config(tmp_path).by_name["groq"].monthly_token_cap == 1000000

    for bad in ("-5", "true", '"many"', "0"):
        (tmp_path / "config.yaml").write_text(stanza + f"    monthly_token_cap: {bad}\n", encoding="utf-8")
        if bad == "0":
            # 0 is the "no ceiling" spelling, so it lands on None rather than a zero-cap provider.
            assert load_config(tmp_path).by_name["groq"].monthly_token_cap is None
        else:
            with pytest.raises(ConfigError, match="monthly_token_cap"):
                load_config(tmp_path)
```

`load_config` validates while it reads, so the call has to sit **inside** `pytest.raises` (amendment 28);
binding it to a name first raises the error out of the block and fails the test for the right reason.

Run: `cd kira-engine && .venv/Scripts/python.exe -m pytest -q tests/test_units.py`
Expected: PASS (19 tests, up from 17).

- [ ] **Step 4: Write the module**

Create `kira-engine/src/kira/overrides.py`:

```python
"""One merged view of the providers, shared by the router, the API and the dashboard.

`config.yaml` is the hand-authored baseline and is never written by Kira. The `settings`
table holds the four fields the dashboard tunes. The merge runs per request instead of
being cached, so a toggle takes effect on the next turn rather than at the next restart,
and a row that cannot be trusted is reported instead of quietly applied.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .config import TIERS, Config, ProviderConfig
from .store import SETTINGS_KEYS, Store

TUNABLE_FIELDS = ("enabled", "priority", "tier", "monthly_cap")


def _boolean(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _integer(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _tier(value: Any) -> str | None:
    return value if isinstance(value, str) and value in TIERS else None


def _cap(value: Any) -> int | None:
    """A stored cap is a non-negative int; 0 is the dashboard's spelling of unlimited."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value >= 0 else None


#: setting key -> validator. `None` from a validator means the row is unusable.
_VALIDATORS: dict[str, Callable[[Any], Any]] = {
    "enabled": _boolean,
    "priority": _integer,
    "tier": _tier,
    "monthly_cap": _cap,
}


class _Junk:
    """Marker for a stored row that cannot be used - distinct from `None`, which is a value."""

    def __repr__(self) -> str:
        return "<junk>"


JUNK = _Junk()


@dataclass
class FieldState:
    base: Any
    override: Any
    effective: Any

    def to_wire(self) -> dict[str, Any]:
        return {"base": self.base, "override": self.override, "effective": self.effective}


@dataclass
class EffectiveProvider:
    name: str
    kind: str
    base_url: str
    models: list[str]
    key_ref: str
    priority: int
    tier: str
    enabled: bool
    monthly_cap: int | None
    base: ProviderConfig
    states: dict[str, FieldState] = field(default_factory=dict)


@dataclass
class MergedView:
    providers: list[EffectiveProvider]
    by_name: dict[str, EffectiveProvider]
    orphan_settings: list[str]


def _baseline(key: str, base: ProviderConfig) -> Any:
    if key == "enabled":
        # config.yaml has no `enabled` key: a stanza you wrote is a provider you meant.
        return True
    if key == "monthly_cap":
        return base.monthly_token_cap
    return getattr(base, key)


def _effective(key: str, baseline: Any, override: Any) -> Any:
    if override is None:
        return baseline
    if key == "monthly_cap":
        return None if override == 0 else override
    return override


def _override_or_junk(key: str, raw_json: str) -> Any:
    """The validated override value, or `JUNK` when the row cannot be trusted."""
    try:
        value = json.loads(raw_json)
    except json.JSONDecodeError:
        return JUNK
    validated = _VALIDATORS[key](value)
    return JUNK if validated is None else validated


def build_view(config: Config, store: Store | None = None) -> MergedView:
    rows = store.settings_map() if store is not None else {}
    orphans: list[str] = []
    providers: list[EffectiveProvider] = []

    for base in config.providers:
        stored = rows.get(base.name, {})
        states: dict[str, FieldState] = {}
        values: dict[str, Any] = {}
        for key in TUNABLE_FIELDS:
            override: Any = None
            if key in stored:
                parsed = _override_or_junk(key, stored[key])
                if isinstance(parsed, _Junk):
                    orphans.append(f"{base.name}.{key}")
                else:
                    override = parsed
            baseline = _baseline(key, base)
            states[key] = FieldState(base=baseline, override=override, effective=_effective(key, baseline, override))
            values[key] = states[key].effective
        orphans.extend(f"{base.name}.{key}" for key in sorted(set(stored) - SETTINGS_KEYS))
        providers.append(
            EffectiveProvider(
                name=base.name,
                kind=base.kind,
                base_url=base.base_url,
                models=list(base.models),
                key_ref=base.key_ref,
                priority=values["priority"],
                tier=values["tier"],
                enabled=values["enabled"],
                monthly_cap=values["monthly_cap"],
                base=base,
                states=states,
            )
        )

    for name in sorted(rows):
        if name in config.by_name:
            continue
        orphans.extend(f"{name}.{key}" for key in sorted(rows[name]))

    return MergedView(
        providers=providers,
        by_name={p.name: p for p in providers},
        orphan_settings=sorted(set(orphans)),
    )


def enabled_providers(view: MergedView) -> list[EffectiveProvider]:
    """What routing sees: stand-down providers are absent here, and therefore everywhere."""
    return sorted((p for p in view.providers if p.enabled), key=lambda p: (p.priority, p.name))
```

- [ ] **Step 5: Run them to watch them pass**

Run: `cd kira-engine && .venv/Scripts/python.exe -m pytest -q tests/test_overrides.py`
Expected: PASS — 15 tests (4 from Task 3 + 11 here).

- [ ] **Step 6: Checkpoint**

Run: `cd kira-engine && .venv/Scripts/python.exe -m pytest -q`
Expected: `73 passed, 1 skipped` (60 after Task 3, +11 `test_overrides.py`, +2 in `test_units.py`).

If git is initialised: `git add kira-engine/src/kira/config.py kira-engine/src/kira/overrides.py kira-engine/tests && git commit -m "feat(engine): merge provider settings over the yaml baseline"`

## Task 5: Routing, `/v1/models` and health read the merged view

**Files:**
- Modify: `kira-engine/src/kira/router.py` (`Router.__init__` at `:43-46`, `plan()` at `:48-93`)
- Modify: `kira-engine/src/kira/app.py` (`Engine.__init__` at `:110-136`, `models()` at `:223-246`, `kira_health()` at `:351-366`)
- Modify: `kira-engine/tests/test_routing.py` (append)
- Modify: `kira-engine/tests/test_api.py` (append)

**Interfaces:**
- Consumes: `build_view()`, `enabled_providers()`, `MergedView`, `EffectiveProvider` from Task 4; `Store.settings_map()`.
- Produces:
  - `Router.__init__(self, registry, ledger, *, view_source: Callable[[], MergedView] | None = None)` — the attribute is `self.view_source`; with no argument it falls back to `lambda: build_view(registry.config, None)`, which is the YAML-only behaviour every existing test already assumes
  - `Engine.view() -> MergedView` — one call, used by the router and by every endpoint, so the dashboard and the router can never be looking at different data
  - The budget gate is **not** here. It arrives in Task 15 with `skipped_budget`, once spend is derivable.

- [ ] **Step 1: Write the failing tests**

Append to `kira-engine/tests/test_routing.py`:

```python
async def test_a_disabled_provider_is_absent_from_every_mode(harness):
    harness.store.set_setting("fast_one", "enabled", False)
    harness.script.queue("fast2", ok(openai_text_chunks("x")))
    assert "fast_one" not in {c.provider for c in harness.engine.router.plan().choices}
    assert "fast_one" not in {c.provider for c in harness.engine.router.plan(mode="FAST").choices}
    assert "fast_one" not in {c.provider for c in harness.engine.router.plan(model="mini").choices}


async def test_disabling_the_only_tier_member_reports_the_tier_honestly(harness):
    from kira.errors import ConfigError

    harness.store.set_setting("big", "enabled", False)
    harness.store.set_setting("ant", "enabled", False)
    with pytest.raises(ConfigError, match="no provider configured with tier 'powerful'"):
        harness.engine.router.plan(mode="POWERFUL")


async def test_custom_refuses_a_disabled_provider_by_name(harness):
    from kira.errors import ConfigError

    harness.store.set_setting("gem", "enabled", False)
    with pytest.raises(ConfigError, match="gem.* disabled"):
        harness.engine.router.plan(mode="CUSTOM", provider="gem")
    # An unknown provider keeps its own, different message: the advice differs.
    with pytest.raises(ConfigError, match="unknown provider 'nope'"):
        harness.engine.router.plan(mode="CUSTOM", provider="nope")


async def test_a_disabled_provider_can_be_switched_back_on(harness):
    harness.store.set_setting("fast_one", "enabled", False)
    assert "fast_one" not in {c.provider for c in harness.engine.router.plan().choices}
    harness.store.clear_setting("fast_one", "enabled")
    assert "fast_one" in {c.provider for c in harness.engine.router.plan().choices}


async def test_an_override_changes_priority_ordering_live(harness):
    harness.script.queue("fast2", ok(openai_text_chunks("yo")))
    harness.store.set_setting("fast_two", "priority", 1)
    state = AttemptState()
    await drain(harness.engine.router, harness.engine.router.plan(), req(), state)
    assert state.served_by == "fast_two"
    assert "fast2.invalid" in harness.script.calls[0]
```

Append to `kira-engine/tests/test_api.py`:

```python
async def test_models_and_health_reflect_effective_tier_and_priority(harness):
    harness.store.set_setting("big", "enabled", False)
    harness.store.set_setting("fast_one", "tier", "powerful")
    harness.store.set_setting("fast_one", "priority", 7)

    models = (await harness.api.get("/v1/models", headers=harness.auth)).json()["data"]
    assert {m["id"] for m in models} == {"mini", "gemini-mock", "claude-mock"}
    assert not any(m["provider"] == "big" for m in models), "a disabled provider must not be selectable"

    snapshot = (await harness.api.get("/v1/kira/health", headers=harness.auth)).json()["configured"]
    rows = {row["name"]: row for row in snapshot}
    assert rows["fast_one"]["tier"] == "powerful" and rows["fast_one"]["priority"] == 7
    assert "big" in rows, "health lists what exists so you can switch it back on"


async def test_a_disabled_provider_still_answers_custom_with_a_400(harness):
    harness.store.set_setting("ant", "enabled", False)
    resp = await harness.api.post(
        "/v1/chat/completions",
        headers=harness.auth,
        json={"messages": [USER], "mode": "CUSTOM", "provider": "ant"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "config_error"
    assert "disabled" in resp.json()["error"]["message"]
```

- [ ] **Step 2: Run them to watch them fail**

Run: `cd kira-engine && .venv/Scripts/python.exe -m pytest -q tests/test_routing.py tests/test_api.py`
Expected: FAIL — `AttributeError: 'Router' object has no attribute 'view_source'` / `TypeError: Router.__init__() got an unexpected keyword argument 'view_source'`, and `test_models_and_health...` failing because `tier` is still the YAML value.

- [ ] **Step 3: Point the router at the view**

In `router.py`, replace the imports line `from .net import HealthLedger` and add:

```python
from .overrides import MergedView, build_view, enabled_providers
from collections.abc import Callable
```

(`Callable` goes on the existing `from collections.abc import AsyncIterator` line, making it `from collections.abc import AsyncIterator, Callable`.)

Replace `Router.__init__`:

```python
    def __init__(
        self,
        registry: ProviderRegistry,
        ledger: HealthLedger,
        *,
        view_source: Callable[[], MergedView] | None = None,
    ) -> None:
        self.registry = registry
        self.ledger = ledger
        # Without an override store this is exactly the YAML-only router every existing test built.
        self.view_source = view_source or (lambda: build_view(registry.config, None))
```

Replace the first four lines of `plan()` body:

```python
        chosen_mode = (mode or self.registry.config.default_mode).upper()
        notes: list[dict] = []
        view = self.view_source()
        configs = enabled_providers(view)
```

and replace the `CUSTOM` branch:

```python
        if chosen_mode == "CUSTOM":
            if not provider:
                raise ConfigError("mode CUSTOM requires a 'provider'")
            wanted = view.by_name.get(provider)
            if wanted is None:
                raise ConfigError(f"unknown provider '{provider}'")
            if not wanted.enabled:
                raise ConfigError(f"provider '{provider}' is disabled - switch it on in the dashboard")
            configs = [wanted]
```

Nothing else in `plan()` changes: `FAST`/`POWERFUL` filter on `c.tier`, the model filter on `c.models`, and the key loop on `c.key_ref` — all of which are effective scalars on `EffectiveProvider`, spelled the same as on `ProviderConfig` for exactly this reason.

- [ ] **Step 4: Give `Engine` one view and use it in the endpoints**

In `app.py`, import `from .overrides import MergedView, build_view, enabled_providers`. In `Engine.__init__`, after `self.registry = ProviderRegistry(...)`:

```python
        self.router = Router(self.registry, self.ledger, view_source=self.view)
```

and add the method right after `__init__`:

```python
    def view(self) -> MergedView:
        """The merged config for this request: YAML baseline plus the settings table."""
        return build_view(self.config, self.store)
```

In `models()`, replace the `data = [...]` comprehension's outer loop:

```python
        view = engine.view()
        data = [
            {"id": model, "object": "model", "owned_by": provider.name, "provider": provider.name, "tier": provider.tier}
            for provider in enabled_providers(view)
            for model in provider.models
        ]
```

In `kira_health()`, replace the `configured` comprehension to read the view instead of `cfg.providers`, so the sidebar cannot show a tier the router disagrees with:

```python
            "configured": [
                {
                    "name": p.name,
                    "kind": p.kind,
                    "tier": p.tier,
                    "priority": p.priority,
                    "models": p.models,
                    "key_present": (engine.registry.key_for(p.name) is not None) if p.key_ref else False,
                }
                for p in engine.view().providers
            ],
```

- [ ] **Step 5: Run everything**

Run: `cd kira-engine && .venv/Scripts/python.exe -m pytest -q`
Expected: `80 passed, 1 skipped` — the 7 new tests, and all 73 existing still green. If any pre-existing routing test breaks, the merge is leaking: `build_view(config, None)` must return providers identical to the YAML.

- [ ] **Step 6: Checkpoint**

Also run the chat suite to prove nothing cross-language moved: `cd kira-chat && npm run test`. Expected `29 passed`.

If git is initialised: `git add kira-engine/src/kira/router.py kira-engine/src/kira/app.py kira-engine/tests && git commit -m "feat(engine): route on merged provider settings"`

## Task 6: Derived spend, overview aggregates, session rows and deletes

**Files:**
- Create: `kira-engine/tests/test_store.py`
- Modify: `kira-engine/src/kira/store.py` (methods after `delete_settings`)

**Interfaces:**
- Consumes: `month_bounds()` from Task 3; the `messages` and `sessions` tables as they already exist.
- Produces, all on `Store`, all taking `(start, end)` epoch floats from `month_bounds()`:
  - `monthly_spend(start, end) -> dict[str, int]` — provider → combined tokens
  - `overview(start, end) -> dict` — `{"month": str, "turns": int, "tokens": {"input": int, "output": int}, "success_rate": float | None, "interrupted": int, "failed": int, "by_provider": [...], "by_model": [...], "daily": [...], "recent_issues": [...]}`
  - `session_rows(limit: int = 50) -> list[dict]` — `id`, `mode`, `created_at`, `message_count`, `tokens`, `last_used_at` (`None` for an empty session)
  - `delete_session(session_id) -> tuple[int, int]` and `clear_sessions() -> tuple[int, int]` — `(sessions, messages)` actually removed
  - `usage_for_month(name: str | None = None) -> tuple[str, dict[str, int]]` — convenience for the router and the providers endpoint: the current month's label and its spend map

- [ ] **Step 1: Write the failing tests**

Create `kira-engine/tests/test_store.py`:

```python
from __future__ import annotations

import json
from datetime import datetime, timezone

from kira.errors import ConfigError
from kira.store import Store, month_bounds


def ts(year: int, month: int, day: int, hour: int = 12) -> float:
    return datetime(year, month, day, hour, tzinfo=timezone.utc).timestamp()


def october() -> tuple[float, float]:
    _, start, end = month_bounds("2026-10")
    return start, end
```


def test_month_bounds_is_a_half_open_utc_window():
    label, start, end = month_bounds("2026-10")
    assert label == "2026-10"
    assert start == ts(2026, 10, 1, 0)
    assert end == ts(2026, 11, 1, 0)
    assert end - start == 31 * 86400


def test_month_bounds_rolls_the_year_over():
    _, start, end = month_bounds("2026-12")
    assert datetime.fromtimestamp(end, timezone.utc).year == 2027


def test_month_bounds_rejects_nonsense():
    for bad in ("2026-13", "10-2026", "2026-1", "next month", ""):
        try:
            month_bounds(bad)
        except ConfigError:
            pass
        else:
            raise AssertionError(f"{bad!r} should not parse as a month")


def test_month_bounds_defaults_to_the_current_month():
    label, _, _ = month_bounds()
    assert label == datetime.now(timezone.utc).strftime("%Y-%m")


def test_spend_counts_turns_that_did_not_finish(tmp_path):
    """An interrupted answer still consumed tokens; skipping it understates the bill."""
    store = Store(tmp_path / "kira.db")
    store.create_session("AUTO", "sess-1")
    start, end = october()
    rows = (("complete", 60, 40), ("interrupted", 25, 5), ("failed", 0, 0))
    for offset, (status, tokens_in, tokens_out) in enumerate(rows):
        store._conn.execute(  # noqa: SLF001 - one window, three statuses, no clock drift
            """INSERT INTO messages(session_id, role, content, provider, model, status,
                                     tool_calls, usage, chain, created_at)
               VALUES('sess-1','assistant','a','groq','mini',?,'[]',?,'[]',?)""",
            (status, f'{{"input_tokens": {tokens_in}, "output_tokens": {tokens_out}}}', start + offset),
        )
    store._conn.commit()
    assert store.monthly_spend(start, end) == {"groq": 130}
    store.close()


def test_spend_is_scoped_to_one_month(tmp_path):
    store = Store(tmp_path / "kira.db")
    sid = store.create_session("AUTO", "sess-1")
    # Two rows in October, one in September: only the window may count.
    for when, tokens in ((ts(2026, 10, 5), 15), (ts(2026, 10, 20), 15), (ts(2026, 9, 30), 999)):
        store._conn.execute(  # noqa: SLF001 - seeding an exact timestamp
            """INSERT INTO messages(session_id, role, content, provider, model, status,
                                     tool_calls, usage, chain, created_at)
               VALUES('sess-1','assistant','a','groq','mini','complete','[]',?,?, '[]', ?)""",
            (f'{{"input_tokens": {tokens // 2}, "output_tokens": {tokens - tokens // 2}}}', when),
        )
    store._conn.commit()
    start, end = october()
    assert store.monthly_spend(start, end) == {"groq": 30}
    _, sep_start, sep_end = month_bounds("2026-09")
    assert store.monthly_spend(sep_start, sep_end) == {"groq": 999}
    store.close()


def test_overview_aggregates_split_the_way_the_spec_defines_them(tmp_path):
    store = Store(tmp_path / "kira.db")
    start, end = october()
    sid = seed_at(store, start + 3600 * 24 * 4, ts(2026, 10, 5))
    view = store.overview(start, end)
    assert view["month"] == "2026-10"
    assert view["turns"] == 3
    assert view["tokens"] == {"input": 18, "output": 7}
    assert view["interrupted"] == 1 and view["failed"] == 1
    assert view["success_rate"] == round(1 / 3, 3)
    assert view["by_provider"] == [{"provider": "ant", "turns": 1, "tokens": 0},
                                   {"provider": "groq", "turns": 2, "tokens": 25}]
    assert view["by_model"][0] == {"provider": "groq", "model": "mini", "turns": 2, "tokens": 25}
    assert view["daily"] == [{"date": "2026-10-05", "turns": 3, "tokens": 25}]
    assert [r["status"] for r in view["recent_issues"]] == ["failed", "interrupted"]
    assert view["recent_issues"][1]["session_id"] == sid
    store.close()
```

Two things the block above gets wrong, both fixed by the helpers below rather than by weakening the
assertions (amendment 30):

1. `seed()` writes through `add_message()`, which always stamps the real clock, so the overview test cannot
   name a day. It is replaced by `seed_at()`, which inserts with the timestamps the test chooses.
2. `create_session()` stamps the real clock too. So a test that seeds October rows and then asks
   `monthly_spend(start, end)` about `"2026-10"` must seed **inside that window** — a `1.0` timestamp is
   January 1970 and would make the spend assertion pass or fail on the calendar rather than on the code —
   and `test_session_rows_carry_counts_and_the_last_activity` has to pin the empty session's `created_at`
   or it outranks the busy one (today really is later than the 5th).

```python
def seed_at(store: Store, first_created: float, day: float) -> str:
    """Three assistant rows in one day: one served, one interrupted, one failed."""
    sid = store.create_session("AUTO", "sess-1")
    rows = [
        ("a1", "groq", "mini", "complete", 10, 5, [{"provider": "groq", "event": "served"}]),
        ("half", "groq", "mini", "interrupted", 8, 2, [{"provider": "groq", "event": "aborted_mid_stream", "reason": "client saw text"}]),
        ("", "ant", "claude", "failed", 0, 0, [{"provider": "ant", "event": "failed", "reason": "provider_5xx status=503 down"}]),
    ]
    for offset, (content, provider, model, status, tokens_in, tokens_out, chain) in enumerate(rows):
        store._conn.execute(  # noqa: SLF001 - a test needs timestamps it controls
            """INSERT INTO messages(session_id, role, content, provider, model, finish_reason,
                                     status, tool_calls, usage, chain, created_at)
               VALUES(?, 'assistant', ?,?,?,NULL,?,'[]',?,?,?)""",
            (sid, content, provider, model, status,
             f'{{"input_tokens": {tokens_in}, "output_tokens": {tokens_out}}}',
             json.dumps(chain), day + offset),
        )
    store._conn.execute(
        "INSERT INTO messages(session_id, role, content, created_at) VALUES(?, 'user', 'q1', ?)",
        (sid, first_created),
    )
    store._conn.commit()
    return sid
```

and append:

```python
def test_success_rate_is_null_not_zero_when_nothing_was_served(tmp_path):
    store = Store(tmp_path / "kira.db")
    start, end = october()
    assert store.overview(start, end)["success_rate"] is None
    assert store.overview(start, end)["turns"] == 0
    store.close()


def test_recent_issues_reports_the_reason_the_chain_already_holds(tmp_path):
    store = Store(tmp_path / "kira.db")
    start, end = october()
    seed_at(store, start + 3600, start + 3600 * 24 * 4)
    issue = store.overview(start, end)["recent_issues"][0]
    assert issue["provider"] == "ant"
    assert "provider_5xx" in issue["reason"]
    store.close()


def test_empty_chain_row_reports_an_empty_reason_not_a_crash(tmp_path):
    store = Store(tmp_path / "kira.db")
    sid = store.create_session("AUTO")
    store.add_message(sid, "assistant", "", provider="groq", status="failed")
    start, end = month_bounds()[1:]
    assert store.overview(start, end)["recent_issues"][0]["reason"] == ""
    store.close()


def test_session_rows_carry_counts_and_the_last_activity(tmp_path):
    store = Store(tmp_path / "kira.db")
    start, _ = october()
    busy = seed_at(store, start + 3600, start + 3600 * 24 * 4)
    quiet = store.create_session("FAST", "sess-empty")
    # create_session stamps the real clock, which is later than any seeded month; the
    # ordering below is about COALESCE(last_used_at, created_at), so pin both ends.
    store._conn.execute("UPDATE sessions SET created_at=? WHERE id=?", (start, quiet))  # noqa: SLF001
    store._conn.commit()
    rows = {row["id"]: row for row in store.session_rows()}
    assert rows[busy]["message_count"] == 4
    assert rows[busy]["tokens"] == 25
    assert rows[busy]["last_used_at"] >= start + 3600 * 24 * 4
    assert rows[quiet]["message_count"] == 0
    assert rows[quiet]["tokens"] == 0
    assert rows[quiet]["last_used_at"] is None
    assert [row["id"] for row in store.session_rows()] == [busy, quiet], "most recently used first"
    store.close()


def test_delete_one_session_cascades_its_messages(tmp_path):
    store = Store(tmp_path / "kira.db")
    seed_at(store, 1.0, 1.0)
    assert store.delete_session("sess-1") == (1, 4)
    assert store.list_sessions() == []
    assert store.messages("sess-1") == []
    assert store.delete_session("sess-1") == (0, 0), "deleting what is already gone is not an error"
    store.close()


def test_clear_all_removes_everything_and_says_how_much(tmp_path):
    store = Store(tmp_path / "kira.db")
    start, end = october()
    seed_at(store, start + 3600, start + 3600 * 24 * 4)
    store.create_session("AUTO", "other")
    assert store.monthly_spend(start, end) != {}, "the rows are inside the window before the delete"
    sessions, messages = store.clear_sessions()
    assert (sessions, messages) == (2, 4)
    assert store.list_sessions() == []
    assert store.monthly_spend(start, end) == {}
    store.close()


def test_disabling_a_provider_never_forgets_what_it_already_spent(tmp_path):
    # The spec's point: a stand-down must not rewrite history.
    store = Store(tmp_path / "kira.db")
    start, end = october()
    seed_at(store, start + 3600, start + 3600 * 24 * 4)
    assert store.monthly_spend(start, end)["groq"] == 25
    store.set_setting("groq", "enabled", False)
    assert store.monthly_spend(start, end)["groq"] == 25
    store.close()


def test_usage_for_month_returns_the_label_it_used(tmp_path):
    store = Store(tmp_path / "kira.db")
    start, _ = october()
    seed_at(store, start + 3600, start + 3600 * 24 * 4)
    label, spend = store.usage_for_month("2026-10")
    assert label == "2026-10"
    assert spend == {"groq": 25, "ant": 0}
    store.close()
```

- [ ] **Step 2: Run them to watch them fail**

Run: `cd kira-engine && .venv/Scripts/python.exe -m pytest -q tests/test_store.py`
Expected: FAIL — `AttributeError: 'Store' object has no attribute 'monthly_spend'` (and `month_bounds` imports cleanly from Task 3).

- [ ] **Step 3: Implement the read side**

In `store.py`, add after `delete_settings()`:

```python
    def monthly_spend(self, month_start: float, month_end: float) -> dict[str, int]:
        """Derived, never accumulated: a partial generation was still billed, so
        interrupted and failed rows count. User rows carry no provider and are excluded."""
        rows = self._conn.execute(
            """SELECT provider,
                      SUM(COALESCE(json_extract(usage,'$.input_tokens'), 0)
                        + COALESCE(json_extract(usage,'$.output_tokens'), 0)) AS tokens
               FROM messages
               WHERE role = 'assistant' AND provider IS NOT NULL
                 AND created_at >= ? AND created_at < ?
               GROUP BY provider""",
            (month_start, month_end),
        ).fetchall()
        return {row["provider"]: int(row["tokens"] or 0) for row in rows}

    def usage_for_month(self, month: str | None = None) -> tuple[str, dict[str, int]]:
        label, start, end = month_bounds(month)
        return label, self.monthly_spend(start, end)

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
```

Add the module-level helper next to `month_bounds()`:

```python
def _failure_reason(chain: list[dict]) -> str:
    """The newest thing the chain blames, so the Overview list is actionable at a glance."""
    for record in reversed(chain):
        if record.get("event") in ("failed", "aborted_mid_stream", "skipped_budget", "skipped_config"):
            return str(record.get("reason") or record.get("event"))
    return str(chain[-1].get("event")) if chain else ""
```

- [ ] **Step 4: Run them to watch them pass**

Run: `cd kira-engine && .venv/Scripts/python.exe -m pytest -q tests/test_store.py`
Expected: PASS — 15 tests.

- [ ] **Step 5: Checkpoint**

Run: `cd kira-engine && .venv/Scripts/python.exe -m pytest -q`
Expected: `95 passed, 1 skipped` (80 after Task 5 + 15 store).

If git is initialised: `git add kira-engine/src/kira/store.py kira-engine/tests/test_store.py && git commit -m "feat(engine): derived spend, overview aggregates, session deletes"`

---

## Task 7: One probe implementation — `probe.py`

Spec amendment 4 says the CLI and the dashboard's Test button must share one implementation so they
cannot drift. This task creates that implementation and switches both callers to it. It adds no
endpoint yet — Task 12 wires `POST /v1/kira/providers/{name}/probe` to `probe_provider()`.

**Files:**
- Create: `kira-engine/src/kira/probe.py`
- Create: `kira-engine/tests/test_probe.py`
- Modify: `kira-engine/src/kira/app.py` (`models()` live branch; find it with `grep -n "if live:" app.py`)
- Modify: `kira-engine/src/kira/__main__.py` (`cmd_models`; find it with `grep -n "def cmd_models" __main__.py`)

**Interfaces produced:**
- `ProbeResult(provider: str, ok: bool, model_count: int, sample: list[str], latency_ms: int | None, error: str | None)` with `.to_wire() -> dict`
- `async probe_models(registry: ProviderRegistry, name: str) -> ProbeResult` — `list_models` only, never spends completion credits
- `async probe_provider(registry: ProviderRegistry, name: str) -> ProbeResult` — `list_models` **plus** one completion capped at `PROBE_MAX_OUTPUT_TOKENS`
- `PROBE_PROMPT: str`, `PROBE_MAX_OUTPUT_TOKENS = 8`, `SAMPLE_LIMIT = 8`

- [ ] **Step 1: Write the failing tests**

Create `kira-engine/tests/test_probe.py`:

```python
from __future__ import annotations

import httpx

from kira.config import Config
from kira.probe import (
    PROBE_MAX_OUTPUT_TOKENS,
    SAMPLE_LIMIT,
    ProbeResult,
    probe_models,
    probe_provider,
)
from kira.providers.registry import ProviderRegistry
from kira.vault import Vault
from conftest import Scripted, ok, ok_json, openai_text_chunks, provider_configs


def registry_for(tmp_path, scripted: Scripted, *, keyed: bool = True) -> ProviderRegistry:
    config = Config(data_dir=tmp_path, providers=provider_configs())
    vault = Vault("memory")
    if keyed:
        for provider in config.providers:
            vault.set(provider.key_ref, "sekret")
    client = httpx.AsyncClient(transport=scripted.transport, timeout=config.request_timeout_s)
    return ProviderRegistry(config, vault, client)


async def test_probe_models_lists_without_calling_the_chat_endpoint(tmp_path):
    scripted = Scripted()
    scripted.queue("fast1", ok_json({"data": [{"id": "mini"}, {"id": "mini-2"}]}))
    result = await probe_models(registry_for(tmp_path, scripted), "fast_one")
    assert result.ok and result.model_count == 2
    assert result.sample == ["mini", "mini-2"]
    # A list probe that completes would spend the user's money without asking.
    assert result.latency_ms is None
    assert scripted.calls == ["fast1https://fast1.invalid/v1/models"]


async def test_probe_sample_stays_short(tmp_path):
    scripted = Scripted()
    scripted.queue("fast1", ok_json({"data": [{"id": f"m{i}"} for i in range(SAMPLE_LIMIT + 12)]}))
    result = await probe_models(registry_for(tmp_path, scripted), "fast_one")
    assert result.model_count == SAMPLE_LIMIT + 12
    assert len(result.sample) == SAMPLE_LIMIT


async def test_probe_provider_adds_one_capped_completion(tmp_path):
    scripted = Scripted()
    scripted.queue("fast1", ok_json({"data": [{"id": "mini"}]}))
    scripted.queue("fast1", ok(openai_text_chunks("ok")))
    result = await probe_provider(registry_for(tmp_path, scripted), "fast_one")
    assert result.ok and result.model_count == 1
    assert result.latency_ms is not None and result.latency_ms >= 0
    body = scripted.body_for("fast1")
    assert body["max_tokens"] == PROBE_MAX_OUTPUT_TOKENS
    # The probe exercises the model you actually route to, not a catalogue id.
    assert body["model"] == "mini"
    assert len(scripted.calls) == 2


async def test_a_failing_completion_is_reported_not_raised(tmp_path):
    scripted = Scripted()
    scripted.queue("fast1", ok_json({"data": [{"id": "mini"}]}))
    scripted.queue("fast1", httpx.Response(500, json={"error": {"message": "upstream down"}}))
    result = await probe_provider(registry_for(tmp_path, scripted), "fast_one")
    assert not result.ok
    assert "upstream down" in (result.error or "")
    assert result.model_count == 1, "the list half still succeeded; say so"


async def test_a_missing_key_costs_no_http_calls(tmp_path):
    scripted = Scripted()
    result = await probe_provider(registry_for(tmp_path, scripted, keyed=False), "fast_one")
    assert not result.ok and scripted.calls == []
    assert "no key" in (result.error or "") and "provider/fast_one" in (result.error or "")


async def test_an_unknown_provider_is_an_error_not_a_crash(tmp_path):
    scripted = Scripted()
    result = await probe_models(registry_for(tmp_path, scripted), "ghost")
    assert not result.ok and "ghost" in (result.error or "")


def test_the_wire_shape_is_the_documented_one():
    assert set(ProbeResult(provider="p", ok=True).to_wire()) == {
        "provider",
        "ok",
        "model_count",
        "sample",
        "latency_ms",
        "error",
    }
```

- [ ] **Step 2: Run them to watch them fail**

Run: `cd kira-engine && .venv/Scripts/python.exe -m pytest -q tests/test_probe.py`
Expected: collection error `ModuleNotFoundError: No module named 'kira.probe'`.

- [ ] **Step 3: Write the module**

Create `kira-engine/src/kira/probe.py`:

```python
from __future__ import annotations

import time
from dataclasses import dataclass, field

import httpx

from .errors import KiraError, ProviderCallError
from .providers.registry import ProviderRegistry
from .types import Completed, GenRequest, Message

#: One word, so a probe cannot turn into an essay that gets billed.
PROBE_PROMPT = "Reply with exactly one word: ok"
PROBE_MAX_OUTPUT_TOKENS = 8
SAMPLE_LIMIT = 8

PROBE_ERRORS = (KiraError, ProviderCallError, httpx.HTTPError)


@dataclass
class ProbeResult:
    """What we learned about one provider. A failure is a value, never an exception."""

    provider: str
    ok: bool
    model_count: int = 0
    sample: list[str] = field(default_factory=list)
    latency_ms: int | None = None
    error: str | None = None

    def to_wire(self) -> dict:
        return {
            "provider": self.provider,
            "ok": self.ok,
            "model_count": self.model_count,
            "sample": list(self.sample),
            "latency_ms": self.latency_ms,
            "error": self.error,
        }


def _missing_key(registry: ProviderRegistry, name: str) -> str | None:
    cfg = registry.config_for(name)
    if cfg.key_ref and registry.key_for(name) is None:
        return f"no key in the {registry.vault.location} (ref '{cfg.key_ref}')"
    return None


async def probe_models(registry: ProviderRegistry, name: str) -> ProbeResult:
    """`list_models` only. This is what the CLI and `?live=true` run: free, read-only metadata."""
    result = ProbeResult(provider=name, ok=False)
    try:
        missing = _missing_key(registry, name)
        if missing:
            result.error = missing
            return result
        listed = await registry.build(name).list_models()
    except PROBE_ERRORS as exc:
        result.error = str(exc)[:300]
        return result
    result.ok = True
    result.model_count = len(listed)
    result.sample = listed[:SAMPLE_LIMIT]
    return result


async def probe_provider(registry: ProviderRegistry, name: str) -> ProbeResult:
    """The dashboard's Test button: metadata plus one tiny completion.

    A human clicked this, so it may spend 8 tokens. Nothing here writes to the `messages`
    table - a diagnostic is not a conversation, so it must not appear in the month's spend.
    """
    result = await probe_models(registry, name)
    if not result.ok:
        return result
    request = GenRequest(
        model=registry.config_for(name).models[0],
        messages=[Message(role="user", content=PROBE_PROMPT)],
        max_output_tokens=PROBE_MAX_OUTPUT_TOKENS,
    )
    started = time.monotonic()
    try:
        async for event in registry.build(name).stream(request):
            if isinstance(event, Completed):
                break
    except PROBE_ERRORS as exc:
        result.ok = False
        result.error = f"completion failed: {str(exc)[:280]}"
        result.latency_ms = int((time.monotonic() - started) * 1000)
        return result
    result.latency_ms = int((time.monotonic() - started) * 1000)
    return result
```

- [ ] **Step 4: Run them to watch them pass**

Run: `cd kira-engine && .venv/Scripts/python.exe -m pytest -q tests/test_probe.py`
Expected: PASS — 7 tests.

- [ ] **Step 5: Rewire the two callers**

In `app.py`, add `from .probe import probe_models` to the `from .` imports (between `.overrides` and
`.providers.registry`, keeping the block alphabetical). Replace the whole
`if live:` block inside `models()` with:

```python
        if live:
            # One implementation for CLI, chat and dashboard probes, so none of them can drift.
            payload["live"] = [
                (await probe_models(engine.registry, provider.name)).to_wire()
                for provider in enabled_providers(view)
            ]
```

`view` is the local Task 5 introduced in the same function; the probe list now follows the merged
view exactly like `data` does, so a disabled provider appears in neither half of the response.

In `__main__.py`, replace `cmd_models` whole:

```python
def cmd_models(args: argparse.Namespace) -> int:
    import httpx

    from .probe import probe_models
    from .providers.registry import ProviderRegistry

    config = load_config(_data_dir(args))
    vault = Vault(args.backend)

    async def probe() -> list[dict]:
        async with httpx.AsyncClient(timeout=config.request_timeout_s) as client:
            registry = ProviderRegistry(config, vault, client)
            return [(await probe_models(registry, p.name)).to_wire() for p in config.providers]

    rows = asyncio.run(probe())
    print(json.dumps(rows, indent=2))
    return 0 if all(row["ok"] for row in rows) else 1
```

The `ProviderCallError` / `KiraError` / `httpx.HTTPError` try-except goes away because `probe_models`
already turns every failure into a value, and `from .providers.registry import ProviderRegistry`
moves up from inside `probe()` — it was only nested there to dodge an import cycle that does not
exist at module level (`__main__` is a script entry point; `providers.registry` never imports it).
`ProviderCallError` then has no other reader in `__main__.py`, so line 12 becomes
`from .errors import KiraError` (still needed by `main()`'s top-level handler). The old CLI row said
`count`; `to_wire()` says `model_count`, which is the shape the contract publishes from Task 8 on —
`kira-contracts/types.ts` still carries the stale `LiveProbe.count` until then, and nothing in the
client reads `live`, so the drift gate and the client suite both stay green across the gap.

- [ ] **Step 6: Run everything**

Run: `cd kira-engine && .venv/Scripts/python.exe -m pytest -q`
Expected: `102 passed, 1 skipped` (95 after Task 6, +7 `test_probe.py`).
`test_models_live_probe_reports_the_truth_per_provider` in `test_api.py` must stay green — it asserts
`sample`, which `probe_models` still fills.

Run: `cd kira-engine && .venv/Scripts/kira-engine.exe models --backend memory`
Expected: a JSON array, one object per provider in `config.yaml` (or `[]` if the file has none).
With a memory vault every object is `ok: false` and names the missing key; exit code is 1 in that
case. Never a traceback — that is the point of `probe_models` returning a value.

- [ ] **Step 7: Checkpoint**

Run: `cd kira-engine && .venv/Scripts/python.exe -m pytest -q`
Expected: `102 passed, 1 skipped`.

If git is initialised: `git add kira-engine/src/kira/probe.py kira-engine/tests/test_probe.py kira-engine/src/kira/app.py kira-engine/src/kira/__main__.py && git commit -m "feat(engine): single probe implementation shared by CLI, chat and dashboard"`

---

## Task 8: Contract version 2 — document everything before anything ships

One version bump carries four changes: `skipped_budget` joins `CHAIN_EVENTS`, `budget_exhausted`
joins `ERROR_CODES`, the dashboard schemas and paths are published, and `LiveProbe` is folded into
`ProbeResponse`. Doing this as one task is deliberate: `check-drift.mjs` compares the engine export
against the hand-written mirror, so a half-bumped contract is a red gate, and the chat's version
guard means engine and UI must agree at every checkpoint from here on.

**Files:**
- Modify: `kira-engine/src/kira/errors.py` (after `AllProvidersExhausted`, `:55-62`)
- Modify: `kira-engine/src/kira/contracts.py` (`CONTRACT_VERSION` `:19`, `CHAIN_EVENTS` `:21-30`, `ERROR_CODES` `:35-46`, `schemas` `:120-350`, `paths` `:353-460`, `OPENAPI["components"]` `:351`)
- Modify: `kira-contracts/contract.ts`, `kira-contracts/types.ts`
- Regenerate: `kira-contracts/openapi.json`, `kira-contracts/contract.json`, `kira-contracts/VERSION`
- Create: `kira-engine/tests/test_contract_v2.py`
- Modify: `kira-chat/src/components/ChainTrace.tsx` (`LABELS`/`TONE` at `:3-21`)
- Modify: `kira-chat/src/fake-engine.ts` (healthz default at `:46`)

**Spec amendments this task records** (add both to the spec's amendment list at the same time):

9. **`LiveProbe` and `ProbeResponse` become one schema.** Spec `:150` defines
   `ProbeResponse {provider, ok, model_count, latency_ms, error}` while `/v1/models?live=true`
   already returns `{provider, ok, count, sample, error}`. Two shapes for one fact is the drift the
   spec itself warns about, so v2 publishes a single `ProbeResponse`
   (`provider, ok, model_count, sample, latency_ms, error`) and `ModelsResponse.live` is
   `ProbeResponse[]`. `count` is renamed `model_count`; the only shipped reader asserts `sample`
   (`test_api.py:54`), and no UI reads the live list at all, so the rename costs nothing beyond the
   bump this work needs anyway.
10. **`SessionRow` and `MessageRow` become named top-level schemas.** Today they are inline item
    objects, and `check-drift.mjs:91` only inspects `components.schemas`, so the fields Task 9 adds
    (`message_count`, `tokens`, `last_used_at`) would be unprotected. Promoting them puts them inside
    the gate. `RecentIssue` (amendment 1's list rows) and `ProviderSettings` (the four FieldStates)
    get the same treatment for the same reason.
11. **`DELETE /v1/kira/providers/{name}/cooldown` returns `ProvidersResponse`.** The spec left its
    body unspecified. Returning the freshly merged provider list means the client refreshes the row
    it clicked without a second request, and it avoids inventing a one-field schema.
12. **The `skipped_budget` chip label lands with the contract, not with the budget gate.** A
    documented chain event with no UI label renders a blank chip, and Tasks 15-16 are three tasks
    away; `ChainTrace.tsx` gets `"over budget"` in this task so no build can ship an unlabelled event.
13. **A refused confirm is `401 unauthorized`; a malformed body is `config_error` 400. Neither gets a
    new code.** The spec says writes "require" the second secret but not what failure looks like.
    `X-Kira-Confirm` is a proof-of-possession factor — the caller's *identity* is what failed, not a
    permission — so the existing `AuthError` carries it, the message names which secret was wrong, and
    v2 needs no new error code. Same reasoning for the 422 sanitizer in Task 12: FastAPI's default
    validation body is a different shape *and* echoes the submitted value, so a mistyped provider-key
    body could read its own secret back out of an error. The pair `config_error` 400 / `unauthorized`
    401 is what Task 14's dialog keys on: only the 401 re-opens for another keystroke, because only the
    401 means "the secret was wrong".

- [ ] **Step 1: Write the failing tests**

Create `kira-engine/tests/test_contract_v2.py`:

```python
from __future__ import annotations

from kira.contracts import CHAIN_EVENTS, CONTRACT_VERSION, ERROR_CODES, OPENAPI, contract_facts
from kira.errors import BudgetExhausted

SCHEMAS = OPENAPI["components"]["schemas"]

DASHBOARD_PATHS = [
    ("get", "/v1/kira/overview"),
    ("get", "/v1/kira/providers"),
    ("get", "/v1/kira/sessions"),
    ("put", "/v1/kira/providers/{name}/settings"),
    ("put", "/v1/kira/providers/{name}/key"),
    ("delete", "/v1/kira/providers/{name}/key"),
    ("delete", "/v1/kira/providers/{name}/cooldown"),
    ("post", "/v1/kira/providers/{name}/probe"),
    ("delete", "/v1/kira/sessions/{session_id}"),
    ("delete", "/v1/kira/sessions"),
]

WRITE_PATHS = [
    ("put", "/v1/kira/providers/{name}/settings"),
    ("put", "/v1/kira/providers/{name}/key"),
    ("delete", "/v1/kira/providers/{name}/key"),
    ("delete", "/v1/kira/providers/{name}/cooldown"),
    ("post", "/v1/kira/providers/{name}/probe"),
    ("delete", "/v1/kira/sessions/{session_id}"),
    ("delete", "/v1/kira/sessions"),
]

READ_PATHS = [
    ("get", "/v1/models"),
    ("get", "/v1/kira/health"),
    ("get", "/v1/kira/overview"),
    ("get", "/v1/kira/providers"),
    ("get", "/v1/kira/sessions"),
    ("get", "/v1/kira/sessions/{session_id}/messages"),
]


def test_the_contract_is_version_two_and_the_facts_agree():
    assert CONTRACT_VERSION == 2
    facts = contract_facts()
    assert facts["contract_version"] == 2
    assert OPENAPI["info"]["version"] == "2"
    assert facts["error_codes"] == sorted(facts["error_codes"])


def test_budget_is_a_documented_non_retryable_429():
    assert "skipped_budget" in CHAIN_EVENTS and len(CHAIN_EVENTS) == 9
    assert BudgetExhausted.code == "budget_exhausted"
    assert BudgetExhausted.code in ERROR_CODES
    err = BudgetExhausted("every provider is over its monthly cap", [])
    assert (err.status, err.retryable, err.chain) == (429, False, [])


def test_every_dashboard_schema_is_published_with_properties():
    for name in (
        "FieldStateBool", "FieldStateInt", "FieldStateStr", "FieldStateCap",
        "ProviderView", "ProvidersResponse", "OverviewResponse", "TokenSplit",
        "ProviderUsage", "ModelUsage", "DailyUsage", "BudgetRow", "RecentIssue",
        "ProbeResponse", "ProviderSettings", "SettingsResponse", "SettingsRequest",
        "KeyRequest", "KeyResponse", "DeletedResponse", "SessionRow", "MessageRow",
    ):
        assert name in SCHEMAS, f"{name} is not a published schema"
        assert SCHEMAS[name]["properties"], f"{name} publishes no fields"


def test_one_probe_shape_only():
    assert "LiveProbe" not in SCHEMAS
    assert SCHEMAS["ModelsResponse"]["properties"]["live"]["items"]["$ref"].endswith("ProbeResponse")


def test_history_rows_are_named_schemas_so_the_gate_checks_them():
    assert SCHEMAS["SessionsResponse"]["properties"]["sessions"]["items"]["$ref"].endswith("SessionRow")
    assert SCHEMAS["MessagesResponse"]["properties"]["messages"]["items"]["$ref"].endswith("MessageRow")
    assert SCHEMAS["SessionRow"]["required"] == [
        "id", "mode", "created_at", "message_count", "tokens", "last_used_at",
    ]


def test_the_dashboard_endpoints_are_documented():
    for verb, path in DASHBOARD_PATHS:
        assert path in OPENAPI["paths"], path
        op = OPENAPI["paths"][path][verb]
        assert "200" in op["responses"], f"{verb.upper()} {path} has no success body"
        assert "401" in op["responses"], f"{verb.upper()} {path} does not document auth"


def test_writes_ask_for_the_confirm_header_and_reads_do_not():
    for verb, path in WRITE_PATHS:
        params = OPENAPI["paths"][path][verb].get("parameters", [])
        assert any(p.get("$ref", "").endswith("Confirm") for p in params), f"{path} is a write with no confirm"
    for verb, path in READ_PATHS:
        params = OPENAPI["paths"][path][verb].get("parameters", [])
        assert not any("Confirm" in p.get("$ref", "") for p in params), f"{path} is a read that demands a confirm"
    # A bearer token alone must stay enough to script a read.
    assert OPENAPI["components"]["parameters"]["Confirm"]["in"] == "header"
    assert OPENAPI["components"]["parameters"]["Confirm"]["name"] == "X-Kira-Confirm"


def test_chat_documents_the_budget_status():
    responses = OPENAPI["paths"]["/v1/chat/completions"]["post"]["responses"]
    assert "429" in responses
    assert responses["429"]["content"]["application/json"]["schema"]["$ref"].endswith("ErrorResponse")
    assert "503" in responses, "the old exhaustion status must survive the bump"
```

- [ ] **Step 2: Run them to watch them fail**

Run: `cd kira-engine && .venv/Scripts/python.exe -m pytest -q tests/test_contract_v2.py`
Expected: `ImportError: cannot import name 'BudgetExhausted' from 'kira.errors'`.

- [ ] **Step 3: `BudgetExhausted`**

In `errors.py`, after `AllProvidersExhausted`:

```python
class BudgetExhausted(KiraError):
    """Every candidate had already reached its monthly cap.

    Not retryable: waiting does not help, the counter resets next month or the cap moves.
    """

    code = "budget_exhausted"
    status = 429
    retryable = False

    def __init__(self, message: str, chain: list[dict]) -> None:
        super().__init__(message)
        self.chain = chain
```

Add `budget_exhausted` to `ERROR_CODES` in `contracts.py` by importing the class and listing
`BudgetExhausted.code` — that is the only way `test_contract_publishes_every_kira_error_code` in
`test_units.py` stays green, because it compares `ERROR_CODES` against the codes of every
`KiraError` subclass. In the import block at `contracts.py:7-17` add `BudgetExhausted`, and in the
set at `:35-46` add `BudgetExhausted.code`.

- [ ] **Step 4: Publish the v2 schemas**

In `contracts.py`, bump the version and the event list first:

```python
CONTRACT_VERSION = 2

CHAIN_EVENTS = (
    "attempt",
    "served",
    "failed",
    "skipped_cooling",
    "skipped_missing_key",
    "skipped_config",
    "skipped_budget",
    "aborted_mid_stream",
    "tool_executed",
)
```

Then replace the `"SessionsResponse"` and `"MessagesResponse"` entries in `schemas` with these (the
inline item objects become `$ref`s, which is what puts them under the drift gate):

```python
            "SessionRow": {
                "type": "object",
                "description": "One session with what it cost. `last_used_at` is the newest message timestamp, null for an empty session.",
                "required": ["id", "mode", "created_at", "message_count", "tokens", "last_used_at"],
                "properties": {
                    "id": {"type": "string"},
                    "mode": {"type": "string"},
                    "created_at": {"type": "number"},
                    "message_count": {"type": "integer"},
                    "tokens": {"type": "integer", "description": "input + output, combined, as every other total in this contract"},
                    "last_used_at": {"type": ["number", "null"]},
                },
            },
            "SessionsResponse": {
                "type": "object",
                "required": ["sessions"],
                "properties": {
                    "sessions": {"type": "array", "items": {"$ref": "#/components/schemas/SessionRow"}}
                },
            },
            "MessageRow": {
                "type": "object",
                "description": "One stored message, with the chain that produced it when it is an answer.",
                "required": ["id", "session_id", "role", "content", "status"],
                "properties": {
                    "id": {"type": "integer"},
                    "session_id": {"type": "string"},
                    "role": {"type": "string"},
                    "content": {"type": "string"},
                    "provider": {"type": ["string", "null"]},
                    "model": {"type": ["string", "null"]},
                    "finish_reason": {"type": ["string", "null"]},
                    "status": {"type": "string", "enum": ["complete", "max_steps", "interrupted", "failed"]},
                    "created_at": {"type": "number"},
                    "tool_calls": {"type": "array", "items": {"$ref": "#/components/schemas/ToolCallWire"}},
                    "usage": {
                        "type": "object",
                        "description": "Stored with engine-internal names, not the OpenAI-style wire names.",
                        "properties": {
                            "input_tokens": {"type": "integer"},
                            "output_tokens": {"type": "integer"},
                        },
                    },
                    "chain": {"type": "array", "items": {"$ref": "#/components/schemas/ChainRecord"}},
                },
            },
            "MessagesResponse": {
                "type": "object",
                "required": ["session_id", "messages"],
                "properties": {
                    "session_id": {"type": "string"},
                    "messages": {"type": "array", "items": {"$ref": "#/components/schemas/MessageRow"}},
                },
            },
```

Everything above is the same field set that was inline before, plus `SessionRow`'s three new
numbers. Delete the `"LiveProbe"` entry (`contracts.py:225-235`) and point `ModelsResponse.live` at
the new probe schema:

```python
                    "live": {"type": "array", "items": {"$ref": "#/components/schemas/ProbeResponse"}},
```

Finally append these entries at the end of the `schemas` dict, right after `"HealthzResponse"`:

```python
            "FieldStateBool": {
                "type": "object",
                "description": "One tunable boolean: what config.yaml says, what the settings table overrides, what the router uses.",
                "required": ["base", "override", "effective"],
                "properties": {
                    "base": {"type": "boolean"},
                    "override": {"type": ["boolean", "null"]},
                    "effective": {"type": "boolean"},
                },
            },
            "FieldStateInt": {
                "type": "object",
                "required": ["base", "override", "effective"],
                "properties": {
                    "base": {"type": "integer"},
                    "override": {"type": ["integer", "null"]},
                    "effective": {"type": "integer"},
                },
            },
            "FieldStateStr": {
                "type": "object",
                "required": ["base", "override", "effective"],
                "properties": {
                    "base": {"type": "string"},
                    "override": {"type": ["string", "null"]},
                    "effective": {"type": "string"},
                },
            },
            "FieldStateCap": {
                "type": "object",
                "description": "Monthly token cap. null means unlimited at every level, so a null effective value is not 'missing'.",
                "required": ["base", "override", "effective"],
                "properties": {
                    "base": {"type": ["integer", "null"]},
                    "override": {"type": ["integer", "null"]},
                    "effective": {"type": ["integer", "null"]},
                },
            },
            "ProviderView": {
                "type": "object",
                "description": "A provider as the router currently sees it. `name`, `kind`, `base_url` and `models` are config.yaml-only.",
                "required": [
                    "name", "kind", "base_url", "models", "key_ref", "key_present",
                    "enabled", "priority", "tier", "monthly_cap", "spend_this_month", "health",
                ],
                "properties": {
                    "name": {"type": "string"},
                    "kind": {"type": "string", "enum": ["openai_compat", "anthropic", "gemini"]},
                    "base_url": {"type": "string"},
                    "models": {"type": "array", "items": {"type": "string"}},
                    "key_ref": {"type": "string", "description": "Credential Locker ref name. Never the value."},
                    "key_present": {"type": "boolean"},
                    "enabled": {"$ref": "#/components/schemas/FieldStateBool"},
                    "priority": {"$ref": "#/components/schemas/FieldStateInt"},
                    "tier": {"$ref": "#/components/schemas/FieldStateStr"},
                    "monthly_cap": {"$ref": "#/components/schemas/FieldStateCap"},
                    "spend_this_month": {"type": "integer"},
                    "health": {"$ref": "#/components/schemas/ProviderState"},
                },
            },
            "ProvidersResponse": {
                "type": "object",
                "required": ["providers", "orphan_settings", "month"],
                "properties": {
                    "providers": {"type": "array", "items": {"$ref": "#/components/schemas/ProviderView"}},
                    "orphan_settings": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "'provider.key' rows the settings table holds but config.yaml no longer has a provider or a tunable key for",
                    },
                    "month": {"type": "string", "description": "YYYY-MM the spend figures are for"},
                },
            },
            "TokenSplit": {
                "type": "object",
                "required": ["input", "output"],
                "properties": {"input": {"type": "integer"}, "output": {"type": "integer"}},
            },
            "ProviderUsage": {
                "type": "object",
                "required": ["provider", "turns", "tokens"],
                "properties": {
                    "provider": {"type": "string"},
                    "turns": {"type": "integer"},
                    "tokens": {"type": "integer"},
                },
            },
            "ModelUsage": {
                "type": "object",
                "required": ["provider", "model", "turns", "tokens"],
                "properties": {
                    "provider": {"type": "string"},
                    "model": {"type": "string"},
                    "turns": {"type": "integer"},
                    "tokens": {"type": "integer"},
                },
            },
            "DailyUsage": {
                "type": "object",
                "description": "Only days inside the selected month, oldest first: the sparkline plots exactly these points.",
                "required": ["date", "turns", "tokens"],
                "properties": {
                    "date": {"type": "string", "description": "YYYY-MM-DD in UTC"},
                    "turns": {"type": "integer"},
                    "tokens": {"type": "integer"},
                },
            },
            "BudgetRow": {
                "type": "object",
                "description": "cap null means unlimited, and then remaining is null - a bar with no right edge, not a full one.",
                "required": ["provider", "cap", "used", "remaining"],
                "properties": {
                    "provider": {"type": "string"},
                    "cap": {"type": ["integer", "null"]},
                    "used": {"type": "integer"},
                    "remaining": {"type": ["integer", "null"]},
                },
            },
            "RecentIssue": {
                "type": "object",
                "description": "A turn that did not finish cleanly, newest first, at most ten.",
                "required": ["id", "session_id", "status", "provider", "model", "created_at", "reason"],
                "properties": {
                    "id": {"type": "integer"},
                    "session_id": {"type": "string"},
                    "status": {"type": "string", "enum": ["interrupted", "failed"]},
                    "provider": {"type": ["string", "null"]},
                    "model": {"type": ["string", "null"]},
                    "created_at": {"type": "number"},
                    "reason": {"type": "string"},
                },
            },
            "OverviewResponse": {
                "type": "object",
                "required": [
                    "month", "turns", "tokens", "success_rate", "interrupted", "failed",
                    "by_provider", "by_model", "daily", "budgets", "recent_issues",
                ],
                "properties": {
                    "month": {"type": "string"},
                    "turns": {"type": "integer", "description": "assistant rows in the window"},
                    "tokens": {"$ref": "#/components/schemas/TokenSplit"},
                    "success_rate": {
                        "type": ["number", "null"],
                        "description": "(turns - interrupted - failed) / turns; null when turns is 0 because 'no data' is not '0% healthy'",
                    },
                    "interrupted": {"type": "integer"},
                    "failed": {"type": "integer"},
                    "by_provider": {"type": "array", "items": {"$ref": "#/components/schemas/ProviderUsage"}},
                    "by_model": {"type": "array", "items": {"$ref": "#/components/schemas/ModelUsage"}},
                    "daily": {"type": "array", "items": {"$ref": "#/components/schemas/DailyUsage"}},
                    "budgets": {"type": "array", "items": {"$ref": "#/components/schemas/BudgetRow"}},
                    "recent_issues": {"type": "array", "items": {"$ref": "#/components/schemas/RecentIssue"}},
                },
            },
            "ProbeResponse": {
                "type": "object",
                "description": "One live probe. A failure is ok:false with the reason, never an HTTP error, so the UI can show it inline. Probe traffic is not stored as a conversation and does not count toward a month's spend.",
                "required": ["provider", "ok", "latency_ms", "error"],
                "properties": {
                    "provider": {"type": "string"},
                    "ok": {"type": "boolean"},
                    "model_count": {"type": "integer"},
                    "sample": {"type": "array", "items": {"type": "string"}},
                    "latency_ms": {"type": ["integer", "null"], "description": "the one-cap completion only; null for a list-only probe"},
                    "error": {"type": ["string", "null"]},
                },
            },
            "ProviderSettings": {
                "type": "object",
                "description": "The four tunable fields, as base/override/effective after a write.",
                "required": ["enabled", "priority", "tier", "monthly_cap"],
                "properties": {
                    "enabled": {"$ref": "#/components/schemas/FieldStateBool"},
                    "priority": {"$ref": "#/components/schemas/FieldStateInt"},
                    "tier": {"$ref": "#/components/schemas/FieldStateStr"},
                    "monthly_cap": {"$ref": "#/components/schemas/FieldStateCap"},
                },
            },
            "SettingsResponse": {
                "type": "object",
                "required": ["provider", "settings"],
                "properties": {
                    "provider": {"type": "string"},
                    "settings": {"$ref": "#/components/schemas/ProviderSettings"},
                },
            },
            "SettingsRequest": {
                "type": "object",
                "description": "Any subset of the tunable fields. null deletes that override and returns to config.yaml; monthly_cap 0 means unlimited - the two must not be confused.",
                "properties": {
                    "enabled": {"type": ["boolean", "null"]},
                    "priority": {"type": ["integer", "null"], "minimum": 0, "maximum": 1000},
                    "tier": {"type": ["string", "null"]},
                    "monthly_cap": {"type": ["integer", "null"], "minimum": 0},
                },
            },
            "KeyRequest": {
                "type": "object",
                "required": ["key"],
                "properties": {"key": {"type": "string", "minLength": 1}},
            },
            "KeyResponse": {
                "type": "object",
                "description": "Presence, never the value.",
                "required": ["provider", "key_ref", "key_present"],
                "properties": {
                    "provider": {"type": "string"},
                    "key_ref": {"type": "string"},
                    "key_present": {"type": "boolean"},
                },
            },
            "DeletedResponse": {
                "type": "object",
                "required": ["deleted", "messages"],
                "properties": {
                    "deleted": {"type": "integer", "description": "sessions removed"},
                    "messages": {"type": "integer", "description": "messages removed with them"},
                },
            },
```

- [ ] **Step 5: Publish the v2 paths**

Add three helpers just above `OPENAPI` (they exist because repeating this dict fifteen times is how
an endpoint loses its 401):

```python
def _ref(name: str) -> str:
    return f"#/components/schemas/{name}"


def _ok(schema: str) -> dict:
    return {"description": "ok", "content": {"application/json": {"schema": {"$ref": _ref(schema)}}}}


def _bad_request() -> dict:
    return {
        "description": "config_error - unknown provider, unknown field, or an out-of-range value",
        "content": {"application/json": {"schema": {"$ref": _ref("ErrorResponse")}}},
    }


def _provider_param() -> dict:
    return {"name": "name", "in": "path", "required": True, "schema": {"type": "string"}}


def _ref_confirm() -> dict:
    return {"$ref": "#/components/parameters/Confirm"}


def _read(summary: str, schema: str, params: list[dict] | None = None) -> dict:
    return {
        "summary": summary,
        "security": [{"bearerAuth": []}],
        "parameters": params or [],
        "responses": {"200": _ok(schema), "400": _bad_request(), "401": {"$ref": "#/components/responses/Unauthorized"}},
    }


def _write(summary: str, schema: str, params: list[dict], body: str | None = None) -> dict:
    op = _read(summary, schema, [_ref_confirm()] + params)
    if body:
        op["requestBody"] = {
            "required": True,
            "content": {"application/json": {"schema": {"$ref": _ref(body)}}},
        }
    op["description"] = (
        "Needs the bearer token AND the X-Kira-Confirm secret: a missing, wrong or bearer-equal "
        "confirm is 401 unauthorized."
    )
    return op
```

Then add to `paths` (keeping the existing five entries untouched except where noted):

```python
        "/v1/kira/overview": {
            "get": _read(
                "Month aggregates for the Overview screen",
                "OverviewResponse",
                [{"name": "month", "in": "query", "schema": {"type": "string"}, "description": "YYYY-MM; default is the current UTC month; junk is config_error 400"}],
            )
        },
        "/v1/kira/providers": {"get": _read("Merged view + key presence + spend + health + orphans", "ProvidersResponse")},
        "/v1/kira/providers/{name}/settings": {
            "put": _write("Set any subset of the tunable fields", "SettingsResponse", [_provider_param()], "SettingsRequest")
        },
        "/v1/kira/providers/{name}/key": {
            "put": _write("Store a provider key in the Credential Locker", "KeyResponse", [_provider_param()], "KeyRequest"),
            "delete": _write("Forget a provider key", "KeyResponse", [_provider_param()]),
        },
        "/v1/kira/providers/{name}/cooldown": {
            "delete": _write("Drop cooling for one provider now", "ProvidersResponse", [_provider_param()])
        },
        "/v1/kira/providers/{name}/probe": {
            "post": _write("list_models plus one 8-token completion", "ProbeResponse", [_provider_param()])
        },
        "/v1/kira/sessions/{session_id}": {
            "delete": _write("Delete one session and its messages", "DeletedResponse", [{"name": "session_id", "in": "path", "required": True, "schema": {"type": "string"}}])
        },
```

`DELETE /v1/kira/sessions` (clear-all) belongs to the `"/v1/kira/sessions"` entry that already
exists with its `"get"`; add the `"delete"` inside that same dict rather than writing a second
`"/v1/kira/sessions"` key, which would silently replace the get:

```python
        "/v1/kira/sessions": {
            "get": {
                "security": [{"bearerAuth": []}],
                "summary": "Recent sessions",
                "parameters": [{"name": "limit", "in": "query", "schema": {"type": "integer", "default": 50}}],
                "responses": {
                    "200": {
                        "description": "ok",
                        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/SessionsResponse"}}},
                    },
                    "401": {"$ref": "#/components/responses/Unauthorized"},
                },
            },
            "delete": _write("Delete every session and message", "DeletedResponse", []),
        },
```

And add the 429 to the chat endpoint's `responses` (next to the existing `"503"`):

```python
                    "429": {
                        "description": "budget_exhausted - every candidate had reached its monthly cap",
                        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorResponse"}}},
                    },
```

Finally, register the header component. `contracts.py` already does
`OPENAPI["components"]["responses"] = {...}` after the dict literal (`:449-454`); extend that
statement's neighbourhood with:

```python
OPENAPI["components"]["parameters"] = {
    "Confirm": {
        "name": "X-Kira-Confirm",
        "in": "header",
        "required": True,
        "schema": {"type": "string"},
        "description": (
            "The engine/confirm secret from the Credential Locker, re-typed per write in the UI. "
            "Custom header, so a page on another origin cannot set it without a CORS preflight this "
            "engine never grants, and a local process would have to guess 43 characters."
        ),
    }
}
```

- [ ] **Step 6: Run the contract tests to watch them pass**

Run: `cd kira-engine && .venv/Scripts/python.exe -m pytest -q tests/test_contract_v2.py tests/test_units.py`
Expected: PASS — 8 v2 tests plus the existing `test_units.py` (whose
`test_contract_publishes_every_kira_error_code` is the one that fails if `ERROR_CODES` was not
extended).

Then run the whole engine suite, because promoting the two row types to `$ref`s breaks a reader the
task list did not name: `test_api.py`'s `test_shipped_bodies_match_the_documented_required_fields`
walked `MessagesResponse.properties.messages.items` as if it were still an inline object and now hits
`KeyError: 'required'`. Give that file a one-hop resolver and use it:

```python
def _items(schema_name: str, field: str) -> dict:
    """Array item schema, following the one-hop `$ref` v2 uses for named rows."""
    items = _schema(schema_name)["properties"][field]["items"]
    if "$ref" in items:
        return _schema(items["$ref"].rsplit("/", 1)[-1])
    return items
```

so the message-row assertion reads `message_schema = _items("MessagesResponse", "messages")`
(amendment 32). Expected after that: `110 passed, 1 skipped`.

- [ ] **Step 7: Regenerate the published artifacts**

Run: `cd kira-engine && .venv/Scripts/kira-engine.exe contracts --out ../kira-contracts`
Expected: `[kira] wrote D:\1. Ai\project-kira (kimi)\Kira\kira-contracts\openapi.json`
Then confirm the three files moved together:

Run: `cd kira-contracts && cat VERSION && node -e "const f=require('fs');const o=JSON.parse(f.readFileSync('openapi.json','utf8'));console.log(o.info.version, Object.keys(o.components.schemas).length, Object.keys(o.paths).length)"`
Expected: `2` then `2 39 13` (the schema count is whatever the engine says — the point is that
VERSION, `openapi.json.info.version` and `contract.json.contract_version` all read 2, and that no
path silently disappeared: 13 paths = the 6 that shipped with M1-M8 plus the 7 new `/v1/kira/*`
entries, and 39 schemas = 18 minus `LiveProbe` plus the 22 this task publishes; the earlier draft of
this line said 32 and 12 because it forgot `/healthz` and predated the four `FieldState` splits).

- [ ] **Step 8: Mirror the contract in TypeScript**

In `kira-contracts/contract.ts`:

```ts
export const CONTRACT_VERSION = 2;

export const CHAIN_EVENTS = [
  "attempt",
  "served",
  "failed",
  "skipped_cooling",
  "skipped_missing_key",
  "skipped_config",
  "skipped_budget",
  "aborted_mid_stream",
  "tool_executed",
] as const;

export const ERROR_CODES = [
  "budget_exhausted",
  "config_error",
  "internal_error",
  "model_not_found",
  "providers_exhausted",
  "secret_store_unavailable",
  "unauthorized",
] as const;
```

In `kira-contracts/types.ts`, delete `LiveProbe`, change `ModelsResponse.live` to `ProbeResponse[]`,
and add the v2 surface. Property names must match `openapi.json` exactly — that is what the gate
checks, field by field:

```ts
export interface FieldStateBool {
  base: boolean;
  override: boolean | null;
  effective: boolean;
}

export interface FieldStateInt {
  base: number;
  override: number | null;
  effective: number;
}

export interface FieldStateStr {
  base: string;
  override: string | null;
  effective: string;
}

/** null means unlimited at every level, so a null `effective` is a decision, not a gap. */
export interface FieldStateCap {
  base: number | null;
  override: number | null;
  effective: number | null;
}

export interface ProviderView {
  name: string;
  kind: ProviderKind;
  base_url: string;
  models: string[];
  key_ref: string;
  key_present: boolean;
  enabled: FieldStateBool;
  priority: FieldStateInt;
  tier: FieldStateStr;
  monthly_cap: FieldStateCap;
  spend_this_month: number;
  health: ProviderState;
}

export interface ProvidersResponse {
  providers: ProviderView[];
  orphan_settings: string[];
  month: string;
}

export interface TokenSplit {
  input: number;
  output: number;
}

export interface ProviderUsage {
  provider: string;
  turns: number;
  tokens: number;
}

export interface ModelUsage {
  provider: string;
  model: string;
  turns: number;
  tokens: number;
}

export interface DailyUsage {
  date: string;
  turns: number;
  tokens: number;
}

export interface BudgetRow {
  provider: string;
  cap: number | null;
  used: number;
  remaining: number | null;
}

export interface RecentIssue {
  id: number;
  session_id: string;
  status: TurnStatus;
  provider: string | null;
  model: string | null;
  created_at: number;
  reason: string;
}

export interface OverviewResponse {
  month: string;
  turns: number;
  tokens: TokenSplit;
  /** null when there are no turns: "no data" is not "0% healthy". */
  success_rate: number | null;
  interrupted: number;
  failed: number;
  by_provider: ProviderUsage[];
  by_model: ModelUsage[];
  daily: DailyUsage[];
  budgets: BudgetRow[];
  recent_issues: RecentIssue[];
}

export interface ProbeResponse {
  provider: string;
  ok: boolean;
  model_count?: number;
  sample?: string[];
  latency_ms: number | null;
  error: string | null;
}

export interface ProviderSettings {
  enabled: FieldStateBool;
  priority: FieldStateInt;
  tier: FieldStateStr;
  monthly_cap: FieldStateCap;
}

export interface SettingsResponse {
  provider: string;
  settings: ProviderSettings;
}

/** Any subset; `null` deletes that override back to config.yaml. `monthly_cap: 0` is unlimited. */
export interface SettingsRequest {
  enabled?: boolean | null;
  priority?: number | null;
  tier?: string | null;
  monthly_cap?: number | null;
}

export interface KeyRequest {
  key: string;
}

export interface KeyResponse {
  provider: string;
  key_ref: string;
  key_present: boolean;
}

export interface DeletedResponse {
  deleted: number;
  messages: number;
}

export interface SessionRow {
  id: string;
  mode: Mode;
  created_at: number;
  message_count: number;
  tokens: number;
  last_used_at: number | null;
}

export interface MessageRow {
  id: number;
  session_id: string;
  role: Role;
  content: string;
  provider: string | null;
  model: string | null;
  finish_reason: string | null;
  status: TurnStatus;
  created_at: number;
  tool_calls: ToolCallWire[];
  usage: StoredUsage;
  chain: ChainRecord[];
}
```

`SessionsResponse.sessions` and `MessagesResponse.messages` become `SessionRow[]` / `MessageRow[]` —
replace the two interfaces the file already had with these versions rather than leaving both.

- [ ] **Step 9: Run the drift gate**

Run: `cd kira-contracts && npm run check` (or `node kira-contracts/check-drift.mjs` from `Kira/`)
Expected: `kira-contracts OK — v2, 39 schemas, 5 chunk types, 9 chain events`

Then prove the gate is still watching — mutate the mirror and confirm it refuses:

Run: `cd kira-contracts && sed -i.bak 's/export const CONTRACT_VERSION = 2;/export const CONTRACT_VERSION = 1;/' contract.ts && node check-drift.mjs; echo "exit=$?"; mv contract.ts.bak contract.ts`
Expected: `kira-contracts drift: 1 problem(s)` naming the version disagreement, `exit=1`, and the
file restored. A gate that has never been seen to fail is not evidence.

- [ ] **Step 10: Teach the client the new version and event**

`kira-chat/src/fake-engine.ts` hardcodes a v1 healthz today (`:46`). Import the real constant so the
fake cannot outlive the contract again:

```ts
import { CONTRACT_VERSION } from "./contracts.ts";
```

and use it in the default:

```ts
    if (url.pathname === "/healthz") {
      return json(options.healthz ?? { ok: true, contract_version: CONTRACT_VERSION, providers_configured: 2, default_mode: "AUTO" });
    }
```

`ChainTrace.tsx` gains the documented-but-not-yet-emitted event so no build can show a blank chip
(amendment 12): add `skipped_budget: "over budget"` to `LABELS` and `skipped_budget: "warn"` to
`TONE`, beside the two `skipped_*` entries already there. Its detail line needs no change — the
budget note carries `reason`, which the final `return record.reason ?? …` already prints.

`kira-chat/src/api.test.ts:14` asserts the healthz version literally (`toBe(1)`), so the same file
imports the constant and reads `expect(healthz.contract_version).toBe(CONTRACT_VERSION)` — the test
is about the bearer header staying off `/healthz`, and it has no business pinning the version
(amendment 33).

Append to `kira-chat/src/App.test.tsx` (the file's helpers `fakeEngine`, `connectedTo`, `chain` and
`modelSelect` are all already in scope):

```ts
  it("names the budget chain event instead of falling through to the raw code", async () => {
    const chainRecords: ChainRecord[] = [
      { provider: "groq", event: "skipped_budget", reason: "used 1,020,000 of 1,000,000 tokens in 2026-10" },
      { provider: "big", event: "served", model: "claude-sonnet-4-5" },
    ];
    const engine = fakeEngine({
      models: MODELS,
      health: HEALTH,
      chunks: [
        chain(chainRecords[0]),
        chain(chainRecords[1]),
        delta("done"),
        done({ provider_chain: chainRecords }),
      ],
    });
    connectedTo(engine);
    render(<App />);
    fireEvent.change(await screen.findByLabelText("message"), { target: { value: "go" } });
    fireEvent.click(screen.getByRole("button", { name: "send" }));
    const trace = await screen.findByLabelText("provider chain");
    expect(within(trace).getByText("over budget")).toBeTruthy();
    expect(within(trace).getByText(/of 1,000,000 tokens/)).toBeTruthy();
  });
```

The `provider_chain` on the `done` chunk has to carry the budget record too, not just the streamed
`chain` chunks: `turn.ts:49` keeps `chunk.provider_chain` whenever it is non-empty, so a fixture that
lists the skip only in the stream renders one chip and fails for the right reason (amendment 33).

- [ ] **Step 11: Run everything**

Run: `cd kira-chat && npm run check`
Expected: typecheck clean, `The CJS build of Vite's Node API is deprecated`-free build, and
`Test Files  N passed` with every test green (Task 2's shell tests plus this new one).

Run: `cd kira-engine && .venv/Scripts/python.exe -m pytest -q`
Expected: `110 passed, 1 skipped` (102 after Task 7, +8 `test_contract_v2.py`).

- [ ] **Step 12: Checkpoint**

Both gates green in the same command run, in this order:

```
cd kira-engine && .venv/Scripts/python.exe -m pytest -q
cd ../kira-contracts && node check-drift.mjs
cd ../kira-chat && npm run check
```

If git is initialised: `git add -A kira-engine/src/kira/errors.py kira-engine/src/kira/contracts.py kira-engine/tests/test_contract_v2.py kira-contracts kira-chat/src/components/ChainTrace.tsx kira-chat/src/fake-engine.ts kira-chat/src/App.test.tsx && git commit -m "feat(contract): v2 - budget event, dashboard schemas, confirm-header writes"`

---

# M9 close-out: the read-only dashboard must be real

Tasks 9 and 10 finish M9. Stop here if you want to ship a read-only dashboard: the spec is explicit
that "M8+M9 alone leave a genuinely useful read-only dashboard", and nothing before M10 can mutate
anything.

## Task 9: Read endpoints — overview, providers, richer sessions

**Files:**
- Modify: `kira-engine/src/kira/app.py` (imports `:14-30`, `Engine.__init__` `:110-136`, `kira_health` `:351-374`, end of `create_app`)
- Modify: `kira-engine/src/kira/net.py` (add `view(name)` after `snapshot()` at `:100-113`)
- Create: `kira-engine/tests/test_dashboard_api.py`

**Interfaces produced:**
- `HealthLedger.view(name: str) -> dict` — the published `ProviderState` shape for one provider, zeros when unseen
- `GET /v1/kira/overview?month=YYYY-MM -> OverviewResponse`
- `GET /v1/kira/providers -> ProvidersResponse`
- `GET /v1/kira/sessions` now returns `SessionRow`s with counts, tokens and `last_used_at`

- [ ] **Step 1: Write the failing tests**

Create `kira-engine/tests/test_dashboard_api.py`. It reuses the `harness` fixture `conftest.py:168-171`
already provides (five providers, a memory vault holding `key-<name>` per provider and
`test-engine-token`, an ASGI client), so nothing about the wiring is restated here:

```python
from __future__ import annotations

from kira.store import month_bounds


def providers_by_name(body: dict) -> dict:
    return {row["name"]: row for row in body["providers"]}


async def test_providers_reports_base_override_and_effective(harness):
    harness.store.set_setting("fast_one", "priority", 5)
    harness.store.set_setting("fast_one", "tier", "powerful")
    resp = await harness.api.get("/v1/kira/providers", headers=harness.auth)
    assert resp.status_code == 200
    row = providers_by_name(resp.json())["fast_one"]
    assert row["priority"] == {"base": 10, "override": 5, "effective": 5}
    assert row["tier"] == {"base": "fast", "override": "powerful", "effective": "powerful"}
    assert row["enabled"] == {"base": True, "override": None, "effective": True}
    assert row["monthly_cap"] == {"base": None, "override": None, "effective": None}
    assert row["key_ref"] == "provider/fast_one"
    assert row["key_present"] is True
    assert "key-fast_one" not in resp.text, "the ref is published, the value never is"


async def test_providers_names_orphans_rather_than_hiding_them(harness):
    harness.store.set_setting("ghost", "enabled", False)
    # set_setting refuses a non-tunable key on purpose, so a junk row can only arrive the way
    # it would in real life: a hand edit or an older build.
    harness.store._conn.execute(  # noqa: SLF001 - deliberately writing underneath the API
        "INSERT INTO settings(provider, key, value, updated_at) VALUES('fast_one','nonsense','1',0)"
    )
    harness.store._conn.commit()
    resp = await harness.api.get("/v1/kira/providers", headers=harness.auth)
    assert sorted(resp.json()["orphan_settings"]) == ["fast_one.nonsense", "ghost.enabled"]


async def test_providers_carries_month_spend_and_health(harness):
    resp = await harness.api.get("/v1/kira/providers", headers=harness.auth)
    body = resp.json()
    assert body["month"] == month_bounds()[0]
    row = providers_by_name(body)["fast_one"]
    assert row["spend_this_month"] == 0
    assert row["health"] == {"failures": 0, "successes": 0, "cooling_s": 0.0, "last_reason": ""}


async def test_overview_defaults_to_this_month_and_uses_published_names(harness):
    resp = await harness.api.get("/v1/kira/overview", headers=harness.auth)
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {
        "month", "turns", "tokens", "success_rate", "interrupted", "failed",
        "by_provider", "by_model", "daily", "budgets", "recent_issues",
    }
    assert body["turns"] == 0 and body["success_rate"] is None
    assert body["tokens"] == {"input": 0, "output": 0}


async def test_overview_rejects_a_junk_month_with_the_documented_error(harness):
    resp = await harness.api.get("/v1/kira/overview?month=nope", headers=harness.auth)
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "config_error"


async def test_overview_budgets_include_disabled_providers(harness):
    harness.store.set_setting("fast_one", "monthly_cap", 100)
    harness.store.set_setting("fast_two", "enabled", False)
    resp = await harness.api.get("/v1/kira/overview", headers=harness.auth)
    budgets = {b["provider"]: b for b in resp.json()["budgets"]}
    assert budgets["fast_one"] == {"provider": "fast_one", "cap": 100, "used": 0, "remaining": 100}
    assert budgets["fast_two"]["cap"] is None and budgets["fast_two"]["remaining"] is None
    assert budgets["big"]["cap"] is None, "no cap in yaml means unlimited, not missing"


async def test_sessions_now_carry_counts(harness):
    sid = harness.store.create_session("AUTO", "sess-9")
    harness.store.add_message(sid, "assistant", "a", provider="fast_one", model="mini",
                              usage={"input_tokens": 4, "output_tokens": 3})
    resp = await harness.api.get("/v1/kira/sessions?limit=5", headers=harness.auth)
    row = resp.json()["sessions"][0]
    assert row["id"] == "sess-9"
    assert row["message_count"] == 1
    assert row["tokens"] == 7
    assert row["last_used_at"] is not None


async def test_reads_need_the_token_and_no_confirm(harness):
    for path in ("/v1/kira/overview", "/v1/kira/providers", "/v1/kira/sessions"):
        assert (await harness.api.get(path)).status_code == 401
        ok = await harness.api.get(path, headers=harness.auth)
        assert ok.status_code == 200, path
```

Every test is a plain `async def` with no `@pytest.mark.asyncio`: `pyproject.toml` sets
`asyncio_mode = "auto"`, which is how `test_api.py` already works.

- [ ] **Step 2: Run them to watch them fail**

Run: `cd kira-engine && .venv/Scripts/python.exe -m pytest -q tests/test_dashboard_api.py`
Expected: 8 failures, 0 errors — the two new routes answer 404 (`{"detail":"Not Found"}`),
`test_sessions_now_carry_counts` raises `KeyError: 'message_count'`, and none of them comes from a
broken fixture.

- [ ] **Step 3: `HealthLedger.view()`**

`snapshot()` is the right source but it only knows providers that already failed something. Add to
`net.py`, after `snapshot()`:

```python
    def view(self, name: str) -> dict:
        """One provider's ledger row in the published shape, so the dashboard can show a
        provider that has never failed instead of leaving it out."""
        now = self.clock()
        st = self.state(name)
        return {
            "failures": st.failures,
            "successes": st.successes,
            "cooling_s": round(max(0.0, st.cooled_until - now), 1),
            "last_reason": st.last_reason,
        }
```

Note `state(name)` inserts into `_states` on read. That is already true of `available()` and is
harmless here (nothing is persisted), but do not switch it to `self._states.get(name)` inside
`snapshot()` — the chat's health chip test depends on the current behaviour.

- [ ] **Step 4: The three read endpoints**

In `app.py`, add to the imports:

```python
from .store import month_bounds
from .overrides import build_view
```

(`build_view` and `enabled_providers` already arrived in Task 5; `TUNABLE_FIELDS` comes in Task 12,
not here.) Add these endpoints next to `kira_health()`:

```python
    @app.get("/v1/kira/overview", dependencies=[auth])
    async def kira_overview(month: str | None = None) -> dict:
        label, start, end = month_bounds(month)
        view = engine.view()
        spend = engine.store.monthly_spend(start, end)
        overview = engine.store.overview(start, end)
        budgets = [
            {
                "provider": p.name,
                "cap": p.monthly_cap,
                "used": spend.get(p.name, 0),
                "remaining": None if p.monthly_cap is None else max(0, p.monthly_cap - spend.get(p.name, 0)),
            }
            for p in view.providers
        ]
        return {**overview, "budgets": budgets}
```

`month_bounds()` raises `ConfigError` for junk, which the existing `KiraError` handler turns into the
documented 400 — no new error path, which is why `store.month_bounds` is the only month parser in the
codebase.

```python
    @app.get("/v1/kira/providers", dependencies=[auth])
    async def kira_providers() -> dict:
        label, start, end = month_bounds(None)
        spend = engine.store.monthly_spend(start, end)
        view = engine.view()
        rows = []
        for provider in view.providers:
            states = provider.states
            rows.append(
                {
                    "name": provider.name,
                    "kind": provider.kind,
                    "base_url": provider.base_url,
                    "models": list(provider.models),
                    "key_ref": provider.key_ref,
                    "key_present": (engine.registry.key_for(provider.name) is not None) if provider.key_ref else False,
                    "enabled": states["enabled"].to_wire(),
                    "priority": states["priority"].to_wire(),
                    "tier": states["tier"].to_wire(),
                    "monthly_cap": states["monthly_cap"].to_wire(),
                    "spend_this_month": spend.get(provider.name, 0),
                    "health": engine.ledger.view(provider.name),
                }
            )
        return {"providers": rows, "orphan_settings": list(view.orphan_settings), "month": label}
```

Both `view` reads call `engine.view()` once per request and never cache it across requests; a
settings row written by another window must show on the next refresh, which is the whole point of
the derived read.

Then switch `sessions()` to `session_rows()` so the Sessions screen gets counts without a second
round trip:

```python
    @app.get("/v1/kira/sessions", dependencies=[auth])
    async def kira_sessions(limit: int = 50) -> dict:
        return {"sessions": engine.store.session_rows(limit)}
```

Replace the existing `sessions()` body rather than adding a second route on the same path — FastAPI
keeps the last registration for a duplicated path, and the drift gate would still document only one.

The old route clamped with `min(limit, 200)` at the boundary; `store.session_rows()` already clamps
internally, to 500, so the guard moves rather than disappearing (amendment 34). The cap only bounds how
many rows one page reads, and every page in this dashboard asks for 50.

- [ ] **Step 5: Run the whole engine suite**

Run: `cd kira-engine && .venv/Scripts/python.exe -m pytest -q`
Expected: `118 passed, 1 skipped` (110 after Task 8, +8 `test_dashboard_api.py`).

- [ ] **Step 6: Checkpoint**

If git is initialised: `git add kira-engine/src/kira/app.py kira-engine/src/kira/net.py kira-engine/tests/test_dashboard_api.py && git commit -m "feat(engine): read endpoints for overview, providers and counted sessions"`

---

## Task 10: Read the dashboard — `useAsync`, two screens, no writes yet

This closes M9. After it, a browser can see spend, effective-vs-baseline tuning, health and budgets
against a real engine, and still cannot change anything.

**Files:**
- Create: `kira-chat/src/useAsync.ts`, `kira-chat/src/useAsync.test.tsx`
- Create: `kira-chat/src/screens/OverviewScreen.tsx`, `kira-chat/src/screens/ProvidersScreen.tsx`
- Modify: `kira-chat/src/api.ts` (after `health()` at `:70-72`)
- Modify: `kira-chat/src/fake-engine.ts` (`FakeOptions` `:8-17`, route table `:44-63`)
- Modify: `kira-chat/src/App.tsx` (the route switch and `screen-empty` branch from Task 2)
- Modify: `kira-chat/src/App.test.tsx`, `kira-chat/src/api.test.ts`
- Modify: `kira-chat/src/styles.css` (append the screen styles)

- [ ] **Step 1: Write the failing hook test**

Create `kira-chat/src/useAsync.test.tsx`:

```tsx
import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useAsync } from "./useAsync.ts";

describe("useAsync", () => {
  it("goes loading -> ready and keeps the data", async () => {
    const load = vi.fn(async () => ({ n: 1 }));
    const { result } = renderHook(() => useAsync(load, []));
    expect(result.current.kind).toBe("loading");
    await waitFor(() => expect(result.current.kind).toBe("ready"));
    expect(result.current.data).toEqual({ n: 1 });
    expect(result.current.error).toBeNull();
  });

  it("surfaces the rejection instead of an empty screen", async () => {
    const { result } = renderHook(() => useAsync(async () => { throw new Error("engine down"); }, []));
    await waitFor(() => expect(result.current.kind).toBe("error"));
    expect((result.current.error as Error).message).toBe("engine down");
    expect(result.current.data).toBeNull();
  });

  it("re-loads when a dependency changes, and refresh() reloads on demand", async () => {
    let n = 0;
    const load = vi.fn(async () => ++n);
    const { result, rerender } = renderHook(({ month }: { month: string }) => useAsync(load, [month]), {
      initialProps: { month: "2026-10" },
    });
    await waitFor(() => expect(result.current.data).toBe(1));
    rerender({ month: "2026-09" });
    await waitFor(() => expect(result.current.data).toBe(2));
    act(() => result.current.refresh());
    await waitFor(() => expect(result.current.data).toBe(3));
    expect(load).toHaveBeenCalledTimes(3);
  });

  it("ignores a response that lands after the screen moved on", async () => {
    let release!: (value: number) => void;
    const load = vi.fn(() => new Promise<number>((resolve) => { release = resolve; }));
    const { result, rerender } = renderHook(({ k }: { k: number }) => useAsync(load, [k]), {
      initialProps: { k: 1 },
    });
    rerender({ k: 2 });
    await act(async () => { release(1); });
    expect(result.current.kind).toBe("loading");
  });
});
```

- [ ] **Step 2: Run it to watch it fail**

Run: `cd kira-chat && npx vitest run src/useAsync.test.tsx`
Expected: `Failed to resolve import "./useAsync.ts"`.

- [ ] **Step 3: Write the hook**

Create `kira-chat/src/useAsync.ts`:

```ts
import { useCallback, useEffect, useState } from "react";

export type AsyncState<T> =
  | { kind: "loading"; data: null; error: null }
  | { kind: "ready"; data: T; error: null }
  | { kind: "error"; data: null; error: unknown };

const LOADING: AsyncState<unknown> = { kind: "loading", data: null, error: null };

/**
 * One implementation of "loading / empty / error" for every dashboard screen, because the
 * spec demands all three states be explicit on all of them. `deps` says when to re-read;
 * `refresh()` is how a screen re-reads after its own write.
 */
export function useAsync<T>(load: () => Promise<T>, deps: readonly unknown[]): AsyncState<T> & { refresh(): void } {
  const [state, setState] = useState<AsyncState<T>>(LOADING as AsyncState<T>);
  const [epoch, setEpoch] = useState(0);
  const refresh = useCallback(() => setEpoch((n) => n + 1), []);

  useEffect(() => {
    let cancelled = false;
    setState(LOADING as AsyncState<T>);
    load().then(
      (data) => {
        if (!cancelled) setState({ kind: "ready", data, error: null });
      },
      (error) => {
        // A rejected read is state, not a swallowed exception: the screen shows it.
        if (!cancelled) setState({ kind: "error", data: null, error });
      },
    );
    return () => {
      cancelled = true;
    };
    // `load` is deliberately not a dependency: every caller passes a fresh closure, and
    // depending on it would re-fetch on every render. `deps` + `epoch` are the triggers.
  }, [...deps, epoch]);

  return { ...state, refresh };
}
```

- [ ] **Step 4: Run it to watch it pass**

Run: `cd kira-chat && npx vitest run src/useAsync.test.tsx`
Expected: PASS — 4 tests.

- [ ] **Step 5: Give the client the two reads**

Append to `kira-chat/src/api.ts`, after `health()`, and add `OverviewResponse`,
`ProvidersResponse` to the type-only import block at the top:

```ts
  overview(month?: string): Promise<OverviewResponse> {
    const query = month ? `?month=${encodeURIComponent(month)}` : "";
    return this.request<OverviewResponse>(`/v1/kira/overview${query}`);
  }

  providers(): Promise<ProvidersResponse> {
    return this.request<ProvidersResponse>("/v1/kira/providers");
  }
```

Append to `kira-chat/src/api.test.ts` inside its existing `describe` block (it already has an
`engine`/`client` pair built by `fakeEngine()` and `connectedTo`-style helpers in that file):

```ts
  it("reads the dashboard endpoints with the bearer token and nothing else", async () => {
    const engine = fakeEngine();
    const client = new KiraClient({ baseUrl: "http://127.0.0.1:8901", token: "sekret", fetch: engine.fetch });
    await client.overview("2026/10");
    await client.providers();
    expect(engine.calls.map((call) => call.url)).toEqual([
      "/v1/kira/overview?month=2026%2F10",
      "/v1/kira/providers",
    ]);
    for (const call of engine.calls) {
      expect(call.headers.Authorization).toBe("Bearer sekret");
      expect(call.headers["X-Kira-Confirm"]).toBeUndefined();
    }
  });
```

Passing `"2026/10"` is on purpose: the month is URL-encoded by the client, so a hand-built query
string cannot be injected into the path.

- [ ] **Step 6: Teach the fake engine the two routes**

In `kira-chat/src/fake-engine.ts`, extend `FakeOptions` with `overview?: unknown; providers?: unknown;`
and add to the route table, before the sessions branch:

```ts
    if (url.pathname === "/v1/kira/overview") return json(options.overview ?? overviewFixture());
    if (url.pathname === "/v1/kira/providers") return json(options.providers ?? providersFixture());
```

and append the two fixtures at the bottom of the file, so every screen test can either take the
default or overwrite it with the rows it cares about:

```ts
/** The state a personal install is actually in: one override, one no-cap provider, one orphan. */
export function providersFixture(): unknown {
  const state = (base: unknown, override: unknown, effective: unknown) => ({ base, override, effective });
  return {
    month: "2026-10",
    orphan_settings: ["ghost.enabled"],
    providers: [
      {
        name: "groq",
        kind: "openai_compat",
        base_url: "https://api.groq.com/openai/v1",
        models: ["llama-3.3-70b-versatile"],
        key_ref: "provider/groq",
        key_present: true,
        enabled: state(true, null, true),
        priority: state(50, 5, 5),
        tier: state("fast", null, "fast"),
        monthly_cap: state(null, 1000000, 1000000),
        spend_this_month: 250000,
        health: { failures: 0, successes: 12, cooling_s: 0, last_reason: "" },
      },
      {
        name: "openrouter",
        kind: "openai_compat",
        base_url: "https://openrouter.ai/api/v1",
        models: ["claude-sonnet-4-5"],
        key_ref: "provider/openrouter",
        key_present: false,
        enabled: state(true, false, false),
        priority: state(100, null, 100),
        tier: state("powerful", null, "powerful"),
        monthly_cap: state(null, null, null),
        spend_this_month: 0,
        health: { failures: 3, successes: 0, cooling_s: 42.5, last_reason: "rate_limited status=429 too many" },
      },
    ],
  };
}

export function overviewFixture(): unknown {
  return {
    month: "2026-10",
    turns: 40,
    tokens: { input: 12000, output: 4800 },
    success_rate: 0.925,
    interrupted: 1,
    failed: 2,
    by_provider: [{ provider: "groq", turns: 38, tokens: 15000 }],
    by_model: [{ provider: "groq", model: "llama-3.3-70b-versatile", turns: 38, tokens: 15000 }],
    daily: [
      { date: "2026-10-01", turns: 20, tokens: 9000 },
      { date: "2026-10-02", turns: 20, tokens: 7800 },
    ],
    budgets: [
      { provider: "groq", cap: 1000000, used: 250000, remaining: 750000 },
      { provider: "openrouter", cap: null, used: 0, remaining: null },
    ],
    recent_issues: [
      { id: 9, session_id: "sess-9", status: "failed", provider: "openrouter", model: null, created_at: 1, reason: "provider_5xx status=503 down" },
      { id: 8, session_id: "sess-8", status: "interrupted", provider: "groq", model: "llama-3.3-70b-versatile", created_at: 2, reason: "client saw text" },
    ],
  };
}
```

Run: `cd kira-chat && npx vitest run src/api.test.ts`
Expected: PASS, including the new read test.

- [ ] **Step 7: The Overview screen**

Create `kira-chat/src/screens/OverviewScreen.tsx`:

```tsx
import { useState } from "react";
import type { KiraClient } from "../api.ts";
import type { BudgetRow, DailyUsage, OverviewResponse } from "../contracts.ts";
import { useAsync } from "../useAsync.ts";

const MONTH_INPUT = /^\d{4}-\d{2}$/;

function num(value: number): string {
  return value.toLocaleString("en-US");
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="stat">
      <span className="muted">{label}</span>
      <strong className="stat-value">{value}</strong>
      {hint ? <span className="muted mono">{hint}</span> : null}
    </div>
  );
}

function BudgetBar({ row }: { row: BudgetRow }) {
  // An effective cap of 0 is normalised to null by the engine, so these are the only two states.
  if (row.cap === null) {
    return (
      <div className="budget">
        <span className="mono">{row.provider}</span>
        <div className="bar bar-unlimited" aria-label={`${row.provider} has no monthly cap`}>
          <span className="bar-label">{num(row.used)} tokens · no cap</span>
        </div>
      </div>
    );
  }
  const pct = Math.min(100, (row.used / row.cap) * 100);
  return (
    <div className="budget">
      <span className="mono">{row.provider}</span>
      <div className={`bar ${pct >= 100 ? "bar-over" : pct > 80 ? "bar-high" : ""}`} aria-label={`${row.provider} used ${Math.round(pct)}% of its cap`}>
        <span className="bar-used" style={{ width: `${pct}%` }} />
        <span className="bar-label">
          {num(row.used)} / {num(row.cap)} · {num(row.remaining ?? 0)} left
        </span>
      </div>
    </div>
  );
}

function Sparkline({ daily }: { daily: DailyUsage[] }) {
  if (daily.length === 0) return null;
  const peak = Math.max(...daily.map((day) => day.tokens), 1);
  const step = 300 / Math.max(daily.length - 1, 1);
  const points = daily
    .map((day, index) => `${(index * step).toFixed(1)},${(30 - (day.tokens / peak) * 28).toFixed(2)}`)
    .join(" ");
  return (
    <svg className="spark" viewBox="0 0 300 30" preserveAspectRatio="none" role="img" aria-label={`daily tokens, peak ${peak}`}>
      <polyline points={points} fill="none" stroke="currentColor" strokeWidth="1.5" />
    </svg>
  );
}

export function OverviewScreen({ client }: { client: KiraClient }) {
  const [month, setMonth] = useState<string | undefined>(undefined);
  const state = useAsync(() => client.overview(month), [month]);

  if (state.kind === "loading") return <section className="screen"><p className="muted">loading the month…</p></section>;
  if (state.kind === "error") {
    return (
      <section className="screen">
        <p className="error">cannot read the overview: {String((state.error as Error).message ?? state.error)}</p>
      </section>
    );
  }
  const view: OverviewResponse = state.data;
  const served = view.turns - view.interrupted - view.failed;

  return (
    <section className="screen">
      <header className="screen-head">
        <h2>Overview</h2>
        <label className="muted">
          month
          <input
            type="month"
            aria-label="month"
            value={month ?? view.month}
            onChange={(event) => {
              const next = event.target.value;
              setMonth(MONTH_INPUT.test(next) ? next : undefined);
            }}
          />
        </label>
        <span className="spacer" />
        <button type="button" onClick={state.refresh}>
          reload
        </button>
      </header>

      {view.turns === 0 ? (
        <p className="empty">nothing spent in {view.month} yet — the month is empty, not broken.</p>
      ) : (
        <>
          <div className="stats">
            <Stat label="turns" value={num(view.turns)} hint={`${num(served)} served`} />
            <Stat label="tokens" value={num(view.tokens.input + view.tokens.output)} hint={`${num(view.tokens.input)} in · ${num(view.tokens.output)} out`} />
            <Stat label="success rate" value={view.success_rate === null ? "no data" : `${(view.success_rate * 100).toFixed(1)}%`} />
            <Stat label="interrupted" value={num(view.interrupted)} />
            <Stat label="failed" value={num(view.failed)} />
          </div>

          <h3>Budgets</h3>
          {view.budgets.map((row) => (
            <BudgetBar key={row.provider} row={row} />
          ))}

          <h3>By day</h3>
          <Sparkline daily={view.daily} />

          <h3>Top models</h3>
          <table className="grid">
            <thead><tr><th>model</th><th>provider</th><th>turns</th><th>tokens</th></tr></thead>
            <tbody>
              {view.by_model.map((row) => (
                <tr key={`${row.provider}/${row.model}`}>
                  <td className="mono">{row.model}</td>
                  <td>{row.provider}</td>
                  <td>{num(row.turns)}</td>
                  <td>{num(row.tokens)}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <h3>Recent trouble</h3>
          {view.recent_issues.length === 0 ? (
            <p className="empty">no interrupted or failed turns this month.</p>
          ) : (
            <ul className="issues">
              {view.recent_issues.map((issue) => (
                <li key={issue.id}>
                  <span className={`issue-${issue.status}`}>{issue.status}</span>
                  <span className="mono">{issue.session_id}</span>
                  <span>{issue.provider ?? "no provider"} · {issue.reason}</span>
                </li>
              ))}
            </ul>
          )}
          <p className="muted">
            {view.by_provider.length} provider{view.by_provider.length === 1 ? "" : "s"} served this month. Adding a provider
            or a model means editing <span className="mono">config.yaml</span>.
          </p>
        </>
      )}
    </section>
  );
}
```

The recent-issue rows are text in M9; Task 18 turns them into buttons that open the transcript,
because there is no transcript screen to open until then.

- [ ] **Step 8: The Providers screen (read-only)**

Create `kira-chat/src/screens/ProvidersScreen.tsx`:

```tsx
import type { KiraClient } from "../api.ts";
import type { FieldStateBool, FieldStateCap, FieldStateInt, FieldStateStr, ProviderView } from "../contracts.ts";
import { useAsync } from "../useAsync.ts";

type AnyState = FieldStateBool | FieldStateInt | FieldStateStr | FieldStateCap;

function num(value: number): string {
  return value.toLocaleString("en-US");
}

/** One formatter for every FieldState value: the only nulls that reach here are caps meaning unlimited. */
function show(value: unknown): string {
  if (value === null) return "unlimited";
  if (typeof value === "number") return num(value);
  if (typeof value === "boolean") return value ? "on" : "off";
  return String(value);
}

function fieldProps(state: AnyState): { text: string; base: string; overridden: boolean } {
  return { text: show(state.effective), base: show(state.base), overridden: state.override !== null };
}

function Field({ text, base, overridden }: { text: string; base: string; overridden: boolean }) {
  return (
    <td className={overridden ? "field-overridden" : undefined}>
      {text}
      {overridden ? <div className="muted mono">was {base}</div> : null}
    </td>
  );
}

function Row({ provider }: { provider: ProviderView }) {
  return (
    <tr className={provider.enabled.effective ? undefined : "row-disabled"}>
      <td>
        <strong>{provider.name}</strong>
        <div className="muted mono">{provider.kind} · {provider.base_url}</div>
        <div className="muted mono">{provider.models.join(", ")}</div>
      </td>
      <td>
        <span className={provider.key_present ? "badge badge-ok" : "badge badge-none"}>
          {provider.key_present ? "key ok" : "no key"}
        </span>
        <div className="muted mono">{provider.key_ref}</div>
      </td>
      <Field {...fieldProps(provider.enabled)} />
      <Field {...fieldProps(provider.priority)} />
      <Field {...fieldProps(provider.tier)} />
      <Field {...fieldProps(provider.monthly_cap)} />
      <td className="mono">{num(provider.spend_this_month)}</td>
      <td>
        <span>{provider.health.successes}✓ {provider.health.failures}✗</span>
        {provider.health.cooling_s > 0 ? (
          <div className="warn mono">cooling {provider.health.cooling_s}s — {provider.health.last_reason}</div>
        ) : null}
      </td>
    </tr>
  );
}

export function ProvidersScreen({ client }: { client: KiraClient }) {
  const state = useAsync(() => client.providers(), []);

  if (state.kind === "loading") return <section className="screen"><p className="muted">reading providers…</p></section>;
  if (state.kind === "error") {
    return (
      <section className="screen">
        <p className="error">cannot read providers: {String((state.error as Error).message ?? state.error)}</p>
      </section>
    );
  }
  const body = state.data;

  return (
    <section className="screen">
      <header className="screen-head">
        <h2>Providers</h2>
        <span className="muted mono">spend for {body.month}</span>
        <span className="spacer" />
        <button type="button" onClick={state.refresh}>reload</button>
      </header>

      {body.providers.length === 0 ? (
        <p className="empty">no providers in <span className="mono">config.yaml</span> yet — write one and reload.</p>
      ) : (
        <table className="grid">
          <thead>
            <tr>
              <th>provider</th><th>key</th><th>enabled</th><th>priority</th><th>tier</th>
              <th>monthly cap</th><th>spent</th><th>health</th>
            </tr>
          </thead>
          <tbody>{body.providers.map((provider) => <Row key={provider.name} provider={provider} />)}</tbody>
        </table>
      )}

      {body.orphan_settings.length > 0 ? (
        <p className="warn mono">
          settings rows nothing uses: {body.orphan_settings.join(", ")} — clear them with
          <span className="mono">kira-engine settings list</span> then <span className="mono">settings clear PROVIDER KEY --yes</span>.
        </p>
      ) : null}

      <p className="muted">
        Values shown are what the router uses right now. A dimmed <span className="mono">was …</span> line means a
        stored override; <span className="mono">name</span>, <span className="mono">kind</span>,
        <span className="mono">base_url</span> and the model list come only from
        <span className="mono">config.yaml</span>. Probes and tuning controls arrive with the write endpoints.
      </p>
    </section>
  );
}
```

`fieldProps` is what keeps the four columns honest: `override !== null` is the only signal that a
value was tuned, so the dimmed `was …` line can never appear next to a value that came straight from
`config.yaml`, and never fail to appear next to one that did not.

- [ ] **Step 9: Put them behind the routes**

In `kira-chat/src/App.tsx`, import both screens and replace Task 2's ternary with a switch that
still holds the two unbuilt routes:

```tsx
const COMING_SOON: Partial<Record<Route, string>> = {
  models: "Models screen arrives in M12.",
  sessions: "Sessions screen arrives in M12.",
};

// ...inside the pane, replacing the `route === "chat" ? ... : ...` block:
        {route === "chat" ? (
          <ChatScreen client={client} models={models} model={model} setModel={setModel} mode={mode} setMode={setMode} connected={connected} route={route} />
        ) : route === "overview" ? (
          <OverviewScreen client={client} />
        ) : route === "providers" ? (
          <ProvidersScreen client={client} />
        ) : (
          <section className="screen-empty">
            <p className="muted">{COMING_SOON[route]}</p>
          </section>
        )}
```

In `kira-chat/src/App.test.tsx`, the Task 2 test that asserted `Dashboard is arriving in M9.` now
asserts the two routes that still wait, and the two new ones render real data:

```ts
  it("waits for the screens that are not built yet, by name", async () => {
    const engine = fakeEngine({ models: MODELS, health: HEALTH });
    connectedTo(engine);
    window.location.hash = "#/models";
    render(<App />);
    expect(await screen.findByText("Models screen arrives in M12.")).toBeTruthy();
  });

  it("reads the provider table from the merged view", async () => {
    const engine = fakeEngine({ models: MODELS, health: HEALTH });
    connectedTo(engine);
    window.location.hash = "#/providers";
    render(<App />);
    expect(await screen.findByText("no key")).toBeTruthy();
    expect(screen.getByText("openrouter")).toBeTruthy();
    expect(screen.getByText(/was 100/)).toBeTruthy();
    expect(screen.getByText(/settings rows nothing uses/)).toBeTruthy();
    expect(engine.calls.some((call) => call.url === "/v1/kira/providers")).toBe(true);
  });

  it("shows the month's spend, budgets and the honest empty state", async () => {
    const engine = fakeEngine({ models: MODELS, health: HEALTH });
    connectedTo(engine);
    window.location.hash = "#/overview";
    render(<App />);
    expect(await screen.findByText("40")).toBeTruthy();
    expect(screen.getByText(/12,800/)).toBeTruthy();
    expect(screen.getByText(/250,000 \/ 1,000,000/)).toBeTruthy();
    expect(screen.getByText(/no cap/)).toBeTruthy();
    expect(screen.getByText("92.5%")).toBeTruthy();

    const empty = fakeEngine({
      models: MODELS,
      health: HEALTH,
      overview: {
        month: "2026-11", turns: 0, tokens: { input: 0, output: 0 }, success_rate: null,
        interrupted: 0, failed: 0, by_provider: [], by_model: [], daily: [], budgets: [], recent_issues: [],
      },
    });
    connectedTo(empty);
    // Clicking "Overview" again would not re-read: same route, same deps. `reload` bumps the
    // epoch inside useAsync, which is the path a real user has after the engine's month turns over.
    fireEvent.click(screen.getByRole("button", { name: "reload" }));
    expect(await screen.findByText(/nothing spent in 2026-11/)).toBeTruthy();
  });
```

`was 100` is `openrouter`'s priority base; `openrouter` itself is the disabled row, so its enabled
cell reads `off` with `was on` underneath. Assert the strings the fixture actually produces rather
than the ones this file would prefer.

- [ ] **Step 10: Styles**

Append to `kira-chat/src/styles.css`:

```css
/* dashboard screens */
.screen {
  padding: 1.2rem 1.5rem 2.5rem;
  max-width: 72rem;
}
.screen-head {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-bottom: 1rem;
}
.screen h2 {
  font-family: var(--display);
  font-size: 1.25rem;
  margin: 0;
}
.screen h3 {
  font-size: 0.8rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--muted);
  margin: 1.6rem 0 0.5rem;
}
.stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(9rem, 1fr));
  gap: 0.6rem;
}
.stat {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 0.6rem 0.75rem;
}
.stat-value {
  font-size: 1.2rem;
  font-family: var(--mono);
}
.budget {
  display: grid;
  grid-template-columns: 9rem 1fr;
  align-items: center;
  gap: 0.6rem;
  margin: 0.35rem 0;
}
.bar {
  position: relative;
  height: 1.15rem;
  background: var(--panel-2);
  border: 1px solid var(--line);
  border-radius: 5px;
  overflow: hidden;
}
.bar-used {
  position: absolute;
  inset: 0 auto 0 0;
  background: color-mix(in srgb, var(--accent) 45%, transparent);
}
.bar-high .bar-used {
  background: color-mix(in srgb, var(--warn) 60%, transparent);
}
.bar-over .bar-used {
  background: color-mix(in srgb, var(--bad) 60%, transparent);
}
.bar-unlimited {
  background: repeating-linear-gradient(135deg, var(--panel-2), var(--panel-2) 6px, var(--line) 6px, var(--line) 7px);
}
.bar-label {
  position: relative;
  padding-left: 0.45rem;
  font-family: var(--mono);
  font-size: 0.78rem;
  line-height: 1.15rem;
}
.spark {
  width: 100%;
  max-width: 30rem;
  height: 2.2rem;
  color: var(--accent);
}
table.grid {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.9em;
}
table.grid th,
table.grid td {
  text-align: left;
  padding: 0.45rem 0.6rem;
  border-bottom: 1px solid var(--line);
  vertical-align: top;
}
.row-disabled td {
  opacity: 0.55;
}
.field-overridden {
  color: var(--accent);
}
.badge {
  display: inline-block;
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 0.05rem 0.5rem;
  font-size: 0.8em;
}
.badge-ok {
  border-color: var(--accent);
  color: var(--accent);
}
.badge-none {
  border-color: var(--bad);
  color: var(--bad);
}
.issues {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
}
.issues li {
  display: flex;
  gap: 0.6rem;
  align-items: baseline;
}
.issue-failed {
  color: var(--bad);
}
.issue-interrupted {
  color: var(--warn);
}
.empty {
  color: var(--muted);
  font-style: italic;
}
```

`color-mix` is supported by every current Chromium-based WebView; if a check fails on an older
engine, the fallback is a solid `background: var(--accent)` at 45% opacity on `.bar-used`.

- [ ] **Step 11: Run everything, both languages**

Run: `cd kira-chat && npm run check`
Expected: typecheck silent, all tests pass, `vite build` succeeds.

Run: `cd kira-engine && .venv/Scripts/python.exe -m pytest -q`
Expected: `118 passed, 1 skipped` — unchanged from Task 9; this task touches no engine code.

- [ ] **Step 12: Checkpoint — M9 done**

Run from `Kira/`: `node kira-contracts/check-drift.mjs && cd kira-engine && .venv/Scripts/python.exe -m pytest -q && cd ../kira-chat && npm run check`

**M9 acceptance (spec):** the dashboard shows effective-vs-baseline and spend with no write endpoint
yet. Prove the merged view is already live by hand before M10 exists:

```
cd kira-engine && .venv/Scripts/kira-engine.exe serve --backend memory   # in one window
```

Item 39: the subcommand is `serve`, and `serve` does not yet honour `--backend`, so point it at a
throwaway dir (`--data-dir ../.verify-data`, a **sibling** of `.kira-data` so the UI still mounts) and
delete the `engine/token` Locker entry afterwards. Then, in the engine's own directory, insert an
override with a one-liner and watch the dashboard react without a restart:

```
.venv/Scripts/python.exe -c "from kira.store import Store;from pathlib import Path;s=Store(Path('../.verify-data/kira.db'));s.set_setting('groq','enabled',False);print(s.settings_map())"
```

Reload `#/providers` — groq shows `off` with `was on`; the model picker loses groq's model, which is
the same fact the chat chain would show without needing a live key. Put it back with
`s.clear_setting('groq','enabled')`. If `Kira/.kira-data` is not the data
dir your launcher uses, `run_kira.py` prints it at start; do not guess.

If git is initialised: `git add kira-chat/src && git commit -m "feat(chat): read-only overview and providers screens"`

---

# M10 — The confirm secret and the write path

Nothing in M9 can change anything. Everything from here can, which is why the second secret arrives
first, before a single mutating endpoint.

## Task 11: The confirm secret — a second credential the browser can never read

The bearer token proves *a local process* is talking to the engine. It cannot prove a *human* meant
to change a setting: the token is handed to the chat page so that page can read history, so any
script that runs in that page has it. That is the gap the confirm secret closes. It is a separate
value in a separate Locker entry, it appears in **no response body** anywhere in the contract, and
the dashboard only ever receives it because the human typed it into a dialog. A cross-site request
forged from another origin can carry the token (the browser will attach nothing automatically, but
imagine it leaked) and cannot carry this header, because it is not a CORS-safe header and the value
is not readable.

Files:
- Modify: `kira-engine/src/kira/vault.py` — `ENGINE_CONFIRM_REF`, shared `_get_or_create()`
- Modify: `kira-engine/src/kira/app.py` — `Engine.confirm` + its first-run line
- Modify: `kira-engine/src/kira/__main__.py` — `cmd_token`, `keys list`
- Modify: `run_kira.py` — surface the secret at launch
- Modify: `kira-engine/tests/conftest.py` — stored test secret + `Harness.signed`
- Create: `kira-engine/tests/test_confirm_secret.py`

**No contract surface changes.** The `X-Kira-Confirm` parameter already exists in the v2 OpenAPI
(Task 8), and the secret's *value* is deliberately absent from every schema. Do not re-export
contracts or re-run the drift gate in this task — if you find yourself editing `contracts.py`, stop
and reread this line.

- [ ] **Step 1: Write the failing vault tests**

Create `kira-engine/tests/test_confirm_secret.py`:

```python
from __future__ import annotations

import json

from kira.__main__ import main
from kira.app import Engine
from kira.config import Config, write_sample_config
from kira.vault import ENGINE_CONFIRM_REF, ENGINE_TOKEN_REF, Vault


def _bare_config(tmp_path) -> Config:
    data_dir = tmp_path / ".kira-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return Config(data_dir=data_dir, providers=[])


def test_the_confirm_secret_is_its_own_ref_and_its_own_value() -> None:
    vault = Vault("memory")
    token, _ = vault.get_or_create_engine_token()
    confirm, _ = vault.get_or_create_confirm()
    assert confirm != token
    assert vault.get(ENGINE_CONFIRM_REF) == confirm
    assert vault.get(ENGINE_TOKEN_REF) == token


def test_both_secrets_are_minted_once_and_stable() -> None:
    vault = Vault("memory")
    token, first = vault.get_or_create_engine_token()
    token_again, second = vault.get_or_create_engine_token()
    assert first is True and second is False and token_again == token
    confirm, confirm_first = vault.get_or_create_confirm()
    assert confirm_first is True
    assert vault.get_or_create_confirm()[1] is False
    assert len(confirm) >= 32
```

Every later step appends test functions to this file; the imports it needs are already here, so do
not add a second import block halfway down.

- [ ] **Step 2: Refactor the vault so both secrets share one path**

In `vault.py`, add the ref under `ENGINE_TOKEN_REF`:

```python
ENGINE_CONFIRM_REF = "engine/confirm"
```

Replace `get_or_create_engine_token` with:

```python
    def _get_or_create(self, ref: str) -> tuple[str, bool]:
        """Returns (secret, created_now). The caller prints it only when created."""
        existing = self.get(ref)
        if existing:
            return existing, False
        secret = secrets.token_urlsafe(32)
        self.set(ref, secret)
        return secret, True

    def get_or_create_engine_token(self) -> tuple[str, bool]:
        return self._get_or_create(ENGINE_TOKEN_REF)

    def get_or_create_confirm(self) -> tuple[str, bool]:
        return self._get_or_create(ENGINE_CONFIRM_REF)
```

The `created_now` flag is the whole design: a secret that is only ever printed on the run that
mints it cannot be harvested from a log the engine writes on every start.

Run: `cd kira-engine && .venv/Scripts/python.exe -m pytest tests/test_confirm_secret.py -q`
Expected: 2 passed.

- [ ] **Step 3: Write the failing engine tests**

Append to `tests/test_confirm_secret.py`:

```python
def test_the_engine_carries_the_secret_the_vault_holds(tmp_path) -> None:
    vault = Vault("memory")
    vault.set("engine/confirm", "a-stored-confirm")
    engine = Engine(_bare_config(tmp_path), vault=vault)
    assert engine.confirm == "a-stored-confirm"


def test_a_first_run_prints_both_secrets_and_a_second_run_prints_neither(tmp_path, capsys) -> None:
    vault = Vault("memory")
    Engine(_bare_config(tmp_path), vault=vault)
    first = capsys.readouterr().err
    assert "engine token" in first
    assert "confirm secret" in first

    Engine(_bare_config(tmp_path), vault=vault)
    assert capsys.readouterr().err == ""
```

`_bare_config` is the shape the other engine tests use for a provider-less engine — a `Config`
pointing at a `tmp_path` data dir with `providers=[]` — and it is already in the file from Step 1.
Both engines share one vault and one data dir: that is what makes the second run's silence the
proof that neither secret is re-printed on every start.

- [ ] **Step 4: Give `Engine` the confirm secret**

In `app.py`, after the token block at the end of `__init__`:

```python
        self.confirm, confirm_created = self.vault.get_or_create_confirm()
        if confirm_created:
            print(
                f"[kira] first run — confirm secret (shown once, stored in the {self.vault.location}): {self.confirm}",
                file=sys.stderr,
            )
```

`sys` is already imported (the token line uses it). Do not add `self.confirm` to any endpoint
payload — Task 12 asserts the opposite.

Run: `cd kira-engine && .venv/Scripts/python.exe -m pytest tests/test_confirm_secret.py -q`
Expected: 4 passed.

- [ ] **Step 5: Teach the tests how to sign a write**

In `tests/conftest.py`, above `class Harness`, add:

```python
TEST_TOKEN = "test-engine-token"
TEST_CONFIRM = "test-confirm-secret"
```

In `Harness.__init__`, replace the token line with:

```python
        self.vault.set("engine/token", TEST_TOKEN)
        self.vault.set("engine/confirm", TEST_CONFIRM)
```

Replace the `auth` property and add `signed` next to it:

```python
    @property
    def auth(self) -> dict:
        return {"Authorization": f"Bearer {TEST_TOKEN}"}

    @property
    def signed(self) -> dict:
        """What a dashboard write actually looks like on the wire: bearer token plus confirm header."""
        return {"Authorization": f"Bearer {TEST_TOKEN}", "X-Kira-Confirm": TEST_CONFIRM}
```

Every Task-12 test uses `headers=harness.signed`, and the negative tests use `harness.auth` alone —
which is why both stay.

Run: `cd kira-engine && .venv/Scripts/python.exe -m pytest -q`
Expected: `122 passed, 1 skipped` (118 from Task 10, plus the 4 new ones). If a pre-existing test
now fails, something in the `auth` refactor changed a value — `TEST_TOKEN` must equal the old
literal exactly.

- [ ] **Step 6: Write the failing CLI tests**

Append to `tests/test_confirm_secret.py`:

```python
def test_the_token_command_keeps_stdout_to_the_bearer_token(monkeypatch, capsys) -> None:
    monkeypatch.setenv("KIRA_VAULT", "memory")
    assert main(["token"]) == 0
    captured = capsys.readouterr()
    token = captured.out.strip()
    assert captured.out.count("\n") == 1, "a second stdout line breaks `TOKEN=$(kira-engine token)`"
    assert token and not token.startswith("[kira]")
    assert "confirm secret" in captured.err
    assert token not in captured.err


def test_keys_list_reports_the_confirm_ref_without_its_value(tmp_path, capsys) -> None:
    write_sample_config(tmp_path)
    assert main(["keys", "list", "--backend", "memory", "--data-dir", str(tmp_path)]) == 0
    payload = json.loads(capsys.readouterr().out)
    by_ref = {row["ref"]: row for row in payload["secrets"]}
    assert by_ref[ENGINE_CONFIRM_REF]["present"] is False
    assert by_ref[ENGINE_TOKEN_REF]["present"] is False
    assert all(set(row) == {"ref", "purpose", "present"} for row in payload["secrets"])
```

`main(["token"])` builds its own `Vault(None)`, which falls back to `KIRA_VAULT` — hence the
monkeypatch rather than a hand-built vault. The fresh store mints both secrets in that call, so
`created` is `True` here; the assertions hold either way, which is the point: stdout never carries
the notice. A memory vault is per-process, so `keys list` reports `present: false` for refs the real
Locker would show as true — the test asserts the *shape* (`ref`/`purpose`/`present`, never `value`),
not the storage.

- [ ] **Step 7: Split the CLI output and extend `keys list`**

In `__main__.py`, add `ENGINE_CONFIRM_REF` to the existing import line:

```python
from .vault import Vault, ENGINE_CONFIRM_REF, ENGINE_TOKEN_REF
```

Replace `cmd_token`'s body:

```python
def cmd_token(args: argparse.Namespace) -> int:
    vault = Vault(args.backend)
    token, _ = vault.get_or_create_engine_token()
    confirm, _ = vault.get_or_create_confirm()
    # stdout stays exactly the bearer token so `TOKEN=$(kira-engine token)` keeps working; the
    # confirm secret is for a human pasting it into the dashboard, so it goes to stderr.
    print(token)
    print(f"[kira] confirm secret for dashboard writes: {confirm}", file=sys.stderr)
    return 0
```

The old first-creation line (`[kira] created engine token: ...`) went with it on purpose: it was the
one stdout line a script could not predict, and the token itself is always the answer. Nothing else
in the repo or the launcher greps for that string — Step 9's drift gate plus the full suite are the
safety net. Task 19 updates the README's `token` section to say the confirm secret is on stderr.

In `cmd_keys`, replace the `refs` line:

```python
    refs = {
        ENGINE_TOKEN_REF: "engine bearer token",
        ENGINE_CONFIRM_REF: "write-confirm secret (dashboard writes)",
    }
```

Run: `cd kira-engine && .venv/Scripts/python.exe -m pytest tests/test_confirm_secret.py -q`
Expected: 6 passed.

- [ ] **Step 8: Surface the secret where the user actually looks — the launcher**

In `run_kira.py`, inside the `if vault.backend == "keyring":` branch, right after the existing
`say(f"connect-token for the browser ...")` line, add:

```python
        confirm, confirm_created = vault.get_or_create_confirm()
        say(f"confirm secret for dashboard writes ({'created now' if confirm_created else 'already stored'}): {confirm}")
```

and replace the `else` branch's single line with:

```python
        say("secrets: copy the 'engine token' and 'confirm secret' lines below (a memory vault is per-process)")
```

Minting here is intentional: `run-kira.bat` is the one-click path, and a user who never runs
`kira-engine token` still needs to see the value once. Both branches print the launcher's data dir
nearby, so note in the same region — do not add a new line if the existing `say()` already names the
directory — where the values came from.

- [ ] **Step 9: Run everything, both languages**

Run: `cd kira-engine && .venv/Scripts/python.exe -m pytest -q`
Expected: `124 passed, 1 skipped`.

Run: `node kira-contracts/check-drift.mjs`
Expected: still `kira-contracts OK — v2, ...` with an unchanged schema count. The confirm secret has
no wire schema on purpose.

- [ ] **Step 10: Prove the secret cannot be read off the engine**

Run from `Kira/`: `grep -rn "self.confirm" kira-engine/src/kira/`
Expected: two hits, both in `app.py` — the assignment and the first-run line. A third means an
endpoint is publishing it; delete that.

Run: `grep -rn "confirm" kira-engine/src/kira/contracts.py`
Expected: only the `X-Kira-Confirm` *parameter* definition and any prose in a `description` — never
`"response"`, never a schema property.

- [ ] **Step 11: Checkpoint**

Run from `Kira/`: `cd kira-engine && .venv/Scripts/python.exe -m pytest -q && cd ../kira-chat && npm run check`

If git is initialised: `git add kira-engine/src kira-engine/tests run_kira.py && git commit -m "feat(engine): second secret for write confirmation"`

**M10 is not done yet** — the secret exists but nothing checks it. Task 12 is the gate.

## Task 11.5: API versioning support — one namespace, two numbers, no stale bundle

Inserted between Task 11 and Task 12 because Task 12 puts `require_confirm` on the same decorators, and a
namespace gate has to sit **before** any credential is compared. The rule itself is in the spine spec,
"Two versions, two jobs"; this section is the record of what shipped and what was checked.

**What shipped.** `API_VERSION` / `API_PREFIX` in `contracts.py` (with the bump rule as its docstring)
replaced nine hand-typed `/v1` literals in `app.py`, every key in `OPENAPI["paths"]`, the TS mirror, the
client's seven paths and `stream()`, the fake engine's route table, and the vite dev proxy. A pure ASGI
`KiraVersionMiddleware` answers a `^/(v\d+)(/|$)` this engine does not serve with a shaped
`404 unsupported_version` naming both prefixes — without reading the Authorization header — and puts
`X-Kira-Contract-Version` on the `http.response.start` of everything under the namespace. `/healthz` gained
`api_version` and stayed outside the namespace, because it is how a caller learns what the engine speaks.
`App.tsx` keeps the pre-connect refusal and also renders the disagreement as a persistent banner, since the
connect gate disappears once a token is in web storage; `ChatScreen` now surfaces a failed ledger read
instead of swallowing it, so a dead token does not look like an engine that never answered.
`dist/kira-build.json` — written by `kira-chat/scripts/stamp-version.mjs`, wired into `npm run build` — is
the stamp `ensure_chat_bundle` compares against the **imported** engine before serving a bundle that already
exists, and `open_when_ready` prints the pair a live engine reports.

**The gate that keeps the hole closed.** `kira-engine/tests/test_versioning.py` (10 tests) covers the two
numbers being different numbers, the wrong-namespace rejection before credentials and before any provider
dial, `/v1x` not being mistaken for a namespace, the bare prefix and trailing-slash behaviour asserted from
the app rather than assumed, the header on every response kind including a stream, one OpenAPI document with
`/docs` and `/redoc` gone, the contract-versus-`app.routes` diff in both directions against an explicit
whitelist (amendment 44), and a file-reading check that the client never types the namespace by hand.

**Verification run on 2026-10-27.** Engine: `135 passed, 1 skipped` (125 before, +10 here). Chat:
`6 files / 42 tests`, `npm run check` green, build wrote
`{"api_version":1,"contract_version":2,"api_prefix":"/v1"}`. `node kira-contracts/check-drift.mjs` still
prints `kira-contracts OK — v2, 39 schemas, 5 chunk types, 9 chain events`. The gate was proved able to
fail, twice: exporting with `API_VERSION = 2` produced `API_PREFIX /v1 != contract.json api_prefix /v2` plus
the `API_VERSION` line, and an `openapi.json` with one injected `/v2/rogue` path produced
`only /healthz may live outside /v1`; both were reverted and re-exported green. Live against a throwaway
`.verify-data` (memory vault first, then a scripted local provider through the keyring; the directory and
every secret the run created were deleted afterwards, `keys list` showing `provider/stub` →
`present: false`): `/healthz` → `api_version: 1`; `GET /v9/models` with no Authorization → shaped 404 naming
`/v1` and `/v9`; `/v1/models` with the token → `x-kira-contract-version: 2`; `curl -N` of a streamed turn
over a real uvicorn socket returned `chain`, two `delta`, `chain served` and `done` with
`x-kira-session-id` and the version header intact. In the browser the bundle served at `/chat/` loaded, the
badge read `/v1 · v2`, every client call hit the namespaced paths and answered 200, a stale stamp made
`python run_kira.py` rebuild before serving, and the next launch with a matching stamp skipped the build.

**Not exercised, and why.** Sending a message by clicking *send* in the real browser never fired — the
automation's text injection did not reach React's controlled state — so the UI's own SSE path is covered by
the jsdom tests and by curl over a real socket, not by a browser click. That belongs in Task 20's pass.
Two adjacent bugs were noted on purpose as out of this task's scope: a FastAPI `422` body was still
`{"detail": [...]}` rather than the contract's `{"error": {...}}` — **Task 12's sanitizer closed this one** —
and on a first run the `token` CLI and `serve` can each mint a token before the credential store shows the
other's write (one throwaway session printed two different tokens, only one of which the running engine
accepted), which is still open.

## Task 12: `require_confirm` and the five write endpoints, written over `API_PREFIX`

**Read this before the snippets:** Task 11.5 single-sourced the namespace, so every `"/v1/..."` literal in
the steps below is `f"{API_PREFIX}/..."` in the code you actually write. The snippets keep spelling `/v1` so
they stay readable against the contract document; `test_versioning.py` will fail a client file that hard-codes
it, and the decorator literals are what the drift whitelist compares. Write the f-string.

This is the task that lets the dashboard change things. Three rules run through all of it:

**A write needs both secrets.** The bearer token proves a local process; the `X-Kira-Confirm` header
proves a human holding the second secret. Use `AuthError` (401) for a missing, wrong or
bearer-equal confirm — the confirm is an *authentication factor* (proof of possession), not an
authorization rule, and reusing the existing code is why the contract could freeze at Task 8. The
two cases stay distinguishable in the message, which the dialog shows verbatim.

**Reads stay tolerant, writes stay strict.** `build_view` reports an unusable stored row as an orphan
instead of crashing the router, so a hand-edited database degrades visibly. A value the dashboard
writes has to be one the router can actually act on, so the write path validates first and stores
afterwards — never store-then-discover.

**A submitted key never comes back out.** Provider keys are accepted as JSON and written straight to
the Locker; every response reports presence only. FastAPI's default 422 body echoes the offending
value under `input`, so this task also installs one sanitizer that turns any request-validation
failure into the documented 400 shape with field *names* and no values.

**Files:**
- Modify: `kira-engine/src/kira/overrides.py` — `MAX_PRIORITY`, `_WRITER_HINTS`, `validate_setting()`
- Modify: `kira-engine/src/kira/net.py` — `HealthLedger.clear_cooldown()`
- Modify: `kira-engine/src/kira/app.py` — the sanitizer, `require_confirm`, `providers_payload()`, five endpoints
- Modify: `kira-engine/tests/test_overrides.py` (append 4)
- Create: `kira-engine/tests/test_settings_validation.py` (19)

- [ ] **Step 1: Write the failing validator tests**

Append to `kira-engine/tests/test_overrides.py`:

```python
def test_the_write_path_normalises_tier_and_refuses_an_unknown_one(tmp_path):
    assert validate_setting("tier", " Powerful ") == "powerful"
    for bad in ("hyper", "", 7, True):
        with pytest.raises(ConfigError) as exc:
            validate_setting("tier", bad)
    assert "fast" in str(exc.value.message) and "powerful" in str(exc.value.message)


def test_priority_has_the_documented_range_and_a_bool_is_not_an_integer(tmp_path):
    assert validate_setting("priority", 0) == 0
    assert validate_setting("priority", MAX_PRIORITY) == MAX_PRIORITY
    for bad in (-1, MAX_PRIORITY + 1, 12.5, "12", True):
        with pytest.raises(ConfigError):
            validate_setting("priority", bad)


def test_monthly_cap_takes_zero_as_unlimited_and_refuses_the_rest(tmp_path):
    assert validate_setting("monthly_cap", 0) == 0
    assert validate_setting("monthly_cap", 1_000_000) == 1_000_000
    for bad in (-1, 0.5, True, "lots"):
        with pytest.raises(ConfigError):
            validate_setting("monthly_cap", bad)


def test_none_clears_any_field_and_an_unknown_field_is_named(tmp_path):
    for key in TUNABLE_FIELDS:
        assert validate_setting(key, None) is None
    with pytest.raises(ConfigError) as exc:
        validate_setting("colour", "red")
    assert "colour" in exc.value.message
    with pytest.raises(ConfigError) as exc:
        validate_setting("colour", None)
    assert "colour" in exc.value.message, "clearing a field that was never tunable is still a mistake"
```

Add to the import block at the top of that file:

```python
import pytest

from kira.config import TIERS
from kira.errors import ConfigError
from kira.overrides import MAX_PRIORITY, TUNABLE_FIELDS, validate_setting
```

`pytest` is the one Task 3 and Task 4 never needed — these are the first tests in that file that
expect a refusal rather than a value.

- [ ] **Step 2: Write the validator, reusing what the read path already knows**

In `overrides.py`, above `_VALIDATORS`:

```python
#: Matches the `priority` bounds on SettingsRequest in the published contract; keep the two in step.
MAX_PRIORITY = 1000

#: setting key -> the phrase used when a write gets it wrong. Each one describes exactly what the
#: matching read-side validator accepts, plus the bound the tolerant reader leaves alone.
_WRITER_HINTS = {
    "enabled": "true or false",
    "priority": f"an integer from 0 to {MAX_PRIORITY}",
    "tier": f"one of {list(TIERS)}",
    "monthly_cap": "an integer >= 0, where 0 means unlimited",
}
```

and after `build_view`:

```python
def validate_setting(key: str, value: Any) -> Any:
    """The strict twin of the tolerant read path. Returns the value to store; None means clear.

    `build_view` reports a row it cannot use as an orphan, because a hand-edited database must not
    be able to crash the router. This function refuses the same shapes outright, so the dashboard
    never writes one. It borrows `_VALIDATORS` for what a field *is* and adds only the range the
    reader deliberately leaves loose: priority outside 0..1000 still sorts, so reading it tolerates
    it, but asking for it is a typo and a typo deserves an error.
    """
    if key not in TUNABLE_FIELDS:
        raise ConfigError(f"'{key}' is not a tunable setting; settings holds {list(TUNABLE_FIELDS)}")
    if value is None:
        return None
    if key == "tier" and isinstance(value, str):
        # The router compares lowercase; a human typing "Powerful" meant the tier that exists.
        value = value.strip().lower()
    if _VALIDATORS[key](value) is None:
        raise ConfigError(f"{key} needs {_WRITER_HINTS[key]}")
    if key == "priority" and not 0 <= value <= MAX_PRIORITY:
        raise ConfigError(f"priority needs {_WRITER_HINTS[key]}")
    return value
```

`ConfigError` must be imported in `overrides.py` — extend the existing `from .store import ...`
neighbourhood with `from .errors import ConfigError`.

Run: `cd kira-engine && .venv/Scripts/python.exe -m pytest -q tests/test_overrides.py`
Expected: 4 new tests pass, the Task 4 tests unchanged.

- [ ] **Step 3: Write the failing confirm-gate tests**

Create `kira-engine/tests/test_settings_validation.py`:

```python
from __future__ import annotations

import logging

import httpx
from conftest import ok, ok_json, openai_text_chunks
from kira.errors import ProviderCallError
from kira.overrides import MAX_PRIORITY

WRITE_CALLS = [
    ("put", "/v1/kira/providers/fast_one/settings", {}),
    ("put", "/v1/kira/providers/fast_one/key", {"key": "gsk_written"}),
    ("delete", "/v1/kira/providers/fast_one/key", None),
    ("delete", "/v1/kira/providers/fast_one/cooldown", None),
    ("post", "/v1/kira/providers/fast_one/probe", None),
]


async def test_a_write_without_the_confirm_header_is_401(harness):
    for verb, path, body in WRITE_CALLS:
        resp = await harness.api.request(verb, path, json=body)
        assert resp.status_code == 401, f"{verb.upper()} {path} wrote with only a bearer token"
        assert resp.json()["error"]["code"] == "unauthorized"


async def test_a_wrong_confirm_is_401(harness):
    headers = {**harness.signed, "X-Kira-Confirm": "guessed-guessed-guessed"}
    resp = await harness.api.put("/v1/kira/providers/fast_one/settings", json={"priority": 5}, headers=headers)
    assert resp.status_code == 401
    assert harness.store.settings_map() == {}, "a rejected write must not touch the table"


async def test_the_bearer_token_is_refused_as_the_confirm_secret(harness):
    # Paste the token into both boxes and every write becomes an open door; say no instead.
    headers = {"Authorization": "Bearer test-engine-token", "X-Kira-Confirm": "test-engine-token"}
    resp = await harness.api.put("/v1/kira/providers/fast_one/settings", json={"enabled": False}, headers=headers)
    assert resp.status_code == 401
    assert "different value" in resp.json()["error"]["message"]


async def test_a_read_needs_no_confirm(harness):
    for path in ("/v1/kira/overview", "/v1/kira/providers", "/v1/kira/sessions"):
        assert (await harness.api.get(path, headers=harness.auth)).status_code == 200
```

All four fail right now with 404/405 — the endpoints do not exist yet. That is the expected failure;
do not stop here to make them 401 first.

The imports above are what Steps 6-9 need; most of them are unused in this step and that is fine —
do not move them into the functions that use them, and do not delete them to silence a linter.

- [ ] **Step 4: Install the 422 sanitizer before any body-typed endpoint exists**

In `app.py`, add to the FastAPI import line and the errors import (both already present — extend
them):

```python
from fastapi.exceptions import RequestValidationError
```

Immediately after the existing `@app.exception_handler(ProviderCallError)` block:

```python
    @app.exception_handler(RequestValidationError)
    async def _validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        # FastAPI's 422 echoes the offending value under `ctx`/`input`. For a provider-key body that
        # would hand the secret back to whoever guessed the shape, so the response names fields only.
        fields = sorted({
            ".".join(str(part) for part in err.get("loc", ())[1:]) or "body" for err in exc.errors()
        })
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "code": ConfigError.code,
                    "message": f"malformed request body; check {', '.join(fields) or 'the body'}",
                    "status": 400,
                    "retryable": False,
                }
            },
        )
```

`ConfigError.code` is `config_error`, which is what every 400 in this engine already says, so the
sanitizer adds no new code to the contract. Append this test to `test_settings_validation.py` and run
it now — it needs no dashboard endpoint, only the existing chat route:

```python
async def test_a_malformed_body_is_400_and_does_not_echo_the_value(harness):
    resp = await harness.api.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "hi"}], "max_tokens": "not_a_number_9f3a"},
        headers=harness.auth,
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "config_error"
    assert "not_a_number_9f3a" not in resp.text
```

Run: `cd kira-engine && .venv/Scripts/python.exe -m pytest -q tests/test_settings_validation.py -k malformed`
Expected: pass. If `max_tokens` is coerced instead of rejected, pick another field the model cannot
silently convert (`temperature: "hot"`) — the assertion that matters is the echo check, so prove it
on a value that really does fail validation.

- [ ] **Step 5: Add the confirm dependency and the shared providers payload**

In `app.py`, next to `require_token` / `auth`:

```python
    def require_confirm(x_kira_confirm: str | None = Header(None)) -> None:
        provided = (x_kira_confirm or "").strip()
        if provided and secrets.compare_digest(provided, engine.token):
            raise AuthError("the confirm secret is a different value from the bearer token")
        if not provided or not secrets.compare_digest(provided, engine.confirm):
            raise AuthError("this write needs the confirm secret in X-Kira-Confirm - re-enter it in the dialog")

    confirm = Depends(require_confirm)
```

`Header(None)` on `x_kira_confirm` maps to the `X-Kira-Confirm` wire name (FastAPI converts
underscores); do not pass an alias, and do not lowercase the header in the test — httpx sends it as
written.

Then lift Task 9's `kira_providers()` body into a plain function so the cooldown endpoint can return
the identical shape (amendment 11):

```python
    def providers_payload() -> dict:
        # body exactly as Task 9 wrote it, minus the decorator
        ...

    @app.get("/v1/kira/providers", dependencies=[auth])
    async def kira_providers() -> dict:
        return providers_payload()
```

Task 9's `tests/test_dashboard_api.py` is the proof that the move changed nothing: it must stay green
before any endpoint below exists.

While you are in that body, replace the four hand-written `"enabled"/"priority"/"tier"/"monthly_cap"`
lines with one spread, so the write endpoints return the same object the read endpoint builds:

```python
def _settings_wire(provider: EffectiveProvider) -> dict[str, dict]:
    """The four tunable fields as base/override/effective, from the same FieldStates the merge built."""
    return {key: provider.states[key].to_wire() for key in TUNABLE_FIELDS}
```

in the row dict that becomes `**_settings_wire(provider),` in the same position — the keys stay flat,
exactly as `ProviderView` publishes them and as `ProvidersScreen` reads `provider.enabled.effective`.

`EffectiveProvider`, `TUNABLE_FIELDS` and `validate_setting` join the existing
`from .overrides import ...` line in `app.py`.

- [ ] **Step 6: Make the settings endpoint real**

Append to `test_settings_validation.py`:

```python
async def test_a_valid_settings_write_returns_the_merged_field_states(harness):
    resp = await harness.api.put(
        "/v1/kira/providers/fast_one/settings",
        json={"priority": 7, "tier": "powerful", "enabled": False},
        headers=harness.signed,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["provider"] == "fast_one"
    assert body["settings"]["priority"] == {"base": 10, "override": 7, "effective": 7}
    assert body["settings"]["tier"] == {"base": "fast", "override": "powerful", "effective": "powerful"}
    assert body["settings"]["enabled"] == {"base": True, "override": False, "effective": False}
    # The router must agree with what the response just promised - one view, no cache to stale out.
    assert harness.engine.view().by_name["fast_one"].priority == 7
    assert harness.engine.view().by_name["fast_one"].enabled is False


async def test_null_clears_only_the_field_it_names(harness):
    harness.store.set_setting("fast_one", "priority", 3)
    harness.store.set_setting("fast_one", "tier", "powerful")
    resp = await harness.api.put(
        "/v1/kira/providers/fast_one/settings", json={"priority": None}, headers=harness.signed
    )
    assert resp.json()["settings"]["priority"]["override"] is None
    assert resp.json()["settings"]["priority"]["effective"] == 10, "back to the config.yaml baseline"
    assert resp.json()["settings"]["tier"]["override"] == "powerful", "one null must not wipe the row's neighbours"


async def test_an_empty_body_is_a_200_no_op(harness):
    before = harness.store.settings_map()
    resp = await harness.api.put("/v1/kira/providers/fast_one/settings", json={}, headers=harness.signed)
    assert resp.status_code == 200
    assert resp.json()["provider"] == "fast_one"
    assert harness.store.settings_map() == before


async def test_an_out_of_range_value_is_refused_before_anything_is_stored(harness):
    resp = await harness.api.put(
        "/v1/kira/providers/fast_one/settings",
        json={"enabled": False, "priority": MAX_PRIORITY + 1},
        headers=harness.signed,
    )
    assert resp.status_code == 400
    assert "priority" in resp.json()["error"]["message"]
    assert harness.store.settings_map() == {}, "validate the whole body, then write - never half a write"


async def test_an_unknown_field_is_refused_by_name_and_stores_nothing(harness):
    resp = await harness.api.put(
        "/v1/kira/providers/fast_one/settings", json={"colour": "red"}, headers=harness.signed
    )
    assert resp.status_code == 400
    assert "colour" in resp.json()["error"]["message"]
    assert harness.store.settings_map() == {}


async def test_an_unknown_provider_is_refused(harness):
    for path in ("/v1/kira/providers/nosuch/settings", "/v1/kira/providers/nosuch/key"):
        assert (await harness.api.put(path, json={}, headers=harness.signed)).status_code == 400
    assert (await harness.api.delete("/v1/kira/providers/nosuch/cooldown", headers=harness.signed)).status_code == 400
```

`MAX_PRIORITY` is imported at the top of the file from Step 3.

Then implement, in `app.py`:

```python
    @app.put("/v1/kira/providers/{name}/settings", dependencies=[auth, confirm])
    async def kira_put_settings(name: str, body: dict[str, Any]) -> dict:
        view = engine.view()
        if name not in view.by_name:
            raise ConfigError(f"unknown provider '{name}'")
        if not isinstance(body, dict):
            raise ConfigError("the settings body must be a JSON object of field names to values")
        # Whole-body validation first: a rejected write must leave the table exactly as it was.
        checked = {key: validate_setting(key, value) for key, value in body.items()}
        for key, value in checked.items():
            if value is None:
                engine.store.clear_setting(name, key)
            else:
                engine.store.set_setting(name, key, value)
        return {"provider": name, "settings": _settings_wire(engine.view().by_name[name])}
```

`validate_setting` and `_settings_wire` come from the imports Step 5 added. The second `engine.view()`
call is the point of the shape: the response is built from a fresh merge, so what the dashboard
renders is what the next turn's router will see, and there is no cache between them to invalidate.

Run: `cd kira-engine && .venv/Scripts/python.exe -m pytest -q tests/test_settings_validation.py`
Expected: the settings tests pass; the key/cooldown/probe tests still 404 (they come next).

- [ ] **Step 7: Key storage, with the echo guard as the requirement**

Append:

```python
async def test_put_key_stores_in_the_vault_and_reports_only_presence(harness):
    resp = await harness.api.put(
        "/v1/kira/providers/fast_one/key", json={"key": "gsk_super_secret_value"}, headers=harness.signed
    )
    assert resp.status_code == 200
    assert resp.json() == {"provider": "fast_one", "key_ref": "provider/fast_one", "key_present": True}
    assert harness.vault.get("provider/fast_one") == "gsk_super_secret_value", "the Locker got the new value"
    assert "super_secret" not in resp.text, "the response is presence, never the secret"


async def test_delete_key_forgets_it_and_reports_absence(harness):
    # Harness seeds provider/fast_one with "key-fast_one"; deleting must clear that row, not invent one.
    resp = await harness.api.delete("/v1/kira/providers/fast_one/key", headers=harness.signed)
    assert resp.json() == {"provider": "fast_one", "key_ref": "provider/fast_one", "key_present": False}
    assert harness.vault.has("provider/fast_one") is False


async def test_an_empty_key_is_refused_without_touching_the_vault(harness):
    before = harness.vault.get("provider/fast_one")
    resp = await harness.api.put("/v1/kira/providers/fast_one/key", json={"key": "   "}, headers=harness.signed)
    assert resp.status_code == 400
    assert "key" in resp.json()["error"]["message"]
    assert harness.vault.get("provider/fast_one") == before


async def test_no_response_or_log_record_carries_the_submitted_key(harness, caplog):
    caplog.set_level(logging.DEBUG)
    resp = await harness.api.put(
        "/v1/kira/providers/fast_one/key", json={"key": "gsk_do_not_leak"}, headers=harness.signed
    )
    providers = await harness.api.get("/v1/kira/providers", headers=harness.auth)
    health = await harness.api.get("/v1/kira/health", headers=harness.auth)
    assert harness.vault.get("provider/fast_one") == "gsk_do_not_leak", "the write did happen"
    assert "gsk_do_not_leak" not in caplog.text
    for other in (resp, providers, health):
        assert "gsk_do_not_leak" not in other.text
```

That last test is the one that earns the design its name: the secret is provably in the Locker and
provably in nothing the engine says out loud — not a response, not a log record. Keep both halves;
either one alone proves nothing.

Implement:

```python
    @app.put("/v1/kira/providers/{name}/key", dependencies=[auth, confirm])
    async def kira_put_key(name: str, body: dict[str, Any]) -> dict:
        base = _baseline_config(engine, name)
        submitted = body.get("key") if isinstance(body, dict) else None
        if not isinstance(submitted, str) or not submitted.strip():
            raise ConfigError("the key body needs a non-empty 'key' string")
        if not base.key_ref:
            raise ConfigError(f"provider '{name}' has no key_ref in config.yaml - nothing to store it under")
        engine.vault.set(base.key_ref, submitted.strip())
        return {"provider": name, "key_ref": base.key_ref, "key_present": True}

    @app.delete("/v1/kira/providers/{name}/key", dependencies=[auth, confirm])
    async def kira_delete_key(name: str) -> dict:
        base = _baseline_config(engine, name)
        if base.key_ref:
            engine.vault.delete(base.key_ref)
        return {"provider": name, "key_ref": base.key_ref, "key_present": engine.registry.key_for(name) is not None}
```

with the module-level helper they both need — the key lives under the *baseline* `key_ref`, which is
the one string the registry reads, so the endpoint must not consult the merged view here:

```python
def _baseline_config(engine: Engine, name: str) -> ProviderConfig:
    """config.yaml's stanza for a provider, or a 400. Key storage is keyed by the YAML ref, not the
    merged view: `key_ref` is not one of the four tunable fields, so the two can never disagree."""
    try:
        return engine.registry.config_for(name)
    except ConfigError as exc:
        raise ConfigError(f"unknown provider '{name}': {exc.message}") from exc
```

Check `ProviderRegistry.config_for` at `registry.py:32-36`: it raises `ConfigError` for an unknown
name, so the `except` clause keeps the message useful. `ProviderConfig` is already imported in
`app.py`; add it to that line if it is not.

A provider whose stanza has no `key_ref` (a hypothetical local model) is refused on PUT and reported
absent on DELETE rather than inventing a ref — that keeps the door closed on the deferred offline
work instead of storing a key nothing reads.

- [ ] **Step 8: Cooldown clear, returning the whole view**

`HealthLedger` in `net.py` — after `record_success`:

```python
    def clear_cooldown(self, name: str) -> None:
        """Drop the cooling timer now. Counters stay: they are the history the panel shows."""
        st = self.state(name)
        st.cooled_until = 0.0
        self._persist(name, st)
```

Test:

```python
async def test_delete_cooldown_clears_the_timer_and_returns_the_whole_providers_view(harness):
    harness.engine.ledger.record_failure(ProviderCallError("fast_one", "boom", status=503, retryable=True))
    assert harness.engine.ledger.state("fast_one").cooled_until > harness.engine.ledger.clock()
    resp = await harness.api.delete("/v1/kira/providers/fast_one/cooldown", headers=harness.signed)
    assert resp.status_code == 200
    assert {"providers", "orphan_settings", "month"} <= set(resp.json()), "amendment 11: one ProvidersResponse"
    row = next(p for p in resp.json()["providers"] if p["provider"] == "fast_one")
    assert row["health"]["cooling_s"] == 0
    assert row["health"]["failures"] == 1, "the failure history stays visible"
```

`record_failure` on a retryable error sets `cooled_until` from `time.monotonic`, which is exactly what
`available()` compares, so the assertion about the timer is not tautological — it is the only way to
know the endpoint cleared a real cooldown.

Endpoint:

```python
    @app.delete("/v1/kira/providers/{name}/cooldown", dependencies=[auth, confirm])
    async def kira_clear_cooldown(name: str) -> dict:
        if name not in engine.view().by_name:
            raise ConfigError(f"unknown provider '{name}'")
        engine.ledger.clear_cooldown(name)
        return providers_payload()
```

The unknown-provider guard reads the merged view rather than the YAML because that is what the panel
drew: a row you can see is a row you can clear.

- [ ] **Step 9: Probe, whose failure is data**

```python
async def test_a_probe_answers_ok_inline_and_stores_no_conversation(harness):
    harness.script.queue("fast1", ok_json({"data": [{"id": "mini"}]}))
    harness.script.queue("fast1", ok(openai_text_chunks("ok")))
    before = harness.store.session_rows(10)
    resp = await harness.api.post("/v1/kira/providers/fast_one/probe", headers=harness.signed)
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"provider", "ok", "model_count", "sample", "latency_ms", "error"}
    assert body["provider"] == "fast_one" and body["ok"] is True and body["model_count"] == 1
    assert body["latency_ms"] is not None
    assert harness.store.session_rows(10) == before, "probe traffic is not a chat"
    assert harness.script.body_for("fast1")["max_tokens"] == 8


async def test_a_probe_of_a_dead_provider_is_a_200_that_says_no(harness):
    harness.script.queue("fast1", ok_json({"data": [{"id": "mini"}]}))
    harness.script.queue("fast1", httpx.Response(500, json={"error": {"message": "upstream down"}}))
    resp = await harness.api.post("/v1/kira/providers/fast_one/probe", headers=harness.signed)
    assert resp.status_code == 200, "a failed diagnostic is data, not an HTTP error"
    assert resp.json()["ok"] is False and "upstream down" in resp.json()["error"]


async def test_a_probe_of_an_unknown_provider_is_a_400(harness):
    resp = await harness.api.post("/v1/kira/providers/nosuch/probe", headers=harness.signed)
    assert resp.status_code == 400
    assert harness.script.calls == [], "refusing an unknown name costs the provider nothing"
```

`queue()` keys on the short host (`fast1`), the same idiom Task 7's `test_probe.py` uses — see
`Scripted._key` at `conftest.py:73-75`. Two queued responses per probe, because a probe is a list plus
one completion.

The middle test's sibling already exists as a unit test in Task 7 (a provider whose call raises
returns `ok: false` rather than throwing); what these add is the HTTP promise — a dead provider never
surfaces as a red toast, it surfaces as a row.

Endpoint:

```python
    @app.post("/v1/kira/providers/{name}/probe", dependencies=[auth, confirm])
    async def kira_probe(name: str) -> dict:
        if name not in engine.view().by_name:
            raise ConfigError(f"unknown provider '{name}'")
        return (await probe_provider(engine.registry, name)).to_wire()
```

Probe reads `registry.config_for(name)`, so a **disabled** provider is still probeable — that is the
order people actually work in: paste the key, test, then switch on. `probe_provider` spends one capped
completion (8 tokens) against the provider's first model and never writes to `messages`, so a probe
cannot inflate the spend the Overview screen shows. Import it in the same line that brings
`probe_models` in (Task 7).

- [ ] **Step 10: Run everything**

Run: `cd kira-engine && .venv/Scripts/python.exe -m pytest -q`
Expected: `147 passed, 1 skipped` (124 after Task 11, +4 in `test_overrides.py`, +19 in
`test_settings_validation.py`).

Run: `node kira-contracts/check-drift.mjs`
Expected: `kira-contracts OK — v2, 39 schemas, 5 chunk types, 9 chain events` — unchanged. These
endpoints were documented in Task 8; if the gate complains, the endpoint shape drifted from the schema
and the schema is the one to trust.

- [ ] **Step 11: Prove the gate by hand against a running engine**

Two windows. Window one:

```
cd kira-engine && .venv/Scripts/kira-engine.exe serve --backend memory
```

Window two (Git Bash). The memory vault prints its two secrets on the first-run lines at startup —
copy them:

```
curl -s -o /dev/null -w '%{http_code}\n' -X PUT \
  -H "Authorization: Bearer <token>" -H "Content-Type: application/json" -d '{}' \
  http://127.0.0.1:8901/v1/kira/providers/groq/settings
```

Expected `401` — a bearer token alone cannot write. Then with both headers:

```
curl -s -X PUT -H "Authorization: Bearer <token>" -H "X-Kira-Confirm: <confirm>" \
  -H "Content-Type: application/json" -d '{"enabled": false}' \
  http://127.0.0.1:8901/v1/kira/providers/groq/settings
```

Expected a body whose `settings.enabled` reads
`{"base": true, "override": false, "effective": false}`. Then, in `#/chat`, send a message and see
groq missing from the chain — the write is live without a restart. Put it back the same way with
`{"enabled": null}`.

- [ ] **Step 12: Checkpoint**

Run from `Kira/`: `cd kira-engine && .venv/Scripts/python.exe -m pytest -q && cd ../kira-chat && npm run check && node ../kira-contracts/check-drift.mjs`

If git is initialised: `git add kira-engine/src kira-engine/tests && git commit -m "feat(engine): confirm-gated write endpoints"`

The engine can now be commanded. Task 13 finishes the write surface (history deletion); Tasks 14–16
put a dialog, controls and budget enforcement in front of it.

**Executed (2026-10-27).** 158 passed, 1 skipped; `kira-contracts OK — v2, 39 schemas, 5 chunk types,
9 chain events`; `npm run check` 42 passed. Three ways the steps needed correcting once the code was
real, all recorded as amendments 48–51 below: the cooldown test read `p["provider"]` where the published
`ProviderView` row names the field `name`; the sanitizer is a behaviour change for the *whole* API, so
Task 1's `test_validation_errors_are_422_not_silent` had to become a 400 assertion (it is now
`test_validation_errors_are_a_contract_400_naming_the_field`, still checking the two shapes it was written
for); and item 44's `UNIMPLEMENTED` whitelist shrank to the two session deletes, which is that gate
reporting exactly what Task 13 still owes.

Step 11's hand-check ran against a throwaway `--data-dir` (a copy of `config.yaml`, its own empty
`kira.db`, memory vault, port 8914) rather than `.kira-data`, because the writes and the chat turn in the
step are not read-only: the real database would have kept the toggle if the revert were interrupted, and
sending a message spends the user's quota, which stays behind the `KIRA_LIVE=1` opt-in. Proven live over a
real uvicorn socket: bearer-only → 401 with the dialog's message; wrong confirm → the same 401; the bearer
token pasted as the confirm → 401 "a different value from the bearer token"; `{"enabled": false}` →
`{"base": true, "override": false, "effective": false}` **and** `GET /v1/models` dropping groq on the next
call — the router-visible half of "live without a restart", from the same `enabled_providers()` the plan
routes from; `{"enabled": null}` → back to `effective: true` and groq returns to the catalogue; a `[]` body
→ 400 `config_error` naming `body`, not a 422; `{"priority": 99999}` → 400 `priority needs an integer from
0 to 1000`; a key PUT → `{"key_present": true}` with the submitted value absent from the response, from
`GET /v1/kira/providers` and from the engine's own log; key DELETE → `key_present: false`; and the throwaway
`settings` table empty afterwards. The directory and the process were deleted after the run.

## Task 13: History deletion over the same gate

Task 6 gave `Store` the two delete methods and Task 8 published `DeletedResponse`; this is the thin
HTTP layer between them. Two rules worth stating before the code:

**A delete that finds nothing is a success.** `DELETE /v1/kira/sessions/{id}` on an already-gone
session answers `{"deleted": 0, "messages": 0}` with a 200, not 404 — the dashboard's row is a
snapshot of a list the user may have cleared in another tab, and a 404 would mean the UI has to
distinguish "it worked" from "it worked twice". `messages` for a deleted session likewise answers
`{"session_id": ..., "messages": []}` rather than 404, so a transcript refresh after a delete is
quiet.

**The bearer token is not enough, even for `clear-all`.** Both paths take the confirm gate; the whole
point of Task 12's dependency is that any mutation of stored state needs the second secret.

**Files:**
- Modify: `kira-engine/src/kira/app.py` (two endpoints after `session_messages`)
- Modify: `kira-engine/src/kira/__main__.py` (`cmd_settings`, registered in `build_parser`)
- Create: `kira-engine/tests/test_session_deletes.py` (7 tests)
- Create: `kira-engine/tests/test_cli_settings.py` (4 tests)

- [ ] **Step 1: Write the failing tests**

Create `kira-engine/tests/test_session_deletes.py`:

```python
from __future__ import annotations

import httpx
from conftest import ok, openai_text_chunks


def seed_two_sessions(store) -> tuple[str, str]:
    first = store.create_session("AUTO")
    store.add_message(first, "user", "one")
    store.add_message(first, "assistant", "uno", provider="fast_one", model="mini")
    second = store.create_session("AUTO")
    store.add_message(second, "user", "two")
    return first, second


async def test_delete_one_session_reports_the_counts_and_spares_the_other(harness):
    first, second = seed_two_sessions(harness.store)
    resp = await harness.api.delete(f"/v1/kira/sessions/{first}", headers=harness.signed)
    assert resp.status_code == 200
    assert resp.json() == {"deleted": 1, "messages": 2}
    ids = {row["id"] for row in harness.store.session_rows(50)}
    assert ids == {second}, "the cascade takes messages, not neighbours"


async def test_deleting_an_unknown_session_is_a_200_of_zeros(harness):
    resp = await harness.api.delete("/v1/kira/sessions/deadbeefdeadbeef", headers=harness.signed)
    assert resp.status_code == 200
    assert resp.json() == {"deleted": 0, "messages": 0}


async def test_clear_all_reports_how_much_it_removed(harness):
    seed_two_sessions(harness.store)
    resp = await harness.api.delete("/v1/kira/sessions", headers=harness.signed)
    assert resp.json() == {"deleted": 2, "messages": 3}
    assert harness.store.session_rows(50) == []


async def test_clear_all_on_an_empty_history_is_a_200_of_zeros(harness):
    resp = await harness.api.delete("/v1/kira/sessions", headers=harness.signed)
    assert resp.status_code == 200
    assert resp.json() == {"deleted": 0, "messages": 0}


async def test_both_session_deletes_need_the_confirm_secret(harness):
    session_id, _ = seed_two_sessions(harness.store)
    for path in (f"/v1/kira/sessions/{session_id}", "/v1/kira/sessions"):
        resp = await harness.api.delete(path, headers=harness.auth)
        assert resp.status_code == 401, f"{path} deleted with only a bearer token"
    assert len(harness.store.session_rows(50)) == 2, "a refused delete deleted nothing"


async def test_the_transcript_of_a_deleted_session_answers_empty_not_404(harness):
    session_id, _ = seed_two_sessions(harness.store)
    await harness.api.delete(f"/v1/kira/sessions/{session_id}", headers=harness.signed)
    resp = await harness.api.get(f"/v1/kira/sessions/{session_id}/messages", headers=harness.auth)
    assert resp.status_code == 200
    assert resp.json()["messages"] == []


async def test_a_stale_session_id_restarts_the_thread_instead_of_failing(harness):
    # The UI keeps X-Kira-Session-Id in memory; clear-all must not strand a client that still has one.
    session_id, _ = seed_two_sessions(harness.store)
    await harness.api.delete("/v1/kira/sessions", headers=harness.signed)
    harness.script.queue("fast1", ok(openai_text_chunks("fresh")))
    resp = await harness.api.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "again"}], "session_id": session_id},
        headers=harness.auth,
    )
    assert resp.status_code == 200
    assert resp.json()["session_id"] == session_id
    assert [m["content"] for m in harness.store.messages(session_id)] == ["again", "fresh"]
```

The last test is the one that justifies `create_session`'s `INSERT OR IGNORE` (`store.py:61-68`): the
`messages` table has `ON DELETE CASCADE` *and* `PRAGMA foreign_keys=ON`, so an insert that names a
deleted session would be a constraint violation if the session row were not quietly re-created first.
That is not obvious from the endpoint code, which is why the test posts a real turn rather than
asserting on SQL.

- [ ] **Step 2: Run them to watch them fail**

Run: `cd kira-engine && .venv/Scripts/python.exe -m pytest -q tests/test_session_deletes.py`
Expected: 7 failures. The two 401 assertions fail as 405 (`Method Not Allowed`) and the rest as 404
(`Not Found`), because `app.py` registers `GET /v1/kira/sessions` and
`GET /v1/kira/sessions/{session_id}/messages` and nothing else under those paths. A 404 here is the
honest failure — the route genuinely does not exist — so do not "fix" the test to accept it.

- [ ] **Step 3: Add the endpoints**

In `app.py`, immediately after `session_messages`:

```python
    @app.delete("/v1/kira/sessions/{session_id}", dependencies=[auth, confirm])
    async def kira_delete_session(session_id: str) -> dict:
        deleted, messages = engine.store.delete_session(session_id)
        return {"deleted": deleted, "messages": messages}

    @app.delete("/v1/kira/sessions", dependencies=[auth, confirm])
    async def kira_clear_sessions() -> dict:
        deleted, messages = engine.store.clear_sessions()
        return {"deleted": deleted, "messages": messages}
```

Route order is not a concern here: `/v1/kira/sessions/{session_id}` and `/v1/kira/sessions` are
different paths, and the existing `/v1/kira/sessions/{session_id}/messages` is more specific than
neither of them in a way Starlette could confuse. If a test ever resolves the wrong handler, check
`app.py`'s decorator order before touching the store.

`confirm` is the dependency Task 12 defined — these two are the only writes left.

- [ ] **Step 4: Write the failing CLI tests for the orphan prune**

The Providers screen tells the user an orphan row changes no route but hides a typo, and points at
`kira-engine settings`. That command does not exist yet, and the dashboard cannot replace it:
`validate_setting` refuses an unknown key on the write path, so a junk row like `groq.colour` can only
be pruned from the CLI. Create `kira-engine/tests/test_cli_settings.py`:

```python
from __future__ import annotations

import json

from kira.__main__ import main
from kira.config import load_config, write_sample_config
from kira.store import Store


def seeded(tmp_path) -> Store:
    write_sample_config(tmp_path)
    store = Store(load_config(tmp_path).db_path)
    store.set_setting("groq", "enabled", False)
    # A junk key is exactly what the dashboard cannot write, so seed it the way a typo got there.
    store._conn.execute("INSERT INTO settings(provider, key, value, updated_at) VALUES('groq','colour','\"red\"',1.0)")
    store._conn.commit()
    return store


def run(tmp_path, *argv):
    return main(["settings", *argv, "--data-dir", str(tmp_path), "--backend", "memory"])


def test_settings_list_flags_the_orphan_and_prints_no_secrets(tmp_path, capsys):
    seeded(tmp_path)
    assert run(tmp_path, "list") == 0
    rows = json.loads(capsys.readouterr().out)["rows"]
    by_key = {row["key"]: row for row in rows}
    assert by_key["enabled"] == {"provider": "groq", "key": "enabled", "value": "false", "orphan": False}
    assert by_key["colour"]["orphan"] is True
    assert set(by_key["colour"]) == {"provider", "key", "value", "orphan"}


def test_settings_clear_refuses_without_yes_and_takes_the_row_with_it(tmp_path, capsys):
    store = seeded(tmp_path)
    assert run(tmp_path, "clear", "groq", "colour") == 2
    assert store.settings_map()["groq"]["colour"] == '"red"'
    assert "settings clear" in capsys.readouterr().err
    assert run(tmp_path, "clear", "groq", "colour", "--yes") == 0
    assert "colour" not in store.settings_map()["groq"]
    assert "enabled" in store.settings_map()["groq"], "one key cleared is not the row emptied"


def test_settings_clear_without_a_key_removes_every_row_for_that_provider(tmp_path):
    store = seeded(tmp_path)
    store.set_setting("groq", "priority", 5)
    assert run(tmp_path, "clear", "groq", "--yes") == 0
    assert "groq" not in store.settings_map()


def test_settings_clear_of_a_row_that_is_not_there_returns_1(tmp_path, capsys):
    seeded(tmp_path)
    assert run(tmp_path, "clear", "groq", "nosuch", "--yes") == 1
    assert "no settings row" in capsys.readouterr().err
```

`settings_map()` returns the raw JSON text, which is why `value` is `"false"` and `'"red"'` rather
than Python values — the list command shows what is stored, not what the merge decided, because the
whole point of it is to spot a row the merge refused.

- [ ] **Step 5: Add the command**

In `__main__.py`, extend the imports:

```python
from .config import load_config, write_sample_config
from .overrides import build_view
from .store import Store
from .vault import Vault, ENGINE_CONFIRM_REF, ENGINE_TOKEN_REF
```

(`Vault` / `ENGINE_TOKEN_REF` are already on that line from Task 11; `Store` and `build_view` are
new. `write_sample_config` is already imported.)

Add the function after `cmd_keys`:

```python
def cmd_settings(args: argparse.Namespace) -> int:
    config = load_config(_data_dir(args))
    store = Store(config.db_path)

    if args.op == "list":
        view = build_view(config, store)
        rows = [
            {
                "provider": provider,
                "key": key,
                "value": raw,
                "orphan": f"{provider}.{key}" in view.orphan_settings,
            }
            for provider, stored in sorted(store.settings_map().items())
            for key, raw in sorted(stored.items())
        ]
        print(json.dumps({"orphans": view.orphan_settings, "rows": rows}, indent=2))
        return 0

    if not getattr(args, "yes", False):
        print(
            "[kira] settings clear needs --yes: it forgets an override, and the merged value that"
            " would replace it is not shown back to you first",
            file=sys.stderr,
        )
        return 2

    if getattr(args, "key", None):
        if not store.clear_setting(args.provider, args.key):
            print(f"[kira] no settings row for '{args.provider}.{args.key}'", file=sys.stderr)
            return 1
        print(f"[kira] cleared '{args.provider}.{args.key}' - the config.yaml baseline applies again")
        return 0

    removed = store.delete_settings(args.provider)
    print(f"[kira] cleared {removed} settings row(s) for '{args.provider}'")
    return 0 if removed else 1
```

`getattr` on `yes` and `key` because `settings list` shares this function and has neither argument.
A `clear` with no key deletes the whole provider (`delete_settings`, unused since Task 3 introduced
it) and answers 1 when nothing was there, so a script can tell the difference between "pruned" and
"typo in the provider name".

Register it after the `keys` block in `build_parser`:

```python
    st = sub.add_parser("settings", parents=[common], help="list or clear merged settings rows")
    ssub = st.add_subparsers(dest="op", required=True)
    ssub.add_parser("list", parents=[common]).set_defaults(func=cmd_settings)
    sclear = ssub.add_parser("clear", parents=[common], help="forget one override row, or a provider's whole set")
    sclear.add_argument("provider")
    sclear.add_argument("key", nargs="?", default=None)
    sclear.add_argument("--yes", action="store_true")
    sclear.set_defaults(func=cmd_settings)
```

Run: `cd kira-engine && .venv/Scripts/python.exe -m pytest -q tests/test_cli_settings.py`
Expected: 4 passed.

- [ ] **Step 6: Run everything**

Run: `cd kira-engine && .venv/Scripts/python.exe -m pytest -q`
Expected: `158 passed, 1 skipped` (147 after Task 12, +7 here, +4 for the CLI).

Run: `node kira-contracts/check-drift.mjs`
Expected: unchanged `kira-contracts OK — v2, ...`. `DeletedResponse` and both delete paths were
published in Task 8; this task only makes them true.

- [ ] **Step 7: Checkpoint — M10 done**

Run from `Kira/`: `cd kira-engine && .venv/Scripts/python.exe -m pytest -q && cd ../kira-chat && npm run check`

**M10 acceptance (spec):** every mutation the dashboard will ever perform is reachable, is refused
without the second secret, and refuses to echo a secret back. Task 12 Step 11's curl pair is the hand
proof for the gate; `test_no_response_or_log_record_carries_the_submitted_key` is the automated proof
for the echo rule. `kira-engine settings list` now prints the same merged view the panel reads, so a
typo in the table is findable from a terminal as well. Nothing in the UI can reach these endpoints
yet — that is Task 14, and it is why `confirm.tsx` has to be built before any control is wired.

If git is initialised: `git add kira-engine/src/kira/app.py kira-engine/src/kira/__main__.py kira-engine/tests/test_session_deletes.py kira-engine/tests/test_cli_settings.py && git commit -m "feat(engine): session deletes and the settings prune behind one gate"`

**Executed (2026-10-27).** 169 passed, 1 skipped (+7 deletes, +4 CLI); drift gate unchanged at
`v2, 39 schemas, 5 chunk types, 9 chain events` — both delete paths and `DeletedResponse` were published in
Task 8, so this task made them true rather than documenting them; `npm run check` 42 passed. Item 44's
whitelist is now empty, which is the first commit where the contract and the route table agree with nothing
in between. Step 6's `158 passed, 1 skipped` predates this task's own 11 tests (amendment 52).

Live hand-proof, again against a throwaway `--data-dir` on port 8915 that was deleted after the run, with a
session seeded into that copy's own `kira.db` so nothing of the user's history was touched: bearer-only
`DELETE …/sessions/{id}` → 401 with the dialog's message; wrong confirm → 401; signed →
`{"deleted": 1, "messages": 2}`; the same delete a second time → 200 `{"deleted": 0, "messages": 0}`; the
deleted session's transcript → 200 `{"messages": []}`; signed `DELETE …/sessions` → 200; bearer-only
`DELETE …/sessions` → 401. The CLI on the same throwaway directory: `settings list` printed
`"orphan": true` for a hand-seeded `groq.colour` row and no values from any secret store, `clear` without
`--yes` → exit 2 with the explanation, `clear groq colour --yes` → exit 0 and the row gone while
`enabled` stayed, `clear groq nosuch --yes` → exit 1 "no settings row", `clear groq --yes` → exit 0
"cleared 1 settings row(s)", and the second `list` back to `{"orphans": [], "rows": []}`.

---

# M11 — The dashboard drives the engine

The engine can be commanded; now the UI earns the right to command it. Three rules for everything
below: the confirm secret is held **only while a write is in flight** (never `localStorage`, never a
module singleton that outlives the dialog), every screen shows loading / empty / error / stale
explicitly, and a rejected write leaves the rendered row exactly as it was.

## Task 14: `confirm.tsx`, the write methods, and controls that use them

One rule governs this whole task: **the confirm secret exists only between the keystroke and the
response.** The dialog returns the string to the caller, the caller puts it in one header, and the
input is cleared before the network call even finishes. It never enters `localStorage`,
`sessionStorage`, a module-level variable, a URL, or the rendered text of any element that survives
the write. That is what makes the two-secret design worth having; a secret cached in
`localStorage` next to the bearer token would put both in the same place a page script can read.

The second rule is about the DOM: a row is never updated optimistically. The panel's numbers come
from the engine, so a refused write leaves the displayed value exactly as it was — no rollback logic,
because there is no local state to roll back.

**Files:**
- Create: `kira-chat/src/confirm.tsx`, `kira-chat/src/confirm.test.tsx`
- Modify: `kira-chat/src/api.ts` (one private `write()` + seven methods)
- Modify: `kira-chat/src/fake-engine.ts` (write branches with a real 401 path)
- Modify: `kira-chat/src/screens/ProvidersScreen.tsx` (controls replace the static cells)
- Modify: `kira-chat/src/App.tsx` (mount `ConfirmProvider`, pass `onChanged`)
- Modify: `kira-chat/src/api.test.ts` (append 4)
- Create: `kira-chat/src/screens/ProvidersScreen.test.tsx` (6)
- Modify: `kira-chat/src/styles.css` (dialog + cells)

- [ ] **Step 1: Write the failing dialog tests**

Create `kira-chat/src/confirm.test.tsx`:

```tsx
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { act } from "react";
import { describe, expect, it, vi } from "vitest";
import { ConfirmProvider, useConfirm } from "./confirm.tsx";

function Reader({ label = "ask" }: { label?: string }) {
  const ask = useConfirm();
  return (
    <button
      type="button"
      onClick={() => {
        void ask({ summary: "turn groq off" }).then((answer) => {
          (globalThis as Record<string, unknown>).__answer = answer;
        });
      }}
    >
      {label}
    </button>
  );
}

function lastAnswer(): string | null {
  return (globalThis as Record<string, unknown>).__answer as string | null;
}

describe("ConfirmProvider", () => {
  it("holds the answer until the human types the secret", async () => {
    (globalThis as Record<string, unknown>).__answer = "unset";
    render(
      <ConfirmProvider>
        <Reader />
      </ConfirmProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "ask" }));
    expect(await screen.findByText("turn groq off")).toBeTruthy();
    expect(lastAnswer()).toBe("unset");

    fireEvent.change(screen.getByLabelText("Confirm secret"), { target: { value: "s3cret" } });
    fireEvent.click(screen.getByRole("button", { name: "confirm write" }));
    await waitFor(() => expect(lastAnswer()).toBe("s3cret"));
  });

  it("answers null on cancel and writes nothing anywhere", async () => {
    (globalThis as Record<string, unknown>).__answer = "unset";
    const storage = vi.spyOn(Storage.prototype, "setItem");
    render(
      <ConfirmProvider>
        <Reader />
      </ConfirmProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "ask" }));
    fireEvent.change(screen.getByLabelText("Confirm secret"), { target: { value: "typedin" } });
    fireEvent.click(screen.getByRole("button", { name: "cancel" }));
    await waitFor(() => expect(lastAnswer()).toBeNull());
    expect(storage).not.toHaveBeenCalled();
    expect(document.cookie).toBe("");
    expect(screen.queryByDisplayValue("typedin")).toBeNull();
  });

  it("asks again for the next write - it never remembers the last secret", async () => {
    (globalThis as Record<string, unknown>).__answer = "unset";
    render(
      <ConfirmProvider>
        <Reader />
      </ConfirmProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "ask" }));
    fireEvent.change(screen.getByLabelText("Confirm secret"), { target: { value: "first" } });
    fireEvent.click(screen.getByRole("button", { name: "confirm write" }));
    await waitFor(() => expect(lastAnswer()).toBe("first"));

    fireEvent.click(screen.getByRole("button", { name: "ask" }));
    expect((screen.getByLabelText("Confirm secret") as HTMLInputElement).value).toBe("");
  });

  it("refuses a second ask while one is open instead of deadlocking", async () => {
    (globalThis as Record<string, unknown>).__answer = "unset";
    render(
      <ConfirmProvider>
        <Reader />
        <Reader label="ask again" />
      </ConfirmProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "ask" }));
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "ask again" }));
    });
    expect(lastAnswer()).toBeNull();
    expect(screen.getByText("turn groq off")).toBeTruthy(), "the first dialog is still open";
  });

  it("throws when a screen forgets the provider", () => {
    expect(() => render(<Reader />)).toThrow(/ConfirmProvider/);
  });
});
```

The `globalThis.__answer` trick is deliberate: `useConfirm` returns a promise, so the only way to see
what the dialog resolved is to have the test component publish it. Keep it inside the test file; do
not export a debug handle from `confirm.tsx`.

- [ ] **Step 2: Write `confirm.tsx`**

Create `kira-chat/src/confirm.tsx`:

```tsx
import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import type { FormEvent, ReactNode } from "react";

export interface ConfirmRequest {
  /** What the human is approving, in their words: "turn groq off", not "PUT /settings". */
  summary: string;
  detail?: string;
  danger?: boolean;
}

/** Resolves to the typed secret, or null when the human cancelled. */
export type Ask = (request: ConfirmRequest) => Promise<string | null>;

const ConfirmContext = createContext<Ask | null>(null);

export function useConfirm(): Ask {
  const ask = useContext(ConfirmContext);
  if (!ask) throw new Error("useConfirm needs a <ConfirmProvider> above it");
  return ask;
}

interface Open {
  request: ConfirmRequest;
  resolve: (answer: string | null) => void;
}

export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState<Open | null>(null);
  const [typed, setTyped] = useState("");
  const [error, setError] = useState<string | null>(null);
  // The state mirror is not enough to answer "is a dialog up right now" inside a synchronous
  // click handler, so keep one authoritative flag that never lags a render.
  const openRef = useRef<Open | null>(null);

  const close = useCallback(() => {
    openRef.current = null;
    setOpen(null);
    setTyped("");
    setError(null);
  }, []);

  const ask = useCallback<Ask>(
    (request) =>
      new Promise<string | null>((resolve) => {
        if (openRef.current) {
          resolve(null);
          return;
        }
        setTyped("");
        setError(null);
        const next = { request, resolve };
        openRef.current = next;
        setOpen(next);
      }),
    [],
  );

  function submit(event: FormEvent) {
    event.preventDefault();
    const current = openRef.current;
    if (!typed) {
      setError("type the confirm secret, or cancel");
      return;
    }
    close();
    current?.resolve(typed);
  }

  function cancel() {
    const current = openRef.current;
    close();
    current?.resolve(null);
  }

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") cancel();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <ConfirmContext.Provider value={ask}>
      {children}
      {open && (
        <div className="confirm-backdrop" role="dialog" aria-modal="true" aria-labelledby="confirm-title">
          <form className="confirm-card" onSubmit={submit}>
            <h3 id="confirm-title">{open.request.summary}</h3>
            {open.request.detail && <p className="muted mono">{open.request.detail}</p>}
            {open.request.danger && <p className="warn">This cannot be undone from the browser.</p>}
            <label>
              Confirm secret
              <input
                name="confirm_secret"
                type="password"
                value={typed}
                onChange={(event) => setTyped(event.target.value)}
                autoComplete="off"
                spellCheck={false}
                autoFocus
              />
            </label>
            <p className="muted small">
              The engine/confirm value, printed on its first run and by kira-engine token. It goes out
              once, in the X-Kira-Confirm header, and this page keeps no copy of it.
            </p>
            {error && <p className="error">{error}</p>}
            <div className="confirm-actions">
              <button type="button" onClick={cancel}>
                cancel
              </button>
              <button type="submit" className={open.request.danger ? "danger" : undefined}>
                confirm write
              </button>
            </div>
          </form>
        </div>
      )}
    </ConfirmContext.Provider>
  );
}
```

Why a *separate* secret rather than a click-to-confirm: the token is already inside the page (the
chat needs it), so a click proves nothing an attacker could not fake from another origin. The
`X-Kira-Confirm` custom header cannot be sent cross-origin without a CORS preflight this engine never
grants, and its value is never in anything the engine sends back. The dialog is the human's half; the
header is the machine's.

- [ ] **Step 3: Run the dialog tests**

Run: `cd kira-chat && npx vitest run src/confirm.test.tsx`
Expected: 5 passed. If the Escape effect makes the cancel test flaky, it is because `cancel` is
re-created each render — that is fine, the listener is re-bound; do not memoise it just to silence a
lint rule.

- [ ] **Step 4: Write the failing write-method tests**

Append to `kira-chat/src/api.test.ts` (same `describe`, same `fakeEngine` idiom):

```ts
  it("sends a settings write with the confirm header and the encoded name", async () => {
    const engine = fakeEngine({ confirm: "typed-secret", settings: { provider: "gr oq", settings: {} } });
    const client = new KiraClient({ baseUrl: "http://127.0.0.1:8901", token: "sekret", fetch: engine.fetch });
    await client.setSettings("gr oq", { enabled: false }, "typed-secret");
    const call = engine.calls[engine.calls.length - 1];
    expect(call.method).toBe("PUT");
    expect(call.url).toBe("/v1/kira/providers/gr%20oq/settings");
    expect(call.headers["X-Kira-Confirm"]).toBe("typed-secret");
    expect(JSON.parse(call.body ?? "{}")).toEqual({ enabled: false });
  });

  it("refuses to send a write with no secret - the dialog answered cancel", async () => {
    const engine = fakeEngine();
    const client = new KiraClient({ baseUrl: "", token: "sekret", fetch: engine.fetch });
    await expect(client.setSettings("groq", { priority: 5 }, "   ")).rejects.toThrow(/no confirm secret/);
    expect(engine.calls).toEqual([]);
  });

  it("surfaces the engine's refusal instead of hiding it", async () => {
    const engine = fakeEngine({ confirm: "right-one" });
    const client = new KiraClient({ baseUrl: "", token: "sekret", fetch: engine.fetch });
    await expect(client.deleteKey("groq", "wrong-one")).rejects.toMatchObject({
      body: { code: "unauthorized", status: 401 },
    });
  });

  it("keeps a provider key out of the URL and in the body only", async () => {
    const engine = fakeEngine({ confirm: "s" });
    const client = new KiraClient({ baseUrl: "", token: "sekret", fetch: engine.fetch });
    await client.putKey("groq", "gsk_pasted", "s");
    const call = engine.calls[engine.calls.length - 1];
    expect(call.url).toBe("/v1/kira/providers/groq/key");
    expect(call.url).not.toContain("gsk_pasted");
    expect(JSON.parse(call.body ?? "{}")).toEqual({ key: "gsk_pasted" });
  });
```

`KiraApiError` is defined once, in `kira-contracts/types.ts:90-99`: `readonly body: ErrorBody`,
`readonly httpStatus: number`, a message of `` `${body.code}: ${body.message}` `` and a `chain` getter
over `body.provider_chain`. `kira-chat/src/contracts.ts` is a one-line barrel over
`kira-contracts/index.ts`, so importing from `"../contracts.ts"` is correct and the status property to
match on is `httpStatus`, never `status` — the shape of that class is what the third test asserts.

- [ ] **Step 5: Add the write methods**

In `kira-chat/src/api.ts`, extend the type-only import with `DeletedResponse`, `KeyResponse`,
`ProbeResponse`, `ProvidersResponse`, `SettingsResponse`, and add above `stream()`:

```ts
  /**
   * Every mutating call. The secret comes straight from the dialog: it is trimmed, checked, sent in
   * one header and never stored - not in a field on this client, not in storage, not in a URL.
   */
  private async write<T>(path: string, method: string, secret: string, body?: unknown): Promise<T> {
    const value = secret.trim();
    if (!value) throw new Error("no confirm secret - the dialog was cancelled before it could answer");
    return this.request<T>(path, {
      method,
      headers: {
        "X-Kira-Confirm": value,
        ...(body === undefined ? {} : { "content-type": "application/json" }),
      },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
  }
```

and the seven callers:

```ts
  setSettings(name: string, patch: SettingPatch, secret: string): Promise<SettingsResponse> {
    return this.write(`/v1/kira/providers/${encodeURIComponent(name)}/settings`, "PUT", secret, patch);
  }

  putKey(name: string, key: string, secret: string): Promise<KeyResponse> {
    return this.write(`/v1/kira/providers/${encodeURIComponent(name)}/key`, "PUT", secret, { key });
  }

  deleteKey(name: string, secret: string): Promise<KeyResponse> {
    return this.write(`/v1/kira/providers/${encodeURIComponent(name)}/key`, "DELETE", secret);
  }

  clearCooldown(name: string, secret: string): Promise<ProvidersResponse> {
    return this.write(`/v1/kira/providers/${encodeURIComponent(name)}/cooldown`, "DELETE", secret);
  }

  probe(name: string, secret: string): Promise<ProbeResponse> {
    return this.write(`/v1/kira/providers/${encodeURIComponent(name)}/probe`, "POST", secret);
  }

  deleteSession(sessionId: string, secret: string): Promise<DeletedResponse> {
    return this.write(`/v1/kira/sessions/${encodeURIComponent(sessionId)}`, "DELETE", secret);
  }

  clearSessions(secret: string): Promise<DeletedResponse> {
    return this.write("/v1/kira/sessions", "DELETE", secret);
  }
```

and the patch type, exported next to `KiraClientOptions`:

```ts
/** Any subset of the four tunable fields. `null` clears that override back to config.yaml. */
export type SettingPatch = {
  enabled?: boolean | null;
  priority?: number | null;
  tier?: string | null;
  monthly_cap?: number | null;
};
```

Seven methods, not five: `deleteSession`/`clearSessions` are wired in Task 18 but they belong here so
the fake engine and the header rule are one implementation rather than two.

Run: `cd kira-chat && npx vitest run src/api.test.ts`
Expected: the four new tests pass.

- [ ] **Step 6: Teach the fake engine to refuse**

In `kira-chat/src/fake-engine.ts`, add `confirm?: string; settings?: unknown; probe?: unknown;` to
`FakeOptions`, export the default secret, and add a refusal helper inside `fakeEngine` right after
`const calls: Recorded[] = []`:

```ts
export const FAKE_CONFIRM = "fake-confirm";

// inside fakeEngine():
  const wanted = options.confirm ?? FAKE_CONFIRM;
  const confirmHeader = headers["X-Kira-Confirm"] ?? headers["x-kira-confirm"] ?? "";
  const refused = json(
    { error: { code: "unauthorized", message: "this write needs the confirm secret", status: 401, retryable: false } },
    401,
  );
```

Both header spellings are read because the client sends an object literal, so the key is exactly as
written — a test that lowercases it must still be refused, not accidentally match.

Then insert these branches before `return json({ detail: "Not Found" }, 404)`:

```ts
    const method = init.method ?? "GET";
    const settings = url.pathname.match(/^\/v1\/kira\/providers\/([^/]+)\/settings$/);
    if (settings && method === "PUT") {
      if (confirmHeader !== wanted) return refused;
      const name = decodeURIComponent(settings[1]);
      return json(options.settings ?? { provider: name, settings: settingsFixture(name) });
    }
    const key = url.pathname.match(/^\/v1\/kira\/providers\/([^/]+)\/key$/);
    if (key && (method === "PUT" || method === "DELETE")) {
      if (confirmHeader !== wanted) return refused;
      const name = decodeURIComponent(key[1]);
      return json({ provider: name, key_ref: `provider/${name}`, key_present: method === "PUT" });
    }
    const cooldown = url.pathname.match(/^\/v1\/kira\/providers\/([^/]+)\/cooldown$/);
    if (cooldown && method === "DELETE") {
      if (confirmHeader !== wanted) return refused;
      return json(options.providers ?? providersFixture());
    }
    const probe = url.pathname.match(/^\/v1\/kira\/providers\/([^/]+)\/probe$/);
    if (probe && method === "POST") {
      if (confirmHeader !== wanted) return refused;
      const name = decodeURIComponent(probe[1]);
      return json(options.probe ?? { provider: name, ok: true, model_count: 3, sample: ["mini"], latency_ms: 120, error: null });
    }
    if (url.pathname === "/v1/kira/sessions" && method === "DELETE") {
      if (confirmHeader !== wanted) return refused;
      return json(options.deleted ?? { deleted: 2, messages: 5 });
    }
    const session = url.pathname.match(/^\/v1\/kira\/sessions\/([^/]+)$/);
    if (session && method === "DELETE") {
      if (confirmHeader !== wanted) return refused;
      return json(options.deleted ?? { deleted: 1, messages: 3 });
    }
```

`settingsFixture(name)` is a new export beside the other fixtures — the four FieldStates for a
provider that has just had `enabled` overridden off, so a screen test can assert what a write returns
without re-implementing the merge:

```ts
/** After a write: enabled overridden off, the other three still at baseline. */
export function settingsFixture(name = "groq"): unknown {
  const state = (base: unknown, override: unknown, effective: unknown) => ({ base, override, effective });
  return {
    provider: name,
    settings: {
      enabled: state(true, false, false),
      priority: state(50, null, 50),
      tier: state("fast", null, "fast"),
      monthly_cap: state(null, null, null),
    },
  };
}
```

Add `deleted?: unknown;` to `FakeOptions` as well, and note the ordering rule that keeps this honest:
the `/v1/kira/sessions/{id}` matcher sits *after* the exact `/v1/kira/sessions` check, and
`([^/]+)` cannot cross a slash, so `…/sessions/abc/messages` still reaches the existing GET branch.

- [ ] **Step 7: Write the failing screen tests**

Create `kira-chat/src/screens/ProvidersScreen.test.tsx`:

```tsx
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { KiraClient } from "../api.ts";
import { FAKE_CONFIRM, fakeEngine, providersFixture } from "../fake-engine.ts";
import { ConfirmProvider } from "../confirm.tsx";
import { ProvidersScreen } from "./ProvidersScreen.tsx";

const client = (engine: ReturnType<typeof fakeEngine>) =>
  new KiraClient({ baseUrl: "", token: "sekret", fetch: engine.fetch });

function renderScreen(engine: ReturnType<typeof fakeEngine>, onChanged = vi.fn()) {
  render(
    <ConfirmProvider>
      <ProvidersScreen client={client(engine)} onChanged={onChanged} />
    </ConfirmProvider>,
  );
  return onChanged;
}

async function typeSecret(value = FAKE_CONFIRM) {
  fireEvent.change(await screen.findByLabelText("Confirm secret"), { target: { value } });
  fireEvent.click(screen.getByRole("button", { name: "confirm write" }));
}

describe("ProvidersScreen writes", () => {
  it("renders the merged table before anything is clicked", async () => {
    const engine = fakeEngine({ providers: providersFixture() });
    renderScreen(engine);
    expect(await screen.findByText("groq")).toBeTruthy();
    expect(screen.getByText(/was 100/)).toBeTruthy();
    expect(engine.calls.filter((call) => call.method === "PUT").length).toBe(0);
  });

  it("toggling a provider asks first, then sends the new value, then re-reads", async () => {
    const engine = fakeEngine({ providers: providersFixture() });
    const onChanged = renderScreen(engine);
    const toggle = await screen.findByLabelText("enabled groq");
    fireEvent.click(toggle);
    expect(await screen.findByText(/turn groq off/)).toBeTruthy();
    await typeSecret();
    await waitFor(() =>
      expect(
        engine.calls.some(
          (call) =>
            call.method === "PUT" &&
            call.url === "/v1/kira/providers/groq/settings" &&
            call.headers["X-Kira-Confirm"] === FAKE_CONFIRM &&
            call.body === JSON.stringify({ enabled: false }),
        ),
      ).toBe(true),
    );
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
  });

  it("a cancelled dialog sends no request at all", async () => {
    const engine = fakeEngine({ providers: providersFixture() });
    renderScreen(engine);
    fireEvent.click(await screen.findByLabelText("enabled groq"));
    fireEvent.click(await screen.findByRole("button", { name: "cancel" }));
    await waitFor(() => expect(engine.calls.filter((call) => call.method !== "GET").length).toBe(0));
  });

  it("a refused secret re-opens the dialog with the reason instead of a bare error", async () => {
    const engine = fakeEngine({ providers: providersFixture(), confirm: "the-real-one" });
    renderScreen(engine);
    fireEvent.click(await screen.findByLabelText("enabled groq"));
    await typeSecret("guessed");
    // Amendment 14: a 401 is not a dead end in a table cell; the dialog comes back naming the secret.
    expect(await screen.findByText(/refused that secret; type it again/)).toBeTruthy();
    expect((screen.getByLabelText("enabled groq") as HTMLInputElement).checked).toBe(true);
    expect(engine.calls.filter((call) => call.method === "PUT").length).toBe(1);
  });

  it("the second keystroke writes, and nothing about the first was remembered", async () => {
    const engine = fakeEngine({ providers: providersFixture(), confirm: "the-real-one" });
    const onChanged = renderScreen(engine);
    fireEvent.click(await screen.findByLabelText("enabled groq"));
    await typeSecret("guessed");
    await screen.findByText(/refused that secret; type it again/);
    await typeSecret("the-real-one");
    await waitFor(() =>
      expect(
        engine.calls.filter(
          (call) => call.method === "PUT" && call.headers["X-Kira-Confirm"] === "the-real-one",
        ).length,
      ).toBe(1),
    );
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
  });

  it("cap 0 means unlimited and the clear button means back to config.yaml", async () => {
    const engine = fakeEngine({ providers: providersFixture() });
    renderScreen(engine);
    const cap = await screen.findByLabelText("monthly cap openrouter");
    fireEvent.change(cap, { target: { value: "0" } });
    fireEvent.click(screen.getByRole("button", { name: `set cap openrouter` }));
    await typeSecret();
    await waitFor(() =>
      expect(engine.calls.some((call) => call.body === JSON.stringify({ monthly_cap: 0 }))).toBe(true),
    );
    fireEvent.click(screen.getByRole("button", { name: /clear override openrouter/ }));
    await typeSecret();
    await waitFor(() =>
      expect(engine.calls.some((call) => call.body === JSON.stringify({ monthly_cap: null }))).toBe(true),
    );
  });

  it("test spends one probe, renders the answer inline, and forget never echoes the key", async () => {
    const engine = fakeEngine({ providers: providersFixture() });
    renderScreen(engine);
    fireEvent.click(await screen.findByRole("button", { name: "test groq" }));
    await typeSecret();
    expect(await screen.findByText(/3 models · 120ms/)).toBeTruthy();

    fireEvent.change(screen.getByLabelText("new key groq"), { target: { value: "gsk_pasted" } });
    fireEvent.click(screen.getByRole("button", { name: "store key groq" }));
    await typeSecret();
    await waitFor(() =>
      expect(
        engine.calls.some(
          (call) => call.url === "/v1/kira/providers/groq/key" && call.body === JSON.stringify({ key: "gsk_pasted" }),
        ),
      ).toBe(true),
    );
    expect(engine.calls.every((call) => !call.url.includes("gsk_pasted"))).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "forget key groq" }));
    await typeSecret();
    await waitFor(() =>
      expect(
        engine.calls.some((call) => call.method === "DELETE" && call.url === "/v1/kira/providers/groq/key"),
      ).toBe(true),
    );
  });
});
```

- [ ] **Step 8: Replace the static cells with controls**

Rewrite `kira-chat/src/screens/ProvidersScreen.tsx` whole. `Field` and `fieldProps` from Task 10 go
away; `show()` stays, because a `null` cap still has to read "unlimited" in exactly one place, and the
`was …` line moves into `Was` so the tests that assert `/was 100/` keep passing.

```tsx
import { useEffect, useState } from "react";
import type { KiraClient, SettingPatch } from "../api.ts";
// `KiraApiError` is a value (a class), so it needs its own import beside the type-only one.
import { KiraApiError } from "../contracts.ts";
import type { FieldStateBool, FieldStateCap, FieldStateInt, FieldStateStr, ProbeResponse, ProviderView } from "../contracts.ts";
import { useConfirm } from "../confirm.tsx";
import type { ConfirmRequest } from "../confirm.tsx";
import { useAsync } from "../useAsync.ts";

type AnyState = FieldStateBool | FieldStateCap | FieldStateInt | FieldStateStr;

function show(value: unknown): string {
  if (value === null) return "unlimited";
  if (typeof value === "number") return value.toLocaleString("en-US");
  if (typeof value === "boolean") return value ? "on" : "off";
  return String(value);
}

function Was({ state }: { state: AnyState }) {
  return state.override === null ? null : <div className="muted mono">was {show(state.base)}</div>;
}

interface CellProps<State, Value> {
  provider: string;
  state: State;
  busy: boolean;
  commit: (patch: SettingPatch, summary: string) => void;
  value: (raw: string) => Value | null;
}

function NumberCell({ provider, state, busy, commit, label }: { provider: string; state: FieldStateInt; busy: boolean; commit: CellProps<FieldStateInt, number>["commit"]; label: string }) {
  const [raw, setRaw] = useState(String(state.effective));
  // A re-read that changes the value wins over what is in the box; the box only holds a draft.
  useEffect(() => setRaw(String(state.effective)), [state.effective]);
  return (
    <td>
      <label className="cell">
        <span className="sr">{label}</span>
        <input
          aria-label={label}
          name={`priority_${provider}`}
          type="number"
          min={0}
          max={1000}
          value={raw}
          disabled={busy}
          onChange={(event) => setRaw(event.target.value)}
          onBlur={() => {
            const next = Number(raw);
            if (!Number.isInteger(next) || next === state.effective) return;
            commit({ priority: next }, `set ${provider} priority to ${next}`);
          }}
        />
      </label>
      <Was state={state} />
    </td>
  );
}

function CapCell({ provider, state, busy, commit }: { provider: string; state: FieldStateCap; busy: boolean; commit: CellProps<FieldStateCap, number>["commit"] }) {
  const label = `monthly cap ${provider}`;
  const [raw, setRaw] = useState(state.effective === null ? "" : String(state.effective));
  useEffect(() => setRaw(state.effective === null ? "" : String(state.effective)), [state.effective]);
  return (
    <td>
      <input
        aria-label={label}
        name={`cap_${provider}`}
        type="number"
        min={0}
        value={raw}
        placeholder="unlimited"
        disabled={busy}
        onChange={(event) => setRaw(event.target.value)}
      />
      <div className="cell-actions">
        <button
          type="button"
          disabled={busy || raw === ""}
          onClick={() => commit({ monthly_cap: Number(raw) }, `cap ${provider} at ${Number(raw) === 0 ? "unlimited" : Number(raw).toLocaleString("en-US")}`)}
        >
          {`set cap ${provider}`}
        </button>
        <button
          type="button"
          disabled={busy || state.override === null}
          onClick={() => commit({ monthly_cap: null }, `clear the ${provider} cap override`)}
        >
          {`clear override ${provider}`}
        </button>
      </div>
      <Was state={state} />
    </td>
  );
}
```

`NumberCell` is the shape both `priority` and (via `CapCell`) `monthly_cap` need; keeping the cap
separate is what buys it its own two-button vocabulary — `0` and "no override" are different facts and
one input cannot spell both.

Then the row, which owns the dialog and the busy flag:

```tsx
function Row({ provider, client, refresh }: { provider: ProviderView; client: KiraClient; refresh: () => void }) {
  const ask = useConfirm();
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [probe, setProbe] = useState<ProbeResponse | null>(null);
  const [draftKey, setDraftKey] = useState("");

  async function run(summary: string, detail: string, danger: boolean, act: (secret: string) => Promise<unknown>) {
    let request: ConfirmRequest = { summary, detail, danger };
    for (;;) {
      const secret = await ask(request);
      if (!secret) return;
      setBusy(true);
      setNote(null);
      try {
        await act(secret);
        refresh();
        return;
      } catch (error) {
        if (!(error instanceof KiraApiError) || error.httpStatus !== 401) {
          setNote(error instanceof Error ? error.message : String(error));
          return;
        }
        // The spec's refusal clause: a mistyped secret re-opens the dialog with the reason instead of
        // leaving a bare 401 in a table cell, which reads as a broken button. Every pass needs a fresh
        // keystroke, so this cannot spin without a human in the loop, and nothing is remembered.
        request = { ...request, detail: `${detail} — the engine refused that secret; type it again` };
      } finally {
        setBusy(false);
      }
    }
  }

  const save = (patch: SettingPatch, summary: string) =>
    void run(
      summary,
      `PUT /v1/kira/providers/${provider.name}/settings`,
      false,
      (secret) => client.setSettings(provider.name, patch, secret),
    );
  ...
}
```

Every control in the row funnels through `run`, so "asks first", "clears the note", "re-reads on
success" and "shows the engine's own words on failure" are implemented once. The cells above take
`commit={save}`.

**Spec amendment 14, found while writing this task:** the spec says a write refused with 401 "re-opens
the dialog with the reason instead of showing a bare error", and a single-shot `ask` cannot do that
without the caller knowing the error type. So `run` loops: a `KiraApiError` with `httpStatus === 401`
re-asks with the same `summary` and a `detail` that names the refusal, and every other failure — and
every cancel — still ends in one place. It is not a retry: nothing is remembered, each pass needs a
fresh keystroke, and the second attempt is a different write the human chose. Amendment 13 is what makes
401 the right thing to key on: a refused confirm secret is `unauthorized` 401, while a malformed body is
`config_error` 400 — so the loop re-asks exactly when the secret was the problem and shows the row note
when the request was.

The full row body is the four cells plus the key, health and probe actions:

```tsx
  return (
    <tr className={provider.enabled.effective ? undefined : "row-disabled"}>
      <td>
        <strong>{provider.name}</strong>
        <div className="muted mono">{provider.kind} · {provider.base_url}</div>
        <div className="muted mono">{provider.models.join(", ")}</div>
        {note && <div className="error">{note}</div>}
      </td>
      <td>
        <span className={provider.key_present ? "badge badge-ok" : "badge badge-none"}>
          {provider.key_present ? "key ok" : "no key"}
        </span>
        <div className="muted mono">{provider.key_ref}</div>
        <input
          aria-label={`new key ${provider.name}`}
          name={`key_${provider.name}`}
          type="password"
          value={draftKey}
          placeholder="paste a key"
          disabled={busy}
          onChange={(event) => setDraftKey(event.target.value)}
        />
        <div className="cell-actions">
          <button
            type="button"
            disabled={busy || draftKey.trim() === ""}
            onClick={() =>
              void run(
                `store a new key for ${provider.name}`,
                `PUT /v1/kira/providers/${provider.name}/key`,
                false,
                async (secret) => {
                  await client.putKey(provider.name, draftKey.trim(), secret);
                  setDraftKey("");
                },
              )
            }
          >
            {`store key ${provider.name}`}
          </button>
          <button
            type="button"
            disabled={busy || !provider.key_present}
            onClick={() =>
              void run(`forget the ${provider.name} key`, `DELETE /v1/kira/providers/${provider.name}/key`, true, (secret) =>
                client.deleteKey(provider.name, secret),
              )
            }
          >
            {`forget key ${provider.name}`}
          </button>
        </div>
      </td>
      <td>
        <label className="cell">
          <input
            aria-label={`enabled ${provider.name}`}
            name={`enabled_${provider.name}`}
            type="checkbox"
            checked={provider.enabled.effective}
            disabled={busy}
            onChange={(event) => save({ enabled: event.target.checked }, `${event.target.checked ? "turn" : "turn"} ${provider.name} ${event.target.checked ? "on" : "off"}`)}
          />
          <span className="mono">{show(provider.enabled.effective)}</span>
        </label>
        <Was state={provider.enabled} />
      </td>
      <NumberCell provider={provider.name} state={provider.priority} busy={busy} commit={save} label={`priority ${provider.name}`} />
      <td>
        <select
          aria-label={`tier ${provider.name}`}
          name={`tier_${provider.name}`}
          value={provider.tier.effective}
          disabled={busy}
          onChange={(event) => save({ tier: event.target.value }, `set ${provider.name} tier to ${event.target.value}`)}
        >
          <option value="fast">fast</option>
          <option value="powerful">powerful</option>
        </select>
        <Was state={provider.tier} />
      </td>
      <CapCell provider={provider.name} state={provider.monthly_cap} busy={busy} commit={save} />
      <td className="mono">{show(provider.spend_this_month)}</td>
      <td>
        <span>{provider.health.successes}✓ {provider.health.failures}✗</span>
        {provider.health.cooling_s > 0 ? (
          <>
            <div className="warn mono">cooling {provider.health.cooling_s}s — {provider.health.last_reason}</div>
            <button
              type="button"
              disabled={busy}
              onClick={() =>
                void run(
                  `clear the ${provider.name} cooldown`,
                  `DELETE /v1/kira/providers/${provider.name}/cooldown`,
                  false,
                  (secret) => client.clearCooldown(provider.name, secret),
                )
              }
            >
              {`clear cooldown ${provider.name}`}
            </button>
          </>
        ) : null}
        <button
          type="button"
          disabled={busy}
          onClick={() =>
            void run(
              `test ${provider.name}`,
              `POST /v1/kira/providers/${provider.name}/probe — spends about 8 tokens`,
              false,
              async (secret) => setProbe(await client.probe(provider.name, secret)),
            )
          }
        >
          {`test ${provider.name}`}
        </button>
        {probe && (
          <div className="mono probe-result" data-ok={probe.ok}>
            {probe.ok
              ? `${probe.model_count} models · ${probe.latency_ms}ms`
              : `failed: ${probe.error}`}
          </div>
        )}
      </td>
    </tr>
  );
```

Two details that are not cosmetic. The probe result is component state, not engine state: it is a
diagnostic about one click, so it must vanish on the next `reload` rather than be re-read from a table
that never stored it. And `store a new key` clears `draftKey` *inside* the action, after the PUT
succeeded — a refused write leaves the pasted value in the box so the human can fix the secret and
retry without pasting again.

The exported screen keeps Task 10's `useAsync` shell and adds one prop:

```tsx
export function ProvidersScreen({ client, onChanged }: { client: KiraClient; onChanged: () => void }) {
  const state = useAsync(() => client.providers(), []);
  // Both reads: the panel's own rows, and the chat sidebar's key/tier facts, which /v1/kira/health
  // now derives from the same merged view.
  const refresh = () => {
    state.refresh();
    onChanged();
  };
  ...
  <tbody>{body.providers.map((provider) => <Row key={provider.name} provider={provider} client={client} refresh={refresh} />)}</tbody>
```

and the closing paragraph loses the sentence that promised controls were still to come. Its final text
at the end of this task — Task 16 appends the enforcement sentence to it:

```tsx
      <p className="muted">
        Values shown are what the router uses right now. A dimmed <span className="mono">was …</span> line means a
        stored override; <span className="mono">name</span>, <span className="mono">kind</span>,
        <span className="mono">base_url</span> and the model list come only from
        <span className="mono">config.yaml</span>. For the cap, <span className="mono">0</span> means unlimited and
        <span className="mono">clear override</span> puts the <span className="mono">config.yaml</span> value back —
        they are different facts, so they are different buttons.
      </p>
```

- [ ] **Step 9: Mount the provider and hand the screens a re-read**

In `kira-chat/src/App.tsx`, import `ConfirmProvider` and wrap the whole shell (the sidebar's provider
list and the chat live beside the same client, so the dialog belongs above all of them):

```tsx
  return (
    <ConfirmProvider>
      <div className="shell">
        ...
      </div>
    </ConfirmProvider>
  );
```

and pass the existing `refresh` down where the route switch renders the two live screens:

```tsx
          {route === "providers" && <ProvidersScreen client={client} onChanged={voidRefresh} />}
          {route === "overview" && <OverviewScreen client={client} />}
```

with, next to the other `useCallback`s:

```tsx
  const voidRefresh = useCallback(() => {
    void refresh();
  }, [refresh]);
```

`OverviewScreen` takes no `onChanged` — it cannot change anything, and a prop it never calls is a
prop a future reader will wonder about.

- [ ] **Step 10: Style the dialog and the cells**

Append to `kira-chat/src/styles.css`:

```css
/* The confirm dialog: the only surface that asks for a secret, so it reads differently on purpose. */
.confirm-backdrop {
  position: fixed;
  inset: 0;
  display: grid;
  place-items: center;
  background: rgb(0 0 0 / 0.55);
  z-index: 20;
}
.confirm-card {
  width: min(30rem, 92vw);
  display: grid;
  gap: 0.6rem;
  padding: 1.1rem 1.2rem;
  border: 1px solid var(--line-strong);
  border-radius: 10px;
  background: var(--panel);
  box-shadow: 0 12px 32px rgb(0 0 0 / 0.45);
}
.confirm-card h3 {
  margin: 0;
  font-size: 1rem;
}
.confirm-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
}
button.danger {
  border-color: var(--bad);
  color: var(--bad);
}

/* Rows of controls keep their own spacing so the table does not march. */
.cell {
  display: flex;
  align-items: center;
  gap: 0.4rem;
}
.cell-actions {
  display: flex;
  gap: 0.35rem;
  flex-wrap: wrap;
  margin-top: 0.3rem;
}
.probe-result[data-ok="false"] {
  color: var(--bad);
}
```

Check `--line-strong`, `--panel` and `--bad` exist in the file's `:root` block before shipping; if one
is named differently, use that name — the variables are already the project's tokens and this task
must not add a fourth spelling of a colour.

- [ ] **Step 11: Run everything, both languages**

Run: `cd kira-chat && npm run check`
Expected: typecheck silent, all tests pass (16 new: 5 dialog, 4 api, 7 screen — `ProvidersScreen.test.tsx`
holds 7 because amendment 14's re-ask split one test into two), `vite build` succeeds.

Run: `cd kira-engine && .venv/Scripts/python.exe -m pytest -q`
Expected: `158 passed, 1 skipped` — unchanged from Task 13; this task touches no engine code.

Run: `node kira-contracts/check-drift.mjs`
Expected: unchanged OK.

- [ ] **Step 12: Grep the leak surfaces**

Run from `Kira/kira-chat`: `grep -rn "setItem\|localStorage\|sessionStorage" src/confirm.tsx src/api.ts src/screens/ProvidersScreen.tsx`
Expected: no matches. Those three files must never touch web storage; `App.tsx` does, for the base URL
and bearer token only, and that is the whole sanctioned use.

Run: `grep -rn "confirm_secret\|X-Kira-Confirm" src/`
Expected: `confirm.tsx` (the input), `api.ts` (the header), `api.test.ts` and
`ProvidersScreen.test.tsx` (the assertions), `fake-engine.ts` (the refusal). Anything else is a new
place for a secret to be readable.

- [ ] **Step 13: Checkpoint**

Run from `Kira/`: `cd kira-chat && npm run check && cd ../kira-engine && .venv/Scripts/python.exe -m pytest -q`

If git is initialised: `git add kira-chat/src && git commit -m "feat(chat): confirm dialog and live provider controls"`

**M11 halfway.** A human can now tune, key, probe and clear cooldowns from the browser. The budget
*cap* is storable but not yet enforced — the router ignores `monthly_cap` until Task 15 — so Task 16's
cards are honest only about what has been spent, never about what is left.

**Executed (2026-10-27).** Chat went 42 → 58 tests: 5 dialog, 4 api, 7 screen (Step 11's 16 new holds, and
`ProvidersScreen.test.tsx` carries 7 not 6 because amendment 14's re-ask is two facts — the dialog comes
back, and the second keystroke writes). `tsc --noEmit` silent, `vite build` green, engine untouched at
169 passed, 1 skipped (Step 11's `158` was Task 12's figure — amendment 61), drift gate unchanged at
`v2, 39 schemas, 5 chunk types, 9 chain events`.

Step 12's greps came back exactly as the task demands: no `setItem`/`localStorage`/`sessionStorage` in
`confirm.tsx`, `api.ts` or `screens/ProvidersScreen.tsx`, and `confirm_secret`/`X-Kira-Confirm` appear in
only the five files it names — `confirm.tsx` (the input), `api.ts` (the header), `api.test.ts` and
`ProvidersScreen.test.tsx` (the assertions), `fake-engine.ts` (the refusal). README's chat count line moved
42 → 58 in the same commit.

Five steps needed a decision rather than a transcription, and each is an amendment: 54 (the plan's
snippets type `/v1` by hand in the two files the namespace gate reads — both now interpolate
`API_PREFIX`, and the literal paths stay in the tests, where pinning the wire shape is the point), 55
(amendment 36's dead `was 100` assertion reappeared in a new file), 56 (the cap test clicked a button the
row correctly keeps disabled), 57 (a re-read unmounts the row, so it ate the probe answer — `run` takes a
`reread` flag and only the probe passes `false`, because `probe.py` commits no row and touches no ledger),
58 (Step 10's `--line-strong`, `.small` and `.sr` do not exist in this stylesheet), 59, 60.

Live pass for this surface, against a throwaway `--data-dir` plus `--backend memory` on port 8916 (the
sample config's four providers, no keys in that process's vault, directory deleted and port closed after):
the browser's Providers table renders every control; unchecking `enabled groq` opens the dialog, the first
keystroke is a wrong one, the engine answers 401, and the dialog **comes back with the refusal in its
detail line** — amendment 14 proven over real HTTP, not only against the fake. The input is empty when it
re-opens (nothing about the first attempt is kept), and the second keystroke writes: the row re-reads as
`off` with the dimmed `was on`, `GET /v1/kira/providers` reports `{'base': True, 'override': False,
'effective': False}`, and `GET /v1/models` drops groq from the catalogue the router serves — so a browser
toggle reaches the routing decision with no restart. Buttons the row has no business offering stay
disabled: `store key`/`forget key` with no key present, `set cap` with an empty box, `clear override` with
no override.

Two automation notes Task 20 should not mistake for app bugs: browser automation that sets `input.value`
directly never reaches React's `onChange`, so both gate and dialog fields have to be filled through the
native setter plus an `input` event (and `localStorage kira.token` is the only practical way past the
connect gate); and a synthesized click on a checkbox has to be the element's own `.click()`. Neither is a
Kira defect — the jsdom tests drive real events and pass. What is still unexercised by any harness: an SSE
turn in a browser, and the key/probe buttons with a real provider key.

## Task 15: The router enforces the monthly cap

Tasks 4, 6 and 8 each put one piece of the budget in place — `monthly_cap` on the merged view,
`usage_for_month()` deriving spend from stored rows, `BudgetExhausted` and `skipped_budget` published
in contract v2. Nothing yet *reads* the cap when deciding where a turn goes. This task is that gate
and nothing else: no new endpoint, no schema, no contract change, no client change.

**Amendment 7, verbatim, because the ordering is the whole task:**

> A provider that is both over cap and cooling is reported over cap (budget checked before the ledger
> filter, per spec). A candidate list emptied *before* the budget check (e.g. every provider missing a
> key) stays `providers_exhausted`; `budget_exhausted` requires at least one candidate to have reached
> the budget check and every one of those to have been dropped there.

So `plan()` filters in this order, and the order is a claim about which fact the owner can act on:

`mode` (enabled) → `model` → **key** → **budget** → **cooldown** → attempt

A cooled provider is a five-second problem. An over-cap provider is a "raise the cap or wait for the
calendar" problem. Reporting the cooldown beside the cap would hide the only actionable fact, which is
why the budget loop sits before `self.ledger.available()` and why the refusal is raised there instead
of falling through to the exhaustion check.

**Files:**
- Modify: `kira-engine/src/kira/router.py` (the import block, `Router.__init__` as extended by Task 5 Step 3, and the region of `plan()` between the key loop and the ledger filter)
- Modify: `kira-engine/src/kira/app.py` (the `Router(...)` line from Task 5 Step 4; the `KiraError` handler at `app.py:144-149`; the `from .errors import` line at `app.py:21`)
- Create: `kira-engine/tests/test_budget.py`

**Interfaces:**
- Consumes: `EffectiveProvider.monthly_cap` (Task 4), `Store.usage_for_month()` (Task 6), `BudgetExhausted` and the `skipped_budget` event (Task 8), `HealthLedger.available()` as it already behaves.
- Produces: `Router.__init__(self, registry, ledger, *, view_source=None, spend_source=None)`, attribute `self.spend_source`. No argument means `lambda: (month_bounds()[0], {})` — a router built straight from `config.yaml` knows no spend, so every cap reads untouched and Task 5's YAML-only behaviour is preserved exactly.

**Four rules this gate must not blur:**

1. **`cap is None` means unlimited, and there is no "cap of zero" state to fear.** `build_view`
   normalises a `monthly_cap` override of `0` to `None` (Task 4), and `_optional_positive_int` maps a
   YAML `0` to `None`, so `used >= cap` can never stand a provider down by accident. The gate reads
   `monthly_cap`, never the raw override.
2. **One view, one spend map, per `plan()`.** Both are read at the top of the decision, so a dashboard
   write takes effect on the next turn without a restart and one turn can never see two different
   months. There is no cache to invalidate — same reason Task 12's responses come from a fresh view.
3. **A cap is a ceiling, not a preference.** `CUSTOM` naming an over-cap provider is *refused*, not
   quietly answered by someone else: the owner asked for that provider and the honest answer is that it
   is spent.
4. **At most one turn of slack.** Spend comes from stored rows and the plan is made before the turn
   starts, so the turn in flight is not counted and a tool turn runs every step from the same plan.
   Task 16's cards must therefore show `used` against `cap` and never promise "exactly N tokens left"
   while a turn is running.

One known thing, deliberately **not** this task's to fix: `Router.events()` re-yields `plan.notes` each
time the agent loop re-enters it, so a multi-step tool turn repeats its skip notes in the chain. That
predates the dashboard and applies to `skipped_cooling` and `skipped_missing_key` today; changing it
rewrites the expected chain of every tool test. Task 15 inherits it for `skipped_budget` and Task 20
records it as observed behaviour.

- [ ] **Step 1: Write the failing tests**

Create `kira-engine/tests/test_budget.py`:

```python
from __future__ import annotations

import time

import httpx
import pytest

from kira.errors import AllProvidersExhausted, BudgetExhausted
from kira.router import AttemptState
from kira.store import Store, month_bounds
from kira.types import GenRequest, Message
from conftest import ok, openai_text_chunks

USER = {"role": "user", "content": "hi"}

FAST_TIER = ("fast_one", "fast_two", "gem")


def req(model: str | None = None) -> GenRequest:
    return GenRequest(model=model or "mini", messages=[Message(role="user", content="q")])


async def drain(router, plan, request, state) -> list:
    events = []
    async for event in router.events(plan, request, state):
        events.append(event)
    return events


def spend(store: Store, provider: str, tokens: int, *, at: float | None = None) -> None:
    """One assistant row costing `tokens`. Raw SQL because `add_message` always stamps
    `time.time()`, and 'last month does not count' needs a timestamp in last month."""
    sid = store.create_session("AUTO")
    store._conn.execute(  # noqa: SLF001 - the gate is proved against timestamps a test controls
        """INSERT INTO messages(session_id, role, content, provider, model, status,
                                tool_calls, usage, chain, created_at)
           VALUES(?,'assistant','a',?,'mini','complete','[]',?,'[]',?)""",
        (sid, provider, f'{{"input_tokens": {tokens}, "output_tokens": 0}}',
         time.time() if at is None else at),
    )
    store._conn.commit()


def month() -> str:
    # Never a literal: the tests must hold whenever they run, including on the first of a month.
    return month_bounds()[0]


async def test_a_provider_exactly_at_its_cap_is_skipped_with_a_budget_note(harness):
    harness.store.set_setting("fast_one", "monthly_cap", 1000)
    spend(harness.store, "fast_one", 1000)
    plan = harness.engine.router.plan()
    assert "fast_one" not in {c.provider for c in plan.choices}
    assert [(n["provider"], n["reason"]) for n in plan.notes if n["event"] == "skipped_budget"] == [
        ("fast_one", f"used 1,000 of 1,000 tokens in {month()}")
    ]


async def test_one_token_under_the_cap_routes(harness):
    harness.store.set_setting("fast_one", "monthly_cap", 1000)
    spend(harness.store, "fast_one", 999)
    plan = harness.engine.router.plan()
    assert plan.choices[0].provider == "fast_one" and plan.notes == []


async def test_no_cap_means_no_ceiling(harness):
    # Rule 1: the harness config has no `monthly_token_cap` and no override row, so 5M tokens is a
    # number the router reads and ignores. An unlimited provider is `cap is None`, never a big int.
    spend(harness.store, "fast_one", 5_000_000)
    plan = harness.engine.router.plan()
    assert plan.choices[0].provider == "fast_one" and plan.notes == []


async def test_the_budget_note_reaches_the_chain_the_client_draws(harness):
    harness.store.set_setting("fast_one", "monthly_cap", 500)
    spend(harness.store, "fast_one", 500)
    harness.script.queue("fast2", ok(openai_text_chunks("yo")))
    state = AttemptState()
    await drain(harness.engine.router, harness.engine.router.plan(), req(), state)
    assert state.served_by == "fast_two"
    assert [c["event"] for c in state.chain] == ["skipped_budget", "attempt", "served"]
    assert [c["provider"] for c in state.chain] == ["fast_one", "fast_two", "fast_two"]


async def test_a_cooled_and_capped_provider_reports_the_cap(harness):
    # Amendment 7: two facts about one provider, and only one of them is actionable.
    harness.script.queue("fast1", httpx.Response(503, json={"error": {"message": "down"}}))
    harness.script.queue("fast2", ok(openai_text_chunks("back")))
    await drain(harness.engine.router, harness.engine.router.plan(), req(), AttemptState())
    harness.store.set_setting("fast_one", "monthly_cap", 100)
    spend(harness.store, "fast_one", 100)
    events = {n["event"] for n in harness.engine.router.plan().notes if n["provider"] == "fast_one"}
    assert events == {"skipped_budget"}, "the ledger does not get to explain a provider the cap stood down"


async def test_a_disabled_provider_is_gone_before_the_cap_is_asked(harness):
    harness.store.set_setting("fast_one", "enabled", False)
    harness.store.set_setting("fast_one", "monthly_cap", 10)
    spend(harness.store, "fast_one", 10)
    plan = harness.engine.router.plan()
    assert all(n["provider"] != "fast_one" for n in plan.notes), "it was already dropped; the cap is not why"


async def test_every_candidate_over_cap_is_a_budget_refusal(harness):
    for name in FAST_TIER:
        harness.store.set_setting(name, "monthly_cap", 200)
        spend(harness.store, name, 200)
    with pytest.raises(BudgetExhausted) as excinfo:
        harness.engine.router.plan(mode="FAST")
    assert excinfo.value.status == 429 and excinfo.value.retryable is False
    assert {n["provider"] for n in excinfo.value.chain} == set(FAST_TIER)


async def test_a_list_emptied_before_the_gate_is_not_blamed_on_the_cap(harness):
    # Amendment 7's other half. The caps are set so this test also fails if someone moves the budget
    # loop in front of the key filter: there these providers never reach it, so `budget_exhausted`
    # would be a lie about money when the truth is a missing key.
    for name in FAST_TIER:
        harness.vault.delete(f"provider/{name}")
        harness.store.set_setting(name, "monthly_cap", 1)
    with pytest.raises(AllProvidersExhausted) as excinfo:
        harness.engine.router.plan(mode="FAST")
    assert all(n["event"] != "skipped_budget" for n in excinfo.value.chain)


async def test_custom_mode_refuses_an_over_cap_provider_instead_of_answering_from_another(harness):
    harness.store.set_setting("big", "monthly_cap", 50)
    spend(harness.store, "big", 50)
    with pytest.raises(BudgetExhausted, match="big"):
        harness.engine.router.plan(mode="CUSTOM", provider="big")


async def test_the_gate_reads_spend_live_between_two_turns(harness):
    harness.store.set_setting("fast_one", "monthly_cap", 1000)
    spend(harness.store, "fast_one", 900)
    assert harness.engine.router.plan().choices[0].provider == "fast_one"
    spend(harness.store, "fast_one", 100)
    with pytest.raises(BudgetExhausted):
        harness.engine.router.plan(mode="CUSTOM", provider="fast_one")


async def test_last_months_spend_does_not_count_against_this_month(harness):
    _, start, _ = month_bounds()
    harness.store.set_setting("fast_one", "monthly_cap", 100)
    spend(harness.store, "fast_one", 5000, at=start - 3600)
    plan = harness.engine.router.plan()
    assert plan.choices[0].provider == "fast_one" and plan.notes == []


async def test_a_turn_that_never_finished_still_counts_against_the_cap(harness):
    # Derived, not accumulated: the tokens were billed whether or not the answer arrived, so an
    # interrupted turn is spend. A gate that counted only `complete` rows overspends on purpose.
    harness.store.set_setting("fast_one", "monthly_cap", 100)
    sid = harness.store.create_session("AUTO")
    harness.store.add_message(
        sid, "assistant", "partial", provider="fast_one", model="mini",
        status="interrupted", usage={"input_tokens": 60, "output_tokens": 40},
    )
    with pytest.raises(BudgetExhausted):
        harness.engine.router.plan(mode="CUSTOM", provider="fast_one")


async def test_mixed_causes_end_in_exhaustion_with_both_notes_visible(harness):
    # Two over cap, one cooling: the budget alone did not empty the list, so the honest error is
    # `providers_exhausted` - and its chain has to carry both reasons or the owner is guessing.
    harness.script.queue("fast2", httpx.Response(503, json={"error": {"message": "down"}}))
    with pytest.raises(AllProvidersExhausted):
        # The attempt loop ends in exhaustion; all this line wants is the cooldown it records.
        await drain(harness.engine.router, harness.engine.router.plan(mode="CUSTOM", provider="fast_two"), req(), AttemptState())
    for name in ("fast_one", "gem"):
        harness.store.set_setting(name, "monthly_cap", 100)
        spend(harness.store, name, 100)
    with pytest.raises(AllProvidersExhausted) as excinfo:
        harness.engine.router.plan(mode="FAST")
    assert {n["event"] for n in excinfo.value.chain} == {"skipped_budget", "skipped_cooling"}
    assert {n["provider"] for n in excinfo.value.chain if n["event"] == "skipped_budget"} == {"fast_one", "gem"}


async def test_the_api_answers_a_budget_refusal_with_429_and_the_chain(harness):
    for name in FAST_TIER:
        harness.store.set_setting(name, "monthly_cap", 10)
        spend(harness.store, name, 10)
    resp = await harness.api.post(
        "/v1/chat/completions", headers=harness.auth, json={"messages": [USER], "mode": "FAST"}
    )
    assert resp.status_code == 429
    body = resp.json()["error"]
    assert body["code"] == "budget_exhausted"
    assert body["status"] == 429 and body["retryable"] is False
    assert {r["provider"] for r in body["provider_chain"]} == set(FAST_TIER)
    assert {r["event"] for r in body["provider_chain"]} == {"skipped_budget"}


async def test_a_streaming_request_refused_on_budget_is_plain_json(harness):
    # `build_run` plans before the SSE opens, so a refusal is an ordinary error body - which is
    # exactly what `KiraClient.stream` turns into a `KiraApiError` (Task 14), not a broken stream.
    for name in FAST_TIER:
        harness.store.set_setting(name, "monthly_cap", 10)
        spend(harness.store, name, 10)
    resp = await harness.api.post(
        "/v1/chat/completions",
        headers=harness.auth,
        json={"messages": [USER], "mode": "FAST", "stream": True},
    )
    assert resp.status_code == 429
    assert "text/event-stream" not in resp.headers.get("content-type", "")
    assert resp.json()["error"]["code"] == "budget_exhausted"


async def test_a_refused_turn_stores_nothing(harness):
    for name in FAST_TIER:
        harness.store.set_setting(name, "monthly_cap", 10)
        spend(harness.store, name, 10)
    await harness.api.post(
        "/v1/chat/completions", headers=harness.auth, json={"messages": [USER], "mode": "FAST"}
    )
    assert harness.store.session_rows() == [], "the cap stops the turn before the question is filed"
```

`FAST_TIER` is spelled out once because five tests need "every candidate in `mode FAST`", and a list
that drifts from `conftest.provider_configs()` would make those tests pass for the wrong reason. The
three names are the whole fast tier in the harness config, so a fourth fast provider added later makes
`test_every_candidate_over_cap_is_a_budget_refusal` fail loudly instead of routing around an ungated
provider.

Those sixteen tests are the spec's `test_budget.py` bullet clause by clause: one UTC month and no
more, interrupted rows counting, a provider at cap skipped with the note in the chain, all-budget
yielding `BudgetExhausted` 429, mixed causes yielding `AllProvidersExhausted`, and budget evaluated
before cooldown. If one of them feels redundant while you write it, check the clause it carries before
deleting it.

- [ ] **Step 2: Run them to watch them fail**

Run: `cd kira-engine && .venv/Scripts/python.exe -m pytest -q tests/test_budget.py`
Expected: FAIL — `test_a_provider_exactly_at_its_cap...` and the routing tests because nothing is
skipped (fast_one still serves), and `test_the_api_answers...` with `KeyError: 'provider_chain'` if it
gets that far. The two API tests fail for the same reason as the plan tests: the cap is stored and
ignored.

- [ ] **Step 3: The gate**

In `router.py`, extend the import block (Task 5 already added `MergedView, build_view, enabled_providers`):

```python
from .errors import AllProvidersExhausted, BudgetExhausted, ConfigError, ProviderCallError
from .store import month_bounds
```

and give `__init__` the second source:

```python
    def __init__(
        self,
        registry: ProviderRegistry,
        ledger: HealthLedger,
        *,
        view_source: Callable[[], MergedView] | None = None,
        spend_source: Callable[[], tuple[str, dict[str, int]]] | None = None,
    ) -> None:
        self.registry = registry
        self.ledger = ledger
        # Without an override store this is exactly the YAML-only router every existing test built.
        self.view_source = view_source or (lambda: build_view(registry.config, None))
        # No store means no known spend, so every cap reads untouched: the same reasoning as above.
        self.spend_source = spend_source or (lambda: (month_bounds()[0], {}))
```

Then insert the gate between the key loop and the ledger filter. The `eligible_names` line is the
anchor — everything above it stays as Task 5 left it:

```python
        month, spent = self.spend_source()
        within: list[Choice] = []
        over_cap: list[Choice] = []
        for choice in choices:
            cap = view.by_name[choice.provider].monthly_cap
            used = spent.get(choice.provider, 0)
            if cap is not None and used >= cap:
                notes.append(
                    {
                        "provider": choice.provider,
                        "event": "skipped_budget",
                        "reason": f"used {used:,} of {cap:,} tokens in {month}",
                    }
                )
                over_cap.append(choice)
            else:
                within.append(choice)
        choices = within
        # Amendment 7: `budget_exhausted` only when candidates actually reached this check and all of
        # them were dropped here. A list emptied by the key filter above is a different story, and the
        # `if not choices` exhaustion below still tells it.
        if over_cap and not choices:
            names = ", ".join(choice.provider for choice in over_cap)
            raise BudgetExhausted(
                f"mode {chosen_mode}: over the monthly cap for {month} ({names}) - "
                "raise the cap in the dashboard or wait for the reset",
                chain=notes,
            )

        eligible_names = [c.provider for c in choices]
        available, skipped = self.ledger.available(eligible_names)
        notes.extend(skipped)
        choices = [c for c in choices if c.provider in available]
```

`over_cap and not choices` is the whole amendment: `over_cap` non-empty proves at least one candidate
reached the gate, and an empty remainder proves every one was dropped there. The reason text carries
the thousands separators and the month label because it is what the owner reads in the chain trace, and
`used:,` matches the shape Task 8's `ChainTrace` test already expects.

- [ ] **Step 4: Wire the engine's real spend into it**

In `app.py`, replace Task 5's router construction:

```python
        self.router = Router(
            self.registry,
            self.ledger,
            view_source=self.view,
            spend_source=self.store.usage_for_month,
        )
```

`usage_for_month()` takes an optional month and is called with none, so the router always gates against
the current calendar month — the same window the Overview and the Providers table price. It is one
grouped `SELECT` over the month's messages, run once per `plan()`, which is once per chat request; the
read endpoints never call it.

- [ ] **Step 5: Let the 429 carry its chain**

A refusal without the chain is a 429 that says "somebody is out of budget" and hides who. In `app.py`,
add `BudgetExhausted` to the `from .errors import` line at `:21` and widen the handler:

```python
    @app.exception_handler(KiraError)
    async def _kira_error_handler(_: Request, exc: KiraError) -> JSONResponse:
        content = exc.to_dict()
        # Both exhaustion classes carry the notes that explain themselves; the client draws them
        # as a chain instead of showing a bare status.
        if isinstance(exc, (AllProvidersExhausted, BudgetExhausted)):
            content["error"]["provider_chain"] = exc.chain
        return JSONResponse(status_code=exc.status, content=content)
```

- [ ] **Step 6: Run the suite**

Run: `cd kira-engine && .venv/Scripts/python.exe -m pytest -q tests/test_budget.py`
Expected: `16 passed`.

Run: `cd kira-engine && .venv/Scripts/python.exe -m pytest -q`
Expected: `174 passed, 1 skipped` (158 after Task 14 plus these 16). If a pre-existing routing test
breaks, the fallback order changed: without caps the gate is a no-op, so no old expectation should move.

- [ ] **Step 7: Prove nothing else moved**

Run: `cd kira-chat && npm run check`
Expected: all pass — unchanged from Task 14. This task touches no client code: `skipped_budget` already
has a label and a tone from Task 8, so `ChainTrace` can draw it, and a 429 already becomes a
`KiraApiError` in `api.stream`. Folding that refusal's `provider_chain` into the live turn — the part
that makes the chip actually appear in the chat — is Task 16's, not this task's.

Run from `Kira/`: `node kira-contracts/check-drift.mjs`
Expected: unchanged OK. The 429 response and the `skipped_budget` event were published in Task 8; a
drift complaint here would mean the gate's shape diverged from the contract that froze it, and the
contract is the one to trust.

- [ ] **Step 8: Why there is no hand proof in this task**

A `curl` demonstration of the refusal needs spend, spend needs a stored assistant row, and a stored row
needs a provider that actually answered — which a memory-vault engine cannot have, because the key
lives in another process. Rather than write a bogus key into the real Credential Locker or fire a
request at a real provider, the refusal is proved at the HTTP layer by Step 1's last three tests, which
go through the same ASGI app `serve` mounts. The visible version — cap it, chat, watch the chain say
"over budget" — belongs to Task 20's mock-provider browser pass, where the provider is scripted and the
money is fake.

- [ ] **Step 9: Checkpoint**

Run from `Kira/`: `cd kira-engine && .venv/Scripts/python.exe -m pytest -q && cd ../kira-chat && npm run check`

If git is initialised: `git add kira-engine/src/kira/router.py kira-engine/src/kira/app.py kira-engine/tests/test_budget.py && git commit -m "feat(engine): router enforces the monthly cap"`

The cap is now a fact about routing, not a number in a table. Task 16 makes it read back where it bites:
the Overview names the providers the router stood down and points at the one screen where a cap is
raised, a refusal in the chat becomes a link instead of a sentence, and the two languages' agreement
about the event's name gets a machine check.

**Executed (2026-10-27).** Step 2 printed `11 failed, 5 passed`, and the five that passed without the gate
are the ones that assert a cap does *not* bite (no cap, one under, disabled first, last month's spend, a
list emptied by the key filter) — the right shape of failure. After Steps 3-5: `16 passed` for the file and
**185 passed, 1 skipped** for the engine, not Step 6's 174 (amendment 62); chat stayed 58 and
`kira-contracts OK — v2, 39 schemas, 5 chunk types, 9 chain events` moved by nothing, which is the point —
the gate had to match the event name and reason shape Task 8 froze.

One test needed rewriting rather than an implementation change (amendment 63): `spend()` files a session per
row, so the quoted `session_rows() == []` was false before the request existed. The replacement snapshots the
session ids, asserts the 429, and asserts the id set is unchanged — it still fails if a refused turn ever
starts filing, which is the clause the spec actually cares about.

Confirmed by reading the code rather than the plan: `build_run` (`app.py:296-298`) calls `engine.router.plan()`
before `create_session`, which is why a refusal stores nothing, and `Store.usage_for_month()` returns
`(label, {provider: tokens})` — exactly the `spend_source` shape, so no adapter was needed. Rule 4 is now
load-bearing behaviour, not prose: the gate reads the store at plan time, so the turn in flight is never in
the number.

No hand proof, per Step 8.

---

# M11 close-out: the budget is visible, actionable, and agreed across both languages

## Task 16: The cap reads back where it bites

Task 15 made the cap a routing fact. Nothing on any screen yet said so in words a non-engineer could
act on, and two pieces of the read path are actively wrong:

1. **The Overview promised something it cannot know.** Task 10's `BudgetBar` prints
   `{remaining} left`, and Task 15's rule 4 forbids exactly that: spend comes from stored rows and the
   plan is made before the turn starts, so the turn in flight is never in the number. A bar that reads
   "0 left" is true; a bar that reads "312 left" is a promise about a race.
2. **A refusal in the chat was a sentence with no door.** `send()`'s `catch` keeps
   `messageOf(error)` and drops `error.chain`, so the `skipped_budget` chip the spec's browser pass
   expects never appears for a JSON refusal, and there is no way to reach the screen that raises the cap.

**Spec amendment 15, found while writing this task:** Task 15's Step 7 said the client needs no change,
and it is half right — a 429 *does* become a `KiraApiError` in `api.stream` (`api.ts:49-57, 99`), and
`skipped_budget` *does* already have a label and a tone from Task 8. But the refusal's `provider_chain`
is carried on `KiraApiError.chain` (`kira-contracts/types.ts:96-99`) and the chat's `catch` never folds
it into the turn, so the chip cannot render. Folding it is this task's Step 4, and the spec's clause
"the chat renders a budget-exhausted turn with the message plus a link to `#/providers`" is Step 4's
other half.

**Files:**
- Modify: `kira-chat/src/turn.ts` (`Turn` gains `errorCode`, `applyChunk`'s `error` case fills it)
- Modify: `kira-chat/src/screens/ChatScreen.tsx` (the `catch` in `send()`, and the `<div className="error">` in the entry list)
- Modify: `kira-chat/src/screens/OverviewScreen.tsx` (`BudgetBar`, the `capped` block, the slack footnote)
- Modify: `kira-chat/src/screens/ProvidersScreen.tsx` (the enforcement sentence Task 14 left for this task)
- Modify: `kira-chat/src/styles.css` (`.at-cap`, `.small`, `.error a`)
- Modify: `kira-chat/src/turn.test.ts` (append 1), `kira-chat/src/App.test.tsx` (append 4), `kira-chat/src/screens/ProvidersScreen.test.tsx` (append 1)
- Modify: `kira-engine/tests/test_units.py` (append 2, imports `re` and `month_bounds`)

**Interfaces:**
- Consumes: `BudgetRow.remaining` (published by Task 8, produced by Task 9 as
  `None if cap is None else max(0, cap - spend)`, so `remaining === 0` is *exactly* the engine's own
  answer to the router's `used >= cap`), the `#/providers` route from Task 1, `KiraApiError.body.code`
  and `.chain` from `kira-contracts/types.ts:90-99`, `CHAIN_EVENTS` from `kira/contracts.py:20`,
  `Router.spend_source` from Task 15, and the `resolve_data_dir().parent` sibling-bundle idiom already
  used at `kira-engine/tests/test_units.py:166-172`.
- Produces: `Turn.errorCode: string | null`. Nothing downstream needs it — Task 18's transcript reads
  stored rows, which carry their own chain — so this is the last field the plan adds to a client type.

One rule governs the whole task: **the client never re-derives router arithmetic.** Every claim about
being over cap is keyed on `row.remaining === 0`, which is the engine's clamp, not on a `used / cap`
comparison the browser would have to get right on its own. Percentages stay for the bar width, because a
width is not a claim about routing.

- [ ] **Step 1: Write the failing client tests**

Append to `kira-chat/src/turn.test.ts`, inside the existing `describe("applyChunk")` block, before its
closing `});`:

```ts
  it("keeps the engine's code as a field, not only inside the message", () => {
    const turn = applyChunk(emptyTurn(), {
      type: "error",
      error: { code: "budget_exhausted", message: "over the monthly cap for 2026-10 (fast_one)", status: 429, retryable: false },
    } as unknown as ChatChunk);
    expect(turn.status).toBe("interrupted");
    expect(turn.error).toBe("budget_exhausted: over the monthly cap for 2026-10 (fast_one)");
    expect(turn.errorCode).toBe("budget_exhausted");
    expect(emptyTurn().errorCode).toBeNull();
  });
```

Append four tests to `kira-chat/src/App.test.tsx`, inside the `describe("App")` block. The file should
hold 9 tests coming in (4 on disk, +2 in Task 2, +1 in Task 8, +2 in Task 10 with the M9-placeholder test
rewritten in place rather than removed), so if `npx vitest run src/App.test.tsx` reports a different
number before this step, write the difference down instead of "fixing" the count.

```ts
  it("points a budget refusal at the screen that can raise the cap, and shows the chain", async () => {
    const engine = fakeEngine({
      models: MODELS,
      health: HEALTH,
      chatStatus: 429,
      chatJsonError: {
        code: "budget_exhausted",
        message: "mode auto: over the monthly cap for 2026-10 (groq) - raise the cap in the dashboard or wait for the reset",
        status: 429,
        retryable: false,
        provider_chain: [
          { provider: "groq", event: "skipped_budget", reason: "used 1,000,000 of 1,000,000 tokens in 2026-10" },
        ],
      },
    });
    connectedTo(engine);
    window.location.hash = "#/chat";
    render(<App />);
    await waitFor(() => expect(modelSelect().value).toBe("llama-3.3-70b-versatile"));
    fireEvent.change(screen.getByLabelText("message"), { target: { value: "hi Kira" } });
    fireEvent.click(screen.getByRole("button", { name: "send" }));

    const link = await screen.findByRole("link", { name: "raise a cap in Providers" });
    expect(link.getAttribute("href")).toBe("#/providers");
    expect(screen.getByText(/budget_exhausted: mode auto/)).toBeTruthy();
    // Amendment 15: the refusal's chain is part of the turn, so the chip the spec promises is real.
    expect(screen.getByText("over budget")).toBeTruthy();
  });

  it("does not offer a cap link for a refusal that is not about money", async () => {
    const engine = fakeEngine({
      models: MODELS,
      health: HEALTH,
      chatStatus: 503,
      chatJsonError: {
        code: "providers_exhausted",
        message: "mode auto: every provider was filtered out before the request",
        status: 503,
        retryable: false,
      },
    });
    connectedTo(engine);
    window.location.hash = "#/chat";
    render(<App />);
    await waitFor(() => expect(modelSelect().value).toBe("llama-3.3-70b-versatile"));
    fireEvent.change(screen.getByLabelText("message"), { target: { value: "hi Kira" } });
    fireEvent.click(screen.getByRole("button", { name: "send" }));

    expect(await screen.findByText(/providers_exhausted: every provider was filtered out/)).toBeTruthy();
    expect(screen.queryByRole("link", { name: "raise a cap in Providers" })).toBeNull();
  });

  it("names the providers the router stood down, and stops promising tokens", async () => {
    const engine = fakeEngine({
      models: MODELS,
      health: HEALTH,
      overview: {
        month: "2026-10",
        turns: 40,
        tokens: { input: 12000, output: 4800 },
        success_rate: 0.925,
        interrupted: 1,
        failed: 2,
        by_provider: [{ provider: "groq", turns: 38, tokens: 1000000 }],
        by_model: [{ provider: "groq", model: "llama-3.3-70b-versatile", turns: 38, tokens: 1000000 }],
        daily: [{ date: "2026-10-01", turns: 20, tokens: 9000 }],
        budgets: [
          { provider: "groq", cap: 1000000, used: 1000000, remaining: 0 },
          { provider: "openrouter", cap: null, used: 0, remaining: null },
        ],
        recent_issues: [],
      },
    });
    connectedTo(engine);
    window.location.hash = "#/overview";
    render(<App />);

    expect(await screen.findByText(/used all of 2026-10's cap/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "raise a cap in Providers" }).getAttribute("href")).toBe("#/providers");
    expect(screen.getByText("1,000,000 / 1,000,000 · at cap")).toBeTruthy();
    // Task 15 rule 4: "N left" is a promise the engine cannot keep while a turn is running.
    expect(screen.queryByText(/[\d,]+ left/)).toBeNull();
    expect(screen.getByText(/Counted from stored turns/)).toBeTruthy();
  });

  it("says nothing about caps when the month still has room", async () => {
    const engine = fakeEngine({ models: MODELS, health: HEALTH });
    connectedTo(engine);
    window.location.hash = "#/overview";
    render(<App />);

    expect(await screen.findByText(/250,000 \/ 1,000,000/)).toBeTruthy();
    expect(screen.queryByRole("link", { name: "raise a cap in Providers" })).toBeNull();
    expect(screen.queryByText(/at cap/)).toBeNull();
  });
```

The last two tests are the only reason Step 1 comes first: the fourth one drives
`fakeEngine`'s default `overviewFixture()` (groq at 250,000 of 1,000,000, openrouter unlimited) and
asserts the *absence* of the new copy, which is what keeps a month with room from shouting.

Append one test to `kira-chat/src/screens/ProvidersScreen.test.tsx`, inside
`describe("ProvidersScreen writes")`, using that file's existing `renderScreen` and `providersFixture`:

```ts
  it("says plainly that the cap it edits is the cap the router obeys", async () => {
    const engine = fakeEngine({ providers: providersFixture() });
    renderScreen(engine);
    expect(await screen.findByText(/the router reads it before the health ledger/)).toBeTruthy();
    expect(screen.getByText(/the turn in flight is not in it yet/)).toBeTruthy();
  });
```

- [ ] **Step 2: Run them to watch the right ones fail**

Run: `cd kira-chat && npx vitest run src/turn.test.ts src/App.test.tsx src/screens/ProvidersScreen.test.tsx`
Expected: 4 failures — `expected undefined to be 'budget_exhausted'` in `turn.test.ts`, the
`findByRole("link", …)` and `findByText(/used all of/)` waits, and the Providers sentence wait. Two of
the six new tests pass before any code changes and must stay passing: the `providers_exhausted` test is
the guard that stops Step 4 from linking every refusal, and the "month still has room" test is the guard
that stops Step 5 from painting a call-to-action on an uncapped month. They were written first for that
reason, not by accident.

- [ ] **Step 3: Give `Turn` the code**

In `kira-chat/src/turn.ts`, add the field to the interface immediately after `error`, add
`errorCode: null` to `emptyTurn()` in the same position, and fill it in `applyChunk`'s `error` case:

```ts
export interface Turn {
  text: string;
  chain: ChainRecord[];
  toolCalls: ToolCallWire[];
  provider: string | null;
  model: string | null;
  usage: WireUsage | null;
  status: TurnStatus | "streaming";
  error: string | null;
  errorCode: string | null;
  sessionId: string | null;
}
```

```ts
    case "error":
      return {
        ...turn,
        status: "interrupted",
        error: `${chunk.error.code}: ${chunk.error.message}`,
        errorCode: chunk.error.code,
        chain: chunk.provider_chain?.length ? chunk.provider_chain : turn.chain,
      };
```

`Turn`'s own fields are camelCase (`toolCalls`, `sessionId`), so `errorCode` follows the file rather than
the wire. `emptyTurn()` is the only `Turn` literal in the bundle, which is why the field is required
instead of optional: a missing code would then mean "some screen forgot to fill it in", and the link is
rendered on the strength of that value.

- [ ] **Step 4: Let the chat keep a refusal's chain and open a door**

In `kira-chat/src/screens/ChatScreen.tsx`, add the class import next to the existing contracts import (it
is a value used with `instanceof`, so it cannot join the `import type { … }` line):

```tsx
import { KiraApiError } from "../contracts.ts";
```

Replace the two-line `catch` in `send()` — today it reads
`if (!turn.error) turn = { ...turn, status: "interrupted", error: messageOf(error) };` — with:

```tsx
      } catch (error) {
        if (!turn.error) {
          const refusal = error instanceof KiraApiError ? error : null;
          turn = {
            ...turn,
            status: "interrupted",
            error: messageOf(error),
            errorCode: refusal?.body.code ?? null,
            chain: refusal && refusal.chain.length > 0 ? refusal.chain : turn.chain,
          };
        }
      }
```

`refusal.chain` is the getter over `body.provider_chain`, so one fold covers a JSON 429 and a mid-stream
`error` frame even though `api.stream` throws on both (`api.ts:113`). An abort is neither: it has no code
and no chain, so it keeps whatever partial chain arrived before Stop and shows no link.

In the entry list, where Task 2 moved `<div className="error">{entry.turn.error}</div>`, render the door:

```tsx
                  {entry.turn.error && (
                    <div className="error">
                      {entry.turn.error}
                      {entry.turn.errorCode === "budget_exhausted" && (
                        <a href="#/providers">raise a cap in Providers</a>
                      )}
                    </div>
                  )}
```

An anchor rather than `onClick={() => navigate("providers")}` on purpose: the spec asks for a *link*,
`#/providers` is already the deep-link form the shell reads, and a real anchor can be copied,
middle-clicked or left alone. The hash change reaches the shell through Task 1's `onRoute` subscription,
so no prop and no callback cross into `ChatScreen`. The live (streaming) pane stays as Task 2 left it — a
plan-time refusal never appears there, because `finally` files the turn into `entries` before the pane is
next rendered.

- [ ] **Step 5: Make the Overview's bars honest and actionable**

In `kira-chat/src/screens/OverviewScreen.tsx`, replace `BudgetBar`'s capped branch (the block that
computes `pct` and returns the `bar` div) with:

```tsx
  const pct = Math.min(100, (row.used / row.cap) * 100);
  // `remaining` is the engine's own clamp, so `remaining === 0` is exactly the state the router acts
  // on. Anything above zero is not a countdown: the turn in flight is not counted (Task 15, rule 4).
  const atCap = row.remaining === 0;
  return (
    <div className="budget">
      <span className="mono">{row.provider}</span>
      <div
        className={`bar ${atCap ? "bar-over" : pct > 80 ? "bar-high" : ""}`}
        aria-label={atCap ? `${row.provider} is at its monthly cap` : `${row.provider} used ${Math.round(pct)}% of its cap`}
      >
        <span className="bar-used" style={{ width: `${pct}%` }} />
        <span className="bar-label">
          {num(row.used)} / {num(row.cap)}
          {atCap ? " · at cap" : ""}
        </span>
      </div>
    </div>
  );
```

`bar-over` is Task 10's existing rule; driving it from `atCap` instead of `pct >= 100` keeps one class,
one meaning and no dead selector, and a new `.bar-at-cap` is deliberately **not** added. The unlimited
branch above this one does not change — `row.cap === null` has no `remaining` to compare and already reads
"no cap".

Next to `const served = view.turns - view.interrupted - view.failed;` add:

```tsx
  const capped = view.budgets.filter((row) => row.remaining === 0);
```

and replace the `<h3>Budgets</h3>` + `view.budgets.map(…)` block with:

```tsx
          <h3>Budgets</h3>
          {view.budgets.map((row) => (
            <BudgetBar key={row.provider} row={row} />
          ))}
          {capped.length > 0 ? (
            <p className="at-cap">
              <strong>{capped.map((row) => row.provider).join(", ")}</strong>{" "}
              {capped.length === 1 ? "has" : "have"} used all of {view.month}'s cap, so no turn will route
              through {capped.length === 1 ? "it" : "them"} until the cap is raised or the month resets.{" "}
              <a href="#/providers">raise a cap in Providers</a>
            </p>
          ) : null}
          <p className="muted small">
            Counted from stored turns, so the one in flight is not in these numbers yet — a bar can sit just
            under a cap the router is about to reach.
          </p>
```

The sentence is written to stay true for a *disabled* provider that is also at cap, which `BudgetRow`
cannot distinguish: Task 9's `/v1/kira/overview` includes disabled providers (`test_overview_budgets_include_disabled_providers`)
and the schema carries no `enabled` field, and adding one would reopen a contract Task 8 froze. "No turn
will route through it" holds both for a provider the router stood down and for one the owner switched off —
cap and switch share the outcome even when they do not share the reason — and the link goes to Providers,
where both controls live.

- [ ] **Step 6: The Providers sentence Task 14 left here**

Replace the closing `<p className="muted">…</p>` of `kira-chat/src/screens/ProvidersScreen.tsx` — the one
Step 8 of that task wrote, ending "they are different facts, so they are different buttons." — with the
same text plus the enforcement sentences:

```tsx
      <p className="muted">
        Values shown are what the router uses right now. A dimmed <span className="mono">was …</span> line means a
        stored override; <span className="mono">name</span>, <span className="mono">kind</span>,
        <span className="mono">base_url</span> and the model list come only from
        <span className="mono">config.yaml</span>. For the cap, <span className="mono">0</span> means unlimited and
        <span className="mono">clear override</span> puts the <span className="mono">config.yaml</span> value back —
        they are different facts, so they are different buttons.
        It is a limit, not a label: the router reads it before the health ledger, so a provider at its cap is stood
        down for the rest of the month and a mode whose every candidate is at its cap answers
        <span className="mono"> budget_exhausted</span> instead of an answer. The spend column counts stored turns, so
        the turn in flight is not in it yet.
      </p>
```

"before the health ledger" is amendment 7 in ordinary words. It is the only place in the UI that explains
the ordering, and the ordering is why one provider can read as capped in three places at once — this
column, the Overview bar, the chain chip — and never contradict itself.

- [ ] **Step 7: Styles**

Append to `kira-chat/src/styles.css`:

```css
/* budget read-back (Task 16) */
.at-cap {
  margin: 0.7rem 0 0;
  padding: 0.5rem 0.7rem;
  border-left: 3px solid var(--warn);
  background: color-mix(in srgb, var(--warn) 14%, transparent);
  color: var(--text);
}
.small {
  font-size: 0.75rem;
}
.error a {
  margin-left: 0.5rem;
  color: var(--accent);
}
```

`--warn`, `--text` and `--accent` are in the file's `:root` today and `color-mix` is already used by
Task 10's `.bar-over`, so this adds no colour and no technique. `.small` lands here because Task 14's
dialog markup puts `className="muted small"` on a paragraph that no rule defines; the dangling class is
repaired at the same time as the one that needs it.

- [ ] **Step 8: Run the client suite**

Run: `cd kira-chat && npx vitest run src/turn.test.ts`
Expected: `7 passed` (6 on disk, +1).

Run: `cd kira-chat && npx vitest run src/App.test.tsx`
Expected: `13 passed` (9 coming in, +4).

Run: `cd kira-chat && npx vitest run src/screens/ProvidersScreen.test.tsx`
Expected: `8 passed` (Task 14's 7, +1).

Run: `cd kira-chat && npm run check`
Expected: typecheck silent — the new required `errorCode` field is the only type change, and
`emptyTurn()` is its only constructor — all tests pass, `vite build` succeeds.

- [ ] **Step 9: The engine-side agreement the spec asked for**

The spec's `test_units.py` clause is that `skipped_budget` is published in `CHAIN_EVENTS` *and* is the
event an over-cap provider actually produces, so the two cannot drift apart. Python is the only place
both halves are visible: `CHAIN_EVENTS` lives in `kira/contracts.py:20`, the note string is written in
`router.py`, and the chip label lives two packages away in
`kira-chat/src/components/ChainTrace.tsx`. `check-drift.mjs` compares the two TypeScript artifacts against
`contract.json`; it cannot see the router, and vitest cannot see `contracts.py`.

In `kira-engine/tests/test_units.py`, add `import re` above the existing `import pytest`, extend the store
import to `from kira.store import Store, month_bounds`, and append:

```python
def test_an_over_cap_provider_is_stood_down_with_a_published_event_name(harness):
    # Task 15's own file proves the arithmetic; this proves the *name*: the event the router writes is
    # one of the events the contract publishes, so a rename cannot leave the client falling through to
    # `LABELS[record.event] ?? record.event` while every budget test still passes.
    from kira.contracts import CHAIN_EVENTS

    harness.store.set_setting("fast_one", "monthly_cap", 1_000)
    harness.engine.router.spend_source = lambda: (month_bounds()[0], {"fast_one": 1_000})
    notes = [n for n in harness.engine.router.plan(mode="FAST").notes if n["provider"] == "fast_one"]
    assert [n["event"] for n in notes] == ["skipped_budget"]
    assert {n["event"] for n in notes} <= set(CHAIN_EVENTS)


def test_every_published_chain_event_has_a_label_in_the_chat_bundle(monkeypatch):
    # An unlabelled event still renders — as a chip of snake_case jargon. This is the only check that
    # catches that before a human sees it.
    from kira.contracts import CHAIN_EVENTS

    monkeypatch.delenv("KIRA_DATA_DIR", raising=False)
    trace = resolve_data_dir().parent / "kira-chat" / "src" / "components" / "ChainTrace.tsx"
    assert trace.is_file(), f"the chat bundle must sit beside the engine: {trace}"
    block = trace.read_text(encoding="utf-8").split("const LABELS: Record<string, string> = {", 1)[1]
    block = block.split("};", 1)[0]
    labelled = set(re.findall(r"^  (\w+):", block, re.MULTILINE))
    assert labelled == set(CHAIN_EVENTS)
```

FAST is the mode to write: `fast_one`, `fast_two` and `gem` are the tier-`fast` candidates, so standing
`fast_one` down leaves two choices and the turn routes instead of raising — this test wants a `plan()`
that *returns notes*, which is the opposite of Task 15's refusal tests. Overriding `router.spend_source`
instead of inserting rows is what keeps it a unit test: the name is the subject here, not the query that
produces the number. `TONE` is deliberately unchecked — an event with no tone renders `neutral`, which is
a colour preference, not a blank chip.

- [ ] **Step 10: Prove the guards bite**

Neither engine test can be shown red-first, because Task 8 shipped both halves of the agreement already.
Prove them by mutation instead, and revert immediately.

In `kira-engine/src/kira/router.py`, change the budget note's `"event": "skipped_budget"` to
`"event": "over_cap"`, run
`cd kira-engine && .venv/Scripts/python.exe -m pytest tests/test_units.py -q -k over_cap_provider_is_stood_down`,
and expect one failure naming `over_cap`. Put the line back, then run
`grep -c '"skipped_budget"' kira-engine/src/kira/router.py` from `Kira/` and expect `1`.

In `kira-chat/src/components/ChainTrace.tsx`, change `skipped_budget: "over budget",` to
`skipped_budgett: "over budget",`, run
`cd kira-engine && .venv/Scripts/python.exe -m pytest tests/test_units.py -q -k label_in_the_chat_bundle`,
and expect one failure whose diff is a one-element set difference. Put it back, then run
`grep -c skipped_budget kira-chat/src/components/ChainTrace.tsx` from `Kira/` and expect `2`, because
Task 8 wrote the key into `LABELS` and `TONE` and both must be present.

If the mutation instead stays green, stop and read the guard: it means it is asserting something the
code cannot influence, and a test that cannot fail is worse here than no test, because the spec's
acceptance line would be signed off by it.

- [ ] **Step 11: Run everything, both languages**

Run from `Kira/`: `cd kira-engine && .venv/Scripts/python.exe -m pytest -q && cd ../kira-chat && npm run check`
Expected: engine `176 passed, 1 skipped` (174 after Task 15, +2 here); chat all green and build succeeds.

Run from `Kira/`: `node kira-contracts/check-drift.mjs`
Expected: unchanged OK — `skipped_budget` joined `CHAIN_EVENTS` in Task 8, and this task adds no schema,
no event and no path.

Run from `Kira/kira-chat`: `grep -rn "setItem\|localStorage\|sessionStorage" src/turn.ts src/screens/OverviewScreen.tsx`
Expected: no matches. A refusal's code and chain belong to the turn in memory; `errorCode` must never
become a way to carry a provider's name into web storage.

- [ ] **Step 12: Why there is still no hand proof**

The same reason as Task 15's Step 8: a real at-cap refusal needs a stored assistant row, and a stored row
needs a provider that answered. Step 1's Overview and chat tests are the proof of the *words*, Step 9's
two engine tests are the proof of the *agreement*, and the one browser pass that stitches them — set a
cap, send, watch the chain chip and the Providers column and the Overview bar say the same thing three
ways — is Task 20's, against a scripted provider with fake money.

- [ ] **Step 13: Checkpoint**

If git is initialised: `git add kira-chat/src kira-engine/tests/test_units.py && git commit -m "feat(chat): the monthly cap reads back in the UI and is guarded across both languages"`

The budget is now a closed loop: the dashboard writes a cap, the router obeys it, and three surfaces
report the same fact with one name. Task 17 builds the last screen that has no write path at all — the
Models panel, where every row ends with a sentence about `config.yaml`.

**Executed (2026-10-28).** Step 2 first printed **5** failures, not 4, because the `providers_exhausted`
guard asserted a string the client cannot produce (amendment 65); after that one regex was corrected it
printed the planned 4 with both guards green, which is the shape the step asked for. Then: `31 passed`
across the three touched files, `7` in `turn.test.ts`, `16` in `App.test.tsx` (amendment 67), `8` in
`ProvidersScreen.test.tsx`; chat `64 passed (64)` with typecheck silent and the build stamped; engine
`187 passed, 1 skipped`; drift unchanged at `v2, 39 schemas, 5 chunk types, 9 chain events`; the web-storage
grep found nothing in `turn.ts` or `OverviewScreen.tsx`.

Step 10's mutations both bit, and reverting them is what the two greps below prove:
`grep -c '"skipped_budget"' kira-engine/src/kira/router.py` → `1` and
`grep -c skipped_budget kira-chat/src/components/ChainTrace.tsx` → `2` (LABELS and TONE). The first failure
read `assert ['over_cap'] == ['skipped_budget']`; the second was the predicted one-element set difference,
`skipped_budgett` extra on the left, `skipped_budget` missing on the right. Neither file was left touched —
`git checkout --` reverted each immediately, and `git status` showed clean for both afterwards.

The `{remaining} left` clause is gone from the bar, so the Overview now states the ratio and the clamped
fact (`· at cap`) and nothing else; `row.remaining === 0` is the only over-cap test in the client, exactly
as the one rule at the head of this task requires. Task 15's rule 4 is visible in the footnote under the
bars rather than only in a plan document.

No hand proof, per Step 12 — the scripted-provider browser pass in Task 20 is where the chip, the bar and
the Providers column get compared with real clicks.

---

# M12 — The last two screens, the documentation, and the live pass

The spec's M12 bundles three things that only make sense together: the Models and Sessions screens
(Tasks 17 and 18), the README section that describes them (Task 19), and the browser pass that proves
the whole surface against a running engine (Task 20). Its acceptance is "all five screens usable
against a real engine; docs match behaviour", and "docs match behaviour" is why Task 19 ends with a
test rather than a proofread.

## Task 17: The Models screen — what is configured, and what it cost

**Files:**
- Create: `kira-chat/src/screens/ModelsScreen.tsx`
- Create: `kira-chat/src/screens/ModelsScreen.test.tsx` (6)
- Modify: `kira-chat/src/App.tsx` (the `models` branch of the route switch, one `useInChat` handler)
- Modify: `kira-chat/src/App.test.tsx` (append 1, rewrite Task 10's "not built yet" test)
- Modify: `kira-chat/src/styles.css` (append the retired-row marker)

**Interfaces:**
- Consumes: `ModelInfo {id, object, owned_by, provider, tier}` (`kira-contracts/types.ts:119-125`), built
  by `app.py:226` where `owned_by` and `provider` are both `provider.name`; `client.overview()` with no
  month (Task 9/10 — it defaults to the current UTC month); `OverviewResponse.by_model`
  (`ModelUsage[]`, Task 6's SQL at `store.py` `overview()`); `useAsync` (Task 10); `navigate("chat")`
  (Task 1); App's existing `models`, `model`, `setModel` state.
- Produces: `ModelsScreen({ client, models, onUse })` and `useInChat(id: string)` in App. Nothing later
  consumes either; Task 18 is the Sessions screen and reads different endpoints.

There is no engine work in this task, and that is the point: `/v1/models` and `/v1/kira/overview`
already answer every column the spec asks for (model, provider, tier, times served this month). Adding a
`/v1/kira/models` endpoint would create a third place to keep the same rows.

**Two facts about the join, because the screen is a join and not a list:**

1. `by_model.turns` counts every stored assistant row that names a provider — including `interrupted` and
   `failed` ones (Task 6's SQL has no `status` predicate, for the same reason Task 15 counts a turn that
   never finished against the cap: it spent tokens either way). So the column is "turns that name this
   model", and the footnote says so rather than printing "served".
2. The stored model name is `run.attempt.served_model` — what the provider answered with — while the
   configured name is the catalogue id from `config.yaml`. They are usually equal and sometimes not.

**Spec amendment 16, from fact 2:** a `by_model` row with no matching configured row is *shown*, marked
`no longer configured`, with no "use in chat" button. Dropping it would make a month's history vanish
because a YAML edit renamed a model, which is the failure mode `orphan_settings` was added for in Task 4
— the engine reports what it has that the config does not. Conversely a configured model that nobody
used this month still appears, with `0`, because "not used" is a fact about the month, not about the
config.

**Spec amendment 17:** the spec's "each row states that plainly rather than faking an input" is
implemented as *no* editable cell anywhere in the table plus one sentence above it, because repeating
"editing `config.yaml` adds a model" on every row makes the numbers unreadable and the sentence is the
same for all of them. The acceptance test asserts the sentence is present and that the table contains no
`input` or `select` element, which is what "rather than faking an input" is actually testing.

- [ ] **Step 1: Write the failing screen tests**

Create `kira-chat/src/screens/ModelsScreen.test.tsx`:

```tsx
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { KiraClient } from "../api.ts";
import { fakeEngine, overviewFixture } from "../fake-engine.ts";
import { ModelsScreen } from "./ModelsScreen.tsx";

const MODELS = [
  { id: "llama-3.3-70b-versatile", object: "model", owned_by: "groq", provider: "groq", tier: "fast" },
  { id: "claude-sonnet-4-5", object: "model", owned_by: "anthropic", provider: "anthropic", tier: "powerful" },
];

function renderScreen(engine: ReturnType<typeof fakeEngine>, models = MODELS, onUse = vi.fn()) {
  render(
    <ModelsScreen
      client={new KiraClient({ baseUrl: "", token: "sekret", fetch: engine.fetch })}
      models={models}
      onUse={onUse}
    />,
  );
  return onUse;
}

describe("ModelsScreen", () => {
  it("lists every configured model with its tier and its month, including the unused one", async () => {
    const engine = fakeEngine({ overview: overviewFixture() });
    renderScreen(engine);
    expect(await screen.findByText("llama-3.3-70b-versatile")).toBeTruthy();
    expect(screen.getByText("claude-sonnet-4-5")).toBeTruthy();
    expect(screen.getByText("fast")).toBeTruthy();
    expect(screen.getByText("powerful")).toBeTruthy();
    // overviewFixture's by_model has one row: groq/llama-3.3-70b-versatile, 38 turns, 15,000 tokens.
    expect(screen.getByText("38")).toBeTruthy();
    expect(screen.getByText("15,000")).toBeTruthy();
    expect(screen.queryByText("no longer configured")).toBeNull();
  });

  it("shows the zero for a model that was not used, not a blank", async () => {
    const engine = fakeEngine({ overview: overviewFixture() });
    renderScreen(engine);
    await screen.findByText("claude-sonnet-4-5");
    const row = screen.getByRole("row", { name: /claude-sonnet-4-5/ });
    expect(within(row).getAllByText("0")).toHaveLength(2);
  });

  it("keeps a month's history when the config stopped naming the model", async () => {
    const engine = fakeEngine({
      overview: { ...overviewFixture(), by_model: [{ provider: "groq", model: "llama-3.1-8k", turns: 4, tokens: 900 }] },
    });
    renderScreen(engine);
    expect(await screen.findByText("llama-3.1-8k")).toBeTruthy();
    expect(screen.getByText("no longer configured")).toBeTruthy();
    expect(screen.getByText("4")).toBeTruthy();
    expect(screen.getByText("900")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "use in chat llama-3.1-8k" })).toBeNull();
    expect(screen.getByText("groq/llama-3.1-8k")).toBeTruthy();
  });

  it("offers one action and nothing else: use in chat", async () => {
    const engine = fakeEngine({ overview: overviewFixture() });
    const onUse = renderScreen(engine);
    await screen.findByText("llama-3.3-70b-versatile");
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(document.querySelectorAll("table input, table select, table textarea")).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "use in chat llama-3.3-70b-versatile" }));
    expect(onUse).toHaveBeenCalledWith("llama-3.3-70b-versatile");
  });

  it("says the YAML sentence and states the counting rule", async () => {
    const engine = fakeEngine({ overview: overviewFixture() });
    renderScreen(engine);
    // Both patterns stay inside one text node. `config.yaml` is wrapped in a <span>, and testing-library
    // joins only an element's direct text children, so a pattern that ran up to the span would miss.
    expect(await screen.findByText(/Adding or renaming a model means editing/)).toBeTruthy();
    expect(screen.getByText(/interrupted and failed turns are in these numbers/)).toBeTruthy();
  });

  it("states empty and error as themselves", async () => {
    const empty = fakeEngine({ overview: { ...overviewFixture(), by_model: [] } });
    renderScreen(empty, []);
    expect(await screen.findByText(/nothing to route to/)).toBeTruthy();

    // A read that rejects, not a read that returns the wrong shape: the fake cannot fail `/v1/kira/overview`
    // with a non-2xx, and useAsync's error state is what a refused or unreachable engine produces.
    const rejects = { overview: async () => { throw new Error("engine went away"); } } as unknown as KiraClient;
    render(<ModelsScreen client={rejects} models={MODELS} onUse={vi.fn()} />);
    await waitFor(() => expect(screen.getByText(/cannot read this month/)).toBeTruthy());
    expect(screen.getByText("engine went away")).toBeTruthy();
  });
});
```

Six tests, and the last one is why `useAsync` was worth writing in Task 10: the screen has to say
"cannot read this month" plus the engine's own words, rather than rendering a table of `undefined`.
`getByRole("row", { name: … })` works because a row's accessible name is its text content; if that
matcher turns out to return several rows, narrow it with `within(screen.getByRole("table"))` rather than
reaching for `querySelector`. Note `KiraClient` is a value import here even though the screen file imports
it as `import type`: the test constructs one, and `verbatimModuleSyntax` is on, so the two spellings are
not interchangeable.

- [ ] **Step 2: The App test that "use in chat" really routes**

Append to `kira-chat/src/App.test.tsx` inside `describe("App")`:

```ts
  it("use in chat picks the model and moves to the chat pane", async () => {
    const engine = fakeEngine({ models: MODELS, health: HEALTH });
    connectedTo(engine);
    window.location.hash = "#/models";
    render(<App />);
    expect(await screen.findByText("claude-sonnet-4-5")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "use in chat claude-sonnet-4-5" }));
    await waitFor(() => expect(window.location.hash).toBe("#/chat"));
    expect(modelSelect().value).toBe("claude-sonnet-4-5");
  });
```

And rewrite the test Task 10 added, `"waits for the screens that are not built yet, by name"`, so it now
waits for one screen instead of two: keep the body, change the route to `#/sessions`, and change the
expected string to `Sessions screen arrives in M12.`. The `#/models` half of that test no longer has a
placeholder to assert, and Task 18 deletes the `COMING_SOON` map whole.

- [ ] **Step 3: Run them to watch them fail**

Run: `cd kira-chat && npx vitest run src/screens/ModelsScreen.test.tsx src/App.test.tsx`
Expected: `Failed to resolve import "./ModelsScreen.tsx"` for the new file; the App test fails at
`findByText("claude-sonnet-4-5")` because `#/models` still renders the placeholder.

- [ ] **Step 4: Write the screen**

Create `kira-chat/src/screens/ModelsScreen.tsx`:

```tsx
import type { KiraClient } from "../api.ts";
import type { ModelInfo, ModelUsage, OverviewResponse } from "../contracts.ts";
import { useAsync } from "../useAsync.ts";

function num(value: number): string {
  return value.toLocaleString("en-US");
}

function key(provider: string, model: string): string {
  return `${provider}/${model}`;
}

export function ModelsScreen({ client, models, onUse }: { client: KiraClient; models: ModelInfo[]; onUse: (id: string) => void }) {
  const state = useAsync(() => client.overview(), []);

  if (state.kind === "loading") return <section className="screen"><p className="muted">reading the month…</p></section>;
  if (state.kind === "error") {
    return (
      <section className="screen">
        <p className="error">cannot read this month: {String((state.error as Error).message ?? state.error)}</p>
      </section>
    );
  }
  const view: OverviewResponse = state.data;
  const usage = new Map<string, ModelUsage>(view.by_model.map((row) => [key(row.provider, row.model), row]));
  const configured = new Set(models.map((model) => key(model.provider, model.id)));
  // Amendment 16: whatever the month spent that the config no longer names still gets a row.
  const retired = view.by_model.filter((row) => !configured.has(key(row.provider, row.model)));

  if (models.length === 0 && retired.length === 0) {
    return (
      <section className="screen">
        <h2>Models</h2>
        <p className="empty">
          no models in <span className="mono">config.yaml</span> — nothing to route to. The engine reads its
          catalogue from that file; add a <span className="mono">models:</span> list under a provider and
          restart.
        </p>
      </section>
    );
  }


  return (
    <section className="screen">
      <header className="screen-head">
        <h2>Models</h2>
        <span className="spacer" />
        <button type="button" onClick={state.refresh}>reload</button>
      </header>

      <p className="muted">
        Adding or renaming a model means editing <span className="mono">config.yaml</span> and restarting the
        engine — there is no field here on purpose. What this table does know is what each one cost in{" "}
        <span className="mono">{view.month}</span>.
      </p>

      <table className="grid">
        <thead>
          <tr><th>model</th><th>provider</th><th>tier</th><th>turns</th><th>tokens</th><th>chat</th></tr>
        </thead>
        <tbody>
          {models.map((model) => {
            const row = usage.get(key(model.provider, model.id));
            return (
              <tr key={key(model.provider, model.id)}>
                <td className="mono">{model.id}</td>
                <td>{model.provider}</td>
                <td>{model.tier}</td>
                <td>{num(row?.turns ?? 0)}</td>
                <td>{num(row?.tokens ?? 0)}</td>
                <td>
                  <button type="button" onClick={() => onUse(model.id)}>
                    {`use in chat ${model.id}`}
                  </button>
                </td>
              </tr>
            );
          })}
          {retired.map((row) => (
            <tr key={key(row.provider, row.model)} className="row-retired">
              <td className="mono">
                {row.model}
                <div className="muted">no longer configured</div>
              </td>
              <td>{row.provider}</td>
              <td className="muted">—</td>
              <td>{num(row.turns)}</td>
              <td>{num(row.tokens)}</td>
              <td className="muted mono">{key(row.provider, row.model)}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <p className="muted small">
        Turn counts come from stored assistant rows, so interrupted and failed turns are in these numbers —
        they spent tokens too. A model that served this month is listed by the name the provider answered
        with, which is why a renamed entry can appear twice.
      </p>
    </section>
  );
}
```

`retired` is computed from `view.by_model` and never from a guess about why a name is missing, so the row
stays even when the cause is a provider that answered with a different id (`served_model`), not a deleted
config entry. The `—` in the tier cell is UI copy in a browser, so a non-ASCII em dash is right here; the
ASCII-only rule in this plan is about engine messages reaching a GBK console.

The `ModelUsage` in `Map<string, ModelUsage>` is not decoration: it names the join's value type where a
reader would otherwise have to work it out, and `noUnusedLocals` is **on** in `kira-chat/tsconfig.json`, so
the import has to be used by something. Importing the type and letting inference do the work would fail
`npm run check` with an unused-import error — which is the useful kind of failure, since it means the
annotation is what earns its place.

- [ ] **Step 5: Mount it, and give it the one action it has**

In `kira-chat/src/App.tsx`, drop `models` from the `COMING_SOON` map (leave `sessions`, which Task 18
removes), import `ModelsScreen`, and add the handler next to the other App-level actions:

```tsx
  function useInChat(id: string) {
    setModel(id);
    navigate("chat");
  }
```

and in the route switch, between the `overview` and `providers` branches:

```tsx
        ) : route === "models" ? (
          <ModelsScreen client={client} models={models} onUse={useInChat} />
```

`navigate("chat")` rather than setting the hash: Task 1's `navigate` notifies subscribers even when the
value is unchanged, which is what makes a second "use in chat" click from the chat pane behave. One
consequence to know before it looks like a bug: App's `refresh` callback lists `model` in its
dependencies, so changing the model re-reads `/v1/models`, `/v1/kira/health` and the session list. That is
how the chat's own model select already behaves; "use in chat" adds no new cost and must not be
"optimised" by removing the dependency, which would leave the sidebar stale after a provider toggle.

- [ ] **Step 6: Styles**

Append to `kira-chat/src/styles.css`:

```css
/* models screen (Task 17) */
.row-retired td {
  color: var(--muted);
}
.row-retired td:first-child {
  color: var(--text);
}
```

`.grid`, `.screen`, `.screen-head` and `.spacer` all exist from Tasks 10 and 14; this adds only the
retired-row dimming, with the model id kept at full contrast because it is the one fact the owner has to
type into `config.yaml`.

- [ ] **Step 7: Run the client suite**

Run: `cd kira-chat && npx vitest run src/screens/ModelsScreen.test.tsx`
Expected: `6 passed`.

Run: `cd kira-chat && npx vitest run src/App.test.tsx`
Expected: `14 passed` (13 after Task 16, +1 for "use in chat"; the rewritten "not built yet" test stays).

Run: `cd kira-chat && npm run check`
Expected: typecheck silent, all tests pass, `vite build` succeeds.

- [ ] **Step 8: Prove it by hand — this screen needs no keys**

Unlike Tasks 15 and 16, the Models screen reads only a catalogue and a count, so it can be shown for real
without a provider answering:

```
run-kira.bat
```
open `http://127.0.0.1:8901/` (the launcher serves the built bundle), go to `#/models`, and check three
things: every model in `config.yaml` is a row; the tier column matches the file; and every turns/tokens
cell reads `0` on a fresh data directory — which is the *correct* empty, not a failure. Click
"use in chat" on the second row and confirm the chat's model select shows that id and the hash is
`#/chat`. Then send one message on a provider that has a key: reload `#/models` and that model's row gains
a turn. Spend does not need a cap to be worth seeing.

If `Kira/.kira-data` holds turns from earlier sub-projects, the cells will not read `0`; that is the same
truth the Overview is showing, not a defect in this screen.

- [ ] **Step 9: Checkpoint**

Run from `Kira/`: `cd kira-engine && .venv/Scripts/python.exe -m pytest -q && cd ../kira-chat && npm run check && cd .. && node kira-contracts/check-drift.mjs`
Expected: engine `176 passed, 1 skipped` — unchanged, this task touches no engine code; chat all green;
drift gate unchanged OK.

If git is initialised: `git add kira-chat/src && git commit -m "feat(chat): models screen with month usage and use-in-chat"`

Three screens are real now. Task 18 is the last one and the only one that removes data: the Sessions
table, its transcript, delete one, and the typed `DELETE ALL` clear-all that Task 13 already gated.

**Executed (2026-10-28).** Chat went 64 → **71 passed** (ModelsScreen 6, App 17), engine stayed at
**187 passed, 1 skipped** — no engine file touched — and the drift gate stayed `v2, 39 schemas, 5 chunk
types, 9 chain events`. Step 4's join needed the null-model filter (amendment 68) and the test file needed
two local typings (amendment 69) before `npm run check` was silent. Step 8 was done against a
`--backend memory` engine on a throwaway data dir so the real Locker stayed untouched and the bearer token
printed was a value that dies with the process; the browser driver could not drive React's inputs or
buttons, so the pass seeded the two `localStorage` keys and clicked in-page (amendment 70). Everything the
step could show without a key is shown: 5 rows, tiers matching `config.yaml`, `0`/`0` everywhere, one
button per row, no editable cell, and the second row's button moving the chat's model select and the hash.
The row-gains-a-turn claim waits for Task 20's mock lab (amendment 71).

---

## Task 18: The Sessions screen — read it, delete one, delete all

This is the only screen that removes data, so it is the only one where the confirm dialog has to slow a
person down twice. Three things exist already and are consumed here rather than rebuilt:

- `client.deleteSession(id, secret)` and `client.clearSessions(secret)` shipped in Task 14, unconnected.
- The fake engine's two `DELETE` branches shipped in Task 14 (lines 5733-5741 of this plan), including the
  401 refusal path — so no `fake-engine.ts` change belongs to this task.
- The engine's "a delete that finds nothing is a success" rule from Task 13 means the UI never has to tell
  "it worked" from "it worked twice".

**Gap 18, found while planning this task:** spec line 298-300 says clear-all asks for the confirm value
*and* the typed words `DELETE ALL`, and the delete-one dialog must name the session id and its message
count. Task 11 built `ConfirmRequest {summary, detail?, danger?}` — enough to name the damage, not enough
to require a phrase. So `ConfirmRequest` gains `phrase?: string` here, the dialog grows one text field and
one disabled-until-matched submit button, and the phrase stops at the dialog: `ask()` still resolves to the
secret alone. The engine has no idea what `DELETE ALL` is and never will; the words exist to make a human
type the destruction, which is a browser-side concern by design.

**Gap 19, found while planning this task:** amendment 14's re-ask loop lives inside
`ProvidersScreen.tsx`'s `Row`. A second write-heavy screen would either copy it — and a copy is how the
re-ask rule gets dropped in one of the two places — or invent its own error handling. So Step 1 extracts it
into `kira-chat/src/useWrite.ts`, with its own test file, and rewires `ProvidersScreen` to consume it.
Nothing about that screen's behaviour changes and its 8 tests must pass **unmodified**: that is the proof
the extraction is faithful, and it is why the extraction is its own step instead of a side effect.

**Files:**
- Create: `kira-chat/src/useWrite.ts`, `kira-chat/src/useWrite.test.tsx` (4)
- Modify: `kira-chat/src/confirm.tsx` (`ConfirmRequest.phrase`, the phrase field, the disabled submit)
- Modify: `kira-chat/src/confirm.test.tsx` (append 2, add one helper component)
- Modify: `kira-chat/src/screens/ProvidersScreen.tsx` (`Row`'s `busy`/`note`/`run` become the hook)
- Create: `kira-chat/src/screens/SessionsScreen.tsx`
- Create: `kira-chat/src/screens/SessionsScreen.test.tsx` (7)
- Modify: `kira-chat/src/screens/OverviewScreen.tsx` (recent-issue rows become buttons)
- Modify: `kira-chat/src/App.tsx` (mount the screen, `focusSession` state, delete `COMING_SOON`)
- Modify: `kira-chat/src/App.test.tsx` (replace the "not built yet" test with "every route renders", append the issue-link test)
- Modify: `kira-chat/src/styles.css` (transcript + phrase)

**Interfaces:**
- Consumes: `SessionRow {id, mode, created_at, message_count, tokens, last_used_at}` (Task 8's v2 schema),
  `client.sessions(limit)` and `client.messages(sessionId)` (both already in `api.ts:74-80`),
  `MessageRow` with its `chain` and `usage` (`kira-contracts/types.ts:188-201`), `ChainTrace`, `useAsync`,
  `DeletedResponse {deleted, messages}`, `navigate` (Task 1), and Task 14's `FAKE_CONFIRM`.
- Produces: `useWrite(refresh) -> {busy, note, run}` and
  `run(summary, detail, danger, act, options?: {phrase?: string})`; `ConfirmRequest.phrase`;
  `SessionsScreen({ client, focusId, onChanged })`; `OverviewScreen({ client, onOpenSession })`. Task 19
  and 20 consume nothing new from this task.

- [ ] **Step 1: Extract the write loop, and prove the extraction**

Create `kira-chat/src/useWrite.ts`:

```ts
import { useState } from "react";
import { KiraApiError } from "./contracts.ts";
import type { ConfirmRequest } from "./confirm.tsx";
import { useConfirm } from "./confirm.tsx";

export type WriteAct = (secret: string) => Promise<unknown>;

export interface RunOptions {
  /** Words the human must type in full before the dialog will submit. Never sent to the engine. */
  phrase?: string;
}

/**
 * The one place a write is confirmed, sent, re-read and — on a refused secret — asked again.
 * A screen owns its own data; this owns the dialog around it.
 */
export function useWrite(refresh: () => void) {
  const ask = useConfirm();
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  async function run(
    summary: string,
    detail: string,
    danger: boolean,
    act: WriteAct,
    options: RunOptions = {},
  ): Promise<void> {
    let request: ConfirmRequest = { summary, detail, danger, phrase: options.phrase };
    for (;;) {
      const secret = await ask(request);
      if (!secret) return;
      setBusy(true);
      setNote(null);
      try {
        await act(secret);
        refresh();
        return;
      } catch (error) {
        if (!(error instanceof KiraApiError) || error.httpStatus !== 401) {
          setNote(error instanceof Error ? error.message : String(error));
          return;
        }
        request = { ...request, detail: `${detail} — the engine refused that secret; type it again` };
      } finally {
        setBusy(false);
      }
    }
  }

  return { busy, note, run };
}
```

Create `kira-chat/src/useWrite.test.tsx`:

```tsx
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { KiraApiError } from "./contracts.ts";
import { ConfirmProvider } from "./confirm.tsx";
import { useWrite } from "./useWrite.ts";

const refresh = vi.fn();
const unauthorized = new KiraApiError(
  { code: "unauthorized", message: "this write needs the confirm secret", status: 401, retryable: false },
  401,
);
const badBody = new KiraApiError({ code: "config_error", message: "monthly_cap must be >= 0", status: 400, retryable: false }, 400);

function Hook({ act }: { act: (secret: string) => Promise<unknown> }) {
  const write = useWrite(refresh);
  return (
    <button
      type="button"
      disabled={write.busy}
      onClick={() => void write.run("turn groq off", "PUT /v1/kira/providers/groq/settings", false, act)}
    >
      {`write ${write.note ?? "clean"}`}
    </button>
  );
}

async function open(summary = "turn groq off") {
  fireEvent.click(screen.getByRole("button", { name: /^write / }));
  expect(await screen.findByText(summary)).toBeTruthy();
}

describe("useWrite", () => {
  it("does not act at all when the human cancels", async () => {
    const act = vi.fn(async () => undefined);
    render(
      <ConfirmProvider>
        <Hook act={act} />
      </ConfirmProvider>,
    );
    await open();
    fireEvent.click(screen.getByRole("button", { name: "cancel" }));
    await waitFor(() => expect(act).not.toHaveBeenCalled());
    expect(refresh).not.toHaveBeenCalled();
  });

  it("acts with the secret, then re-reads", async () => {
    const act = vi.fn(async (_secret: string) => undefined);
    render(
      <ConfirmProvider>
        <Hook act={act} />
      </ConfirmProvider>,
    );
    await open();
    fireEvent.change(screen.getByLabelText("Confirm secret"), { target: { value: "s3cret" } });
    fireEvent.click(screen.getByRole("button", { name: "confirm write" }));
    await waitFor(() => expect(act).toHaveBeenCalledWith("s3cret"));
    await waitFor(() => expect(refresh).toHaveBeenCalled());
    expect(screen.getByRole("button", { name: "write clean" })).toBeTruthy();
  });

  it("keeps a real failure as the engine's own words and does not re-ask", async () => {
    const act = vi.fn(async () => {
      throw badBody;
    });
    render(
      <ConfirmProvider>
        <Hook act={act} />
      </ConfirmProvider>,
    );
    await open();
    fireEvent.change(screen.getByLabelText("Confirm secret"), { target: { value: "s3cret" } });
    fireEvent.click(screen.getByRole("button", { name: "confirm write" }));
    await waitFor(() => expect(screen.getByRole("button", { name: /config_error/ })).toBeTruthy());
    expect(act).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("turn groq off")).toBeNull();
    expect(refresh).not.toHaveBeenCalled();
  });

  it("asks again on a refused secret and takes the second one", async () => {
    let calls = 0;
    const act = vi.fn(async () => {
      calls += 1;
      if (calls === 1) throw unauthorized;
      return undefined;
    });
    render(
      <ConfirmProvider>
        <Hook act={act} />
      </ConfirmProvider>,
    );
    await open();
    fireEvent.change(screen.getByLabelText("Confirm secret"), { target: { value: "wrong" } });
    fireEvent.click(screen.getByRole("button", { name: "confirm write" }));
    expect(await screen.findByText(/refused that secret; type it again/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Confirm secret"), { target: { value: "s3cret" } });
    fireEvent.click(screen.getByRole("button", { name: "confirm write" }));
    await waitFor(() => expect(act).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(refresh).toHaveBeenCalled());
  });
});
```

`refresh` is a module-level spy shared by four tests, so the tests that assert it *was not* called must run
before the one that asserts it was — which they do, in file order, and vitest runs `it` blocks in
declaration order. `restoreMocks: true` in `vite.config.ts` resets call counts between files, not between
tests; if a later shuffle makes the third test's `not.toHaveBeenCalled()` flaky, move `refresh` into a
`beforeEach(() => refresh.mockClear())` rather than reordering the assertions.

Then rewire `Row` in `kira-chat/src/screens/ProvidersScreen.tsx`: delete its local `const ask =
useConfirm();`, `const [busy, setBusy] = …`, `const [note, setNote] = …` and the whole `run` function body,
and put in their place

```tsx
  const { busy, note, run } = useWrite(refresh);
```

with `import { useWrite } from "../useWrite.ts";` added. `save` and every call site keep their exact
signatures, because the hook's `run` is the same five-argument shape with the fifth optional. Delete the
now-unused `KiraApiError` and `ConfirmRequest` imports from the screen and the `useConfirm` import —
`noUnusedLocals` is on, so leaving them is a build failure, not a lint smell.

Run: `cd kira-chat && npx vitest run src/screens/ProvidersScreen.test.tsx`
Expected: `8 passed` **with no edit to that file.** If any of the eight needs changing, the extraction
moved behaviour rather than code; stop and fix the hook.

Run: `cd kira-chat && npx vitest run src/useWrite.test.tsx`
Expected: `4 passed`.

- [ ] **Step 2: Give the dialog the words field the spec asked for**

In `kira-chat/src/confirm.tsx`, add the field to the request type:

```tsx
export interface ConfirmRequest {
  /** What the human is approving, in their words: "turn groq off", not "PUT /settings". */
  summary: string;
  detail?: string;
  danger?: boolean;
  /** When set, the submit button stays dead until this exact string is typed. Not sent anywhere. */
  phrase?: string;
}
```

Add `const [typedPhrase, setTypedPhrase] = useState("");` beside the existing `typed`/`error` state, clear it
in `close()` and in `ask()` next to `setTyped("")`, and render the field before the secret label — the
destruction is named first, then the credential that authorises it:

```tsx
            {open.request.phrase && (
              <label>
                {`Type ${open.request.phrase} to allow this`}
                <input
                  name="confirm_phrase"
                  type="text"
                  value={typedPhrase}
                  onChange={(event) => setTypedPhrase(event.target.value)}
                  autoComplete="off"
                  spellCheck={false}
                />
              </label>
            )}
```

and gate the submit button, leaving everything else about the dialog untouched:

```tsx
            <div className="confirm-actions">
              <button type="button" onClick={cancel}>
                cancel
              </button>
              <button
                type="submit"
                disabled={open.request.phrase !== undefined && typedPhrase !== open.request.phrase}
                className={open.request.danger ? "danger" : undefined}
              >
                confirm write
              </button>
            </div>
```

Add `PhraseReader` next to the existing `Reader` in `kira-chat/src/confirm.test.tsx`:

```tsx
function PhraseReader({ phrase = "DELETE ALL" }: { phrase?: string }) {
  const ask = useConfirm();
  return (
    <button
      type="button"
      onClick={() => {
        void ask({ summary: "delete every session", detail: "DELETE /v1/kira/sessions", danger: true, phrase }).then(
          (answer) => {
            (globalThis as Record<string, unknown>).__answer = answer;
          },
        );
      }}
    >
      ask with a phrase
    </button>
  );
}
```

and append two tests inside `describe("ConfirmProvider")`:

```ts
  it("will not submit a phrase request until the words match exactly", async () => {
    (globalThis as Record<string, unknown>).__answer = "unset";
    render(
      <ConfirmProvider>
        <PhraseReader />
      </ConfirmProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "ask with a phrase" }));
    const phrase = await screen.findByLabelText("Type DELETE ALL to allow this");
    const submit = screen.getByRole("button", { name: "confirm write" });

    fireEvent.change(phrase, { target: { value: "delete all" } });
    expect((submit as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(phrase, { target: { value: "DELETE ALL " } });
    expect((submit as HTMLButtonElement).disabled).toBe(true);

    fireEvent.change(phrase, { target: { value: "DELETE ALL" } });
    expect((submit as HTMLButtonElement).disabled).toBe(false);
    fireEvent.change(screen.getByLabelText("Confirm secret"), { target: { value: "s3cret" } });
    fireEvent.click(submit);
    await waitFor(() => expect(lastAnswer()).toBe("s3cret"));
  });

  it("keeps the words in the dialog: the answer is the secret alone", async () => {
    (globalThis as Record<string, unknown>).__answer = "unset";
    render(
      <ConfirmProvider>
        <PhraseReader />
      </ConfirmProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "ask with a phrase" }));
    fireEvent.change(await screen.findByLabelText("Type DELETE ALL to allow this"), { target: { value: "DELETE ALL" } });
    fireEvent.change(screen.getByLabelText("Confirm secret"), { target: { value: "only-this" } });
    fireEvent.click(screen.getByRole("button", { name: "confirm write" }));
    await waitFor(() => expect(lastAnswer()).toBe("only-this"));
    expect(lastAnswer()).not.toMatch(/DELETE ALL/);
    expect(screen.queryByDisplayValue("DELETE ALL")).toBeNull();
  });
```

A trailing space keeps the button dead, which is the point of comparing rather than trimming: the words
must be typed, and a paste that carries whitespace is not typing them.

Run: `cd kira-chat && npx vitest run src/confirm.test.tsx`
Expected: `7 passed` (Task 14's 5, +2).

- [ ] **Step 3: Write the failing Sessions tests**

Create `kira-chat/src/screens/SessionsScreen.test.tsx`:

```tsx
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { KiraClient } from "../api.ts";
import { FAKE_CONFIRM, fakeEngine } from "../fake-engine.ts";
import { ConfirmProvider } from "../confirm.tsx";
import { SessionsScreen } from "./SessionsScreen.tsx";

const ROWS = [
  { id: "sess-busy", mode: "AUTO", created_at: 1_700_000_000, message_count: 4, tokens: 1200, last_used_at: 1_700_000_400 },
  { id: "sess-quiet", mode: "POWERFUL", created_at: 1_699_000_000, message_count: 0, tokens: 0, last_used_at: null },
];

const TRANSCRIPT = [
  {
    id: 1, session_id: "sess-busy", role: "user", content: "hi", provider: null, model: null,
    finish_reason: null, status: "complete", created_at: 1_700_000_000, tool_calls: [], usage: {}, chain: [],
  },
  {
    id: 2, session_id: "sess-busy", role: "assistant", content: "hello", provider: "groq", model: "mini",
    finish_reason: "stop", status: "complete", created_at: 1_700_000_400, tool_calls: [],
    usage: { input_tokens: 700, output_tokens: 500 },
    chain: [{ provider: "groq", event: "served", model: "mini" }],
  },
];

function renderScreen(engine: ReturnType<typeof fakeEngine>, props = {}) {
  const onChanged = vi.fn();
  render(
    <ConfirmProvider>
      <SessionsScreen
        client={new KiraClient({ baseUrl: "", token: "sekret", fetch: engine.fetch })}
        focusId={null}
        onChanged={onChanged}
        {...props}
      />
    </ConfirmProvider>,
  );
  return onChanged;
}

async function typeSecret(value = FAKE_CONFIRM) {
  fireEvent.change(await screen.findByLabelText("Confirm secret"), { target: { value } });
  fireEvent.click(screen.getByRole("button", { name: "confirm write" }));
}

describe("SessionsScreen", () => {
  it("lists what each session cost, newest first", async () => {
    const engine = fakeEngine({ sessions: ROWS });
    renderScreen(engine);
    const rows = await screen.findAllByRole("row");
    expect(within(rows[1]).getByText("sess-busy")).toBeTruthy();
    expect(within(rows[2]).getByText("sess-quiet")).toBeTruthy();
    expect(within(rows[2]).getByText("never")).toBeTruthy();
    expect(within(rows[1]).getByText("1,200")).toBeTruthy();
  });

  it("says empty in the engine's words, not a dash", async () => {
    const engine = fakeEngine({ sessions: [] });
    renderScreen(engine);
    expect(await screen.findByText(/no sessions stored yet/)).toBeTruthy();
  });

  it("opens a transcript that shows the turn the engine stored", async () => {
    const engine = fakeEngine({ sessions: ROWS, messages: { "sess-busy": TRANSCRIPT } });
    renderScreen(engine);
    fireEvent.click(await screen.findByRole("button", { name: "transcript sess-busy" }));
    expect(await screen.findByText("hi")).toBeTruthy();
    expect(screen.getByText("hello")).toBeTruthy();
    expect(screen.getByText("answered")).toBeTruthy();
    expect(engine.calls.some((call) => call.url === "/v1/kira/sessions/sess-busy/messages")).toBe(true);
  });

  it("renders the transcript the engine was already pointing at", async () => {
    const engine = fakeEngine({ sessions: ROWS, messages: { "sess-busy": TRANSCRIPT } });
    renderScreen(engine, { focusId: "sess-busy" });
    expect(await screen.findByText("hello")).toBeTruthy();
  });

  it("deletes one after naming it and its message count", async () => {
    const engine = fakeEngine({ sessions: ROWS, deleted: { deleted: 1, messages: 4 } });
    const onChanged = renderScreen(engine);
    fireEvent.click(await screen.findByRole("button", { name: "delete sess-busy" }));
    expect(await screen.findByText(/delete sess-busy and its 4 messages/)).toBeTruthy();
    await typeSecret();
    await waitFor(() =>
      expect(
        engine.calls.some(
          (call) =>
            call.method === "DELETE" &&
            call.url === "/v1/kira/sessions/sess-busy" &&
            call.headers["X-Kira-Confirm"] === FAKE_CONFIRM,
        ),
      ).toBe(true),
    );
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
  });

  it("sends nothing when the delete is cancelled", async () => {
    const engine = fakeEngine({ sessions: ROWS });
    renderScreen(engine);
    fireEvent.click(await screen.findByRole("button", { name: "delete sess-quiet" }));
    fireEvent.click(await screen.findByRole("button", { name: "cancel" }));
    await waitFor(() => expect(engine.calls.filter((call) => call.method !== "GET").length).toBe(0));
  });

  it("clears all only after the words and the secret", async () => {
    const engine = fakeEngine({ sessions: ROWS, deleted: { deleted: 2, messages: 4 } });
    renderScreen(engine);
    fireEvent.click(await screen.findByRole("button", { name: "delete every session" }));
    const phrase = await screen.findByLabelText("Type DELETE ALL to allow this");
    const submit = screen.getByRole("button", { name: "confirm write" });
    expect((submit as HTMLButtonElement).disabled).toBe(true);

    fireEvent.change(phrase, { target: { value: "DELETE ALL" } });
    expect((submit as HTMLButtonElement).disabled).toBe(false);
    fireEvent.change(screen.getByLabelText("Confirm secret"), { target: { value: FAKE_CONFIRM } });
    fireEvent.click(submit);
    await waitFor(() =>
      expect(
        engine.calls.some(
          (call) =>
            call.method === "DELETE" && call.url === "/v1/kira/sessions" && !call.body,
        ),
      ).toBe(true),
    );
    expect(engine.calls.some((call) => JSON.stringify(call.body ?? "").includes("DELETE ALL"))).toBe(false);
  });
});
```

`deleted` is Task 14's `FakeOptions` key, `messages` is the on-disk history branch, and the last
assertion is the whole point of Gap 18 stated as a test: the words the human typed authorised the write
locally and never reached the wire.

Run: `cd kira-chat && npx vitest run src/screens/SessionsScreen.test.tsx`
Expected: `Failed to resolve import "./SessionsScreen.tsx"`.

- [ ] **Step 4: Write the screen**

Create `kira-chat/src/screens/SessionsScreen.tsx`:

```tsx
import { useEffect, useState } from "react";
import type { KiraClient } from "../api.ts";
import type { MessageRow, SessionRow } from "../contracts.ts";
import { ChainTrace } from "../components/ChainTrace.tsx";
import { useAsync } from "../useAsync.ts";
import { useWrite } from "../useWrite.ts";

function num(value: number): string {
  return value.toLocaleString("en-US");
}

function stamp(seconds: number | null): string {
  if (seconds === null) return "never";
  return new Date(seconds * 1000).toLocaleString("en-GB", { hour12: false });
}

export function SessionsScreen({
  client,
  focusId,
  onChanged,
}: {
  client: KiraClient;
  focusId: string | null;
  onChanged: () => void;
}) {
  const [open, setOpen] = useState<string | null>(focusId);
  useEffect(() => setOpen(focusId), [focusId]);

  const list = useAsync(() => client.sessions(200), []);
  const transcript = useAsync(
    () => (open === null ? Promise.resolve(null) : client.messages(open)),
    [open],
  );
  const { busy, note, run } = useWrite(() => {
    list.refresh();
    transcript.refresh();
    onChanged();
  });

  if (list.kind === "loading") return <section className="screen"><p className="muted">reading sessions…</p></section>;
  if (list.kind === "error") {
    return (
      <section className="screen">
        <p className="error">cannot read sessions: {String((list.error as Error).message ?? list.error)}</p>
      </section>
    );
  }
  const rows = list.data.sessions;

  return (
    <section className="screen">
      <header className="screen-head">
        <h2>Sessions</h2>
        <span className="spacer" />
        <button type="button" onClick={list.refresh}>reload</button>
        <button
          type="button"
          className="danger"
          disabled={busy || rows.length === 0}
          onClick={() =>
            void run(
              "delete every session",
              "DELETE /v1/kira/sessions",
              true,
              (secret) => client.clearSessions(secret),
              { phrase: "DELETE ALL" },
            )
          }
        >
          delete every session
        </button>
      </header>
      {note && <p className="error">{note}</p>}

      {rows.length === 0 ? (
        <p className="empty">no sessions stored yet — the engine creates one per conversation, so this is empty
        because nothing has been asked yet, not because anything was deleted.</p>
      ) : (
        <table className="grid">
          <thead>
            <tr><th>session</th><th>mode</th><th>messages</th><th>tokens</th><th>last used</th><th>actions</th></tr>
          </thead>
          <tbody>
            {rows.map((row: SessionRow) => (
              <tr key={row.id} className={open === row.id ? "row-open" : undefined}>
                <td className="mono">{row.id}</td>
                <td>{row.mode}</td>
                <td>{row.message_count}</td>
                <td className="mono">{num(row.tokens)}</td>
                <td className="mono">{stamp(row.last_used_at)}</td>
                <td>
                  <div className="cell-actions">
                    <button type="button" onClick={() => setOpen(row.id)}>{`transcript ${row.id}`}</button>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() =>
                        void run(
                          `delete ${row.id} and its ${row.message_count} message${row.message_count === 1 ? "" : "s"}`,
                          `DELETE /v1/kira/sessions/${row.id}`,
                          true,
                          (secret) => client.deleteSession(row.id, secret),
                        )
                      }
                    >
                      {`delete ${row.id}`}
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {open !== null && (
        <section className="transcript" aria-label={`transcript ${open}`}>
          <header className="screen-head">
            <h3 className="mono">{open}</h3>
            <span className="spacer" />
            <button type="button" onClick={() => setOpen(null)}>close</button>
          </header>
          {transcript.kind === "loading" ? <p className="muted">reading the turns…</p> : null}
          {transcript.kind === "error" ? (
            <p className="error">cannot read this session: {String((transcript.error as Error).message ?? transcript.error)}</p>
          ) : null}
          {transcript.kind === "ready" && transcript.data === null ? (
            <p className="muted">nothing to read — close this and pick a session from the table.</p>
          ) : null}
          {transcript.kind === "ready" && transcript.data !== null && (
            transcript.data.messages.length === 0 ? (
              <p className="empty">the engine has no rows for {open}: it was created and never answered.</p>
            ) : (
              <ol className="turns">
                {transcript.data.messages.map((message: MessageRow) => (
                  <li key={message.id} className={`turn turn-${message.role}`}>
                    <div className="meta">
                      <span>{message.role}</span>
                      <span className="mono">{message.status}</span>
                      {message.provider && <span className="mono">{message.provider}/{message.model}</span>}
                      {message.usage && (
                        <span className="mono">
                          {num((message.usage.input_tokens ?? 0) + (message.usage.output_tokens ?? 0))} tokens
                        </span>
                      )}
                    </div>
                    <div className="content">{message.content || <em className="muted">no text stored</em>}</div>
                    <ChainTrace chain={message.chain} />
                  </li>
                ))}
              </ol>
            )
          )}
        </section>
      )}

      <p className="muted small">
        Deleting is final: the engine removes the session and every message under it in one statement, and
        there is no undo in the browser. A delete that finds nothing still answers as a success, because the
        row you clicked is a snapshot of a list someone else may have already cleared.
      </p>
    </section>
  );
}
```

`transcript` reads with `open` in its dependency list and resolves to `null` when nothing is open, so no
request goes out for a closed transcript — `useAsync` guards the epoch, not the fetch.
`client.sessions(200)` is a deliberate ceiling: the endpoint's default is 30 and a dashboard that paginates
nothing should at least not pretend to show everything. The last-used column is the engine's
`last_used_at`, which is `null` for a session that was created and never answered; `stamp` renders that as
`never` rather than a 1970 date.

- [ ] **Step 5: Route the Overview's trouble here**

In `kira-chat/src/screens/OverviewScreen.tsx`, change the props to
`{ client, onOpenSession }: { client: KiraClient; onOpenSession: (sessionId: string) => void }` and replace
the `<li>` body of the recent-issues list so the id is the control:

```tsx
            <ul className="issues">
              {view.recent_issues.map((issue) => (
                <li key={issue.id}>
                  <span className={`issue-${issue.status}`}>{issue.status}</span>
                  <button type="button" className="link" onClick={() => onOpenSession(issue.session_id)}>
                    {issue.session_id}
                  </button>
                  <span>{issue.provider ?? "no provider"} · {issue.reason}</span>
                </li>
              ))}
            </ul>
```

This is a button and not an anchor because a transcript is React state, not a URL: the shell's route parser
understands exactly five names (Task 1) and `#/sessions/sess-9` would parse to `chat`. The spec asks that
those rows "link straight to their session transcript", which is about where the click lands, and
deep-linking a session id is Task 20's note if the owner ever wants it.

- [ ] **Step 6: Mount the last screen**

In `kira-chat/src/App.tsx`, delete the `COMING_SOON` map and its `screen-empty` branch — every route now
renders something real — and add the focus state beside the other screen state:

```tsx
  const [focusSession, setFocusSession] = useState<string | null>(null);

  function openSessionTranscript(sessionId: string) {
    setFocusSession(sessionId);
    navigate("sessions");
  }
```

and two branches in the route switch:

```tsx
        ) : route === "overview" ? (
          <OverviewScreen client={client} onOpenSession={openSessionTranscript} />
        ) : route === "sessions" ? (
          <SessionsScreen client={client} focusId={focusSession} onChanged={refresh} />
```

`ProvidersScreen` keeps `onChanged={refresh}` from Task 14, so both screens that write re-read what the
shell shows. `setFocusSession` is App state rather than a ref because the transcript must reopen when the
same session is clicked twice from Overview — a ref would not re-render, and `useEffect` on `focusId` is
what makes the second click land.

- [ ] **Step 7: One App test for the whole route table, one for the link**

Replace the test Task 18's Step 2 left standing ("waits for the screens that are not built yet, by name")
with these two in `kira-chat/src/App.test.tsx`:

```ts
  it("renders a real screen for every route and a placeholder for none", async () => {
    const engine = fakeEngine({
      models: MODELS,
      health: HEALTH,
      sessions: [{ id: "sess-1", mode: "AUTO", created_at: 1, message_count: 2, tokens: 10, last_used_at: 2 }],
    });
    connectedTo(engine);
    for (const route of ["chat", "overview", "providers", "models", "sessions"] as const) {
      window.location.hash = `#/${route}`;
      render(<App />);
      expect(await screen.findByText("Kira")).toBeTruthy();
      expect(screen.queryByText(/arrives in M12/)).toBeNull();
      unmount();
    }
  });

  it("opens the transcript an Overview trouble row points at", async () => {
    const engine = fakeEngine({
      models: MODELS,
      health: HEALTH,
      sessions: [{ id: "sess-9", mode: "AUTO", created_at: 1, message_count: 2, tokens: 10, last_used_at: 2 }],
      messages: {
        "sess-9": [
          { id: 1, session_id: "sess-9", role: "assistant", content: "the answer that broke", provider: "openrouter", model: null, finish_reason: null, status: "failed", created_at: 2, tool_calls: [], usage: {}, chain: [{ provider: "openrouter", event: "failed", reason: "503", cooldown_s: 5 }] },
        ],
      },
    });
    connectedTo(engine);
    window.location.hash = "#/overview";
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "sess-9" }));
    expect(await screen.findByText("the answer that broke")).toBeTruthy();
    expect(window.location.hash).toBe("#/sessions");
  });
```

`unmount` comes from destructuring `render` in the first test — `const { unmount } = render(<App />)` — so
each route iteration starts with an empty document; without it the loop's second iteration finds the first
iteration's screens. The `findByText("Kira")` wait is the rail's word, present on every route, and it is
the cheapest assertion that the shell itself mounted. If a fixture id collides with the sidebar's own
recent-sessions list, narrow the second test's click with
`within(screen.getByRole("list", { name: "recent trouble" }))`, which is why the Overview's `<ul
className="issues">` should gain `aria-label="recent trouble"` in Step 5.

- [ ] **Step 8: Styles**

Append to `kira-chat/src/styles.css`:

```css
/* sessions and transcript (Task 18) */
.transcript {
  margin-top: 1.5rem;
  border-top: 1px solid var(--line);
  padding-top: 1rem;
}
.turns {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.7rem;
}
.turn {
  background: var(--panel);
  border-left: 3px solid var(--line);
  padding: 0.5rem 0.7rem;
}
.turn-user {
  border-left-color: var(--muted);
}
.turn-assistant {
  border-left-color: var(--accent);
}
.row-open td {
  background: color-mix(in srgb, var(--accent) 10%, transparent);
}
button.link {
  background: none;
  border: none;
  color: var(--accent);
  cursor: pointer;
  font: inherit;
  padding: 0;
  text-decoration: underline;
}
```

`--line`, `--panel`, `--muted`, `--accent` are all in `:root` today, and `.meta`, `.content` and
`ol.chain` are ChatScreen's existing classes — the transcript reuses them rather than inventing a second
turn renderer, which is what "transcript detail reusing ChainTrace" means.

- [ ] **Step 9: Run the client suite**

Run: `cd kira-chat && npx vitest run src/screens/SessionsScreen.test.tsx`
Expected: `7 passed`.

Run: `cd kira-chat && npx vitest run src/App.test.tsx`
Expected: `15 passed` (14 after Task 17, +2 from Step 7 and −1 for the placeholder test Step 7 replaces).

Run: `cd kira-chat && npm run check`
Expected: typecheck silent, all tests pass, `vite build` succeeds. `OverviewScreen` gaining a required prop
is the only signature change, and App is its only caller — if the typecheck complains about
`OverviewScreen` inside `App.test.tsx`, the tests there render `<App />`, not the screen, so it does not.

- [ ] **Step 10: Prove the deletes by hand, on a scratch data directory**

Never do this against `Kira/.kira-data`: the point of the proof is that a delete is final, and the real
directory holds the owner's actual history. Use a directory the proof creates and the proof removes.

```
mkdir -p /tmp/kira-scratch
cd kira-engine
.venv/Scripts/python.exe -c "from pathlib import Path;from kira.store import Store;s=Store(Path('/tmp/kira-scratch/kira.db'));a=s.create_session('AUTO');s.add_message(a,'user','proof one');s.add_message(a,'assistant','answer one',provider='groq',model='mini');b=s.create_session('POWERFUL');s.add_message(b,'user','proof two');print(a,b)"
.venv/Scripts/kira-engine.exe serve --data-dir /tmp/kira-scratch --port 8911
```
The printed ids are what the table must show, with `messages` counts 2 and 1 and a `never` for the second
one's `last_used_at`. Open `http://127.0.0.1:8911/`, point the connection panel at
`http://127.0.0.1:8911`, and walk it: transcript opens and shows both turns with their chain chips;
`delete <id>` names the session and its count and needs the confirm secret from `kira-engine token` —
refuse it once by typing wrong, and confirm the dialog re-opens with the reason; then complete the delete
and watch the row vanish from both the table and the chat sidebar on the next read. `delete every session`
must stay inert with the words mistyped — try `delete all`, try `DELETE ALL ` with a trailing space — and
only submit when the exact phrase is in the box. Finish with Ctrl+C on the engine and
`rm -rf /tmp/kira-scratch`. If `--data-dir` is not accepted by `serve`, stop and fix that first: the
launcher and the CLI both take it from the shared `common` group, and a proof that lands on the real
directory is not a proof.

- [ ] **Step 11: Checkpoint**

Run from `Kira/`: `cd kira-engine && .venv/Scripts/python.exe -m pytest -q && cd ../kira-chat && npm run check && cd .. && node kira-contracts/check-drift.mjs`
Expected: engine `176 passed, 1 skipped` — unchanged, no engine code in this task; chat all green with
`useWrite.test.tsx` (4), `confirm.test.tsx` (7), `SessionsScreen.test.tsx` (7) and `ProvidersScreen.test.tsx`
(8) all present; drift gate unchanged OK.

Run from `Kira/kira-chat`: `grep -rn "DELETE ALL" src/`
Expected: `confirm.tsx` (the type), `confirm.test.tsx`, `screens/SessionsScreen.tsx` (the request),
`screens/SessionsScreen.test.tsx`, and `useWrite.test.tsx` if a phrase case was added there. No match in
`api.ts` — the words are not a field in any request body, and that grep line is Gap 18's machine check.

If git is initialised: `git add kira-chat/src && git commit -m "feat(chat): sessions screen, transcript, and two-stage deletes"`

All five screens exist, every write goes through the dialog, and the budget closes its loop. Task 19 is
documentation: the launcher's first-run output, the README's token and confirm-secret sections, and the
CLI verbs the dashboard does not cover.

**Executed (2026-10-28).** Chat went 71 → **87 passed** (useWrite 4, confirm 8, SessionsScreen 8, App 18,
ProvidersScreen 8), engine stayed at **187 passed, 1 skipped** — no engine file touched — and the drift gate
stayed `v2, 39 schemas, 5 chunk types, 9 chain events`. Gap 19's proof held: `ProvidersScreen.test.tsx`
passed with no edit once `Row` consumed the hook, though the hook needed a `reread` option the snippet lost
(amendment 72). Gap 18's machine check held: the grep named `confirm.tsx`, `confirm.test.tsx`,
`SessionsScreen.tsx` and `SessionsScreen.test.tsx`, and nothing in `api.ts` — the words never enter a request
body. Step 2 needed a submit-time re-check, because a disabled button does not stop Enter (amendment 73), and
Step 4's null-transcript branch was unreachable (74). Step 10 was run against a `--backend memory` engine on a
scratch directory the proof created and deleted: 3 rows with messages `2 / 1 / 0` and `never` on the third
(75), transcript with both turns and the `answered` chip, a refused secret re-asking with the reason and
costing no row, the deleted row gone from the table on the re-read, and clear-all inert against `delete all`
and `DELETE ALL ` with its space. That walk caught the one real defect — the transcript of a session deleted
while open stayed mounted and claimed it had never been answered (76) — and it needed a cache-bypassing reload
to see the new bundle at all (77). Counts and the dead `.screen-empty` are in 78.

## Task 19: Documentation that a test can check

Eighteen tasks have doubled the HTTP surface, added a second secret, changed the order the router
filters in, renamed nothing, and added two CLI verbs. `Kira/README.md` still describes the tree as
"sub-project 1 of 8", lists seven endpoints where there are sixteen, names eight chain events where
the contract publishes nine, tells the reader to gate a change with `npm test` when every checkpoint
in this plan gated it with `npm run check`, and quotes a binary (`kira keys set`) that has never
existed — `pyproject.toml:23` installs `kira-engine`. None of that was malice; it is what happens when
documentation is only ever *written* and never *checked*.

**Gap 20, found while planning this task:** the spec asks for a "README dashboard section" and nothing
more, which makes this task unreviewable — a proofread finds the typos the reviewer happens to know
about. So Task 19 adds `kira-engine/tests/test_docs_match_engine.py`, which compares the README against
the running app (`harness.app.routes`), the published contract (`CHAIN_EVENTS`), the parser
(`build_parser()`) and the merge (`TUNABLE_FIELDS`). A README list that a test can diff against code is
the only kind that stays true, and it is the same argument that produced `check-drift.mjs` for the
types.

**Gap 21, same source:** the README's `Checks` section names `npm test`, which is vitest alone. The
gate this plan has used since Task 8 is `npm run check` — typecheck, vitest, build — because
`noUnusedLocals` and `verbatimModuleSyntax` failures are invisible to `npm test` and a dashboard that
does not build is not shipped. Documentation that names a weaker gate than the one actually in force is
a defect, not a stylistic choice.

**Files:**
- Create: `kira-engine/tests/test_docs_match_engine.py`
- Modify: `README.md` (preamble, one-click, a new `Two secrets` section, the CLI table, the endpoint
  table, the routing section, a new `The dashboard` section, `Checks`, `Deliberately not here`)
- Modify: `PROVENANCE.md` (the dashboard's design-influence row)
- Modify: `run_kira.py` (`open_when_ready` names the screens; the docstring says which two secrets it
  prints)

**Interfaces:**
- Consumes: `harness.app` (`tests/conftest.py:155`, which is `create_app(self.config, engine=self.engine)`
  — every route this plan added is registered there), `CHAIN_EVENTS` (`contracts.py:20`, nine members
  after Task 8), `TUNABLE_FIELDS` (`overrides.py`, `("enabled", "priority", "tier", "monthly_cap")`),
  `build_parser()` (`__main__.py:144`), the repo-root idiom already used at
  `tests/test_live_providers.py:28` (`Path(__file__).resolve().parents[2]`), the launcher's `say()`
  helper (`run_kira.py:41`) and the two secret lines Task 11 Step 8 added.
- Produces: nothing later code consumes. `docs/qa/` is created by Task 20, and the README's tree
  section gains that line **there**, not here — documenting a directory that does not exist yet is the
  kind of drift the new test cannot catch, because no code owns it.

- [ ] **Step 1: Write the failing docs tests**

Create `kira-engine/tests/test_docs_match_engine.py`:

```python
"""Keep README.md and the engine in the same sentence.

Docs rot the moment a surface changes and nobody's job was to notice. Every check
here compares README against code that is already the source of truth - the app's
own route table, the published event list, the parser's verbs, the merge's tunable
fields - so a task that adds an endpoint without documenting it fails a test
instead of shipping a wrong README.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from kira.contracts import CHAIN_EVENTS
from kira.__main__ import build_parser
from kira.overrides import TUNABLE_FIELDS

README = Path(__file__).resolve().parents[2] / "README.md"


def readme() -> str:
    assert README.is_file(), f"README must sit at the repo root: {README}"
    return README.read_text(encoding="utf-8")


def canon(path: str) -> str:
    """`/v1/kira/sessions/{id}/messages` and `.../{session_id}/...` are the same route."""
    return re.sub(r"\{[^}]+\}", "{}", path)


def _readme_rows() -> set[str]:
    rows: set[str] = set()
    for line in readme().splitlines():
        if not line.strip().startswith("|"):
            continue
        found = re.search(r"`([A-Z]+ /[^`]*)`", line.split("|")[1])
        if not found:
            continue
        method, path = found.group(1).split(" ", 1)
        path = path.rstrip("/")
        if path.startswith("/v1") or path == "/healthz":
            rows.add(f"{method} {canon(path)}")
    return rows


def _leaf_verbs() -> list[str]:
    """Every command a user can actually run: `keys set`, `settings clear`, ..."""
    leaves: list[str] = []

    def walk(parser: argparse.ArgumentParser, prefix: str) -> None:
        actions = [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)]
        if not actions:
            if prefix.strip():
                leaves.append(prefix.strip())
            return
        for action in actions:
            for name, sub in action.choices.items():
                walk(sub, f"{prefix}{name} ")

    walk(build_parser(), "")
    return leaves


def test_the_readme_endpoint_table_matches_the_app(harness) -> None:
    documented = _readme_rows()
    published = {
        f"{method} {canon(route.path)}"
        for route in harness.app.routes
        if getattr(route, "methods", None) and (route.path.startswith("/v1") or route.path == "/healthz")
        for method in route.methods - {"HEAD", "OPTIONS"}
    }
    assert published - documented == set(), f"routes with no README row: {sorted(published - documented)}"
    assert documented - published == set(), f"README rows with no route: {sorted(documented - published)}"


def test_the_readme_names_exactly_the_published_chain_events() -> None:
    named = set(re.findall(r"`(attempt|served|failed|skipped_[a-z_]+|aborted_mid_stream|tool_executed)`", readme()))
    assert named == set(CHAIN_EVENTS), f"missing: {set(CHAIN_EVENTS) - named}; invented: {named - set(CHAIN_EVENTS)}"


def test_every_cli_verb_is_documented() -> None:
    text = readme()
    missing = [verb for verb in _leaf_verbs() if f"kira-engine {verb}" not in text]
    assert missing == [], f"verbs with no README entry: {missing}"


def test_every_tunable_field_is_documented() -> None:
    text = readme()
    missing = [key for key in TUNABLE_FIELDS if f"`{key}`" not in text]
    assert missing == [], f"tunable settings with no README entry: {missing}"
```

Three things about this file worth knowing before you edit it:

- The route comparison is a set comprehension over `harness.app.routes` rather than a call into
  `app.openapi()`, because the OpenAPI document is built from the same routes but adds FastAPI's
  validation and error responses; the route table is the smaller truth.
- The `/chat/` row is **not** compared. `/chat` is a `StaticFiles` mount whose registered path is not the
  `/chat/` a browser types, and the row documents a shell, not an API. The `_readme_rows` filter
  (`/v1` or `/healthz`) keeps it out of both sides of the comparison, and the comprehension's own filter
  keeps the mount off the other side.
- `test_the_readme_endpoint_table_matches_the_app` takes the `harness` fixture, so it builds an `Engine`
  against a `tmp_path` data dir and a memory vault. It never touches `.kira-data` and never reads the
  Locker, like every other test in this suite.

Run: `cd kira-engine && .venv/Scripts/python.exe -m pytest -q tests/test_docs_match_engine.py`
Expected: `4 failed`. The route test lists nine undocumented rows (`GET /v1/kira/overview`,
`GET /v1/kira/providers`, the five provider writes, the two session deletes); the event test reports
`missing: {'skipped_budget'}`; the verb test reports `['keys rm', 'token', 'models', 'settings list',
'settings clear']`; the tunable test reports `['enabled', 'priority', 'tier', 'monthly_cap']`.

Run: `cd kira-engine && .venv/Scripts/python.exe -m pytest -q`
Expected: `176 passed, 1 skipped` becomes `176 passed, 1 skipped, 4 failed` — nothing existing broke.

- [ ] **Step 2: README — what this tree is, and what one click prints**

Replace the opening paragraph (the one that begins "One local AI agent that routes chat") and the tree
code block with:

````markdown
One local AI agent that routes chat to whichever provider you own a key for, and tells you afterwards
who actually answered. This tree carries **sub-project 1 — the spine** (providers, router, API,
contract, browser chat) and **sub-project 9 — the control dashboard** (spend, keys, tuning, monthly
caps, history) as tabs beside that chat. Tool execution, the desktop shell, memory and local inference
are still later sub-projects.

```
kira-engine/     Python 3.12 FastAPI engine (the only thing that talks to providers)
kira-chat/       TypeScript + React: the chat and the five-screen dashboard, served at /chat/
kira-contracts/  hand-written TS types + check-drift.mjs, the cross-language gate
kira-engine/tools/  dev-only scripts (a mock provider and the browser-pass lab)
docs/specs/      the design each sub-project implements
docs/plans/      the task-by-task build plan, including the decisions planning forced
```
````

Then in `## One click`, replace the sentence that ends "…the connect screen wants the `connect-token`
line it printed." with:

````markdown
The first run prints two lines you need before that window closes:

```
[kira] connect-token for the browser (created now): <token>
[kira] confirm secret for dashboard writes (created now): <secret>
```

The token is what the connect screen asks for. The confirm secret is what every dashboard **write**
asks for, again, once per write — see `Two secrets` below. Both live in the Windows Credential Locker
under service `kira` and neither is ever written to disk; `kira-engine token` reprints the token on
stdout and the confirm secret on stderr. A `KIRA_VAULT=memory` run keeps them in the engine's own
process, so they appear on the engine's `first run` stderr lines instead.
````

Keep the existing "Useful flags" paragraph as it is — `--port`, `--skip-keys`, `--rebuild`,
`--no-browser`, `KIRA_DATA_DIR`, `KIRA_VAULT` are all still exactly right.

- [ ] **Step 3: README — the `Two secrets` section**

Insert this section between `## One click` and `## Run it by hand`:

````markdown
## Two secrets

| Secret | Locker ref | Grants | Where it is printed |
| --- | --- | --- | --- |
| bearer token | `engine/token` | reads: `/v1/models`, chat, every `GET /v1/kira/*` | the launcher, `kira-engine token` on **stdout**, the engine's first-run line on stderr |
| confirm secret | `engine/confirm` | nothing alone; it must travel **with** the bearer token in `X-Kira-Confirm` | the launcher, `kira-engine token` on **stderr**, the engine's first-run line |

Two because the browser necessarily holds the first one, so any script that ever runs in that page has
it. A write therefore also needs a value the page cannot read: you retype it into the dialog, it lives
only while that one request is in flight, and the engine refuses a write whose confirm value is
missing, wrong, or simply the bearer token again.

- One dialog per write. The single exception is a Providers row edited across several fields, which is
  one write and one dialog — separate writes could half-apply a change and route traffic you did not
  intend.
- A provider key or the confirm secret never enters `localStorage`, the URL, a response body, `engine.log`,
  or a module-level variable that outlives the dialog. The check is scoped to that claim, not to every web
  storage read:
  `grep -rn "localStorage" kira-chat/src/` returns only `App.tsx`'s `kira.base` and `kira.token` lines —
  the loopback bearer token is the one value the page keeps, and Task 14 Step 12 says so. If a third key
  appears, or either grep below matches, that is the finding.
  `grep -rniE "localStorage\.(set|get)Item\(\"?(confirm|key)" kira-chat/src/` returns nothing.
- Clearing **all** history additionally requires typing `DELETE ALL`. Those words are UI-side only and
  are never sent to the engine; `grep -rn "DELETE ALL" kira-chat/src/api.ts` returns nothing.
- Rotating either secret is `kira-engine keys rm engine/token` (or `engine/confirm`); the next read or
  write mints a replacement and prints it once. Provider keys are `keys rm provider/<name>`.
````

- [ ] **Step 4: README — the CLI table (replaces the "Run it by hand" block)**

Replace everything from the `## Run it by hand` heading down to (but not including)
`### Developing the UI separately` with:

````markdown
## Run it by hand

```bash
cd kira-engine
python -m venv .venv && .venv/Scripts/activate        # Windows
pip install -e ".[dev]"
```

Every verb below also takes `--data-dir PATH` and `--backend keyring|memory`, before or after the verb.

| Verb | What it does |
| --- | --- |
| `kira-engine serve` | run the engine on loopback (`--port`, `--log-level`) |
| `kira-engine config` | print the resolved config as JSON; `--sample` writes a starter `config.yaml` |
| `kira-engine keys set provider/openrouter --from-env OPENROUTER_API_KEY` | store a key from the environment or `--from-stdin`, never from the command line, so it stays out of shell history |
| `kira-engine keys rm provider/openrouter` | forget one key, or one secret (`engine/token`, `engine/confirm`) |
| `kira-engine keys list` | every ref with `present: true/false` — presence only, never values |
| `kira-engine token` | bearer token on stdout, confirm secret on stderr |
| `kira-engine models` | `list_models` per provider, live. Free: no completion is requested, so no credit is spent |
| `kira-engine contracts` | regenerate `openapi.json` / `contract.json` / `VERSION` for the TS gate (`--out`) |
| `kira-engine settings list` | every stored override, with `orphan: true` on rows the merge refuses |
| `kira-engine settings clear groq monthly_cap --yes` | forget one override, or a provider's whole set (`settings clear groq --yes`) |

`--backend memory` keeps secrets in the process instead of the Locker: tests and the browser-pass lab
only, because a memory vault is per-process and nothing survives the exit. `settings clear` without
`--yes` exits 2 without touching the database — it deletes an override, and the merged value that then
applies is not shown back to you first.

What the dashboard deliberately does **not** cover, and why:

- **Adding or renaming a provider or a model is a `config.yaml` edit.** The UI never writes YAML; the
  Models screen says the same thing on screen.
- **An orphan override row can only be pruned from the CLI.** `validate_setting` refuses an unknown key
  on the write path, so `settings clear <provider> <key> --yes` is the only way to remove a junk row
  that got there by hand; `settings list` is how you find it.
- **The contract export stays a CLI step.** `kira-engine contracts` is a build tool for the drift gate,
  not something to click while tuning a provider.
- **Rotating a secret is a CLI step,** for the same reason a password change is: a browser that could
  print the confirm secret on demand would not need you to type it.
````

This is the step that makes `test_every_cli_verb_is_documented` pass; note that the table is the only
place the README now names each verb, and that `kira keys set` — the nonexistent binary the old prose
quoted — is gone.

- [ ] **Step 5: README — the endpoint table**

In `## HTTP surface`, replace the table rows with exactly these seventeen — sixteen API endpoints plus
the `/chat/` shell row, which stays last even though the test ignores it (the `Auth` column is the point
of the table, so keep it):

```markdown
| `GET /healthz` | none | liveness + contract version, so a client can check compatibility before sending a token |
| `GET /v1/openapi.json` | none | machine-readable contract |
| `GET /v1/models` | bearer | catalogue built from *your* config, merged settings included; `?live=true` adds a free `list_models` probe per provider |
| `POST /v1/chat/completions` | bearer | `stream: true` → SSE `delta` / `chain` / `tool_call` / `done` / `error`; `false` → OpenAI-shaped JSON |
| `GET /v1/kira/health` | bearer | per-provider ledger, with the effective tier and priority the router is using |
| `GET /v1/kira/overview` | bearer | one UTC month: turns, tokens, success rate, per-provider and per-model usage, daily series, budget rows, recent trouble |
| `GET /v1/kira/providers` | bearer | one row per provider: baseline-vs-effective settings, key presence, spend, ledger, plus `orphan_settings` |
| `GET /v1/kira/sessions` | bearer | session list with message and token counts (`?limit=`, default 50) |
| `GET /v1/kira/sessions/{id}/messages` | bearer | stored history with chain and usage |
| `PUT /v1/kira/providers/{name}/settings` | bearer + confirm | write one or more of the four tunable fields; an explicit `null` clears that override |
| `PUT /v1/kira/providers/{name}/key` | bearer + confirm | store a provider key |
| `DELETE /v1/kira/providers/{name}/key` | bearer + confirm | forget it |
| `DELETE /v1/kira/providers/{name}/cooldown` | bearer + confirm | stand a provider back up now |
| `POST /v1/kira/providers/{name}/probe` | bearer + confirm | live test: `list_models` **plus one 8-token completion** — the only click that spends |
| `DELETE /v1/kira/sessions/{id}` | bearer + confirm | delete one session and its messages |
| `DELETE /v1/kira/sessions` | bearer + confirm | delete every session |
| `GET /chat/` | none for the shell | the bundled UI; it asks for the token |
```

Path parameters are written `{id}` and `{name}` here; the test normalizes `{...}` on both sides, so the
spelling is yours to choose and the coverage is not. What it will not forgive is a row for a route that
no longer exists — which is how a deleted endpoint stays "documented" for a year.

- [ ] **Step 6: README — how routing decides, with the budget in it**

Replace the numbered list under `## How routing decides` (the three lines beginning "1. filters by mode
and `priority`") with:

```markdown
1. filters by mode and by `enabled` — a disabled provider is not a candidate — then keeps those
   offering the requested model, then drops those whose key is missing,
2. drops providers already at or over their `monthly_cap` for the current UTC month,
3. drops providers still in cooldown,
4. tries what remains in `priority` order.
```

Add immediately after that list:

```markdown
Budget is checked before health, so a provider that is both over cap and cooling is reported over cap.
Spend is read from stored rows at plan time, which means the turn in flight is not counted — at most one
turn of slack, never a running total the UI promises to respect. If every remaining candidate is over
cap the turn is refused with `budget_exhausted` (429, not retried, no provider billed); if the list
emptied *before* the budget check, because nobody had a key, you get `providers_exhausted` instead. Those
are different facts and the honest answer is different for each.
```

Then in the same section, add `skipped_budget` to the provenance sentence so it reads (this is what
`test_the_readme_names_exactly_the_published_chain_events` checks — nine backticked names, no more):

```markdown
Every turn carries its provenance: `attempt`, `served`, `failed`, `skipped_cooling`,
`skipped_missing_key`, `skipped_config`, `skipped_budget`, `aborted_mid_stream`, `tool_executed`. The
UI renders it as chips and a one-line summary, so "which model answered me" is never a guess.
```

Leave the three failover bullets exactly as they are: 429/5xx retryable, 4xx not retryable,
mid-stream death terminal. The dashboard changes none of that.

- [ ] **Step 7: README — `The dashboard`**

Insert this section before `## Checks`:

````markdown
## The dashboard

`http://127.0.0.1:8901/chat/` is one bundle with a hash route and five screens. The route survives a
refresh, so a refusal can deep-link you to the screen that fixes it:

| Route | Screen |
| --- | --- |
| `#/chat` | chat: composer, mode and model selects, the streaming turn, chain chips, usage line, recent sessions |
| `#/overview` | one month: turns, tokens, success rate, spend against cap per provider, a daily series, top models, recent trouble |
| `#/providers` | `enabled`, `tier`, `priority`, `monthly_cap`, key, ledger and cooldown, and Test |
| `#/models` | every configured model with its provider, tier and month usage; "use in chat" hops to the composer |
| `#/sessions` | session table, transcript with the same chain chips, delete one, delete all |

Three rules hold every screen together:

- **Numbers are derived, never accumulated.** Every figure comes from the `messages` table over one
  half-open UTC month window, so there is no counter to drift and a delete really does reduce spend. A
  budget row's `remaining` is the engine's own clamp: `0` means at or over cap, and the UI never does
  that subtraction a second time.
- **One merged view.** Overrides live in a SQLite `settings` table layered over `config.yaml`, which the
  dashboard never writes. The merge happens per request, so a toggle takes effect on the next turn
  without a restart, and `/v1/models`, the router and the panels read the same view — a screen cannot
  disagree with a route.
- **Four fields are tunable, the rest are YAML.** `enabled`, `priority`, `tier` and `monthly_cap` each
  have a baseline in `config.yaml` and an optional override in the table; the UI shows baseline vs
  effective and offers "reset to baseline". `name`, `kind`, `base_url` and `models` are YAML-only. Note
  the one naming seam: the YAML key is `monthly_token_cap`, while the override row, the API field and
  the panel all call it `monthly_cap`.

A month with no turns is a real state, not an error: Overview says "no turns recorded for 2026-10" and
the bars sit at zero. A provider with no key says `no key` and shows Set key. A row whose write was
refused stays exactly as it was, because the panel's numbers come from the engine and nothing is
updated optimistically.
````

- [ ] **Step 8: Run the docs tests to watch them pass**

Run: `cd kira-engine && .venv/Scripts/python.exe -m pytest -q tests/test_docs_match_engine.py`
Expected: `4 passed`.

If the endpoint test still complains about a `documented` row, read which side it named: the README
inventing a route means an earlier task did not ship what it planned, and that is a finding for that
task, not something to paper over by deleting the row.

- [ ] **Step 9: README — Checks, live providers, and what is not here**

Replace the `## Checks` block with the three commands that actually gate a change. Write the numbers
**from the run you just did**, not from memory or from this plan:

```bash
cd kira-engine && .venv/Scripts/python -m pytest -q   # 180 tests, every provider faked; the live suite is skipped
cd kira-chat  && npm run check                        # tsc --noEmit, then vitest (jsdom), then vite build
node kira-contracts/check-drift.mjs                   # cross-language contract gate: v2, schemas, events
```

Expected: engine `180 passed, 1 skipped` (176 before this task, +4 docs tests). For the client line, run
`npm run check` first and paste the `Test Files` and `Tests` totals it printed into the comment — if the
total is not what Tasks 1-18 add up to, find out which file lost tests before you write anything.
`check-drift.mjs` prints `kira-contracts OK — v2, …, 9 chain events`; the chain-event count is the number
this section is about, so if it still reads 8 the README and the contract are being edited in the wrong
order.

Add under it:

```markdown
The engine suite includes `tests/test_docs_match_engine.py`, which fails when this README's endpoint
table, chain-event list, CLI verb list or tunable-field list drifts from the code. Everything else in
this file is prose, and prose is checked by the hand proofs in `docs/plans/` — a claim with no command
behind it is a claim nobody verified.
```

Then in `### Live providers (opt-in, spends real credits)`, keep the paragraph as written and add one
line after the `KIRA_LIVE=1` command block:

```markdown
The dashboard's Test button is the same honesty in miniature: it is the only click that requests a
completion, and `kira-engine models` and `?live=true` never do.
```

Finally, replace the first bullet of `## Deliberately not here` — the one that ends "`KIRA_LIVE` probes
are the gap to close" — because probes now exist:

```markdown
- **No local/offline model** yet — sub-project 5 (llama.cpp as another tier). Router modes are online
  tiers only; there is no `LOCAL` mode, and the dashboard never pretends otherwise. Live probes, by
  contrast, are built: `kira-engine models`, `GET /v1/models?live=true` and the Providers Test button all
  go through `probe.py`, and only the button spends.
```

- [ ] **Step 10: PROVENANCE — record the dashboard's design influence**

Append one row to the table in `PROVENANCE.md`. The Global Constraints require it: the dashboard is the
part of this project whose *UX* was studied in a donor, and "studied" is only a footnote until it is
written down.

```markdown
| Control dashboard (`kira-chat/src/screens/*`, `confirm.tsx`, `useWrite.ts`, `overrides.py`,
`probe.py`, the derived-spend aggregates in `store.py`) | FreeLLMAPI dashboard
(`Source code/freellmapi-main.zip`) — screen list, per-provider spend and key management UX | MIT | no |
```

Keep the existing "Not yet ported" note about FreeLLMAPI's free-provider catalogue: the dashboard
borrowed a *layout*, and the decision to refuse the provider pool is unchanged and still the reason
`GET /v1/models` lists only your own config.

Run: `grep -c "freellmapi-main" PROVENANCE.md`
Expected: `1`. One row, one citation; if a second appears later it must name a different module.

- [ ] **Step 11: The launcher names the screens**

In `run_kira.py`, `open_when_ready()` — the two branches that print `opened {url}` and `chat UI: {url}` —
leave both branch bodies alone and add one line after them, still inside `if resp.status == 200:` and
before `return`, so `--no-browser` gets it too. The block ends looking like this:

```python
                if resp.status == 200:
                    say(f"engine is up at {base}")
                    if browse:
                        webbrowser.open(url)
                        say(f"opened {url} - paste the token into the connect screen")
                    else:
                        say(f"chat UI: {url}")
                    # One line for both branches: the dashboard is why most people start Kira now, and
                    # a route the launcher never mentions is a route nobody finds.
                    say("screens: #/overview #/providers #/models #/sessions - each write re-asks for the confirm secret")
                    return
```

ASCII hyphens, not em dashes: the launcher runs under whatever console the double-click gives it, which
is exactly why `serve()` sets `PYTHONUTF8` for the child and not for itself.

And extend the module docstring's flag line so it names what the first run now prints:

```python
Flags: --port N  --no-browser  --rebuild  --skip-keys
On first run it prints the browser token and the dashboard confirm secret once each; both come from the
Windows Credential Locker (service `kira`), and `kira-engine token` reprints them.
```

- [ ] **Step 12: Prove the launcher's lines by hand, quarantined**

A memory vault and a scratch data dir, so nothing reaches the real Locker or the real history:

```
mkdir -p /tmp/kira-launch
KIRA_DATA_DIR=/tmp/kira-launch KIRA_VAULT=memory python run_kira.py --skip-keys --no-browser --port 8913
```

Expected, in order: `providers: openrouter, groq, anthropic, gemini` (the sample config it just wrote),
`skipping key entry for: … (--skip-keys)`, then

```
[kira] secrets: copy the 'engine token' and 'confirm secret' lines below (a memory vault is per-process)
```

then `serving http://127.0.0.1:8913 (loopback only) - Ctrl+C stops`, `engine is up at
http://127.0.0.1:8913`, `chat UI: http://127.0.0.1:8913/chat/`, the new `screens: #/overview …` line, and
the engine's own two `first run` stderr lines carrying the values. Ctrl+C → `stopping engine...` and a
clean exit; then `rm -rf /tmp/kira-launch`.

The `keyring` branch is **not** run here, on purpose: it would mint `engine/token`, `engine/confirm` and
a real provider entry in your Credential Locker for a config you are about to delete. That branch's CLI
half is covered by `test_the_token_command_keeps_stdout_to_the_bearer_token` (Task 11) and its launcher
half by the owner's own next double-click — say so in the commit message if it comes up, rather than
implying a proof that did not happen.

- [ ] **Step 13: Checkpoint**

Run from `Kira/`: `cd kira-engine && .venv/Scripts/python.exe -m pytest -q && cd ../kira-chat && npm run check && cd .. && node kira-contracts/check-drift.mjs`
Expected: engine `180 passed, 1 skipped`; client all green with the totals you pasted into `Checks`;
`kira-contracts OK — v2, …, 9 chain events`.

Run from `Kira/`: `grep -rn "localStorage" kira-chat/src/`, `grep -rniE "localStorage\.(set|get)Item\(\"?(confirm|key)" kira-chat/src/` and `grep -rn "DELETE ALL" kira-chat/src/api.ts`
Expected: the first lists only `App.tsx`'s `kira.base` / `kira.token` reads and writes (three lines, the
gate that already ships); the second and third produce no output. That is exactly the narrowed claim the
README section makes — provider keys and the confirm secret never reach web storage, the loopback bearer
token does, on purpose (amendment 24) — and a grep is the check for both halves.

Read the finished README once against the running lab you are about to build in Task 20 and cross out
any sentence you cannot point at on screen.

If git is initialised: `git add README.md PROVENANCE.md run_kira.py kira-engine/tests/test_docs_match_engine.py && git commit -m "docs: make the README match the dashboard, and keep it matching"`

Documentation now has a gate instead of a memory. Task 20 spends the pass that every checkpoint in this
plan has been deferring: all five screens, in a real browser, against a real engine, with a cap that
actually bites — and a mock provider so that "real" does not mean "expensive".

**Executed (2026-10-28).** `tests/test_docs_match_engine.py` went in first and failed 4, exactly the way
Gap 20 predicted it should; the README was then rewritten in eight places until all four passed. Engine went
187 → **191 passed, 1 skipped**, client stayed at **87 passed / 11 files**, drift gate `v2, 39 schemas, 5
chunk types, 9 chain events`. The endpoint table is 16 API rows + the shell row and the test now diffs it
against `harness.app.routes` both ways; the provenance sentence carries all nine event names; the CLI table
is the only place verbs are named and `kira keys set` — the binary that never existed — is gone;
`Checks` names `npm run check` instead of `npm test` (Gap 21). `PROVENANCE.md` gained the dashboard's
FreeLLMAPI row and `grep -c "freellmapi-main"` is `1`. The launcher prints the `screens: …` line under
`--no-browser` too, proven on a `KIRA_VAULT=memory` run against a scratch data dir which was then deleted —
the keyring branch was deliberately not run, per Step 12. Steps' own predictions drifted in six places
(79-84): two of the four failing checks reported less than expected (79), `tools/` cannot be documented before
Task 20 creates it (80), the localStorage grep returns eight lines in two files rather than three (81), three
quoted UI strings in Step 7 do not exist and were replaced with the shipped ones (82), two accurate
parentheticals survived Step 5's rewrite (83), and Step 12's expected lines differ by the version suffix and
an unobserved farewell (84). Reading the README against the running lab waits for that lab (85).

## Task 20: The live pass — five screens, a real engine, no real money

Every checkpoint in this plan has been a command. The spec's M12 acceptance is not: "all five screens
usable against a real engine; docs match behavior". Nineteen tasks of jsdom and ASGI-in-process tests
have proven that each part behaves; what none of them prove is that the bundle the browser actually
loads, talking HTTP to a uvicorn that is a separate process, with a hash route and a static mount, is
the dashboard that was designed. That gap is the one ALTREX shipped with — 683 passing tests and every
live provider marked `NOT TESTED, calls: 0` — and Kira's standing answer to it is a recorded run.

**Gap 22, found while planning this task:** the pass cannot honestly be run against your own install. A
turn through a real provider spends credits you did not budget for; a scratch `config.yaml` with real
`key_ref`s mints entries in the Windows Credential Locker that outlive the experiment; a scratch run that
shares `.kira-data` deletes the owner's history through the Sessions screen it is testing. And a pass you
can only do once, wrong, is not a pass — it is a story. So this task adds two checked-in dev tools:
`tools/mock_openai.py` (a scripted OpenAI-compatible provider, stdlib only) and `tools/kira_lab.py`
(engine + mock + memory vault + throwaway data dir, in one command). Nothing in either is imported by the
product or the test suite, and no new dependency is added: the lab uses `uvicorn`, which `serve` already
requires.

**Gap 23, from Task 15's open note:** `Router.events()` re-yields `plan.notes` on every step of a
multi-step tool turn, so one skipped provider prints its chip twice. Task 15 declined to fix it because
the fix rewrites the expected chain of every tool test. It is reproducible here, and cheaply — the engine
registers the `echo` demo tool by default (`app.py:127`-ish, `ToolRegistry` + `register_demo_tools`),
`tools_enabled` defaults to `True` server-side and the client never sends it, and the mock can emit a tool
call on a marker word. So the pass records it as *observed*, with the chip count, instead of as a
rumour.

**Files:**
- Create: `kira-engine/tools/mock_openai.py`
- Create: `kira-engine/tools/kira_lab.py`
- Create: `docs/qa/dashboard-browser-pass.md` (the record, written from what the screen showed)
- Modify: `README.md` (the `docs/qa/` line in the tree, which Task 19 deliberately left out because the
  directory did not exist yet, plus a `### The browser-pass lab` subsection)

**Interfaces:**
- Consumes: `OpenAICompat.list_models()` expecting `{"data": [{"id": …}]}` and `.stream()` expecting
  `data:` SSE lines with `choices[].delta.content`, `choices[].finish_reason` and a `usage` chunk
  (`providers/openai_compat.py:44-115`); `parse_arguments` wanting a JSON object string
  (`providers/base.py:51`); `Engine(config, *, vault=…, http_client=…, store=…)` (`app.py:110`) and
  `create_app(config, engine=…)` (`app.py:138`); `chat_dist_dir()`'s `KIRA_CHAT_DIST` override
  (`app.py:103`); `load_config(data_dir)`; `Vault("memory")`; `engine.token` and `engine.confirm`
  (Task 11); `say()`-free stderr printing, because the lab is not the launcher.
- Produces: `mock_openai.serve(port) -> ThreadingHTTPServer` and `kira_lab.main() -> int`. Nothing
  imports them; they are run.

- [ ] **Step 1: The mock provider**

Create `kira-engine/tools/mock_openai.py`:

```python
"""A scripted OpenAI-compatible provider, for checks that must not cost anything.

Stdlib only, loopback only, no persistence and no upstream: every answer is the same
canned text with the same token counts, so a monthly cap can be hit on a turn you can
predict. The whole point is that "real engine" and "real money" are different things -
the engine believes it is talking to a provider, and nothing is billed.

Run: .venv/Scripts/python.exe tools/mock_openai.py [port]     (default 8999)
Or import it: mock_openai.serve(8999) starts it on a daemon thread.

The text arrives in one read, not one character at a time: this is a scripted provider,
not a latency simulator, and a pass that measures smoothness proves nothing.
"""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ANSWER = "mock answer, scripted by tools/mock_openai.py"
TOOL_ANSWER = "the tool round trip came back"
#: Fixed, so `used + 1` as a cap is a turn you can plan.
USAGE = {"prompt_tokens": 100, "completion_tokens": 50}
MODELS = ["mini", "small"]
#: A prompt containing this word gets a tool call first, which is how the pass reaches a
#: multi-step turn and sees Router.events() re-yield its skip notes.
TOOL_MARKER = "TOOL"
TOOL_ARGS = '{"text": "echo round trip"}'


def text_chunks(text: str) -> list[dict]:
    chunks = [{"choices": [{"index": 0, "delta": {"content": word + " "}}]} for word in text.split()]
    chunks.append({"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}], "usage": USAGE})
    return chunks


def tool_call_chunks() -> list[dict]:
    return [
        {
            "choices": [
                {
                    "index": 0,
                    "delta": {"tool_calls": [{"index": 0, "id": "call_lab_1", "type": "function", "function": {"name": "echo", "arguments": ""}}]},
                }
            ]
        },
        {"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0, "function": {"arguments": TOOL_ARGS[:12]}}]}}]},
        {"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0, "function": {"arguments": TOOL_ARGS[12:]}}]}}]},
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
    ]


def reply_for(payload: dict) -> list[dict]:
    """A turn that already carries a tool result is the loop's second step: answer it."""
    messages = payload.get("messages") or []
    if any(m.get("role") == "tool" for m in messages):
        return text_chunks(TOOL_ANSWER)
    last_user = next((m for m in reversed(messages) if m.get("role") == "user"), {})
    if TOOL_MARKER in str(last_user.get("content") or ""):
        return tool_call_chunks()
    return text_chunks(ANSWER)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:  # a pass reads the UI, not access logs
        return

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("content-type", content_type)
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path.rstrip("/").endswith("/models"):
            data = {"object": "list", "data": [{"id": m, "object": "model"} for m in MODELS]}
            self._send(200, json.dumps(data).encode(), "application/json")
            return
        self._send(404, b'{"error":{"message":"mock serves /v1/models only"}}', "application/json")

    def do_POST(self) -> None:
        if not self.path.rstrip("/").endswith("/chat/completions"):
            self._send(404, b'{"error":{"message":"mock serves /v1/chat/completions only"}}', "application/json")
            return
        length = int(self.headers.get("content-length") or 0)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._send(400, b'{"error":{"message":"mock needs a JSON body"}}', "application/json")
            return
        body = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in reply_for(payload)) + "data: [DONE]\n\n"
        self._send(200, body.encode(), "text/event-stream")


def serve(port: int = 8999) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)  # loopback only, like the engine
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


if __name__ == "__main__":
    wanted = int(sys.argv[1]) if len(sys.argv) > 1 else 8999
    print(f"[mock] http://127.0.0.1:{wanted}/v1  models={MODELS} usage={USAGE} marker={TOOL_MARKER!r}", file=sys.stderr)
    serve(wanted).serve_forever()
```

The `answer` is fixed and the usage is fixed, which is what makes Step 6's arithmetic a plan rather than
a guess: one turn costs 150 tokens against `monthly_spend`, which sums `input + output` over stored
assistant rows (Task 6), including the `interrupted` and `failed` ones.

- [ ] **Step 2: The lab**

Create `kira-engine/tools/kira_lab.py`:

```python
"""Everything a browser pass needs, in one command, with nothing real at stake.

A fresh temp data directory, a memory vault seeded with two fake provider keys, the
mock provider on loopback, and the engine serving the built chat bundle. Both secrets
are printed, because the whole point is that they are disposable. Ctrl+C removes the
temp directory; --data-dir keeps a run so you can come back to the same history - or
change --models and see what the Models screen does with a model that is gone.

Run: .venv/Scripts/python.exe tools/kira_lab.py [--port 8912] [--mock-port 8999]
                                        [--models mini,small] [--data-dir PATH]
"""

from __future__ import annotations

import argparse
import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import mock_openai  # noqa: E402  (same directory, by design: neither is a package)

from kira.app import Engine, create_app  # noqa: E402
from kira.config import load_config  # noqa: E402
from kira.vault import Vault  # noqa: E402

CONFIG = """\
host: 127.0.0.1
port: {port}
default_mode: FAST
max_agent_steps: 6
request_timeout_s: 30

providers:
  - name: mock_one
    kind: openai_compat
    base_url: http://127.0.0.1:{mock_port}/v1
    tier: fast
    key_ref: provider/mock_one
    priority: 10
    models: [{models}]
  - name: mock_two
    kind: openai_compat
    base_url: http://127.0.0.1:{mock_port}/v1
    tier: fast
    key_ref: provider/mock_two
    priority: 20
    models: [{models}]
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Kira dashboard lab (mock provider + scratch engine)")
    parser.add_argument("--port", type=int, default=8912)
    parser.add_argument("--mock-port", type=int, default=8999)
    parser.add_argument("--models", default="mini,small", help="comma-separated model ids offered by both providers")
    parser.add_argument("--data-dir", help="reuse this directory instead of a temp one, and keep it")
    args = parser.parse_args()

    dist = Path(os.environ.get("KIRA_CHAT_DIST") or ROOT / "kira-chat" / "dist")
    if not (dist / "index.html").exists():
        print(f"[lab] no chat bundle at {dist} - run: cd kira-chat && npm run build", file=sys.stderr)
        return 2
    os.environ["KIRA_CHAT_DIST"] = str(dist)

    if args.data_dir:
        data_dir = Path(args.data_dir)
        data_dir.mkdir(parents=True, exist_ok=True)
        keeps = "kept - it is yours to delete"
    else:
        data_dir = Path(tempfile.mkdtemp(prefix="kira-lab-"))
        atexit.register(shutil.rmtree, data_dir, True)
        keeps = "temp, deleted on exit"

    (data_dir / "config.yaml").write_text(
        CONFIG.format(port=args.port, mock_port=args.mock_port, models=", ".join(args.models.split(","))),
        encoding="utf-8",
    )

    mock_openai.serve(args.mock_port)

    vault = Vault("memory")
    vault.set("provider/mock_one", "lab-key-one")
    vault.set("provider/mock_two", "lab-key-two")
    config = load_config(data_dir)
    engine = Engine(config, vault=vault)
    app = create_app(config, engine=engine)

    def note(line: str) -> None:
        # stderr, so stdout stays free for anything that pipes the lab later.
        print(f"[lab] {line}", file=sys.stderr, flush=True)

    note(f"mock    http://127.0.0.1:{args.mock_port}/v1 models={args.models} usage={mock_openai.USAGE}")
    note(f"data    {data_dir} ({keeps})")
    note(f"chat    http://127.0.0.1:{args.port}/chat/")
    note(f"token   {engine.token}")
    note(f"confirm {engine.confirm}")
    note("every secret here is disposable; a memory vault is per-process and shares nothing with your Locker")

    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

`Vault("memory")` is not an approximation of the real thing where it matters: it is the same class, the
same `get_or_create_engine_token()` path, the same `engine/confirm` mint, and the same
`secrets.compare_digest` gate. What differs is only the storage, and the storage is the part that must
not be touched by an experiment.

- [ ] **Step 3: Smoke it over HTTP before any browser is involved**

```
cd kira-engine && .venv/Scripts/python.exe tools/kira_lab.py --data-dir /tmp/kira-lab
```

The `--data-dir` is not a nicety: Step 9 restarts this same lab with one model removed and reads the history
back out of it, so the pass needs a directory that survives the first process. Without the flag the lab takes
a `tempfile.mkdtemp` and deletes it on exit — worth knowing, so after Step 12 you will run it once with the
flag omitted and watch the `[lab] data …  (temp, deleted on exit)` line and the gone directory.

Expected on stderr: the engine's own two `first run` lines (`[kira] first run — engine token …` and,
after Task 11, the confirm-secret one) and then the five `[lab]` lines. The duplication is correct and is
not a bug to fix: a fresh memory vault means `Engine.__init__` minted the token itself, and the lab's
lines exist so the values are still readable after uvicorn's own output. Nothing is written to the
Credential Locker, because the vault the lab hands to `Engine` is `Vault("memory")`. Then, in another
shell, substituting the printed values:

```
curl -s http://127.0.0.1:8912/healthz
curl -s -H "Authorization: Bearer <token>" http://127.0.0.1:8912/v1/models
curl -s -H "Authorization: Bearer <token>" -H "content-type: application/json" \
  -d '{"messages":[{"role":"user","content":"smoke"}],"stream":false}' \
  http://127.0.0.1:8912/v1/chat/completions
curl -s -H "Authorization: Bearer <token>" "http://127.0.0.1:8912/v1/kira/overview"
```

Expected: `{"ok":true,"contract_version":2,"providers_configured":2,"default_mode":"FAST"}`; a `data`
array of four entries (`mini`/`small` under both `mock_one` and `mock_two`, each with `provider` and
`tier`); a completion whose content is the mock's answer and whose usage is 100/50; and an overview whose
`turns` is `1`, whose `tokens` is `{"input": 100, "output": 50}`, and whose `by_provider` contains
`{"provider": "mock_one", "turns": 1, "tokens": 150}` with no `mock_two` row yet. If the third call
instead reports `providers_exhausted`, the lab's vault keys did not reach the registry — check the
`key_ref` values in `CONFIG` against the refs `vault.set()` writes, in that order.

- [ ] **Step 4: Chat and Overview in the browser**

Open `http://127.0.0.1:8912/chat/` (use the browser driver this session has — `browser-use` MCP tools
`navigate_page` / `take_snapshot` / `click` / `fill` are enough, and `take_screenshot` is optional
evidence you should not commit). Paste the `[lab] token` value into the connect screen. Expected:
the rail with five items, the connection dot green, and a contract version that is not a mismatch
warning. If the screen says the engine speaks contract v2 and the client speaks v1, stop: the bundle
being served is stale, and `npm run build` is the fix — a pass on an old bundle proves nothing.

Then, in order, and writing down what the screen actually said:

1. Send `first turn` in `#/chat`. The answer streams (all at once, from the mock), the turn's chain shows
   `attempt mock_one` then `served mock_one`, and the usage line is non-zero.
2. Send `second turn`. Same shape. Note the session id the chat sidebar shows — it is an eight-character
   prefix, while `#/sessions` prints the whole id, so Step 9 matches them on the prefix and writes down
   whether that was easy.
3. Go to `#/overview`. Expected: the current month's label, non-zero turns / tokens / success rate, and
   the Budgets section listing both providers — `mock_one` reading `300 tokens · no cap` (two turns at the
   mock's fixed 100 in / 50 out) and `mock_two` reading `0 tokens · no cap`. An uncapped row still shows its
   spend; only the percentage is meaningless, which is why the unlimited branch prints a number at all. Then
   `mini` in top models, a daily series of exactly one day, and **no** entries in the recent-trouble list.
4. Refresh with `#/overview` in the address bar. Expected: still Overview. The route survives, which is
   what makes `#/providers` a link a refusal can point at.
5. On `#/providers`, read `mock_one`'s spend cell. Expected: the same number `#/overview` accounts for
   (its Budgets `used` for `mock_one`, which is `spend_this_month` from the one derived read — Task 9's
   single `monthly_spend` map). Two screens, one number; this is the claim Task 9 exists to make, and it is
   worth checking in a browser because the two endpoints build that column in different functions.

- [ ] **Step 5: Providers — a write, a refused write, and a cap that is about to bite**

On `#/providers`, for `mock_one`:

1. Click `test mock_one`. The dialog summary is `test mock_one` and its detail names the route and says it
   spends about 8 tokens; type the confirm secret **wrong** first. Expected: the dialog re-opens with the
   reason in its detail line, ending `the engine refused that secret; type it again`, and no result row
   appears. Then type it correctly. Expected: a result row reading `2 models · <N>ms` (the mock publishes
   `mini` and `small`, and a completion round trip is timed). The row shows count and latency only — Task 14
   deliberately does not render `sample` in the table, so if you expect a model list here you are remembering
   `ModelsScreen`, not this cell. And afterwards `mock_one`'s spend is **unchanged** at 300: a diagnostic is
   not a conversation and must not enter the month (Task 7).
2. Read `mock_one`'s spend as a number (Step 4 left it at 300 — two turns of 150). In the `monthly cap
   mock_one` box type **spend + 1** = `301`, then click `set cap mock_one`; the dialog summary reads
   `cap mock_one at 301`. Confirm with the secret. Expected: the box holds `301`, a dimmed
   `was unlimited` line appears under it because an override now exists, and `clear override mock_one`
   becomes enabled. Providers shows the *setting* here, not the ratio — `300 / 301` is Step 6's Overview
   string.
3. Toggle `enabled mock_one` off and back on, watching the ledger column and `/v1/models` on the chat
   side. Expected: while off, `mock_one` disappears from the chat's model select — one merged view, no
   restart, as Task 5 designed.
4. Set `priority mock_two` to 5 and confirm. Expected: `mock_two` is now the first candidate, so the next
   turn answers from it. Set it back to 20 afterwards, or Step 6's failover will not look like failover.

- [ ] **Step 6: The one turn of slack, then the skip — three surfaces, one fact**

Go to `#/chat` and send `third turn`. Expected, and this is the whole point of the exercise: the turn
**still succeeds through `mock_one`**. The plan was made when `used` was 300 and the cap was 301, so
`mock_one` was not at cap yet; the spend it books this turn (150) puts it over afterwards. That is
amendment 15's rule 4 happening live, and it is why no UI in this product may promise "exactly N tokens
left".

Now send `fourth turn`. Expected:

- The answer comes from `mock_two`: the chain carries `skipped_budget` for `mock_one` — labelled **over
  budget**, in the same muted tone as `skipped_cooling`, with the reason `used 450 of 301 tokens in
  <this month>` — then `attempt mock_two`, then `served mock_two`. That reason string is the only place the
  chip tells you *why* the router stood it down, so read it and check the numbers against Overview.
- `#/providers`: `mock_one`'s cap cell shows the `301` override with its dimmed `was …` line underneath, and
  its spend column reads `450` — above the number you just typed. That is all this screen says. There is no
  bar and no `at cap` badge here: Task 16 gave Providers a static enforcement sentence, and the badge lives
  on Overview. Read the sentence and confirm it is *true* of this row; if the spend-vs-cap arithmetic is not
  obvious enough for a human to spot without a badge, write that in Findings as a follow-on for the spec. Do
  not add a column to a screen during a proof.
- `#/overview`: the `mock_one` bar reads `450 / 301 · at cap` in the over-cap class, and below the bars the
  sentence names `mock_one` as having used all of the month's cap, with the link `raise a cap in Providers`,
  plus the caveat that the count comes from stored turns. The link must land on `#/providers` when clicked —
  follow it once, in the browser, because "the href is `#/providers`" is a unit-test claim and this is the
  claim that a human can act on.
- The screens agree on one number. `450` should be the same in the Overview bar, the Providers spend column,
  and what the chain's usage line for the third turn adds up to. If Overview says 450 and Providers says 300,
  that is a finding for Task 9/16, not something to note in the record and move past.

- [ ] **Step 7: Both capped — the refusal, and what a refusal leaves behind**

Set `mock_two`'s cap to `1` and confirm (its spend is already above that, so it is at cap immediately —
no slack to wait through). Send `fifth turn`. Expected: no answer, an error in the turn whose text is the
engine's `budget_exhausted` message, and the `raise a cap in Providers` link beside it, because Task 16
folds the refusal's chain into the turn instead of dropping it.

Then check what the engine stored, because this is where the pass earns its keep:

- `#/overview`'s recent-trouble list stays **empty**, and neither provider's spend grows.
- `#/sessions` gains **nothing** — no new row and no message inside the old ones. `plan()` raises at
  `app.py:176`, one line *before* `create_session`, so the question is never filed; Task 15's
  `test_a_refused_turn_stores_nothing` asserts exactly that with `session_rows() == []`.
- Prove the local/engine split you can see on screen: refresh the page and reconnect. The refused turn is
  **gone** from `#/chat`, because it only ever existed in React state. Then open a session that did reach a
  provider and see its turns come back from the engine.

Write that down as observed behaviour with its reason. A refusal is fully visible in the chat and completely
invisible to the engine: no tokens were spent, so the cap arithmetic stays honest, but there is also no
record that anyone was refused — no trouble row, no session, nothing in a month's review that says "you hit
the ceiling five times". That asymmetry is a design consequence worth revisiting (a refusal counter would
live outside the message table, since a message row is what it refuses to write). Record it as a follow-on
for the spec's next revision; do not "fix" it inside a proof.

- [ ] **Step 8: A tool turn, to see the note repetition for real**

Raise `mock_two`'s cap (set it to a number above its spend, or clear the override), and send a prompt
containing the word `TOOL` — the mock answers it with an `echo` tool call, the loop executes the demo
tool, and the second step re-enters `Router.events()`. Expected, with `mock_one` still at cap:

- The final text is `the tool round trip came back` — the mock answers any prompt containing `TOOL` with an
  `echo` call, and answers the step after a `role=tool` message with that sentence.
- The chain, read top to bottom, is `over budget` (mock_one) → `attempt mock_two` → `tool_executed echo` →
  `over budget` (mock_one) **again** → `served mock_two`. Two copies of one skip note, one per plan entry.
- Read `mock_two`'s spend before and after. One user turn cost **300** tokens, not 150: two completions, each
  with the mock's fixed 100/50. That is amendment 15's rule 4 from the money side, and it is the reason
  Overview's bar can sit just under a cap and cross it inside a single turn.

That is the `Router.events()` defect from Task 15's note, observed rather than described: the notes are
re-yielded per step, so a multi-step turn repeats its skips. Record the exact chip sequence in the QA
file with a pointer to `router.py`'s `events()`, and state that fixing it means rewriting the expected
chain of every tool test — which is why it is a decision for the spec, not a stray edit in a pass.

- [ ] **Step 9: Models and Sessions, including the row that is no longer configured**

Still on the first run: on `#/models`, expect four rows — both providers × both models — each with its tier
and its turns/tokens for the month, `0` where a model never served, and the sentence
`Adding or renaming a model means editing config.yaml and restarting the engine — there is no field here on
purpose`. Read the footnote too: it says the counts include interrupted and failed turns, which is why the
numbers from Step 4 onward are the month's whole truth and not a success-only tally. Assert with your eyes
that the table has **no** input or select in it — the only control in the last column is
`use in chat <model>`. Click it on `mini` and expect the composer's model select on `#/chat` to read `mini`.
While you are on `#/chat`, look at that select: it renders four options, each labelled
`<id> · <provider> · <tier>`, so the provider is named even though the option *value* is the bare id and the
two providers collide there. Note what that means in practice — picking a model does not pin a provider, and
the engine still chooses by mode and priority. Write down whether the chain you get after `use in chat mini`
makes that visible to a human; if it does not, it is a finding for the spec, not something to fix mid-pass.

Before the restart, one more thing: set the composer's model select to `small` and send `modelled turn`.
Expected: it is served, and `#/models` now has a `small` row with one turn and 150 tokens against whichever
provider answered — Step 8 left `mock_one` at cap, so read the row rather than assuming. This is not padding.
The retired row in the next paragraph only exists if the month has a **stored turn** naming `small`, and
`by_model` is built from stored rows; without this turn, `--models mini` would simply drop a row that had
always shown `0`, and the pass would prove nothing about amendment 16.

Then stop the lab (Ctrl+C) and start it again against the same history, with one model removed:

```
.venv/Scripts/python.exe tools/kira_lab.py --data-dir /tmp/kira-lab --models mini
```

Use the **new** `[lab] token` line — a memory vault is per-process, so the old value is gone and the
connect screen needs the fresh one. Expect on `#/models`: a row for `small` under the provider that served it
above, marked `no longer configured`, tier `—`, its turns and tokens still counted, and no `use in chat`
button — only the `provider/model` key in the last column. Write down which provider it names.
That is amendment 16's rule seen from the outside: a rename in YAML must not delete a month of spend from
the screen that reports it.

Then `#/sessions`. Expect **more than one** row, and count them before you judge it: Step 4's address-bar
refresh dropped the client's in-memory session id — `sessionId` is a `useState`, and nothing may persist it —
so the first turn after that refresh opened a new session. Write down how many sessions the five or six turns
produced and whether the split is what you expect from a product that reloads to a fresh chat; if it is not,
that is a finding about the connect flow, not about this screen.

Click `transcript <id>` on the session that holds the Step 6 turns and expect both turns with their chips
(`over budget` among them, because `ChainTrace` here reads the `chain` field Task 9 put on each message row)
and per-turn token counts. Then `delete <id>` on the *other* session: the dialog summary must name the id and
its message count — read it before confirming, and record whether the naming made it obvious what was about to
go. After confirming, that id is gone from the table *and* from the chat sidebar on the next read, and the
session you did not delete still holds every turn it had.

Then `delete every session`: type `delete all` (wrong case) and
`DELETE ALL ` with a trailing space and expect the submit to stay inert both times; type the exact words
and confirm, and expect the table, the Overview numbers and the chat sidebar to all empty on the next
read.

- [ ] **Step 10: The record**

Create `docs/qa/dashboard-browser-pass.md`. Fill every row from the screen, not from this plan; a row you
did not observe says `not exercised` with the reason, and a row that matched what was expected says so
plainly. Template:

```markdown
# Dashboard browser pass — <UTC date>

Engine: `tools/kira_lab.py` on `http://127.0.0.1:8912`, mock provider
`tools/mock_openai.py` on `http://127.0.0.1:8999`, data dir `<path>` (memory vault, nothing in
the Credential Locker, nothing in `.kira-data`).

| # | Check | Observed | Verdict |
| --- | --- | --- | --- |
| 1 | connect + contract v2 + five nav items | | |
| 2 | chat turn streams, chain = attempt + served, usage non-zero | | |
| 3 | Overview numbers equal Providers numbers | | |
| 4 | route survives a refresh | | |
| 5 | wrong confirm secret re-asks with the reason | | |
| 6 | Test spends nothing: spend unchanged after a probe | | |
| 7 | cap = spend + 1 still routes (one turn of slack) | | |
| 8 | next turn: `over budget` chip, failover to mock_two | | |
| 9 | Overview `450 / 301 · at cap` + sentence + working link; Providers shows the same number with no badge (finding if that reads as unclear) | | |
| 10 | both capped: `budget_exhausted` + link in chat, no spend, no trouble row, nothing stored (the turn vanishes on refresh) | | |
| 11 | tool turn: skip note twice + `tool_executed`, and one user turn billed 300 | | |
| 12 | Models: no editable cell, `use in chat` hops | | |
| 13 | Models: removed model shown as `no longer configured`, no button | | |
| 14 | Sessions: how many sessions the turns made, transcript chips, delete one names id + count | | |
| 15 | clear-all inert until the exact `DELETE ALL` | | |
| 16 | after clear-all, every screen empty | | |

## Not exercised, and why
- The launcher's `keyring` branch (it would mint real Locker entries for a throwaway config).
- A real provider call. The only live paths in this product are `KIRA_LIVE=1`, `?live=true`,
  `kira-engine models` and the Test button, and none of them were used here.
- Concurrent windows (two tabs writing the same provider). `useWrite`'s busy flag is per screen.

## Findings
- <a plan-time refusal writes nothing at all — `plan()` raises before `create_session` — so no screen can
  report that you were refused; Task 15's `test_a_refused_turn_stores_nothing` is the unit proof>
- <Router.events() repeats skip notes on multi-step turns — Task 15's note, now observed>
```

- [ ] **Step 11: README — the lab and the record**

Add the tree line Task 19 left out, now that the directory exists:

```
docs/qa/         records of checks that only a real run can make
```

And under `### Developing the UI separately`, add (the outer fence is four backticks because this block
contains a three-backtick block — Task 19 used the same convention):

````markdown
### The browser-pass lab

```bash
cd kira-chat && npm run build          # once — the engine serves kira-chat/dist
cd ../kira-engine
.venv/Scripts/python.exe tools/kira_lab.py --data-dir /tmp/kira-lab
```

`tools/kira_lab.py` runs the real engine against `tools/mock_openai.py` — a scripted provider with fixed
150-token answers — with a memory vault, so it spends no credits, touches no Credential Locker entry and
cannot reach your history. That is the only way a dashboard pass can be run more than once. `--data-dir`
keeps the history for a second start; restart with `--models mini` and the Models screen shows a
`no longer configured` row for a model the catalogue no longer offers. Omit `--data-dir` and the lab makes a
temp directory and deletes it on exit. Both secrets are printed on stderr because both are disposable.
The pass itself is recorded in `docs/qa/dashboard-browser-pass.md`.
````

The `npm run build` line is the README's only honest confession that the lab needs a bundle: without
`kira-chat/dist/index.html` the lab exits with code 2 and a line telling you to run it. Say that in prose
rather than pretending the lab builds the UI itself.

- [ ] **Step 12: Checkpoint — M12 done, sub-project 9 done**

Stop the lab, then:

```
rm -rf /tmp/kira-lab
ls -la .kira-data
```

Expected: `config.yaml` and `logs/` and **no `kira.db`** — compare against what you listed before Step 3
and require the same two entries. If a `kira.db` appeared, something in Steps 3-11 wrote to the real data
dir; find it (the usual cause is running `kira-engine serve` without `--data-dir` instead of the lab) and
note it in the record as a mistake made and corrected, not omitted.

Run from `Kira/`: `cd kira-engine && .venv/Scripts/python.exe -m pytest -q && cd ../kira-chat && npm run check && cd .. && node kira-contracts/check-drift.mjs`
Expected: engine `180 passed, 1 skipped` — this task adds no engine or client code, which is the point of
a pass; client unchanged; `kira-contracts OK — v2, …`.

Run from `Kira/`: `grep -rn "127.0.0.1" kira-engine/tools/`
Expected: every socket the lab and mock bind, and no `0.0.0.0`. An experiment that listens on all
interfaces is not an experiment, it is an exposure.

**M12 acceptance (spec):** all five screens usable against a real engine — Steps 4 to 9, recorded with
what the screen showed. Docs match behaviour — Task 19's four checks are in the suite and green, and the
README sections the pass exercised (`Two secrets`, `The dashboard`, the endpoint table) were read against
the running product, not against this plan.

If git is initialised: `git add kira-engine/tools docs/qa README.md && git commit -m "test(qa): browser pass over all five screens against a scripted provider"`

Sub-project 9 ends here. What it deliberately did not take on, restated so the next sub-project starts
with a clean sheet: tools and the harness (sub-project 2), the desktop shell (3), memory (4), a local
model tier (5), and the two follow-ons this pass wrote down — a plan-time refusal that no screen reports,
and a chain of skip notes that repeats itself once per agent step.

**Executed (2026-10-28).** All twelve steps, in a real browser, across three lab processes against one
disposable data directory: `kira_lab.py` + `mock_openai.py` on `127.0.0.1:8912`/`:8999`, connected by
seeding `kira.base` and `kira.token` and driving the page in-page (amendment 70's recipe, extended by
87-88). Steps 3-9 were read twice — once on the first process, whose numbers start one turn high because
the Step 3 `curl` turn is stored (86), and once on a fresh process at cap `151` over spend `150`, which
reproduced the planned `used 300 of 151`, the `300 / 151 · at cap` bar, the `over budget` failover, the
`budget_exhausted` refusal that stores nothing, and the tool turn with its skip note printed twice.
Step 8 needed the mock to send `usage` on the tool-call completion before its 300-token claim came true
(90). The restart with `--models mini` showed `small / no longer configured / mock_two / — / 1 / 150` with
no button, and `#/sessions` turned 8 turns into 6 sessions (92), deleted one with a dialog that named the
id and its 2 messages, and stayed inert for `delete all` and `DELETE ALL ` until the phrase was exact.
Recorded in `docs/qa/dashboard-browser-pass.md`: 16 rows, all filled from screens, plus five
not-exercised cases and twelve findings — including two the pass can only hand to the spec (a refusal no
screen reports; a chain that repeats its skips) and two it found on the way (`delete every session`
re-arms every cap, 93; a provider that omits `usage` under-reports the month, 90). README gained the
`  tools/` and `docs/qa/` lines and `### The browser-pass lab`, with the temp-directory sentence
corrected to what a killed process actually does (94). Checkpoint: engine **191 passed, 1 skipped**,
client **87 passed / 11 files** and an unchanged build — no product code moved, which is the point of a
pass — drift `v2, 39 schemas, 5 chunk types, 9 chain events`, the three storage greps holding, every
socket in `tools/` on loopback, and `.kira-data` still only `config.yaml` and `logs/`. M12 is done;
sub-project 9 ends here.

<!-- APPEND-10 -->

