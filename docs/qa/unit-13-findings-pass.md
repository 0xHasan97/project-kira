# Unit 13 — findings closeout: verification record — 2026-10-30

This is **not** a browser pass. The browser pass that produced the findings is
[`dashboard-browser-pass.md`](dashboard-browser-pass.md), run 2026-10-29. This record covers the ten
findings it left open and says, per finding, which test fails without the fix and what was run.

Decisions are in [`docs/specs/2026-10-30-kira-unit-13-findings-design.md`](../specs/2026-10-30-kira-unit-13-findings-design.md).

## Per finding

| Finding | Fix | Test that would fail without it |
| --- | --- | --- |
| F1 plan-time refusal is invisible to the engine | `refusals` table + overview `refusals` + screen block outside the empty-month branch | `test_a_refusal_is_recorded_where_no_turn_could_store_it`, `test_a_served_turn_does_not_enter_the_refusal_ledger`, `test_clearing_the_history_does_not_erase_the_refusals`, `test_a_refusal_counts_in_the_month_it_happened`; `OverviewScreen.test.tsx` → "reports a refusal in a month that spent nothing, because no row could hold it" |
| F2 plan notes repeat per agent step | `AttemptState.notes_emitted` | `test_budget.py::test_an_agent_step_does_not_repeat_the_plan_notes` |
| F6 a stale token draws a shell, not the gate | only `unauthorized` clears the token | `App.test.tsx` → "sends a refused token back to the gate instead of leaving the shell up" (and its guard: "keeps the shell for a failure that is not about the token") |
| F7 redundant overrides | `matches_baseline()` compared by effect | `test_settings_validation.py::test_a_write_equal_to_the_yaml_baseline_leaves_no_override`, `test_an_old_override_is_dropped_when_a_write_lands_on_the_baseline` |
| F8 one sitting, many sessions | `sessionStorage["kira.session"]` + restore on mount | `useChat.test.tsx` → "remembers the session a turn created, so a reload continues the same sitting", "forgets a stored session the engine no longer has", "remembers the session the rail opened" |
| F9 picker names a provider it does not choose | one option per id, every serving provider named, `no key` only when none can answer | `App.test.tsx` → "lists a model once and names every provider that serves it", "does not stamp no key on a model another provider can answer" |
| F10 Providers cannot show `at cap` | router's own cap test in the spent cell | `ProvidersScreen.test.tsx` → "marks the provider the router is standing down, and only that one" |
| F11 `never` as `last used` | decision only — unreachable from the UI; fallback kept | existing `SessionsScreen` unit coverage of an empty session |
| F12 user row prints `complete · 0 tokens` | assistant-only meta | `SessionsScreen.test.tsx` → "gives a user row only what a user row has — no status word and no token count" |

Findings F3 (the lab's mock omitted `usage` on tool calls) and F4 (the lab's temp dir survives a
kill) were fixed at the time of the pass, in `tools/mock_openai.py` and the README wording.

## Gates, as run

Engine, from `kira-engine/` with `.venv/Scripts/python.exe`:

```
pytest -q  →  466 passed, 1 skipped
```

Client, from `kira-chat/`:

```
npm run check  →  tsc --noEmit clean · vitest 236 passed / 27 files · vite build · kira-build.json
                  {"api_version":1,"contract_version":2,"api_prefix":"/v1"}
```

Contract, from the repo root:

```
node kira-contracts/check-drift.mjs  →  kira-contracts OK — v2, 68 schemas, 6 chunk types, 16 chain events
```

The engine suite moved 462 → 466 with F1's four tests; the client suite moved 231 → 236 with F8's
three and F1's two, and the overview fixture gained `refusals` so every existing App render still
matches the published shape.

## What this record does not claim

- No browser was driven for these ten fixes. Refresh persistence, the 401 gate, the cap badge and
  the refusal block are asserted by jsdom component tests and API tests, not by a human watching a
  page. The next full-app pass will exercise them for real.
- F8's restore path is tested against the fake engine; the real engine's `messages` 404 for an
  unknown session is covered by the fake engine's `session_not_found` branch, which mirrors the
  engine's own handler.
