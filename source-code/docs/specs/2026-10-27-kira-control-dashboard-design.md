# Kira control dashboard — design spec

Date: 2026-10-27
Status: approved 2026-10-27 (user reviewed the spec and accepted the separate `engine/confirm` secret)
Sub-project: 9 (control surface). Builds on sub-project 1 (`2026-10-27-kira-spine-design.md`), which is complete.
Reference studied: FreeLLMAPI dashboard structure (`Source code/freellmapi-main.zip`) — screens and UX mechanisms only; no code copied, see `PROVENANCE.md`.

## Goal

Give the single human owner of one Kira install a browser control surface where they can see
what Kira spent and on which provider, add or forget a provider key, enable/disable and
re-prioritise providers, set a monthly token ceiling that the router actually enforces, and read
or delete stored history — without leaving the tab that already holds chat.

Non-goals: multi-user accounts, client/agent profiles, per-IP analytics, licence upsell screens,
a remote model-catalogue feed, non-chat modalities (image/video/audio/embeddings), and any
free-tier endpoint aggregation. Those exist in the donor because it hosts many clients and
aggregates hundreds of shared free endpoints; Kira is loopback, BYOK and single-user.

## Decisions taken with the user

| Fork | Chosen | Why the alternatives were rejected |
| --- | --- | --- |
| Authority | See *and* control, including enforced budgets | Read-only would leave key and config management in the CLI, which is the friction the user is paying this project to remove. |
| Persistence | SQLite `settings` overrides layered on `config.yaml` | Rewriting YAML would destroy hand-authored comments and ordering and put boot-critical file surgery on the write path. A pending-ops file makes toggles and caps non-live, which fails "control". |
| Chat | One app, chat is a tab | A second `kira-admin` bundle means two builds, two token gates and a duplicated API client. |
| Screens | Overview + usage, Providers & health, Models catalogue, Sessions & transcripts | First slice; each maps to data the engine already stores. |
| Secrets over HTTP | Yes: `PUT .../key` stores into the Credential Locker, returns presence only | Rejected the pairing-code variant as extra ceremony for a loopback-only service; the confirm header below is the cheaper equivalent of "prove a human is here". |
| Budget unit | Per provider, calendar month, enforced in the router | Per-model caps multiply config and UI for little gain at 1-4 providers. Alerts-only cannot protect the wallet. |
| History | Delete one session, clear all, both behind confirmation | Append-only leaves test noise undeletable. |
| Styling | Extend the existing hand-written CSS; charts drawn as inline SVG | No new dependency, and it stays exactly what the future Electron window renders. |
| Write authorisation | Bearer token for reads, plus a **separate** `engine/confirm` secret re-typed per write and sent as `X-Kira-Confirm` | Chosen initially as "same token + per-write re-entry"; the spec-writing pass found that self-defeating (see "What the confirm header does and does not buy") - it re-asks the same secret the page already holds, so it protects against nothing. **User approved the separate secret on 2026-10-27.** A dedicated admin token with its own lifetime was rejected as splitting secret management further than one confirm value already does. |

## Architecture

```
kira-chat/src
  App.tsx                 shell: nav rail, hash route -> screen, engine status, version guard
  screens/ChatScreen.tsx  today's chat, moved verbatim
  screens/OverviewScreen.tsx
  screens/ProvidersScreen.tsx
  screens/ModelsScreen.tsx
  screens/SessionsScreen.tsx
  hash-route.ts           read/write location.hash, subscribe to changes (~30 lines)
  confirm.ts              the per-write confirm prompt; holds the value only while a request is in flight
  api.ts                  + read/write methods for every new endpoint
  components/ChainTrace.tsx (unchanged, reused by Sessions)
kira-engine/src/kira
  overrides.py            EffectiveProvider + merge(config.providers, settings rows)
  probe.py                probe_provider(...) -> {ok, model_count, latency_ms, error}
  store.py                settings table + monthly spend + overview aggregates + delete
  router.py               budget gate in plan()
  config.py               ProviderConfig.monthly_token_cap (optional, YAML baseline)
  vault.py                ENGINE_CONFIRM_REF + get_or_create_confirm(), same Locker as the token
  app.py                  new /v1/kira/* endpoints, confirm-header dependency
  contracts.py            contract version 2 + new schemas/events
```

`__main__.py`'s `token` command prints both secrets (it already prints one), and `run_kira.py` shows
the confirm value on the same line it shows `connect-token`, labelled as the one the dashboard asks
for on writes. Neither is ever written to disk.

`kira-engine/src/kira/__main__.py`'s `models` command switches to `probe.py`, so the CLI and the
dashboard's Test button share one implementation and cannot drift.

## Data model

New table, created by the existing `_init_schema` migration path:

```sql
CREATE TABLE IF NOT EXISTS settings (
    provider   TEXT NOT NULL,
    key        TEXT NOT NULL,   -- enabled | priority | tier | monthly_cap
    value      TEXT NOT NULL,   -- JSON scalar: true / 60 / "fast" / 1000000
    updated_at REAL NOT NULL,
    PRIMARY KEY (provider, key)
);
```

Mutable fields are exactly those four. `name`, `kind`, `base_url` and `models` stay YAML-only:
the dashboard shows them and links to the file, but never writes them. This keeps one obvious
place for structure and one for tuning.

Baselines the YAML does not literally carry, stated so the merge and the UI agree:

- `enabled` has no YAML key. Its base is always `true`; the field's only purpose is to let the
  dashboard stand a provider down without deleting its stanza. (`kind`, `base_url` and `models` are
  required by `_provider_from`, so they need no such note.)
- `monthly_cap`'s base is the new optional `monthly_token_cap:` YAML field; absent means `null`,
  which means unlimited, which is what everyone expects from a field they never wrote.

A provider whose effective `enabled` is `false` is invisible everywhere routing is decided: it is
excluded from `Router.plan()` candidates, from `GET /v1/models`, and from `CUSTOM` selection - but
it still appears in `GET /v1/kira/providers` (that is how you switch it back on) and its historical
spend still counts toward the Overview month. Disabling must never rewrite history or hide a
provider you already paid tokens to.

Merge rule (`overrides.merge`), evaluated per request rather than cached:

- `effective` = override when a row exists and parses as that field's type, else the YAML baseline.
- A row whose provider is no longer in `config.yaml` is an **orphan**: ignored by the merge, and
  reported by `GET /v1/kira/providers` as `orphan_settings: ["oldname.enabled", ...]` so the UI can
  offer a one-click prune. Deleting a provider from YAML can never resurrect it.
- A row that fails to parse (wrong type) behaves as absent and is reported the same way, so a
  hand-edited database cannot silently change routing.

Monthly spend is **derived**, not accumulated, from the table that already exists:

```sql
SELECT provider,
       SUM(json_extract(usage,'$.input_tokens') + json_extract(usage,'$.output_tokens'))
FROM messages
WHERE role = 'assistant' AND provider IS NOT NULL
  AND created_at >= :month_start AND created_at < :month_end
GROUP BY provider;
```

"Month" is a calendar month in UTC, matching `created_at`'s epoch. Assistant rows with status
`interrupted` or `failed` are counted, because a partial generation was still billed. User rows
carry no provider and are excluded. No rollup table: at personal scale this scan is instant and a
derived number cannot go stale.

## Contract: version 2

Two facts visible on the wire change, so `CONTRACT_VERSION` goes 1 -> 2. The chat's existing guard
refuses a mismatched engine/UI pair, which is the correct outcome when they are built separately.

- `CHAIN_EVENTS` gains `skipped_budget` (9 events).
- `ERROR_CODES` gains `budget_exhausted` from a new `BudgetExhausted(KiraError)` with
  `status = 429`, `retryable = False`.
- The live-probe row is published once, as `ProbeResponse`, so `ModelsResponse.live` is
  `ProbeResponse[]` and the old `count` field is renamed `model_count` (amendment 9).

New schemas, all mirrored in `kira-contracts/types.ts` and checked by `check-drift.mjs`:

```
FieldState(bool)    {base: bool, override: bool|null, effective: bool}
FieldState(int)     {base: int,  override: int|null,  effective: int}
FieldState(str)     {base: str,  override: str|null,  effective: str}
FieldState(cap)     {base: int|None(unlimited), override: int|null, effective: int|None}
ProviderView   {name, kind, base_url, models[],
                enabled: FieldState(bool), priority: FieldState(int),
                tier: FieldState(str), monthly_cap: FieldState(cap),
                key_ref, key_present, spend_this_month,
                health: ProviderState}                # existing ledger shape: failures/successes/cooling_s/last_reason
ProvidersResponse {providers: ProviderView[], orphan_settings: string[], month: "YYYY-MM"}
OverviewResponse  {month, turns, tokens: {input, output}, success_rate,
                   interrupted, failed,
                   by_provider: [{provider, turns, tokens}],
                   by_model: [{provider, model|null, turns, tokens}],
                   daily: [{date, turns, tokens}],
                   budgets: [{provider, cap, used, remaining}],
                   recent_issues: [{id, session_id, status, provider, model, created_at, reason}]}
ProbeResponse     {provider, ok, model_count, sample[], latency_ms, error}  # error null when ok; the one shape /v1/models?live=true and the Test button share
SettingsResponse  {provider, settings: {enabled, priority, tier, monthly_cap}}  # FieldStates after write
KeyResponse       {provider, key_ref, key_present}                # never the value
DeletedResponse   {deleted: int, messages: int}
```

Definitions that have to be pinned down or each screen will invent its own:

- `turns` counts assistant rows in the window; one turn is one user message and the answer it got.
  `interrupted` and `failed` are the same rows split by status, so the clean count is
  `turns - interrupted - failed`. No `served` field is published: it is derived in the UI, because two
  numbers for one fact is how a dashboard starts disagreeing with itself.
- `success_rate` = `(turns - interrupted - failed) / turns`; `turns = 0` gives `success_rate: null`,
  not `0` or `NaN`, because "no data" and "0% healthy" are different messages to show.
- `tokens` in every aggregate is input + output combined, since the cap is combined too; `tokens.input`
  and `tokens.output` stay split in `OverviewResponse.tokens` for the stat cards.
- `by_model[].model` is `null` for a turn that failed before any model answered it. The row stays: the
  turn counts in `turns`, so hiding it would make the table add up to less than the card above it. The
  Overview names the row `no model reached` rather than leaving the cell blank.
- `daily` contains only the days inside the selected month, oldest first; the Overview sparkline plots
  exactly those points, so the card and the chart can never disagree.
- `budgets[].cap` is `null` for unlimited, and then `remaining` is `null` as well.
- `ProviderView` carries no cooldown of its own: the countdown reads `health.cooling_s`, the one place
  the ledger already publishes it.
- `SessionRow` gains `message_count`, `tokens` (same combined definition) and `last_used_at` (the newest
  `created_at` in it). `ErrorBody.code` stays an open string, as it is today, so the new
  `budget_exhausted` code needs no enum change.

## API surface

Reads (bearer token only):

| Endpoint | Purpose |
| --- | --- |
| `GET /v1/kira/overview?month=YYYY-MM` | aggregates above; defaults to the current UTC month; an invalid month is `config_error` 400 |
| `GET /v1/kira/providers` | merged view + key presence + spend + ledger health + orphans |
| `GET /v1/kira/sessions` | existing list, now with counts and tokens |

Writes (bearer token **and** `X-Kira-Confirm` carrying the separate confirm secret from
`engine/confirm`; missing or wrong confirm is `unauthorized` 401 - see the subsection below):

| Endpoint | Body / effect |
| --- | --- |
| `PUT /v1/kira/providers/{name}/settings` | any subset of `{enabled, priority, tier, monthly_cap}`; `null` clears that override back to baseline; unknown field or out-of-range value is `config_error` 400 |
| `PUT /v1/kira/providers/{name}/key` | `{key}` -> stores in the Locker as that provider's `key_ref`; responds with `KeyResponse` |
| `DELETE /v1/kira/providers/{name}/key` | forgets the key; responds with `KeyResponse` (`key_present: false`) |
| `DELETE /v1/kira/providers/{name}/cooldown` | ledger clears cooling for that provider immediately |
| `POST /v1/kira/providers/{name}/probe` | live `list_models` + one completion capped at 8 output tokens; `ProbeResponse`; a failing probe is a 200 with `ok: false` so the UI renders it inline |
| `DELETE /v1/kira/sessions/{id}` | cascades messages |
| `DELETE /v1/kira/sessions` | clears every session and message |

An unknown `{name}` on any of these is `config_error` 400 naming the provider. Secrets are never
written to `engine.log`, never returned in a response body, and never placed in a URL.

Write validation, so a bad value cannot reach the router and become a mystery:

| Field | Accepted | Rejected as `config_error` 400 |
| --- | --- | --- |
| `enabled` | `true` / `false` | anything else, including `0`/`1` |
| `tier` | `"fast"` / `"powerful"` (the existing `TIERS`) | any other string |
| `priority` | int `0..1000` | negative, above 1000, non-int |
| `monthly_cap` | `0` means unlimited, int above 0 means that many tokens | negative, non-int |

`null` on any field means "delete the override row, go back to `config.yaml`" - it is not how you say
unlimited, and the two must not be confusable because they look identical in a JSON body.
`PUT .../settings` with an empty object changes nothing and returns the current `SettingsResponse`,
so the UI can read the post-write state without a second request.

Probe is grouped with the writes even though it mutates nothing: it spends real credits and calls a
third party with your key, so an unattended script should not be able to fire it either. Probe traffic
is deliberately **not** stored in `messages` - a diagnostic is not a conversation - so the tokens it
burns never appear in the derived month total, and the Providers screen says so in one line rather
than letting Overview and the probe card look like they disagree.

### What the confirm header does and does not buy

Stated plainly, because the mechanism is easy to oversell:

- It **does** stop a page from another origin, and any local process that can open a socket to
  127.0.0.1, from mutating keys, settings or history: the header is a custom header, so a foreign
  page cannot set it without a CORS preflight that this engine never grants, and a non-browser
  caller would have to guess a 43-character secret.
- It **does not** defend against script already running inside this page's origin. Such script can
  read the bearer token out of `localStorage` and put it in the confirm header, so if the token equals
  the confirm value, the two are one secret.
- Therefore the confirm value is **not** the bearer token. It is a second Locker secret,
  `engine/confirm`, created with the token on first run and shown once by `run-kira.bat` and
  `kira-engine token`. Reads keep working with the bearer token alone; writes need the typed confirm,
  which no page script can obtain from storage.

`AuthError` (401) is the response when it is missing or wrong; no new error code is needed, and the
UI's `unauthorized` state already exists.


## Budget enforcement

In `Router.plan()`, once candidates are limited by mode/tier/model, disabled providers are dropped
and missing keys are noted, and **before** the cooldown ledger filter:

1. read the effective cap and the month's spend for each candidate,
2. drop any candidate whose spend already meets its cap, noting
   `{"provider": p, "event": "skipped_budget", "reason": "used 1,020,000 of 1,000,000 tokens in 2026-10"}`,
3. if the surviving list is empty and *every* dropped candidate was dropped for budget, raise
   `BudgetExhausted`. Mixed causes (some cooling, some budget) stay `AllProvidersExhausted`, because
   "wait a minute" is the honest advice there but "raise a cap" is not.

Budget is checked before cooldown so a provider that is both over budget and cooling is reported as
over budget — the one the user can actually act on.

`state.chain` carries the note, so `skipped_budget` shows up in the live chain chips, in the stored
message, and in the Sessions transcript with no extra plumbing. The chat renders a budget-exhausted
turn with the message plus a link to `#/providers`.

## UI

Shell: a persistent left rail (Chat, Overview, Providers, Models, Sessions), the connection dot and
contract version that exist today, and a hash route so `#/providers` survives refresh and can be
deep-linked from an error. No router dependency; `hash-route.ts` exposes
`currentRoute()` and `onRoute(fn)`.

- **Chat** — today's screen moved whole: composer, mode/model selects, streaming turn, chain chips,
  usage line, session sidebar. Its sidebar keeps the short recent-sessions list it has now, so chat
  behaves exactly as before; the Sessions screen is where the full list, counts and deletion live.
  `ChainTrace.tsx` gains one label for `skipped_budget` ("over budget") in the same muted tone as
  `skipped_cooling`, so the new chain event reads like the rest instead of falling through to a
  blank chip.
- **Overview** — month selector, stat cards (turns, tokens in/out, success rate, interrupted, failed),
  one stacked bar per provider showing `used / cap` with unlimited drawn as a full-width neutral bar,
  a daily inline-SVG sparkline over exactly the days `daily` returned, top models by tokens, and a list of the most recent
  `interrupted`/`failed` turns linking straight to their session transcript.
- **Providers** — one row per provider: enabled toggle, tier select, priority number input, monthly
  cap input, baseline-vs-effective hint with "reset to baseline", key badge (`key ok` / `no key` +
  Set key / Forget key), ledger counters with a live cooldown countdown, and Test, which calls probe
  and shows `model_count` + latency or the error text inline. Every control goes through the confirm
  dialog before it fires.
- **Models** — every configured model with its provider, tier and how many times it served this
  month; "use in chat" sets the model and routes to `#/chat`. Adding a model means editing YAML, so
  each row states that plainly rather than faking an input.
- **Sessions** — table of sessions (mode, message count, tokens, last used), transcript detail reusing
  `ChainTrace`, delete one, and clear-all with a dialog that requires typing `DELETE ALL`.

Confirm dialog: it appears **per write**, not once per session - typing the confirm secret is the
point at which a human agreed to this specific change, so a remembered value would throw the
mechanism away. `confirm.ts` holds the value only for the single in-flight request and drops it as
soon as the response lands (never `localStorage`, never the URL, never a component prop that a later
screen could read). A write that comes back 401 because the value was mistyped re-opens the dialog
with the reason instead of showing a bare error. The only exception is the multi-field Providers row
edit: one dialog covers the fields actually changed in that row, because sending them as separate
writes would let a half-applied change route traffic you did not intend.

Deleting history asks for the confirm value *and* the typed words `DELETE ALL` for clear-all, and the
Sessions row delete names the session id and its message count in the dialog so it is obvious what is
going.

States are explicit on every screen: loading, empty (with the reason — "no providers in
`config.yaml` yet" vs "nothing spent this month"), and error (engine unreachable, version
mismatch, `budget_exhausted`, `providers_exhausted`, `unauthorized`).

## Testing

Engine (`pytest`, fake providers, temp data dir, memory vault):

- `test_overrides.py` — merge precedence, type-parse failure treated as absent, orphan rows reported
  and prunable, `null` clearing an override.
- `test_budget.py` — spend derived over exactly one UTC month, interrupted rows counted, provider at
  cap skipped with `skipped_budget` in the chain, all-budget yields `BudgetExhausted` 429, mixed
  causes yield `AllProvidersExhausted`, budget evaluated before cooldown.
- `test_dashboard_api.py` — every read endpoint's live body satisfies the contract schema (the
  existing `_schema()` subset-assertion pattern); every write endpoint refuses with no
  `X-Kira-Confirm`, with a wrong one, and with the **bearer token substituted as the confirm** (the
  assertion that makes the two secrets provably not one thing); accepts the real confirm; and a key
  write's response plus `engine.log` are asserted not to contain the submitted value.
- `test_settings_validation.py` — the four-field table enforced: `tier: "medium"`, `priority: -5`,
  `monthly_cap: -1`, `enabled: 1` each return `config_error`; `monthly_cap: 0` means unlimited;
  `null` removes the override row instead of meaning unlimited.
- `test_probe.py` — probe reports ok, model count, latency, and a failure as `ok: false` rather than
  raising; the CLI `models` command uses the same function.
- `test_store.py` — session delete cascades messages, clear-all counts match, aggregates group by
  provider/model/day.
- `test_routing.py` gains the enable/disable rule: a provider disabled by override is absent from
  `plan()` candidates in every mode including `CUSTOM`, absent from `/v1/models`, and its past spend
  still shows in the month total.
- `test_units.py` keeps the contract checks it already runs (every `KiraError` code published,
  default data dir keeps `kira-chat` a sibling) and gains one for `skipped_budget`: the event is
  published in `CHAIN_EVENTS` and is the event an over-cap provider actually produces, so the two
  cannot drift apart.

Contracts: `node kira-contracts/check-drift.mjs` must pass against the v2 artifacts, and the
mutation test that proved it fails on injected drift is re-run once after the new schemas land.

Chat (`vitest` + jsdom, `fake-engine.ts` extended with the new routes): hash router back/forward,
each screen's loading/empty/error path, Providers toggling opens the confirm dialog and writes only
after it, a second write in the same session asks again (no remembered value), the confirm is cleared
from the client after the response, the two-secrets refusal renders a re-opened dialog rather than a
raw 401, `null` reset button, probe result rendering, a multi-field row edit costing one dialog,
Sessions delete naming the session and requiring typed `DELETE ALL` for clear-all, Overview
unlimited-cap rendering, and one test that no write path ever touches web storage (`confirm.tsx`,
`api.ts` and the screens — the gate's own `kira.base` / `kira.token` lines in `App.tsx` are the single
sanctioned use, and the bearer token being readable there is exactly why the confirm secret is separate).

Real browser pass: the throwaway mock-provider harness again (local scripted provider + engine),
walk all five screens, set a cap low enough that the next turn returns `budget_exhausted`, confirm
the chain chip and the Providers screen agree, then delete the harness. This is recorded in the
milestone notes, not claimed from unit tests.

## Milestones

- **M8** — `hash-route.ts`, shell, `ChatScreen.tsx` extracted, nav rail, styles for the shell.
  Acceptance: chat behaves exactly as before, `#/chat` survives refresh, all existing chat tests pass.
- **M9** — `settings` table, `overrides.py`, `ProviderConfig.monthly_token_cap` (+ a commented example
  in `SAMPLE_CONFIG`), `probe.py` + CLI switch, read endpoints (`providers`, `overview`, extended
  `sessions`), contract v2 + TS mirror + drift gate green, `Router.plan()` and `/v1/models` reading the
  **merged** view, Providers and Overview screens **read-only** on real data.
  Acceptance: the dashboard shows effective-vs-baseline and spend with no write endpoint yet, and an
  override row inserted by hand (via `store.set_setting`) demonstrably changes routing - proving the
  merged view is live before anything can write to it.
- **M10** — `engine/confirm` in the Locker, confirm-header dependency, `token` command and launcher
  surface it, write endpoints (settings, key set/forget, cooldown clear, probe), store deletes,
  `DeletedResponse`, `confirm.ts` per-write dialog, security tests.
  Acceptance: keys and tuning managed from the browser; a write is refused when the confirm is
  missing, wrong, or the bearer token itself; the missing-value assertions pass.
- **M11** — `skipped_budget` + `BudgetExhausted` + router gate, the `ChainTrace` "over budget" label,
  budget cards, cap inputs wired to writes.
  Acceptance: a low cap stops a provider mid-month, failover and the all-budget error both verified.
- **M12** — Models and Sessions screens with their actions, README dashboard section, live browser
  pass recorded, full suite green.
  Acceptance: all five screens usable against a real engine; docs match behavior.

M8+M9 alone leave a genuinely useful read-only dashboard, so the work can stop there and resume
later without a half-built write path.

## Follow-on

The same `/v1/kira/*` surface is what sub-project 3's Electron shell will render, and the budget
gate already treats a local llama.cpp provider (sub-project 5) as just another tiered candidate with
an optional cap. `orphan_settings` pruning is where a future "delete provider from config" UI hangs.

**2026-10-30:** the twelve findings in `docs/qa/dashboard-browser-pass.md` are closed — ten here,
two inside the units that owned the code. The decisions, including the refusal ledger that lives
outside `messages`, are recorded in `docs/specs/2026-10-30-kira-unit-13-findings-design.md`; the
verification record is `docs/qa/unit-13-findings-pass.md`. The spend meter still re-arms on history
deletion, which stays deliberate: it counts what is stored.
