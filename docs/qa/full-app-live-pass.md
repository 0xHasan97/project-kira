# Full-app pass — 2026-10-29 (sandbox engine, scripted provider)

Three questions had to be answered with evidence rather than reasoning:

1. Does either shell actually reach the tool harness, or is `tools_enabled` silently off?
2. Is the agent path — tool call, approval, write, checkpoint, deny — usable from the UI?
3. Does a provider that needs no credential work, given that roadmap unit 5 is a local model?

All three are answered below. The run is 29 checks, all passing, in one script.

## How it was run

Engine: the real `kira` package, `--backend memory serve`, data dir
`%LOCALAPPDATA%\Temp\kira-e2e` on `http://127.0.0.1:8941` (loopback only), its own SQLite file, its
own workspace, and a memory vault — nothing in this run read or wrote the Credential Locker, and the
token and confirm secret it printed are per-process and gone with the process.

Provider: `mock_provider.py` on `http://127.0.0.1:8940/v1`, an OpenAI-compatible SSE stub whose config
stanza declares **no `key_ref`**. It answers a tool call when the *latest* user message asks for one
(`write`/`list`/`read`/`time`) and then echoes the tool result, so a turn is a real two-step agent loop
with no model choosing anything. What this proves is the wire between engine, tools, approvals,
checkpoints and the UI. What it cannot prove is what a real model would decide to call — that path is
`docs/qa/live-providers.md`, and it is currently blocked by quota (see Findings 4).

Client: the built `kira-chat/dist` served by the engine at `/chat/`, driven headless over raw CDP —
the cached Playwright Chromium (`%LOCALAPPDATA%\ms-playwright\chromium-1248\chrome-win64\chrome.exe`),
1440×900 at scale 1, Node 24 `fetch`/`WebSocket`, no npm packages. `kira.base`, `kira.token` and
`kira.shell=agent` seeded in one evaluate, then `Page.reload`. The confirm secret was typed into the
approval card only, and never into `localStorage`: the run ends by asserting `localStorage` holds
exactly `kira.base`, `kira.shell`, `kira.token`.

Script: `%LOCALAPPDATA%\Temp\e2epass.mjs`; screenshots and `report.json` in
`%LOCALAPPDATA%\Temp\kira-e2e-pass`. `RESULT 29/29 ok`, `EXCEPTIONS []`.

## What was driven

| # | Check | Observed | Verdict |
| --- | --- | --- | --- |
| 1 | Agent shell renders against the sandbox engine | `div.app` with `shell=agent theme=charcoal` — the switch paints before a single turn exists. | matched |
| 2 | The keyless provider is the default model and is not called broken | `select[aria-label="model"]` → `default=mock-agent options=["mock-agent · mock · fast"]`. No `· no key` suffix on a provider that asks for no key. | matched after finding 1 |
| 3 | No surface labels a keyless provider `no key` | Sidebar row reads `mock no key needed 14✓ 0✗`; a regex over every `.providers li` finds no bare `no key`. | matched after finding 1 |
| 4 | A read-only tool turn runs and lands in the transcript | `list the files in the workspace…` → `MOCK-TOOL-RESULT {"path": ".", "entries": [{"name": "notes", …}]}`; footer chip `complete mock-agent 70↑ / 30↓ 2 served · 0 failed · 0 skipped · 1 tool runs`. | matched |
| 5 | The step spine names the tool that ran | `tool ran list_dir("call_list_dir_1") → ok, 83 chars`, then `mock trying mock-agent` / `mock answered`. | matched |
| 6 | A write tool raises an approval card and holds the turn | `card: write_file · write · needs permission { "path": "notes/mock.txt", "content": "written by the mock harness" } allow deny`. | matched |
| 7 | Approving with the confirm secret runs the write | `allow clicked` → the assistant row settles as `MOCK-TOOL-RESULT {"path": "notes/mock.txt", "bytes": 27}`. | matched |
| 8 | The bytes really landed in the sandbox workspace | `kira-e2e/workspace/notes/mock.txt` → `written by the mock harness`. | matched |
| 9 | The work panel lists the write and its checkpoint | Changes tab: `notes/mock.txt · checkpoint 998e52476aa04254`. | matched |
| 10 | Denying the next approval ends the turn without writing | Second write prompt, same card, `deny` → the spine shows the denial and the file stays absent; stored chain `["attempt","served","tool_executed","tool_approval_requested","checkpoint_created","tool_denied"]`. | matched |
| 11 | Seven routes × two shells, each screen itself | `#/chat`, `#/call`, `#/overview`, `#/providers`, `#/models`, `#/sessions`, `#/tools` — fourteen renders, each with its own content (Overview counted `turns 13 10 served tokens 1,000 700 in · 300 out success rate 76.9%`; Tools listed every builtin with risk, source, default policy). | matched |
| 12 | Overview's month field is the current month, not a default | `input[aria-label="month"]` → `2026-10`. | matched |
| 13 | Engine truth: history stores the tool call, not just the text | `GET /v1/kira/sessions/{id}/messages` → `tool_calls` on the assistant rows: `[{"id":"call_list_dir_1","name":"list_dir","arguments":{"path":"."}}]`, chain events as listed above. | matched |
| 14 | A confirm-gated write round-trips | `PUT /v1/kira/providers/mock/settings` (cap override) → `{"base":null,"override":null,"effective":null}` after clearing; the Providers table repaints from the engine, not from local state. | matched |
| 15 | Storage hygiene | `localStorage=["kira.base","kira.shell","kira.token"]`; zero uncaught exceptions for the whole run. | matched |

## Does the shell actually use the harness?

Yes, and no flag was flipped to make it so. `ChatRequest.tools_enabled` defaults to `True`
(`kira-engine/src/kira/app.py:63`) and `build_run` passes `tools=engine.tools` whenever it is true;
the client never sends the field, so **both** shells run the real registry — which is what checks 4–10
measure from the UI. `ChatScreen` renders `ApprovalCard` in both shells, so the same card and the same
confirm-secret gate appear in Chat as in Agent; only the surrounding surface changes.

## Findings

1. **A provider that needs no key could not be built at all** — fixed test-first, this run.
   `ProviderRegistry.build()` raised `ConfigError` whenever the vault had no key, while `router.plan()`
   had already decided that a stanza with no `key_ref` needs no credential. The two rules disagreed, so
   a local OpenAI-compatible server could be listed and never served: the first turn against it died
   with `{"provider": "mock", "event": "skipped_config", "reason": "provider 'mock' has no key in the
   in-process memory store (not persisted) (ref=''); set it with: kira-engine keys set "}` — an advice
   line telling the user to store a secret that the config says does not exist. `build()` now refuses
   only a provider that *declares* a ref and has none, `OpenAICompat._headers()` omits `Authorization`
   entirely when there is no key (a bare `Bearer ` is its own kind of wrong for a strict local server),
   and `tests/test_providers.py` + `tests/test_api.py` cover both halves, including a whole offline
   turn (`served offline`, `served` last in the chain).
   Roadmap consequence: **unit 5 is now "install a server, add a stanza", not new engine work.**
2. **`key_present` alone is not enough to label a provider, and four surfaces used only it.**
   Contract v2 grew a second boolean, `needs_key`, on `ModelInfo`, `ConfiguredProvider` and
   `ProviderView` (additive, so `API_VERSION` stays 1 and `CONTRACT_VERSION` stays 2), regenerated and
   mirrored — the drift gate now reports `v2, 56 schemas, 6 chunk types, 16 chain events`. The
   interpretation lives in one client module, `kira-chat/src/keying.ts` (`answersToday`, `keyBadge`),
   which the model picker, the Chat/Agent sidebar, the options panel and the Providers table all read,
   so `no key needed` (ok) and `no key` (warning) can no longer drift apart. Guard tests:
   `keying.test.ts`, plus "prefers a provider that needs no credential over one whose key is missing",
   "never says no key about a provider that does not ask for one" and the Providers-screen equivalent.
3. **A keyless provider must still be a *fallback* choice, not the only one, and the picker now knows
   the difference.** Defaulting the model select to the first catalogue row sent every fresh turn to a
   provider whose key was missing; it now defaults to the first row that `answersToday()` accepts, and
   keeps a model the user chose even when its provider has no key — because the user choosing it is
   information the catalogue does not have.
4. **No live turn was possible when this run happened, and the engine said so honestly.** The user's
   Gemini key returned `429 You exceeded your current quota, please check your plan and billing details`
   on every attempt; the chain recorded `failed` then `providers_exhausted`, and the cooldown escalated
   20 → 40 → 80 s. That is provider quota, not a code defect, and it is why this pass is a sandbox pass:
   claiming a live tool turn here would be a claim about a mock. *Corrected the same day:* the limit is
   a **daily** free-tier reset, and `docs/qa/live-app-pass.md` later drove the real turns this one could
   not — streamed answer, model-chosen tool call, model-asked write denied with nothing written.
5. **`vision:` is absent from this machine's `config.yaml`, so every provider reads `text only`.**
   The shipped sample declares `vision: true`; a stanza without the key defaults to false, so an image
   turn filters every provider out with `skipped_config` and the call screen keeps frames on the device.
   Reported, not changed — it is the user's config and their camera, and a real decision needs a working
   key first.
6. **One 404 in an old engine log, not reproduced.** `GET /v1/kira/sessions//messages` appears in the
   pre-fix sandbox log — a transcript fetch with an empty session id. Both databases now have zero
   messages with an empty or null `session_id` (18 rows in the real one, 26 in the sandbox), and every
   call site passes a row's own id, so there is no reproducible defect to fix. Left as a note; a guard
   in `KiraClient.messages()` would be speculative until someone reproduces it.

## Gates at this run

- `kira-engine`: `pytest -q` → **363 passed, 1 skipped** (the skipped file is the live-provider suite,
  which needs `KIRA_LIVE=1`).
- `kira-chat`: `npm run check` → tsc clean, **25 files / 213 tests**, vite build, stamp
  `{api_version:1,contract_version:2,api_prefix:"/v1"}`.
- `node kira-contracts/check-drift.mjs` → `kira-contracts OK — v2, 56 schemas, 6 chunk types, 16 chain events`.
- `README.md` numbers corrected to the above; `docs/ROADMAP.md` carries the keyless-provider finding.
