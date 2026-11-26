# Live app pass — 2026-10-29 (real engine, real key, real browser)

`docs/qa/live-providers.md` asks what the wire says when the engine calls a provider. `docs/qa/full-app-live-pass.md`
asks whether the UI reaches the tool harness — against a scripted provider in a sandbox. This pass is the question
neither answers: **does the app the user actually launches work, on the user's actually-configured engine, with the
user's own Gemini key, in a browser?** Every turn below is a real model deciding to call a real tool, and every
verdict is read back from the engine's own stored rows, not from the bubble that claims it.

Three runs, 25–26 checks each: `13:51` (24 ok), `14:17` (all 26 green under the harness rule of that moment),
`14:25` (22 ok, 1 skipped, 3 bad — the key's daily quota, see *Quota*). The useful reading is the union: the
successes are what the product does, and the three failures are four defects, each fixed test-first.

## How it was run

Engine: the shipped launcher path, `KIRA_DATA_DIR="<repo>/.kira-data" .venv/Scripts/python -m kira serve --port 8931`
— the real config, the real SQLite, the real Credential Locker, loopback only, serving the built `kira-chat/dist` at
`/chat/`. Both engine fixes described below were already in the process (started 13:21:57, first run 13:51). The
token is read from the Locker by the harness's own launcher and handed over as an argument; it never appears in a
terminal, a log, a report or this file.

Client: cached Playwright Chromium (`%LOCALAPPDATA%\ms-playwright\chromium-1248`) with `--headless=new`, driven over
raw CDP with Node 24 `fetch`/`WebSocket` — no npm packages, no test framework. Script
`%LOCALAPPDATA%\Temp\livepass_final.mjs`; `report.json` and screenshots per run in
`%LOCALAPPDATA%\Temp\kira-live-pass-<run>`, with `RUN` and `P` parameters so a re-run does not clobber the evidence it
is checking.

Two harness rules had to be earned, and both are worth keeping because both were bugs in the *harness*:

- **Boot is proved, not timed.** `Target.createTarget` → wait for `Page.loadEventFired` → assert `location.href` is
  on the engine origin → seed `kira.base`, `kira.token`, `kira.shell` in one `Runtime.evaluate` IIFE (a top-level
  `return` there is a `SyntaxError`, which is how the first revision silently seeded nothing) → `Page.reload` → wait
  for `div.app[data-shell]`, up to three attempts. The two `2/24` runs were this race, not the app.
- **Poll, do not sleep.** The client fills the model list and the key badges on the first `/v1/models` round-trip
  after mount, so at t=0 the picker legitimately says *no models configured*. Every step waits for the reading it
  asserts on.
- **A step can only be called ok if its detail says so.** The first revision scored `ok` on a step whose detail
  ended `FAIL an empty assistant row was stored`, because the ok rule read the first word. Now `FAIL`, `JSERR` or
  `CDPERR` anywhere in the detail fails the step, and a step the provider outage made unprovable is reported
  `SKIP`, never a pass.

## What the wire gave

| Check | Observed | Verdict |
| --- | --- | --- |
| The live app renders | `shell=agent` on `div.app` against the real engine. | matched |
| The model list fills | 5 rows after one `/v1/models`. | matched |
| The default is a provider that can answer | `default=gemini-3.5-flash`, with `llama-3.3-70b-versatile · groq · fast · no key` and the two openrouter rows listed after it. | matched |
| The badges name the truth | `openrouter key ok · groq no key · anthropic no key · gemini key ok`; no surface says `no key needed` about a provider that asks for a key, and no provider that asks for none is called `no key`. | matched |
| A plain streamed answer | `A vector database is a specialized database designed to store, index, and retrieve high-dimensional vector embeddings for fast similarity search.` — chip `complete gemini-3.5-flash 405↑ / 25↓ 1 served · 0 failed · 0 skipped · 0 tool runs`. | matched |
| A real tool round-trip, chosen by the model | `now` called, answer `The exact epoch number returned by the tool is 1793261806.` — chip `complete … 2 served · 0 failed · 0 skipped · 1 tool runs`; chain `attempt · served · tool_executed · attempt · served`. | matched — and this is the turn the `thought_signature` fix made possible |
| A model-asked write raises the card | `card: write_file · write · needs permission { "path": "kira_live_pass_probe.txt", "content": "PROBE" } allow deny`. | matched |
| Denying it writes nothing | `denied -> file on disk: false`; stored chain `attempt · served · tool_executed · tool_approval_requested · tool_denied`, stored `tool_calls` `["now","write_file"]`. | matched |
| Seven routes × two shells | `#/chat`, `#/call`, `#/overview`, `#/providers`, `#/models`, `#/sessions`, `#/tools` in both `agent` and `chat`, each with its own content (1,121–3,882 chars), zero uncaught exceptions across all three runs (`EXCEPTIONS []`). | matched |
| The engine has one row per turn, and an empty row only ever says so honestly | `turns=1 empty_and_their_status=["failed"] chain=["attempt","failed"]` — every stored assistant row matches its user turn, and a row with no text is a row whose status is not `complete` and whose chain names the failure. | matched after finding 2 |
| The bubble agrees with the database | `both say failed` — the newest chip's first word equals the newest stored row's status. | matched after finding 3 |
| Storage hygiene | `localStorage=["kira.base","kira.token","kira.shell"]` — the confirm secret never enters it. | matched |

## Four defects, all fixed test-first

**1 — A Gemini tool turn died on the second request.** The first `functionCall` round-trip worked; replaying it in
the history for the follow-up call got `400 Function call is missing a thought_signature`. Google's thinking models
sign every `functionCall` part and demand the signature back verbatim, and Kira dropped it, so **a tool turn that
had to replay its own call could not finish** while the unit tests — which replay their own fabricated calls — were
green. `ToolCall` grew an optional `signature` (additive; nothing in the UI, the history or the wire contract reads
it, so `API_VERSION` stays 1 and `CONTRACT_VERSION` stays 2), `Gemini` captures it when parsing and re-attaches it
as `thoughtSignature` beside the `functionCall` when serialising. Guards:
`test_gemini_captures_the_thought_signature_it_is_asked_to_return`,
`test_gemini_puts_the_thought_signature_back_on_the_function_call`,
`test_a_gemini_tool_turn_replays_the_call_with_its_thought_signature`. Measured live: the row above with
`tool_executed` between two `served` events, and an answer that quotes the tool's own epoch. One nuance the run
showed and this fix does not claim: the signature lives only for the turn that minted it — stored history carries
`{id, name, arguments}` (`app.py:241`), so a *later* turn replays an older call unsigned, and the 13:51 run's
`write_file` turn was served with the earlier `now` call sitting unsigned in its session history
(`tools=["now","write_file"]`, chain `attempt · served · tool_executed · tool_approval_requested · tool_denied`). Whether Google
enforces it only on an outstanding call is not something this pass proved; it is the reason the field is
documented as provider plumbing rather than as message state.

**2 — A turn that ended on a provider error wrote two assistant rows and called the empty one `complete`.**
The non-streaming path caught `KiraError` and `ProviderCallError` in one clause and only re-raised the first, so a
provider error that escaped the loop fell through to the success tail: a `failed` row, then a second row with no
text and status `complete`. Anything reading history — the Sessions screen, the export, a later context build —
would find a successful empty answer. Now the escaped `ProviderCallError` writes exactly one row and answers
`502` with the provider's own code, status, retryability and chain. Guard:
`test_a_turn_that_ends_on_a_provider_error_writes_one_row_and_does_not_claim_success`.

**3 — The same turn changed its name when the user reloaded.** A Gemini `503 …high demand` that arrived before the
first token was stored by the engine as `failed`; the client chip said `interrupted` — and it said it in both places
the word is set, the `error` frame handler and the `catch`. It is visible in this pass's own output:
`interrupted 0 served · 1 failed · 0 skipped · 0 tool runs` on a bubble with no text. The client now mirrors the
engine's rule in both places — text on screen makes it `interrupted`, nothing on screen makes it `failed` — and a
turn the *user* stopped is named as theirs (`you stopped this turn`) rather than as a provider fault. Guards:
`marks an error frame that left nothing to show as failed, the way the engine stores it`,
`keeps a partial answer interrupted when the error frame arrives after text`,
`records a refusal as a failed turn with its chain`, `calls a stop an interruption even when nothing had streamed
yet`. Proved live by `chip agrees with the stored row :: both say failed`, which is the assertion that would have
failed this whole pass before the fix. Making that test reachable needed one more thing: `fake-engine.ts` now wires
`init.signal` into its SSE stream, because a real `fetch` rejects the body reader when the caller aborts and
previously the stop path could not be tested at all.

**4 — A provider that answered with nothing was invisible in the chip.** `chainSummary` counted `served`,
`failed`/`aborted_mid_stream`, `skipped_*` and `tool_executed` — but unit 13's router added `empty_answer`, which
fell into no bucket, so a turn that genuinely failed rendered `0 served · 0 failed · 0 skipped · 0 tool runs`. The
chip hid the one event that explains an empty bubble. It now has its own segment, and the segment only appears when
there is one to report: `0 served · 0 failed · 1 empty · 0 skipped · 0 tool runs`. Guard:
`counts a turn that providers answered with nothing, because the chip would hide it`. This case is *not* one this
pass observed — on this machine the quota failure was recorded as a skip, not an empty answer — so the guard rests
on `router.py`'s classification, which is stated in the test's own comment rather than claimed as measured.

## Quota

The user's Gemini key is a free-tier key with a **daily request limit**, and this pass spent it. Runs after ~14:20
come back `failed 0 served · 0 failed · 1 skipped · 0 tool runs` and
`providers_exhausted: mode AUTO: nothing left to ask model 'gemini-3.5-flash' - gemini: rate_limited status=429
{"error": {"code": 429, "message": "You exceeded your current quota…`. Two things are worth naming precisely,
because they are easy to misreport as product defects:

- **Kira's behaviour is correct here.** The router does not spend a second call on a cooled provider — the ledger
  cooldown turns the attempt into a `skipped` with the reason in the chain — and the client says `failed`, matching
  the stored row. Earlier in the day the same code path returned `attempt · failed · providers_exhausted` for a
  transient `503 … Spikes in demand are usually temporary`, which is the same classification with a different cause.
- **The harness now refuses to pretend.** A turn that dies on a transient 5xx is retried once after 9 s; a step the
  provider outage makes unprovable is reported `SKIP` with the last reading printed. Before that rule, run `14:17`
  printed `26/26 ok` while its approval step actually held `no card … providers_exhausted`, and its engine-truth
  step printed a `FAIL` suffix that the ok rule ignored. The honest re-read of that run is: everything it could
  prove about a *live turn* it proved in the 13:51 and 14:17 reports together, and the approval round-trip is the
  13:51 run's, not the 14:17 one's.

Re-run when the key's daily limit resets — `RUN=15 node livepass_final.mjs` — to get one run with all 26 steps
green on the same evidence, including a live deny.

## One design question this pass raises and does not change

`router.plan()` applies the requested-model filter in **every** mode, `AUTO` included, and the model select has no
"any model" entry — so an `AUTO` turn from the UI is pinned to one provider, and the failover the engine implements
is unreachable while the picker holds a model. README documents the default as *the first catalogue row whose
provider has a key*, which is the right default for a machine with one working key, and is also why the pinning
matters here: on this machine `AUTO` has exactly one provider to fail over *to*, i.e. none. Reported, not changed —
whether the picker should gain an unpinned "auto" choice is the user's call, and it is a contract-visible decision
(`API_VERSION` and `CONTRACT_VERSION` would not move, but the select and `ChatRequest.model` semantics would).

### Resolved 2026-10-31

The user asked for the change, and it shipped test-first. `AUTO` now treats a named model as a *preference*: the providers that
carry it are put at the front of the queue and every other configured provider stays behind them, each answering with its own
`models[0]` (`kira-engine/src/kira/router.py:94`). `FAST`, `POWERFUL` and `CUSTOM` keep the hard filter, so the strictness this
section defended is only relaxed in the lane that means "you decide". The pickers gained an unpinned entry, `Auto · the
router picks`, which sends `model: null`, and it is the default — README's *first catalogue row whose provider has a key* is
gone because it was the pin. `API_VERSION` 1 and `CONTRACT_VERSION` 2 did not move, exactly as predicted: `attempt` and `served
already name the model that answered, so a cross-provider fallback reports itself without a new chain event. See ROADMAP
§Failover from a pinned model, and `kira-engine/tests/test_routing.py`.

## What this pass cannot prove

Failover across two *live* providers is still unproved: this machine has one working key, so the second hop is
always a script or a skip. The `503` high-demand path is proven to be classified and reported honestly, not proven
to recover — the retry exists and the turn that needed it came back, but Google's capacity is not something this
pass controls. A month of real spend, a mid-stream abort on a live provider, the two local voices (neither
installed) and an approve-with-write against the live engine (the sandbox pass did the approve; the live pass did
the deny) are all outside it. And one run's quota failure is a provider reality, not a regression — which is exactly
why it is reported as a skip with the reason printed rather than as a pass or a bug.

## Gates at this run

- `kira-engine`: `pytest -q` → **367 passed, 1 skipped** (the skipped file is the live-provider suite).
- `kira-chat`: `npm run check` → tsc clean, **25 files / 216 tests**, vite build, stamp
  `{api_version:1,contract_version:2,api_prefix:"/v1"}`.
- `node kira-contracts/check-drift.mjs` → `kira-contracts OK — v2, 56 schemas, 6 chunk types, 16 chain events`.
