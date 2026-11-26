# Auto-picker pass — 2026-10-31 (UTC)

Two shipped decisions and one config flag, driven in a browser: the model select that opens on
`Auto · the router picks` instead of naming a provider, the `AUTO` lane that holds a named model as a
**preference** with every other provider queued behind it, and the `vision:` flag a call reads before it
sends a frame. Both were decided test-first on 2026-10-31 (`kira-engine/tests/test_routing.py`,
`kira-chat/src/App.test.tsx`); this pass is the first time either was clicked.

Engine: `tools/kira_lab.py --port 8912 --mock-port 8999 --models mini,small --models-two solo --vision mock_two`,
i.e. two scripted providers whose catalogues **do not overlap** — `mock_one` serves `mini, small`,
`mock_two` serves only `solo` and is the one marked `vision: true`. That asymmetry is what the pass needs:
a model the picker can name and exactly one provider can answer. Data dir a temp one, vault in memory,
nothing in the Credential Locker, nothing billed — `tools/mock_openai.py` answers every request with the
same 150-token script.

Browser: `http://127.0.0.1:8912/chat/`, headless over raw CDP — the cached Playwright Chromium
(`%LOCALAPPDATA%\ms-playwright\chromium-1248\chrome-win64\chrome.exe`), 1440×900, device scale 1, Node 24's
global `fetch` and `WebSocket`, no npm packages. `kira.base` and `kira.token` seeded in one evaluate and the
page **reloaded** (`Page.navigate` to the same URL with the same fragment is a same-document hop and does not
re-read storage). The confirm secret was typed into the confirm card and nowhere else. One script, start to
finish; screenshots 01–06 and `report.json` beside this file. The clock on this machine reads UTC+6; no
timestamp below is quoted except what the UI printed.

## What was driven

The picker's opening state and its per-id provider names; one unpinned `AUTO` turn; the vision column on
`#/providers`; a monthly cap written through the confirm gate; the same pinned model in `AUTO` and in
`FAST` against the same exhausted provider; a model id nobody offers; `GET /v1/kira/providers` and
`GET /v1/kira/voice` read back over the same authenticated channel the page uses.

| # | Check | Observed | Verdict |
| --- | --- | --- | --- |
| 1 | The select opens with no pin, and the footer counts ids not rows | `select[name="model"].value` was `""` with the selected row reading `Auto · the router picks`; the four options were `Auto · the router picks`, `mini · mock_one · fast`, `small · mock_one · fast`, `solo · mock_two · fast`; mode `AUTO`; footer `Enter sends · 3 models · AUTO` — three ids from three catalogue rows, Auto not counted. | matched |
| 2 | An unpinned `AUTO` turn lets the engine choose | Sending `first turn, no pin` with the select on Auto produced the chain `mock_one · trying · mini` → `mock_one · answered · mini`, and the message footer `complete mini 100↑ / 50↓ 1 served · 0 failed · 0 skipped · 0 tool runs`. Nothing was named by the client; `mini` is `mock_one`'s own first model. | matched |
| 3 | A model is listed once and names who serves it | Same option list as check 1: `solo` appears under `mock_two` alone, so the queue a pin creates is visible before sending. | matched |
| 4 | The vision flag reads back on the provider table | `#/providers`: the `mock_one` row carried `text only`, the `mock_two` row `sees images` — the only difference between them being the lab's `--vision mock_two`. | matched |
| 5 | A cap is a confirm-gated write that reads back where it bites | `set cap mock_one` at `149` behind the confirm card: the input held `149`, the row read `was unlimited` and `150 at cap`, and the ✓/✗ counters stayed `1 ✓ 0 ✗`. | matched |
| 6 | The pin survives a route change | `mini` was still selected after `#/providers` and back to `#/chat`. | matched |
| 7 | **`AUTO` holds a named model as a preference, and the queue behind it answers** | With `mini` pinned — a model **only `mock_one` carries** — and `mock_one` over its cap, the turn sent `pinned turn, first provider over cap` came back answered: `mock_one · over budget · used 150 of 149 tokens in 2026-10` → `mock_two · trying · solo` → `mock_two · answered · solo`, footer `complete solo … 1 served · 0 failed · 1 skipped`. Before this change the model filter ran first and dropped `mock_two` for not carrying `mini`, so the same click ended in a refusal. Screenshot `05-auto-failed-over.png`. | matched |
| 8 | The strict lanes stayed strict | Same state, mode `FAST`, same pin: `no text returned`, `failed 0 served · 0 failed · 1 skipped · 0 tool runs`, and the reason named — `budget_exhausted: mode FAST: over the monthly cap for 2026-10 (mock_one) - raise the cap in the dashboard or wait for the reset`, with the `raise a cap in Providers` link. `mock_two` was **not** used: a lane the user chose means that lane. Screenshot `06-fast-lane-refuses.png`. | matched |
| 9 | A typo still costs nothing | `POST /v1/chat/completions` with `model: "minim"`, `mode: "AUTO"`: `400 {"error":{"code":"config_error","message":"no provider in mode AUTO offers model 'minim'; configured: ['mini', 'small', 'solo']","retryable":false}}` — the soft pin kept the refusal, and named the ids it does have. | matched |
| 10 | The engine agrees with the screen about vision | `GET /v1/kira/providers` → `mock_one: false`, `mock_two: true`; `GET /v1/kira/voice` → `vision: {"provider": "mock_two", "model": "solo"}` — the stage `#/call` prints, chosen by the flag and nothing else. | matched |

## Findings

`report.json` keeps the script's own step numbers, which differ from the table's by one: its step 2
re-read the Auto label after the lane switch and said the same thing, so it is folded into row 1 here
rather than counted twice. All 11 of its entries are `matched`.

1. **`default_mode` in `config.yaml` does not reach the picker.** The lab config says
   `default_mode: FAST` and the screen opened in `AUTO` anyway: `kira-chat/src/App.tsx:82` initialises
   `useState<Mode>("AUTO")`, the client always sends a mode, and `app.py:581` only falls back to
   `cfg.default_mode` when a request omits one — which the UI never does. The field is therefore live for
   any other caller and dead for the chat screen. Not fixed here: the user's own config says `AUTO`, so
   nothing on this machine is misbehaving, and seeding the select from `/v1/kira/health` (which already
   returns `default_mode`) is a behaviour change with its own call to make. Reported rather than patched.
2. **Check 5's first draft read the wrong thing.** It looked for `149` in the row's `textContent`; a
   `type="number"` input carries that in `value`, so the check failed while the write had succeeded. The
   assertion was corrected to read the input and the `at cap` marker together and the whole pass was
   re-run from a fresh lab — the table above is that second run, 11 of 11, with the screenshots from it.

## What this pass cannot prove

The stale-pin drop — a pin the catalogue no longer recognises falling back to Auto — is unit-tested
(`kira-chat/src/App.test.tsx`, the refresh button against a changed catalogue) but not browser-driven here,
because changing the catalogue means restarting the lab, and the pin is component state that a reload
clears by itself. Two keyed *remote* providers failing over is still unproved for the same reason it always
was: one working key on this machine. And `#/call` was not opened — the mock has no voice stages — so
check 10 proves the engine's choice of a vision provider, not a frame crossing the wire to it.

## Gates at this run

- `kira-engine`: `pytest -q` → **541 passed, 1 skipped** (the skipped file is the live-provider suite).
- `kira-chat`: `npx vitest run` → **327 passed across 37 files**; `npx tsc --noEmit` clean; `npm run build`
  stamped `{"api_version":1,"contract_version":2,"api_prefix":"/v1"}`.
- `node kira-contracts/check-drift.mjs` → `kira-contracts OK — v2, 77 schemas, 6 chunk types, 16 chain events`.
  The contract did not move for either decision: `attempt` and `served` already carried the answering
  provider and model, which is what makes check 7 self-reporting.
