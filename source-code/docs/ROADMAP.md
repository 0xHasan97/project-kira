# Kira — full project roadmap

Generated 2026-10-28. Every **done** line below is backed by a command that was run; every
**not started** line is a claim about code that does not exist. Percentages state their method,
because a bare percentage is unfalsifiable.

## Where Kira actually stands

| | |
|---|---|
| Engine | `kira-engine/` — config, Credential-Locker vault, SQLite WAL store, 3 provider kinds, router with failover + provenance chain, FastAPI `/v1` SSE, contracts-first OpenAPI |
| Client | `kira-chat/` — React 19 + TS, eleven routes (ten on the rail, in two shells Chat / Agent, plus `#/pair` which renders before the token gate), hash routing, per-write confirm gate, a live `#/call` screen on its own WebSocket, and a `#/remote` that mints pairing codes |
| Launch | `run-kira.bat` + `run_kira.py` — one click, loopback only, builds the bundle it serves |
| Gates | 822 engine tests (+8 skipped) · 510 chat tests across 48 files · drift gate `v2, 77 schemas, 6 chunk types, 16 chain events` · README-vs-engine test |
| Real UI run | Browser passes over the routes: sub-project 9's dashboard pass, sub-project 10's shell pass, unit 6's call pass, unit 2's tool/approval pass and unit 4's memory pass — all against a scripted provider: `docs/qa/dashboard-browser-pass.md`, `docs/qa/shell-modes-browser-pass.md`, `docs/qa/call-browser-pass.md`, `docs/qa/tool-harness-browser-pass.md`, `docs/qa/memory-browser-pass.md`, `docs/qa/skills-browser-pass.md` and `docs/qa/remote-pair-browser-pass.md`. The 2026-10-31 pass over the unpinned picker and the `AUTO` soft pin is `docs/qa/auto-pin-pass.md`. The 2026-10-29 re-run of the whole surface, including the approval round-trip and the keyless-provider labelling, is `docs/qa/full-app-live-pass.md`. **The same day, the surface was also driven against the real engine with the user's own Gemini key** — a streamed answer, a model-chosen `now` call whose epoch the model quoted back, and a model-asked `write_file` that the harness denied and that wrote nothing: `docs/qa/live-app-pass.md`, which found four more defects, all fixed test-first. Unit 5's pass (`docs/qa/unit-5-local-model.md`) drove the same surface against a real local model on this machine, not a scripted one. What no pass can prove here is the two local voices, because neither is installed. The 2026-10-31 pair went the other way round: `docs/qa/agent-shell-pass.md` drove the agent surface and the composer on a desktop window and found three defects (a settled approval still wearing a pending clock, an offline shell that said nothing, and a desktop layout that scrolled the document instead of the thread), and `docs/qa/mobile-web-pass.md` read the manifest, the worker's cache contents and the 390 px geometry out of an emulated phone. |
| Live providers | **Proved over the wire on 2026-10-29** with the user's own Gemini key: `KIRA_LIVE=1` answered for real and the record is `docs/qa/live-providers.md` + `docs/qa/live-providers.json`. That pass found four genuine defects — silence counted as an answer in the router and in the probe, a probe budget under a thinking model's hidden output, a model name Gemini has retired, and 401/403 aborting instead of failing over — all fixed test-first. **Same day, later: that Gemini key is a free-tier key with a daily request limit, and the app pass spent it** — `429 …exceeded your current quota` with the cooldown escalating 20 → 40 → 80 s. It was never a billing problem to solve and never a code defect: Kira records `failed` + `providers_exhausted`, names the reason in the chain, and stops spending on a cooled provider. Earlier that afternoon the same key served real turns (answer, tool call, approval), and the pass re-runs when the limit resets. Still not true: the openrouter entry in this machine's Locker is a one-character placeholder (it answers `400` to everything, including `GET /models`), and groq and anthropic have no key at all. BYOK means the user supplies those; nothing is fetched, scraped or shared. |
| Keyless providers | **Found and fixed test-first on 2026-10-29.** `ProviderRegistry.build()` refused any provider whose key was absent from the Locker, while `router.plan()` had already decided a provider that declares no `key_ref` needs none — so a local OpenAI-compatible server (unit 5's whole point) could be listed but never built, and the chain told the user to run `kira-engine keys set ` with an empty ref. Contract v2 grew `needs_key` beside `key_present` (additive: `API_VERSION` 1, `CONTRACT_VERSION` 2 unchanged), and `kira-chat/src/keying.ts` is now the single place that decides what the pair means, so four surfaces stopped labelling a keyless provider `no key`. Recorded in `docs/qa/full-app-live-pass.md`. |
| Not yet true | Tools work only inside `data_dir/workspace`; no OS control. Memory is **lexical only** — a paraphrase that shares no token with the stored text is a miss, and `#/memory` is where you see that. The desktop window exists (unit 3) but is an ordinary rectangular app: no global hotkeys, no click-through overlay, and the artefact is a folder to copy, not an installer. The offline tier is real but CPU-only and small: a 4 B Q4 model is a floor, reached last in `AUTO`, not a substitute for a remote frontier model. The voice stack now runs locally through a Portable AI Studio tree: `whisper-cli` with `ggml-base.bin` and a Kokoro runtime are present, so `voice.stt_engine: auto` / `voice.tts_engine: auto` pick them; Kokoro downloads its ONNX model into the studio's `tts-cache` on first use. |
| Failover from a pinned model | **The open question is closed — decided and shipped 2026-10-31, at the user's instruction (`fix all of this`).** `router.plan()` used to apply the requested-model filter in every mode, `AUTO` included, and the model select had no unpinned entry, so an `AUTO` turn from the UI was tied to one provider and cross-provider failover was unreachable from the picker: invisible while one key worked, fatal with two. A model named in `AUTO` is now a *preference* — the providers carrying it stand at the front of the queue and every other configured provider stays behind them, each answering with its own `models[0]` (`kira-engine/src/kira/router.py:94`, `:109`). `FAST`, `POWERFUL` and `CUSTOM` keep the hard filter, and a model no provider carries is still refused in the same words (`no provider in mode AUTO offers model …`, `:91`), so a typo in the picker cannot spend a turn. No contract change was needed: `attempt` and `served` already name the model that actually answered, so a fallback reports itself instead of wearing the pinned id. The select opens on `Auto · the router picks`, which sends `model: null`, and a pin the catalogue no longer recognises drops back to it rather than posting an id the engine refuses. Proven test-first (`kira-engine/tests/test_routing.py`, `kira-chat/src/App.test.tsx`) and against this machine's live config with zero provider calls: naming `qwen3:4b` now queues `ollama → gemini → openrouter` where it used to queue ollama alone. Driven in a browser the same day: with `mini` pinned to a provider that is over its cap and the only provider carrying it, `AUTO` answered anyway (`over budget · used 150 of 149 tokens` → `mock_two · answered · solo`) while `FAST` refused the same click — `docs/qa/auto-pin-pass.md` checks 7 and 8. See also `docs/qa/live-app-pass.md` §One design question, which asked for exactly this. |
| Vision in the live config | **Marked 2026-10-31.** The engine has always had the flag — `ProviderConfig.vision` (`kira-engine/src/kira/config.py:32`, parsed at `:181`), the sample config inside `config.py` sets it — but this machine's `.kira-data/config.yaml` carried no `vision:` stanza, so `#/call` had nowhere to send a webcam frame: the flag is read back at `kira-engine/src/kira/app.py:899`, reaches the client over `GET /v1/kira/providers` and `GET /v1/kira/voice`, and `voice/stack.py:_pick_vision` (`:75`) refuses any provider that does not declare it. `openrouter`, `anthropic` and `gemini` now say `vision: true` — all three provider kinds implement image parts — and `groq` (`llama-3.3-70b-versatile`) and `ollama` (`qwen3:4b`) are deliberately left unmarked, so a call served by one of them keeps frames on the device and the chain says `images_dropped` rather than losing them quietly. Measured here without spending: `GET /v1/kira/voice` returns `vision = {"provider": "gemini", "model": "gemini-3.5-flash"}`, and Providers says `sees images` on exactly those three rows. The same flag was driven in a browser against a lab whose second provider is the only one marked: `#/providers` read `sees images` / `text only` and `GET /v1/kira/voice` chose `{"provider": "mock_two", "model": "solo"}` — `docs/qa/auto-pin-pass.md` checks 4 and 10. |

## Units

Numbering follows the decomposition recorded in the spine spec (8 units) plus the two the user
added later (9, 10) and the three this month's requests exposed (11, 12, 13). Each unit gets its
own spec → plan → implementation cycle; that is why #9's plan ran 20 tasks and #1 ran seven
milestones.

| # | Unit | Status | Evidence / blocker |
|---|---|---|---|
| 1 | Spine: engine, providers, router, API, contracts, chat client, launcher | **done** | M1–M7, real-browser run |
| 9 | Control dashboard: settings overrides, monthly caps, keys over HTTP, history deletion | **done** | M8–M12, merged to `master`, contract v2 |
| 10 | Shell modes: Chat/Agent switch, MYRAA + ALTREX/PocketStrike skins | **done** | `docs/specs/2026-10-28-kira-shell-modes-design.md` → `docs/plans/2026-10-28-kira-shell-modes.md` (18 tasks) → `docs/qa/shell-modes-browser-pass.md`; merged to `master` (`e327eb6`) |
| 2 | Tool harness + permissions: real tools, allow/ask/deny, checkpoints, declarative plugins | **done** | `docs/specs/2026-10-28-kira-tool-harness-design.md` → `docs/plans/2026-10-28-kira-tool-harness.md` (21 tasks) → `docs/qa/tool-harness-browser-pass.md`; spend-ledger + usage-estimate findings closed inside it |
| 4 | Memory + retrieval | **done** | `docs/specs/2026-10-29-kira-memory-design.md` → `docs/plans/2026-10-29-kira-memory.md` (13 tasks) → `docs/qa/memory-browser-pass.md`; M19–M22 shipped and merged to `master`. Facts with pin/edit/forget and dedupe, a bounded injected block (pinned → BM25 → recent, 12 items / 1 500 chars), `recall` and `remember` tools behind the capture switch, opt-in extraction, FTS5 history search that indexes `user`/`assistant` text only, `GET /v1/kira/memory{,/search,/settings}`, export, and a real `#/memory` screen in both shells. Contract v2 grew ten schemas, 56 → 66. PocketStrike's Hermes files + laya's ChromaDB+FTS5+RRF were the two studied designs; RRF stayed deferred, because one index and one query have nothing to fuse. |
| 5 | Offline / local model tier | **done, runtime moved to llama.cpp** | `docs/qa/unit-5-local-model.md` recorded the first tier on Ollama; Ollama has since been uninstalled and its models removed. The tier is now a keyless `openai_compat` stanza at `priority 140` / `tier fast` — last in `AUTO`, first when named — and `#/studio` can start/stop `llama-server` from a Portable AI Studio tree, adding `local_llama` while it runs. Proved live 2026-11-21: a 13 GB Qwen 35B Q2 GGUF loaded in 81 s, answered over `/v1/chat/completions`, and the provider disappeared on stop. Machine measured: Ryzen 5 5600G, 24 GB, **RX 5500 4 GB, AMD — no CUDA**, so layers stay on CPU unless `KIRA_LLAMA_NGL` opts in. The image half of the same studio integration is a separate row below |
| 3 | Desktop shell (window, tray, launcher packaging) | **done** | `docs/specs/2026-10-30-kira-desktop-shell-design.md` → M27 module/CLI/`--window`, M28 packaging, M29 pass, M30 docs/gates → `docs/qa/desktop-shell-pass.md`. `kira-engine desktop` runs the same loopback engine and the same `Vault` on a daemon thread behind a pywebview 6 / WebView2 window that renders `/chat/`; the window boots hidden, one JSON-encoded `localStorage.setItem` puts the token in memory-only storage (`private_mode`) and the second load shows the window, so the connect gate never flashes. The confirm secret is never injected. pystray tray (Show / Open in browser / Quit), close-to-tray, one window per data dir via a named mutex, geometry in `<data>/desktop.json` (geometry only). The packaged build is PyInstaller onedir: `kira-engine/packaging/build.ps1` → `packaging/dist/Kira/Kira.exe`, 55 MB, `console=False`, frozen data dir `%LOCALAPPDATA%\Kira`, chat bundle inside `sys._MEIPASS`. The live pass found three defects, all fixed test-first: the never-showing window (a same-URL navigation raises no second `loaded`), a second-launch message that contradicted the window it had just raised, and both frozen paths (`sys._MEIPASS`, `%LOCALAPPDATA%`). **Not in it:** no global hotkeys/PTT, no click-through or transparent overlay (that stays unit 11), no installer, no code signing, no auto-update, no start-with-Windows |
| 6 | Voice: capture, VAD, STT, TTS, barge-in, wake word | **done** | `docs/specs/2026-10-28-kira-realtime-call-design.md` → `docs/plans/2026-10-28-kira-realtime-call.md` (12 tasks, all executed) → `32cc337..77581e6`, merged to `master` (`8ff4e17`). Shipped: energy VAD, local/BYOK STT + TTS, `WS /v1/voice` with sentence-sliced playback and local barge-in, webcam self-view + 4 s vision frames, `#/call`. `docs/qa/call-browser-pass.md` drove it on a real browser with fake devices and found three defects, each fixed test-first. **Wake word is not in it** — see the note below |
| 11 | 3D avatar stage (MMD/PMX) | **in progress — T16** | T1–T15 complete (import, routes, screen, idle, visemes, companion). T16 live-pass load fixes: `render_head` separation (`mesh.py`), loop detection (`krm1.ts`), texture folder prefix (`pmx.ts`). All 509 chat + 820 engine tests pass. 10 donor archives imported. `docs/qa/avatar-stage-pass.md` recorded. Connect gate removed; app boots directly to shell. Remaining: T16b live stage measurement, final commit. |
| 12 | Remote reach (phone) via loopback + pairing token | **done** | `docs/specs/2026-10-30-kira-remote-reach-design.md` → M25/M26, browser pass `docs/qa/remote-pair-browser-pass.md`. The compliant substitute for Ultron's `0.0.0.0` bind: the engine still binds loopback and never adds a listener — the user's own tunnel (Tailscale Serve, `cloudflared`, SSH) forwards to `127.0.0.1:8901`. Kira adds two principals: the owner token from first run, and a `kd_` device token minted by an 8-character single-use 120 s code exchanged at most 10 times a minute. A device reads and chats; every mutation is closed to it because the confirm secret never leaves the desktop, and so are `GET /v1/kira/devices` and minting a code. Only the SHA-256 of a device token is stored (schema v3 `devices` table, revoked rows kept), revocation is 401 from the next request, and `#/pair?code=…` renders before the token gate so an unpaired phone can reach it. Contract v2 grew six schemas, 71 → 77. The pass found two defects, both fixed test-first: one shared `sqlite3.Connection` across FastAPI's threadpool (now one per thread, WAL, `busy_timeout`) and the rail's refresh never re-reading the screen on show (every data screen now takes a `pull` counter). **Not in it:** no QR code, no LAN listener of any kind, no bundled tunnel, no per-device scopes |
| 7 | Skills pack | **done** | `docs/specs/2026-10-30-kira-skills-design.md` → M23/M24, browser pass `docs/qa/skills-browser-pass.md`. A skill is Markdown with frontmatter; `persona` is pinned to a turn by `ChatRequest.skill` and becomes its first system message (memory block appended after), `method` is offered through one built-in `use_skill` tool and only enters the prompt when the model asks. Two roots — builtin `kira-engine/skills/` (`concise`, `reviewer`, `debug`, `research`) and `data_dir/skills/`, which shadows a builtin of the same name — and a bad file is listed with its reason, never fatal. `GET /v1/kira/skills` and `#/skills`, with a composer chip that shows and clears the pinned persona. Contract v2 grew three schemas, 68 → 71. **M35 (2026-11-04): the pack stopped being a demonstration.** A skill now also loads in the folder form `skills/<name>/SKILL.md` that published packs use; `kira-engine skills install PATH` copies a pack someone else wrote — a `.zip` or a folder — into `data_dir/skills`, reading only `<top>/skills/<name>/SKILL.md` and the `LICENSE` files, so no `.py`/`.js`/`.sh` from the archive is copied or run and the same skill shipped for three harnesses lands once; a donor file with no `kind` becomes `kind: method`. Past `INLINE_LIMIT = 24` methods `use_skill` stops carrying every name — 268 of them on every request is a kilobyte tax — and `search_skills` becomes how the model finds one. `GET /v1/kira/skills` answers `discovery` (`none`/`inline`/`search`) so the screen and the CLI say what the engine does rather than repeating a guess, and `#/skills` gained a search box, a kind filter and counts. ECC-main is installed on this machine: **266 of its 314 canonical skills**, 48 refused for the 16 KB prompt cap and one unusable name, MIT notice copied, in both `Kira/.kira-data/skills` and the lab. **Not in it:** no code in a skill, no per-skill model or tool override, and no import route — a CLI that copies from a path the user names is the install surface, an HTTP endpoint that would is a larger blast radius. **M36 (2026-11-26): the prompt library Mia described is `#/prompts`.** Twelve built-in instructions in three categories plus automations, each with `{name}` placeholders that must be filled before use; a custom prompt is saved in this browser under `kira.prompts`, and using one fills the composer and hops to chat. No engine route and no scheduler: a prompt is a starting instruction, not a stored conversation. `rea` joins the builtin methods as a ~2 KB distillation of the 23 KB donor skill (over the 16 KB cap), with its MIT notice in the frontmatter |
| 8 | Web + mobile surfaces | **done** | `docs/specs/2026-10-30-kira-web-mobile-design.md` → M31 manifest/icons-in-code/service worker/engine headers, M32 phone layout, M33 pass → `docs/qa/mobile-web-pass.md`. One bundle, one engine, no second codebase: the phone gets a layout. `manifest.webmanifest` (`standalone`, `scope: /chat/`, 192/512/maskable PNGs + `theme-color` + `apple-touch-icon`, every icon drawn from the same `draw_icon` code as the tray icon), and a service worker that answers navigations network-first and assets cache-first under a cache name hashed from the built `index.html` — so a new build can never be shadowed by an old shell — and **never caches `/v1`** (proved by reading `cache.keys()` back: 5 shell entries, zero API entries). At 390×844: `100dvh` shell with the thread as the only scroller (`documentElement.scrollHeight` = viewport), bottom bar Chat · Call · Sessions · Overview · Menu with 44 px targets, the full rail behind Menu, session/provider strip capped at 34 dvh, safe-area insets on the bar and the composer, 16 px type where iOS zooms on focus. Offline was driven for real: the shell mounts from cache, the token survives, and the screen says `no answer from the engine at http://127.0.0.1:8901` instead of pretending there is nothing to talk to. **Not in it:** no real phone (Chromium's emulation, not iOS Safari or Android on hardware), no install prompt clicked, no standalone window launched, no Lighthouse run — and a phone across a tunnel needs TLS from that tunnel, because `http://127.0.0.1` is a secure context and a forwarded port is not. **M37 (2026-11-27): the shell got cheaper and gained an index.** The 3D stage, call, companion and Studio are lazy routes instead of static imports, so the first JavaScript bundle is 359 KB (108 KB gzip) rather than 962 KB; the 566 KB stage is fetched only by a screen that draws it, and a rail hover/focus starts that fetch early. Hashed `/chat/assets` now carry `public, max-age=31536000, immutable`, while `index.html`, `sw.js` and the manifest stay `no-cache`; the worker stores a route chunk after its first online visit so a lazy screen still opens offline. Ctrl/Cmd+K opens a command palette over every rail label plus new chat, appearance, settings and refresh; the chat header and a Sessions transcript export Markdown with provider/model evidence; Sessions filters by id or mode. **Not in it:** no per-screen data cache, no compression middleware (the tunnel may already compress), and no focus trap in the palette |
| 13 | Findings cleanup: the 12 items #9's browser pass wrote down | **done** | `docs/specs/2026-10-30-kira-unit-13-findings-design.md` → `docs/qa/unit-13-findings-pass.md`. Ten fixes across engine and client: a refusal ledger outside `messages` (overview counts `refusals`), plan notes once per turn, 401 returns to the gate, baseline-equal overrides dropped, the sitting survives a reload (`sessionStorage`), the picker groups by id and names every provider, Providers shows `at cap`, user rows lose the assistant's status/token columns; `never` as `last used` recorded as unreachable display code. Findings F3/F4 were fixed inside the pass itself |

## Completion, with the arithmetic

Weight = delivered milestones, calibrated on the finished units (#1 = 7, #9 = 5, #10 = 3, #2 = 6 →
21 delivered). Unit 6 was estimated at **3** milestones in the plan (VAD+STT, TTS+stack+doctor, the
WebSocket call + client + screen) and delivered all three, so it joins the numerator: **24 delivered**.
Unit 4 was estimated at 3 and delivered **4** — storage+tokenizer (M19), recall+injection and the
`recall`/`remember` tools (M20), API/contract (M21), and screen+docs+browser pass (M22) — so it adds 4
and the numerator was
**28**. Unit 13 was estimated at 1 and delivered 1 (the findings closeout, ten fixes with tests and
the decision record), so the numerator became **29**. Unit 5 was estimated at 3 and delivered 3 —
install + models, the stanza and a live engine turn, and the docs/gates/browser pass — so it was
**32**. Unit 7 was estimated at 2 and delivered 2 — the loader/prompt assembly/`use_skill`/route
(M23), then the screen, the composer chip and the docs (M24) — so it was **34**. Unit 12 was
estimated at 2 and delivered 2 — the devices table, pairing, the second principal and the routes
(M25), then `#/remote`, `#/pair`, the docs and the browser pass (M26) — so it was **36** (an
earlier line printed 35; 34 + 2 is 36). Unit 3 was estimated at 3 and delivered 3 — the window,
tray, single-instance lock, token injection and `--window` launcher (M27), the PyInstaller
build (M28), and the live pass plus docs and gates (M29) — so the numerator was **39**. Unit 8 was
estimated at 3 and delivered 3 — the manifest, icons-in-code, worker and engine headers (M31), the
phone layout (M32), and the live pass with docs and gates (M33) — so the numerator is **42**.
Remaining estimates: 11 ≈ 2 → **2**, so the project stays at **44** weighted milestones.

**42 / 44 ≈ 95 %** of the project as currently imagined. Range **92–96 %**: the denominator moves
whenever a unit is added, and unit 4 overshot its own estimate by one, which is the direction the
range's upper end already assumed. Unit 8's 3 is provisional in the same way unit 12's was: the
manifest, the worker, the cache discipline and the 390 px geometry were read out of a real browser, but
no phone held the device, no install prompt was clicked and no standalone window was launched. Unit 6's share is still provisional on the two local voices
actually running, which no machine here has done; units 3, 4, 5, 7 and 12's are not — all five ran
against the real engine, and unit 5 answered a live turn on this machine's own hardware. Unit 13's 1
is honest in the other direction: the fixes are unit- and API-tested, not browser-driven, and its own
record says so. Unit 5's 3 is honest in a third direction: the model is real but small, and the tier
is CPU-only on this GPU. Unit 7's 2 is honest in a fourth: the mechanism is proved end to end, but
the shipped pack is four starter files — a library of skills is content, not code. Unit 12's 2 is
honest in a fifth: the pass reached `#/pair` through a loopback reverse proxy standing in for the
tunnel and a second browser context standing in for the phone, so what was proved is the code path,
not a phone on a Tailscale tailnet. Unit 3's 3 is honest in a sixth: the window, the tray
registration, close-to-tray, the single-instance guard and both frozen paths were driven by the OS,
but the tray *menu* was never clicked, `Quit` and the geometry *write* were not observed live, and
the artefact is an unsigned folder — `docs/qa/desktop-shell-pass.md` says each of those in its own
words.

Three honest deductions from that 95 %:

- **Wake word did not ship**, and the unit's title says "wake word". The call is push-to-start. A wake
  word means the engine processes audio continuously before any conversation exists, which contradicts
  the rule the call is built on (the microphone's PCM leaves the browser only once a call is live and
  unmuted). If you want it, it is a small unit of its own — a keyword model in the browser, e.g.
  Porcupine or openWakeWord, gated on your consent to a model download.
- **Nothing has ever been heard or spoken on this machine.** Both local stages are absent by default,
  so every engine test in unit 6 fakes whisper and Piper, as it must. The browser pass read a real
  microphone — Chromium's fake device, but through the worklet, the socket, the VAD and the commit that
  would have handed a wav to whisper — and every packet came back `stt_unavailable`. The remote path is
  the one that will actually run first, and it wants a key.
- **Memory is lexical.** FTS5 with `bm25` and a `LIKE` fallback finds what shares a token with what was
  stored; ask "what language do I like for scripts?" and a stored "I prefer pnpm" is only found if the
  query also says pnpm. Embeddings and RRF are the fix, and both were deliberately deferred — no
  second index exists to fuse, and unit 5 shipped a chat model but no embedding model, so a v2 index
  would need a second local pull before it had anything to search. `#/memory`'s
  history tab is exactly where the miss is visible: it returns nothing rather than the near miss, which
  is honest but not smart.

The same repo read a different way, which is the more useful framing:

- **A chat product that works end to end: 100 %.** Type a prompt, get a streamed answer from a
  provider you configured, with failover, provenance, budgets, caps and a dashboard, one click to
  start. Nothing in that path is stubbed.
- **An agent product: ~70 %.** It has two full surfaces, real tools behind a three-policy gate,
  checkpoints with restore, declarative plugins, a spend ledger, a voice/video call, memory that
  is captured, injected and searchable, a native window with a tray instead of a tab, an installable
  phone surface, and — since the 2026-10-31 agent pass — a turn that reads as a turn: a folded
  transcript in verbs, a composer that answers to Enter, and a status strip that counts the open turn.
  What a user would still read as missing is a body with a face (unit 11) and acting unprompted (a
  scheduler no unit owns yet — Mia's "automations").
- **Ambition covered by the corpus so far: 12 of 13 units.** The capability matrix was built from
  every donor; Kira implements the spine, the control surface, the two-shell skin, the harness, the
  real-time call, memory + retrieval, the offline tier, the skills pack, remote reach through the
  user's own tunnel, the desktop shell, the web/mobile surface and the findings cleanup that keeps all
  of those honest.

## Order, and why

```
10 skins/switch ──► 2 harness ──┬──► 4 memory (done) ──► (11 avatar needs 3 shell, done)
                                ├──► 5 offline model (done)
                                ├──► 6 voice ────► (done, out of order — see 4.)
                                └──► 7 skills (done) ──► 12 remote (done) ──► 8 web/mobile (done)
                                13 findings (done, rode along)
```

1. **#10 first** because it is the visible thing you asked for, it is client-only, and it rolls
   back by deleting one HTML attribute. No engine risk.
2. **#2 is done** because Agent mode's five empty work-panel tabs were a standing advertisement for
   it, and #4, #6, #11 and #12 all hang off a tool registry with a real policy. The four excluded
   Ultron shapes got their compliant replacements designed: argv-only commands, a workspace
   boundary, per-tool policies and confirm-gated restore.
3. **#13 rides along** — the delete-all re-arms caps finding and the omitted-`usage` finding should
   be fixed inside #2, since both touch spend accounting and #2 touches the same code.
4. **#4 before #6 was the plan; #6 went first on your request.** You asked for the real-time call
   against the diagram (Pi + webcam → Whisper → local model → Piper) and it was the visible thing, so
   it moved ahead of memory. The cost of that order is exactly what the plan predicted: a call you can
   have is a call the engine forgets the moment the socket closes. `voice/call.py` keeps a rolling
   `HISTORY_TURNS` window for the length of one call and writes the transcript to the same
   `messages` table chat writes to, but nothing is *recalled* — unit 4 is now the difference between a
   call that answers and a call that knows you.
   **Unit 4 shipped 2026-10-30, so that bill is paid:** a call's transcript is written to `messages`
   and indexed by the same history search, and the injected fact block rides the call's first prompt
   like any chat turn.
5. **#3 before #11**: an avatar needs a window that can be transparent and click-through; a browser
   tab cannot do it. And #11 waits on you supplying a `.pmx`.
6. **#5 shipped when the GPU question was answered the cheap way** — it is a router tier, not new
   plumbing. No CUDA here, so it runs CPU-only on a 4 B Q4 model, sits last in `AUTO`, and is the
   answer when the network is down rather than a replacement for a remote model.
7. **#8 last, and it stayed worth waiting for**: mobile is a second surface for a product whose first
   surface still changes weekly. It shipped 2026-10-31 as a layout and a worker on the same bundle —
   which is why it cost 3 milestones and not 8.

## Donor intelligence — what `leanrea-main.zip` and `rea-main.zip` do and do not give us

Read 2026-10-28 at the user's pointer (`Ai agents/rea (skills)/`). Asked and answered: can they
recover the two donor looks §2 of the #10 spec declared unknowable?

- **`rea-main.zip`** is *Reverse Engineer Anything*: ~30 markdown references plus MCP/IDA/npm
  tooling (`docs/ida-provider.md`, `docs/binary-diagnostics.md`, `docs/browser-observation.md`).
  It has **no PyInstaller guidance and no NSIS/Inno-Setup guidance** — the corpus-wide grep that
  first appeared to match "NSIS" was matching the substring in "co**nsis**tent". Method is worth
  stealing: label every claim **seen / inferred / unknown**, and "static reading is not observed
  execution".
- **`leanrea-main.zip`** is the CLI-only distillation (already installed at user scope). Its
  commands are macOS-first — `otool -L`, `lipo`, `nm`, `brew install`, APFS `cp -c`. It covers
  Electron asar, minified JS with sourcemaps, Go, Hermes, APKs, SQLite, pcaps. It does **not**
  cover either of our two blind targets.
- **What this machine can actually do:** `7z`/`7za`/`7zr` are **not installed**, so there is no
  generic archive-extractor path today. Probes run:
  - `ZORION.exe` — 7 `pyi-` markers and a `python312.dll` string at the tail: a normal PyInstaller
    onedir whose CArchive is appended to the exe. Carving it is a **stdlib Python job** (read
    TOC by offset, `zlib` decompress, no execution) — but whether the QML that draws its screens is
    *inside* that archive is **unknown until carved**. `_internal/ui/qml/` being empty is the bad
    sign; data files usually land in `_internal`.
  - `NEXTRON-X100-V2-Setup.exe` — `MZ` header, **no** `NullsoftInst` and **no** `Inno Setup Setup
    Data` in its last 1 MB, an embedded `MZ` in there somewhere, no `app.asar` in the first 5 MB.
    Format unidentified. Without an installer-recognising extractor it stays opaque.
- **Verdict:** neither archive unblocks the two looks. A ~40-line stdlib carver is a legitimate
  1-spike unit for ZORION, and `unknown` is the honest answer for NEXTRON-X100 — screenshots from
  you, or consent to install a third-party extractor, are the two ways past that. Ground rule 3
  (never execute donor installers) is why "just run it" is not on the menu, and nothing above ran
  anything.

## Donor intelligence — project-Mia, read 2026-10-29

The user's own assistant, at `Ai agents/project-Mia` (Streamlit UI + LangGraph `create_react_agent`,
~18 capabilities across `core/`, `handlers/`, `ui/`, `voice/`, `integrations/`). **Method:** read-only
source inspection, as everywhere else in this section — nothing in that folder was executed, no
installer or script run (ground rule 3), and **no credential value was opened, quoted or logged**; the
redaction scan that found the finding below printed field names and character counts only.

**First, the thing that is not a feature request.** `data/providers.json` holds **three live provider
keys in plaintext** — `providers.freellmapi.key` (59 chars), `providers.groq.key` (56 chars, `gsk_…`
shape), `providers.gemini.key` (53 chars, `AQ.…` shape) — and `core/config.py` reads them straight
through a `key` field, while Settings → Raw renders the whole config to screen. `.env` is present but
every value in it is empty, so it is not the leak.

**Moved off disk on 2026-10-31, at the user's explicit instruction ("fix all of this"), which replaced
the recommendation below.** Each key was written to the Windows Credential Locker under
`archive/project-Mia/<provider>` (service `kira`), read back and compared, and the JSON field now holds a
pointer string naming that entry. No key material is left in the file, and none was printed, quoted or
logged during the move. **Rotating the three at their providers is still yours to do** — moving a secret
off disk does not un-expose it, and a key that has sat in a plaintext JSON in a folder that has been
zipped, copied and shared around is a key to treat as exposed. To hand one back to the donor app, read the
Locker entry and paste it into that field. What did **not** happen: none of them were copied into Kira's own
`provider/*` entries — BYOK means a credential the user did not type here is not silently adopted into the
router, and the move was to an archive namespace, not a routing one. Note that one of the three is a
working **Groq** key — which is why this roadmap's line "groq has no key" reads as true for *Kira* and
false for *this machine*. The pinned-model failover question this paragraph used to hang on is answered
without it: `AUTO` now treats a named model as a preference and keeps every other provider behind it (see
§How routing decides), so a second keyed provider widens the queue instead of being the only way to have one.

**What Mia has that Kira does not**, ranked by what it would cost to port:

| Gap | Mia's mechanism (file) | Where it lands |
|---|---|---|
| Personas + response styles + a prompt library | hardcoded personality/style/fun-mode dicts concatenated into the system prompt (`core/agent.py:229-247`, `core/grok.py:3-9`); saved templated prompts with `{vars}` (`core/prompts.py`, `data/prompts.json`) | **library shipped 2026-11-26 as `#/prompts`**; personas remain skills, because a persona is a prompt pack, not an engine feature. The library is browser-local (no engine row) and its templates are Kira's own |
| One-click "Automations" | button-run saved prompts, **no trigger** (`core/automations.py`, `data/automations.json`) | **shipped 2026-11-26 as the `Automation` category in `#/prompts`**, still one click and still no trigger. A scheduler remains unowned; see the correction below |
| Multi-step research that writes a report | decompose → ≤3 web searches → synthesise, live step expanders, downloadable markdown (`core/grok.py:30-75`) | fits Kira's existing loop: a `web_search` tool + a step spine already exist in the Agent shell; the orchestration is a prompt + one tool |
| Read-only tools without a workspace | YouTube transcript, web scrape, SMTP mail, PDF/DOCX/CSV extraction (`integrations/*.py`, `handlers/pdf_export.py`) | unit 2's registry, each as risk `network`/`read` behind the existing `ask` default |
| Image generation + gallery, screen/camera capture | 6 providers, seeds, batch threads, PNG gallery (`core/imagegen.py`, `data/gallery/`); `mss` capture (`core/handlers.py`) | **image generation shipped 2026-11-21** after studying Portable AI Studio: `#/images`, stable-diffusion.cpp behind `image_generate`, PNG + JSON sidecar gallery, no bundled weights (`kira-engine/src/kira/images.py`). **Full studio integration shipped 2026-11-21**: `#/studio` discovers the folder, reuses `sd-cli`, `llama-server`, `whisper-cli` and Kokoro in place, starts/stops the local chat server, and downloads a model only through an explicit allowlisted request. Live: a DreamShaper XL PNG at 512×512 in 75 s and a 35B GGUF answering over the local provider. Screen/camera capture stays closed: it is the desktop-control door the tool harness chose not to open |
| Wake word that actually runs | openWakeWord "hey jarvis" on a daemon thread (`voice/wake_word.py`) — but `consume()` is never polled, so it triggers nothing | unit 6's deferred wake word; the donor got as far as the model, which is the same wall Kira documented (continuous audio before consent) |

**Three corrections to what this roadmap previously assumed about the corpus**, because the audit
contradicted the folklore and a roadmap that repeats a wrong assumption is worse than an empty one:

- **Mia has no memory system.** `data/memory.json` is a hand-edited facts file injected wholesale as a
  text prefix (`core/memory.py:build_memory_prefix`) — no FTS, no embeddings, no retrieval, no
  auto-extraction. `data/mia_memory.db` is a LangGraph `SqliteSaver` **checkpoint store**
  (`core/agent.py:100-134`), i.e. conversation state, not user memory. Chat history itself lives in
  `st.session_state` and is lost on restart. So unit 4 has no donor design to reimplement here; the two
  studied designs remain PocketStrike's Hermes files and laya's ChromaDB+FTS5+RRF.
- **Mia's tools have no permission model.** Four `@tool`s (`web_search` via ddgs plus three REA tools)
  appended to the ReAct agent with no gate, and their outputs are dropped from the stream
  (`core/agent.py:11-97`). Kira's three policies, confirm-gated approvals and checkpoints are strictly
  more than the donor, so unit 2 gains nothing from it.
- **`ALTREX/` inside Mia is orphaned** — `core/altrex_integration/*` is imported by neither `mia.py` nor
  `ui/`, and `paperclip/` + `rea/` are vendored third-party apps Mia shells out to, which is where the
  26,847-file FreeLLMAPI-style bulk in this folder comes from. Porting them would be porting a *donor's*
  dependency, not Mia's design, and `PROVENANCE.md` already rejects the ALTREX director/Codex wrapper.

**Verdict:** the portable part of Mia was small and is now routed — the prompt library and automations
shipped as `#/prompts`, and the read-only tools/research prompt remain deliberately unported. Unit 4's
design survey, unit 7's persona shape and unit 11's avatar work had all closed before the user's
deletion permission was exercised on **2026-11-26**: `Ai agents/` and `Source code/` are gone, as is the
root `Portable-Local-Studio-main/` path. Studio was not destroyed — its 34.1 GB (11,711 files) moved to
`Kira/.kira-data/studio`, which discovery checks first, with no copy. The scratch `.kira-lab` data dir
was removed as well, so the workspace is now just `Kira/`; a dev run can still point
`KIRA_STUDIO_DIR` at the same folder. One human action remains: rotate Mia's three provider keys,
which were exposed before the folder was removed and are still valid wherever they were copied.

## Ground rules that constrain every unit above

BYOK only, no free-tier catalogue or scraping · reimplement, never copy, log it in
`PROVENANCE.md` · never execute donor code or installers, read-only inspection · provider keys and
both engine secrets in the Windows Credential Locker only, never on disk or in logs · loopback-only
binding, enforced in config validation · no `git init` or git-config changes unasked (granted for
`Kira/`; identity passed per command).

Two things this roadmap changed on record: the "MYRAA 3D/MMD character engine — rejected" row in
`PROVENANCE.md` is re-opened by unit 11, and unit 12 exists because the compliant substitute for
Ultron's LAN dashboard was chosen over porting it.
