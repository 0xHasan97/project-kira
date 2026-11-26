# Kira

One local AI agent that routes chat to whichever provider you own a key for, and
tells you afterwards who actually answered. This tree carries the spine
(providers, router, API, contract, browser chat), the control dashboard (spend,
keys, tuning, monthly caps, history), the two shell modes, the tool harness with
policies and checkpoints, the real-time voice/video call, and local memory with
retrieval, remote pairing, local inference, and skills. The desktop shell wraps all
of it in a native window with a tray, and `packaging\build.ps1` turns it into one
`Kira.exe` folder.

```
kira-engine/     Python 3.12 FastAPI engine (the only thing that talks to providers)
  tools/         a scripted mock provider and the browser-pass lab — nothing real at stake
kira-chat/       TypeScript + React: the chat and the ten routes beside it, served at /chat/
kira-contracts/  hand-written TS types + check-drift.mjs, the cross-language gate
setup/           one-click installer, standalone source downloader, GitHub notes
docs/specs/      the design each sub-project implements
docs/plans/      the task-by-task build plan, including the decisions planning forced
docs/qa/         records of checks that only a real run can make
```

## One click

For a fresh copy, double-click **`setup\Kira-Setup.cmd`**. It checks for
Python 3.12+ and Node 20.19+/22.12+, installs a missing one with `winget` when
available, creates `kira-engine/.venv`, installs the engine and UI packages,
builds the UI, writes a desktop shortcut, and starts Kira. From GitHub, use
**Code -> Download ZIP** first; the whole source tree is one archive.
`setup/README.md` covers the flags and the standalone downloader.

After that first setup, **`run-kira.bat`** (or `python run_kira.py`) is the fast
start. It writes `.kira-data/config.yaml` if missing, rebuilds the UI if the
bundle on disk was built for a different API revision (`dist/kira-build.json`
is the stamp), starts the engine on loopback, and opens
`http://127.0.0.1:8901/chat/` as soon as `/healthz` answers, already connected.
Provider API keys are entered in the app's **Providers** screen, not at the
console. Ctrl+C in that window stops everything.

The first run prints two lines you need before that window closes:

```
[kira] connect-token for the browser (created now): <token>
[kira] confirm secret for dashboard writes (created now): <secret>
```

The token is what a manually opened tab's connect screen asks for; the launcher
passes it in the URL fragment, which the UI consumes before React mounts and
removes from history. The confirm secret is what a destructive dashboard
**write** asks for, again, once per write — see `Two secrets` below. Provider
management asks only for the token: storing or forgetting a key, turning a
provider on or off, tuning its tier/priority/cap, testing it and clearing a
cooldown are desktop-only writes, not destructive acts, and the token already
proves the request came from the desktop.
Both live in the Windows Credential Locker under service `kira` and neither is
ever written to disk; `kira-engine token` reprints the token on stdout and the
confirm secret on stderr. A `KIRA_VAULT=memory` run keeps them in the engine's
own process, so they appear on the engine's `first run` stderr lines instead.

Useful flags: `--port 8905`, `--rebuild` (force the UI build even when the stamp
matches), `--no-browser`. `KIRA_DATA_DIR` relocates the data
directory; `KIRA_VAULT=memory` keeps secrets in-process for tests (the token then
lives only in that run).

**Avatar Stage (Unit 11):** 10 donor archives (MYRAA, Brahma, PocketStrike, Ultron, TGSR, ALTREX, ZORION) imported with three live-pass load fixes:
- **render_head separation** in `mesh.py`: body certification (6 counts) split from full PMX certification (9 counts)
- **Loop detection** in `krm1.ts`: relaxed bone ordering, added cycle detection for renderable skeletons
- **Texture folder prefix** in `pmx.ts`: correct file routing for nested vs flat archives
The full chat and engine suites pass.

## Two secrets

| Secret | Locker ref | Grants | Where it is printed |
| --- | --- | --- | --- |
| bearer token | `engine/token` | reads: `/v1/models`, chat, every `GET /v1/kira/*` | the launcher, `kira-engine token` on **stdout**, the engine's first-run line on stderr |
| confirm secret | `engine/confirm` | nothing alone; it must travel **with** the bearer token in `X-Kira-Confirm` | the launcher, `kira-engine token` on **stderr**, the engine's first-run line |

Two because the browser necessarily holds the first one, so any script that ever
runs in that page has it. A destructive write therefore also needs a value the
page cannot read: you retype it into the dialog, it lives only while that one
request is in flight, and the engine refuses a write whose confirm value is
missing, wrong, or simply the bearer token again. Provider keys and the three
provider controls (`settings`, `cooldown`, `probe`) are the exception: they
demand the engine token itself (`owner`, see `Remote`), so the key table and
the controls ask for nothing extra.

- One dialog per destructive data write. Provider controls are not dialogs:
  they are owner-only. A Providers row edited across several fields is still one
  write, because separate writes could half-apply a change and route traffic you
  did not intend.
- A provider key or the confirm secret never enters `localStorage`, the URL, a
  response body, `engine.log`, or a module-level variable that outlives the
  dialog. The check is scoped to that claim, not to every web storage read:
  `grep -rn "localStorage" kira-chat/src/` returns only nine keys —
  `kira.base`, `kira.token` (the two above) and `kira.shell`, `kira.theme`,
  `kira.appearance`, `kira.look`, `kira.sidebar`, `kira.prompts`, `kira.public`
  (presentation, the prompt library and the Remote screen's public base URL, see
  "Two modes" below). They live in `App.tsx`, `shell.ts`, `theme.ts`,
  `appearance.ts`, `look.ts`, `screens/PromptsScreen.tsx`, `screens/RemoteScreen.tsx`,
  and the tests that seed them.
  The loopback bearer token is the one secret the page keeps, on purpose, and
  `docs/plans/` records that decision. If a tenth key appears, or either grep
  below matches, that is the finding.
  `grep -rniE 'localStorage\.(set|get)Item\("?(confirm|key)' kira-chat/src/` returns nothing.
  The current conversation id is not a secret and is not one of those keys: `useChat` keeps it in
  `sessionStorage["kira.session"]`, so a reload or a route change continues the same sitting while a
  closed tab forgets it. `grep -rn "localStorage" kira-chat/src/useChat.ts` returns nothing.
- Clearing **all** history asks for the same confirm secret as any other destructive write; there is
  no extra phrase to type and the browser still keeps no copy of the secret.
- **New chat**, in the chat-mode sidebar, drops the tab's pointer to the current session and lets the
  engine mint the next one. It never deletes anything: the earlier transcript stays in **Sessions**.
- Rotating either secret is `kira-engine keys rm engine/token` (or
  `engine/confirm`); the next read or write mints a replacement and prints it
  once. Provider keys are `keys rm provider/<name>`.

## Run it by hand

```bash
cd kira-engine
python -m venv .venv && .venv/Scripts/activate        # Windows
pip install -e ".[dev]"
```

Every verb below also takes `--data-dir PATH` and `--backend keyring|memory`,
before or after the verb.

| Verb | What it does |
| --- | --- |
| `kira-engine serve` | run the engine on loopback (`--port`, `--log-level`) |
| `kira-engine desktop` | the engine inside a native window instead of a browser tab — needs `pip install -e ".[desktop]"` and a built `kira-chat/dist`, both explained under "Desktop window" below |
| `kira-engine config` | print the resolved config as JSON; `--sample` writes a starter `config.yaml` |
| `kira-engine keys set provider/openrouter --from-env OPENROUTER_API_KEY` | store a key from the environment or `--from-stdin`, never from the command line, so it stays out of shell history |
| `kira-engine keys rm provider/openrouter` | forget one key, or one secret (`engine/token`, `engine/confirm`) |
| `kira-engine keys list` | every ref with `present: true/false` — presence only, never values |
| `kira-engine token` | bearer token on stdout, confirm secret on stderr |
| `kira-engine models` | `list_models` per provider, live. Free: no completion is requested, so no credit is spent |
| `kira-engine contracts` | regenerate `openapi.json` / `contract.json` / `VERSION` for the TS gate (`--out`) |
| `kira-engine voice doctor` | the same status `/v1/kira/voice` returns, plus the exact paths it searched and the two install lines; never downloads anything |
| `kira-engine settings list` | every stored override, with `orphan: true` on rows the merge refuses |
| `kira-engine settings clear groq monthly_cap --yes` | forget one override, or a provider's whole set (`settings clear groq --yes`) |
| `kira-engine characters import PATH` | copy one `.pmx`, or a `.zip` that carries one with its textures, into `<data>/characters/` — the file stays where it is and nothing is downloaded |
| `kira-engine characters list` | every imported character with the one on stage, read from the profiles so no 45 MB model is re-walked |
| `kira-engine characters show ID` | one profile whole: counts, textures resolved or missing, morph and frame names, and the licence text that came with the file |
| `kira-engine characters use ID` | put that character on stage (`characters use --off` takes everyone off) |
| `kira-engine characters remove ID --yes` | delete the imported copy, clearing the stage in the same call if it was the one on it |
| `kira-engine skills install PATH` | copy `<top>/skills/<name>/SKILL.md` from a `.zip` or a folder into `<data>/skills/` — text and licences only, never the pack's scripts (`--dry-run`, `--force`) |
| `kira-engine skills list` | every skill the engine would load from both roots, with each refused file and its reason |

`characters` is the same engine code the avatar screen calls, so a model the CLI refused is a model the
dashboard refuses too. Skins are licensed downloads the user already owns: they are copied from a path the
user names, never fetched, and `<data>/characters/` is git-ignored so one can't end up in a repo or a build.

`--backend memory` keeps secrets in the process instead of the Locker: tests and
the browser-pass lab only, because a memory vault is per-process and nothing
survives the exit. `settings clear` without `--yes` exits 2 without touching the
database — it deletes an override, and the merged value that then applies is not
shown back to you first.

What the dashboard deliberately does **not** cover, and why:

- **Adding or renaming a provider or a model is a `config.yaml` edit.** The UI
  never writes YAML; the Models screen says the same thing on screen.
- **An orphan override row can only be pruned from the CLI.** `validate_setting`
  refuses an unknown key on the write path, so
  `settings clear <provider> <key> --yes` is the only way to remove a junk row
  that got there by hand; `settings list` is how you find it.
- **The contract export stays a CLI step.** `kira-engine contracts` is a build
  tool for the drift gate, not something to click while tuning a provider.
- **Rotating a secret is a CLI step,** for the same reason a password change is:
  a browser that could print the confirm secret on demand would not need you to
  type it.

### Developing the UI separately

```bash
cd kira-chat
npm install
npm run dev          # http://127.0.0.1:5173/chat/, /v1 + /healthz proxied to :8901
```

The engine mounts `kira-chat/dist` at `/chat/`, so build before serving the UI
from the engine: `npm run build`.

### The browser-pass lab

```bash
cd kira-chat && npm run build          # once — the engine serves kira-chat/dist
cd ../kira-engine
.venv/Scripts/python.exe tools/kira_lab.py --data-dir /tmp/kira-lab
```

`tools/kira_lab.py` runs the real engine against `tools/mock_openai.py` — a
scripted provider with fixed 150-token answers — with a memory vault, so it
spends no credits, touches no Credential Locker entry and cannot reach your
history. That is the only way a dashboard pass can be run more than once.
`--data-dir` keeps the history for a second start; restart with `--models mini`
and the Models screen shows a `no longer configured` row for a model the
catalogue no longer offers. Omit `--data-dir` and the lab makes a temp directory
and removes it when you stop it with Ctrl+C — a process killed outright leaves
that directory behind, because the cleanup runs on the way out, not on a signal
it never sees. Both secrets are printed on stderr because both are disposable; a
second process mints new ones, so reconnect with the token it just printed. The
pass itself is recorded in `docs/qa/dashboard-browser-pass.md`.

Without `kira-chat/dist/index.html` the lab does not try to serve a blank page:
it exits with code 2 and tells you to run the build.

### Desktop window

```bash
cd kira-engine
pip install -e ".[desktop]"     # pywebview + pystray + pillow; nothing else needs it
.venv/Scripts/kira-engine.exe desktop
```

`setup\Kira-Setup.cmd` installs these extras, so a one-click install can use
`run-kira.bat --window` without another pip command. The manual command above is
only for a bare checkout.

`kira-engine desktop` runs the same loopback engine on the same port, but inside a
native window (WebView2 via pywebview) instead of a tab. It refuses with exit code 2
when `kira-chat/dist/index.html` is missing — a window on a 404 is a blank pane with
no console to explain it.

The window starts hidden, injects the bearer token into its own `localStorage`
(`private_mode`, so it is memory-only and never on disk), navigates to `/chat/`, and
only shows itself once that page has loaded — the connect gate never flashes. The
confirm secret is **not** injected: destructive writes still re-ask for it in the
dialog, exactly as in a browser. Closing the window hides it to the tray (Show Kira / Open in browser
/ Quit); Quit stops the engine too. A second launch of the same data directory brings
the running window forward instead of starting a second engine. Window geometry lives
in `<data>/desktop.json` and only geometry — the file is rewritten from a fixed set of
integer fields, so a token pasted into it by hand cannot survive a save.
`run-kira.bat --window` is the same thing with the venv already set up; without the flag
the launcher behaves exactly as before.

#### The packaged app (`Kira.exe`)

```powershell
cd kira-engine
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
.\packaging\dist\Kira\Kira.exe desktop
```

`build.ps1` builds `kira-chat/dist` with npm, then PyInstaller (`pip install -e ".[build]"`,
one time) packs the engine, that bundle and the window stack into
`kira-engine/packaging/dist/Kira/` — one folder, ~55 MB, `console=False` so no console window
opens behind it. `-SkipClient` reuses an existing bundle. The frozen app writes its data to
`%LOCALAPPDATA%\Kira` unless `KIRA_DATA_DIR` or `--data-dir` says otherwise, because an
installed copy usually sits in Program Files, where nothing may write; from a source checkout
the default stays `<repo>/.kira-data`.

Not in it, deliberately: no installer (MSI/NSIS), no code signing, no auto-update, no
start-with-Windows. The folder can be copied anywhere and started; SmartScreen will warn once
on an unsigned exe.

## How routing decides

Modes are `AUTO`, `FAST`, `POWERFUL`, `CUSTOM` — tier filters over your own
providers, never a hidden catalogue. Per request the router:

1. filters by mode and by `enabled` — a disabled provider is not a candidate —
   then puts those offering the requested model at the front of the queue (in `AUTO`:
   everywhere else a model the lane does not carry is refused outright), then drops
   those whose key is missing,
2. drops providers already at or over their `monthly_cap` for the current UTC
   month,
3. drops providers still in cooldown,
4. tries what remains in `priority` order.

Budget is checked before health, so a provider that is both over cap and cooling
is reported over cap. Spend is read from stored rows at plan time, which means
the turn in flight is not counted — at most one turn of slack, never a running
total the UI promises to respect. If every remaining candidate is over cap the
turn is refused with `budget_exhausted` (429, not retried, no provider billed);
if the list emptied *before* the budget check, because nobody had a key, you get
`providers_exhausted` instead. Those are different facts and the honest answer is
different for each. That refusal names the model it was asked for and carries each dropped provider's
own reason (`mode AUTO: nothing left to ask model 'x' - groq: vault ref 'provider/groq' empty`), because
"every provider was filtered out" tells a reader nothing they can act on.

Failover rules, in the order they matter:

- **429 / 5xx** → provider is retryable: mark it in the ledger with backoff, try the next.
- **401 / 403** → the provider is rejecting the *credentials*, not the body, so it is treated like an
  ill provider: cool this one down and hand the turn on. Measured with a deliberately bad key against
  every provider kind the product ships: Groq answers `401 invalid_api_key`, Anthropic answers
  `401 authentication_error`, OpenRouter answers `401 User not found`. The abort rule exists for our own
  mapping bugs, and an expired key is not one; without the carve-out a single dead credential ends the
  chat while another working provider waits its turn.
- **Other 4xx** → not retryable: abort. A bad request is our mapping bug; failing over
  would bury it under another provider's answer. That rule has a known cost, measured live: Google
  reports a bad `AIza…` key as `400` carrying `API_KEY_INVALID`, and OpenRouter reports a one-character
  placeholder as an empty `400`. Kira does not read provider bodies for credential signals, because an
  empty `400` and a malformed-request `400` are indistinguishable; the dashboard probe names the failing
  provider instead. See `docs/qa/live-providers.md`.
- **Died mid-stream after you saw text** → terminal `aborted_mid_stream`. The
  partial is persisted as `interrupted` rather than silently re-asked.
- **Opened, ran, and said nothing** → `empty_answer`, and the next provider gets the turn. A
  reasoning model whose whole output budget goes to hidden thinking completes with zero characters
  and `finish_reason=length`; measured live on Gemini 3.5 Flash, the same prompt at 64 tokens
  answered a word on one call and nothing at all on another. Silence is not an answer, so it is not
  served as one.

Every turn carries its provenance: `attempt`, `served`, `failed`,
`skipped_cooling`, `skipped_missing_key`, `skipped_config`, `skipped_budget`,
`aborted_mid_stream`, `empty_answer`, `tool_executed`, `tool_approval_requested`, `tool_denied`,
`checkpoint_created`, `usage_estimated`, and on a call `images_attached` or
`images_dropped` — the record that says whether a webcam frame left the device. The UI
renders it as chips and a one-line summary, so "which model answered me" is never a guess.

## A model on this machine

A local llama.cpp server is just another stanza — the one thing it does not have is a key:

```yaml
  - name: llama_cpp
    kind: openai_compat
    base_url: http://127.0.0.1:8080/v1
    tier: fast
    priority: 140
    models:
      # Whatever alias llama-server answers with; -a/--alias sets it at startup.
      - local-model
```

Start it yourself, pointing at any single-file GGUF:

```bash
llama-server -m models/qwen2.5-7b-instruct-q4_k_m.gguf --port 8080 --alias local-model
```

Kira does not bundle a model, and it never fetches one on its own. It can, however, start and stop
`llama-server` for you on the Studio screen (`#/studio`) when a GGUF and the executable are already on
this machine; a stanza you wrote by hand keeps working exactly the same way. The same stanza shape works
for LM Studio, vLLM or any other OpenAI-compatible server — only the loopback port and the model id
change.

Priorities are tried in ascending order, and this one sits after every shipped remote
(50–120), so `AUTO` keeps preferring a remote answer and reaches this machine only when
nothing remote can serve — including when the network is down. Naming the model
(`model: local-model`) puts it at the front of the queue in `AUTO` — where every other provider stays
behind it as failover — and is a hard filter in `FAST`, `POWERFUL` and `CUSTOM`, which
is what the model picker does. A keyless provider is never "broken": the Providers screen reads `no key needed`,
its key buttons are disabled, and routing never skips it for a missing key. `kira-engine models`
proves the stanza before you send a turn.

## Studio: the Portable AI Studio runtimes

`#/studio` is the one screen that looks at another folder. Portable AI Studio ships stable-diffusion.cpp, llama.cpp, whisper.cpp and a Kokoro runtime in one tree; Kira reuses those
binaries and checkpoints in place, without copying tens of gigabytes and without making the folder a
requirement.

- **Discovery.** A folder is a studio when it has `scripts/server/serve.cjs` and an `app/` directory.
  Kira looks at `KIRA_STUDIO_DIR`, then `<data>/studio`, then `Portable-Local-Studio-main` /
  `Portable-AI-Studio` beside the data folder and its parents. Nothing is ever written into it.
- **Images.** `#/images` prefers the studio's `sd-cli` (the build that writes `-o`) and lists every
  checkpoint under `app/models`. A server-only `sd-<backend>` build is not silently driven with CLI flags.
- **Local chat.** `#/studio` lists the GGUFs under `app/llm-models`; *start local model* spawns
  `llama-server` on loopback and appends a keyless provider named `local_llama`. *stop* terminates the
  child and removes the provider. Layers stay on the CPU unless `KIRA_LLAMA_NGL` says how many the GPU
  can hold — guessing `99` on a small card is a long load followed by an allocation failure.
- **Speech.** `voice.stt_engine: auto` prefers the studio's `whisper-cli` when a `ggml-*.bin` model is
  present, otherwise `faster-whisper`. `voice.tts_engine: auto` prefers Kokoro through the studio's Node
  worker, otherwise Piper. Forcing `whisper_cpp` / `kokoro` / `faster_whisper` / `piper` is a hard filter,
  never a fallback. Kokoro's first run downloads its ONNX model into the studio's `tts-cache`, so it is
  the one path here that needs a network the first time.
- **Downloading a model.** `#/studio` accepts a Hugging Face file URL and writes it into the folder the
  chosen loader scans. The scheme, host, extension and `KIRA_DOWNLOAD_MAX_BYTES` ceiling are checked
  before a socket opens; a partial file is removed rather than left as a model. A loopback mirror is
  allowed for an offline machine.
- **The studio's own server.** Portable AI Studio's Node server also owns transcription history, Kokoro
  outputs, the four model folders and the hardware report. Instead of reimplementing them, Kira can
  start that server on loopback itself (`node scripts/server/serve.cjs`, port 1420 or
  `KIRA_STUDIO_PORT`), keeps the child in its own process group and kills it with the engine. While it
  answers, `#/studio` forwards only `/api/`, `/tts-outputs/`, `/transcriptions/` and `/outputs/`
  calls through the authenticated proxy below — the bearer token never reaches the studio, and a
  `delete`/`stop` path needs the confirm secret. A studio started by `windows.bat` is detected and
  left running; `KIRA_STUDIO_URL` points Kira at one it does not manage. Chat stays Kira's own: the
  Kira UI never calls the studio's chat route, because `/v1/kira/chat/completions` owns conversation,
  memory and tools.

## Images on this machine

`#/images` is a local Stable Diffusion workspace modelled on Portable AI Studio's text-to-image screen.
It calls [stable-diffusion.cpp](https://github.com/leejet/stable-diffusion.cpp), not a cloud API, and it
downloads nothing — a missing engine or checkpoint is a sentence on the screen, never a hidden install.

- **Engine.** Put `sd.exe` / `sd` or `sd-cli` (Windows `sd-cli.exe`) in `<data>/images/engines`, or set
  `KIRA_SD_BACKEND` to its absolute path. The CLI build is the one that takes `-o`; a server-only
  `sd-vulkan.exe` is not driven with CLI flags. A Portable AI Studio `app/backend/<platform>` is used
  automatically when one is found.
- **Server instead of an executable.** Set `KIRA_SD_URL=http://127.0.0.1:8080` to use a
  stable-diffusion.cpp server you already run; Kira then posts to its `/sdapi/v1/txt2img`.
- **Models.** Single-file `.safetensors`, `.ckpt` or `.gguf` checkpoints in `<data>/images/models`,
  or `KIRA_SD_MODEL` for one checkpoint elsewhere. Multi-file diffusion GGUF sets are not loaded.
- **Output.** Every generation writes a PNG and a JSON sidecar with the prompt, seed, size, steps, CFG,
  sampler, model and duration into `<data>/images/outputs`. `#/images` lists them, shows the settings,
  and deletes only through the confirm secret. The agent gets the same workspace as the
  `image_generate` tool, which is approval-gated like every other write.
- **Bounds.** Prompt ≤ 4 000 characters, width/height 64–2 048 in multiples of 8, steps 1–150, CFG 0–30,
  sampler a stable-diffusion.cpp method name (`euler_a`, `dpm++2m`, …). A seed of `-1` picks one, and
  the answer carries the value that was used.

## HTTP surface

| Endpoint | Auth | Purpose |
| --- | --- | --- |
| `GET /healthz` | none | liveness + `api_version` + `contract_version`, so a client can check compatibility before sending a token |
| `GET /v1/openapi.json` | none | machine-readable contract (`GET /openapi.json` is the same document, not a second opinion) |
| `GET /v1/models` | bearer | catalogue built from *your* config, merged settings included; each row carries `key_present` and `needs_key`, so the picker can stamp the rows that cannot answer and never call a keyless provider broken; `?live=true` adds a free `list_models` probe per provider |
| `POST /v1/chat/completions` | bearer | `stream: true` → SSE `delta` / `chain` / `tool_call` / `done` / `error`; `false` → OpenAI-shaped JSON |
| `GET /v1/kira/health` | bearer | per-provider ledger, with the effective tier and priority the router is using |
| `GET /v1/kira/voice` | bearer | the real-time-call stack: listen / speak / see, each with its mode, whether it can run here, and why not |
| `GET /v1/kira/overview` | bearer | one UTC month: turns, tokens, success rate, per-provider and per-model usage, daily series, budget rows, recent trouble, and `refusals` — the turns the plan rejected before a session existed, with `count`, `by_code` and the latest reasons |
| `GET /v1/kira/providers` | bearer | one row per provider: baseline-vs-effective settings, key presence, spend, ledger, plus `orphan_settings` |
| `GET /v1/kira/sessions` | bearer | session list with message and token counts (`?limit=`, default 50) |
| `GET /v1/kira/sessions/{id}/messages` | bearer | stored history with chain and usage |
| `PUT /v1/kira/providers/{name}/settings` | bearer (owner) | write one or more of the four tunable fields; an explicit `null` clears that override |
| `PUT /v1/kira/providers/{name}/key` | bearer (owner) | store a provider key |
| `DELETE /v1/kira/providers/{name}/key` | bearer (owner) | forget it |
| `DELETE /v1/kira/providers/{name}/cooldown` | bearer (owner) | stand a provider back up now |
| `POST /v1/kira/providers/{name}/probe` | bearer (owner) | live test: `list_models` **plus one 8-token completion** — the only click that spends |
| `GET /v1/kira/approvals` | bearer | tool calls waiting on an allow/deny decision |
| `POST /v1/kira/approvals/{id}` | bearer + confirm | allow or deny one pending tool call |
| `GET /v1/kira/checkpoints` | bearer | recent pre-write snapshots (`?limit=`, `?session_id=`) |
| `GET /v1/kira/checkpoints/{id}` | bearer | one checkpoint with a per-file unified diff |
| `POST /v1/kira/checkpoints/{id}/restore` | bearer + confirm | put the files back; a moved file is 409 until `force: true` |
| `GET /v1/kira/tools` | bearer | every callable tool with its risk, source and effective policy, plus plugin load status |
| `GET /v1/kira/skills` | bearer | every loaded skill with its kind and source, every file's status (a bad file is reported, never fatal), and how a model reaches a method: `none`, `inline` or `search` |
| `PUT /v1/kira/tools/{name}` | bearer + confirm | set one tool to `allow` / `ask` / `deny`; `null` clears the override |
| `GET /v1/kira/memory` | bearer | saved facts with their kind, origin, pin and use count, plus the three switches and the tokenizer in use |
| `POST /v1/kira/memory` | bearer + confirm | keep one fact (`text` ≤ 2 000 chars, `kind` one of `fact` / `preference` / `note`) |
| `PATCH /v1/kira/memory/{id}` | bearer + confirm | edit text, kind or pin; an unknown id is 404 |
| `DELETE /v1/kira/memory/{id}` | bearer + confirm | forget one fact — the index row goes with it |
| `GET /v1/kira/memory/search` | bearer | ranked snippets over conversation text (`?q=`, `?limit=`); tool output is never indexed |
| `GET /v1/kira/memory/export` | bearer | every fact as JSON, for a backup you own |
| `GET /v1/kira/memory/settings` | bearer | `inject`, `capture`, `extract`, and which FTS tokenizer this build gave you |
| `PUT /v1/kira/memory/settings` | bearer + confirm | set any subset; `capture: "off"` also removes the `remember` tool |
| `DELETE /v1/kira/sessions/{id}` | bearer + confirm | delete one session and its messages |
| `DELETE /v1/kira/sessions` | bearer + confirm | delete every session |
| `POST /v1/kira/pairing-code` | bearer + confirm | mint a single-use code, good for 120 seconds and shown only on the desktop |
| `POST /v1/kira/pair` | none | exchange a pairing code for a device token (`kd_…`), returned once and stored engine-side as a hash |
| `GET /v1/kira/devices` | bearer | the live devices a code paired, with when each was last seen — never their tokens |
| `DELETE /v1/kira/devices/{id}` | bearer + confirm | revoke a device; its token stops authenticating on the next request |
| `GET /v1/kira/characters` | bearer | the imported library with each body's counts, plus `active` — who is on stage, or `null`; a pick that points at a folder that is gone reads `null` |
| `POST /v1/kira/characters` | bearer (owner) | import `{path}` — a `.pmx` or `.zip` already on this machine, no confirm to type; `201` with the row, `409 already_imported` for bytes already here, `413 too_large` for a zip bomb, `400` for anything that is not a model |
| `PUT /v1/kira/characters/active` | bearer (owner) | `{id}` puts a character on stage, `{"id": null}` takes everyone off; an id that is not in the library is `404` and the old pick survives |
| `GET /v1/kira/characters/{id}` | bearer | one character whole: the body's capability report, the models that came in the same archive, and every file in its folder |
| `DELETE /v1/kira/characters/{id}` | bearer + confirm | delete a character: its folder and its stage pick both go |
| `GET /v1/kira/characters/{id}/file` | bearer | one file from that folder (`?path=`, relative to the folder): `model.pmx`, `tex/颜.png`, `profile.json` — with the media type its extension says. An escaping, absolute, empty, NUL-bearing or symlink-out path is `400 unsafe_entry`, and an extension the stage does not load is `400` before the disk is touched |
| `GET /v1/kira/characters/{id}/mesh` | bearer | the body as one flat `KRM1` blob the stage draws — positions, normals, uvs, four-slot skin, faces, texture paths, materials, bones and vertex morphs, packed by the same walk that wrote the report above. A model that walk cannot certify is `400 pmx_truncated` rather than half-drawn; a prop-only character is `404 character_file_not_found` |
| `GET /v1/kira/images` | bearer | the local image workspace: whether an engine and a checkpoint are present, the reason when they are not, the checkpoint folder's contents, and the PNG gallery with each sidecar's settings |
| `POST /v1/kira/images/generate` | bearer + confirm | draw one PNG with stable-diffusion.cpp; `400 image_request_invalid` for an empty prompt or a size that is not a multiple of 8, `503 image_backend_missing` when no engine or model is installed, `502 image_generation_failed` when the engine runs and fails; the PNG and its settings sidecar land in the images folder together |
| `GET /v1/kira/images/file/{name}` | bearer | the bytes of one generated PNG, with the token in the header — never a query string; a name this workspace did not write is `404 image_not_found` |
| `DELETE /v1/kira/images/{name}` | bearer + confirm | forget one generated image and its sidecar |
| `GET /v1/kira/studio` | bearer | the Portable AI Studio components Kira can see — image engine and checkpoints, llama.cpp and GGUFs, whisper.cpp and its models, the Kokoro runtime — plus whether a local chat server is running and on which port. With no studio folder it reports Kira's own folders instead |
| `POST /v1/kira/studio/llm/start` | bearer + confirm | start `llama-server` on one GGUF and append it as the keyless `local_llama` provider; `{model}` picks a name from the list, absent picks the first; `503 llm_unavailable` when there is no engine or model, `502 llm_start_failed` when the child never answers |
| `POST /v1/kira/studio/llm/stop` | bearer + confirm | stop the child process and remove the provider again; a second click is a no-op |
| `POST /v1/kira/studio/download` | bearer + confirm | download one model file from `huggingface.co` (or a loopback mirror) into the folder its loader reads: `llm` → `llm/models`, `image` → `images/models`, `stt` → `voice/models`; the host allowlist, extension and `KIRA_DOWNLOAD_MAX_BYTES` ceiling are checked before a socket opens |
| `GET /v1/kira/studio/app` | bearer | the studio's Node server: whether it answers, whether Kira spawned it, its loopback URL and pid, and its `/api/health` build and issues; `503 studio_unavailable` is not used here, a stopped or missing studio is a `running: false` answer |
| `POST /v1/kira/studio/app/start` | bearer + confirm | spawn `node scripts/server/serve.cjs` in the studio folder on loopback and wait for its health probe; `400 studio_refused` when no studio folder exists or `KIRA_STUDIO_URL` already points somewhere dark, `503 studio_unavailable` when the child never answers |
| `POST /v1/kira/studio/app/stop` | bearer + confirm | stop the child process tree Kira started (Windows `taskkill /T`); a studio Kira did not spawn is left running and the answer says so |
| `GET /v1/kira/studio/proxy` | bearer | forward one studio API `GET` to `?path=/api/...`; only `/api/`, `/tts-outputs/`, `/transcriptions/` and `/outputs/` prefixes are allowed and `..` is refused; the caller's bearer token is not forwarded |
| `POST /v1/kira/studio/proxy` | bearer + confirm for delete/stop paths | forward one studio API `POST` with its body and content type (JSON, or a raw WAV for `/api/speech/transcribe`); the studio's status and bytes come back unchanged |
| `GET /chat/` | none for the shell | the bundled UI; it asks for the token |

Two version numbers, two jobs: `API_PREFIX` (`/v1`) is the URL namespace,
`CONTRACT_VERSION` (`2`) is the revision of the fields inside it. A request for
a `/vN` this engine does not serve gets `404 unsupported_version` naming both
prefixes — before any token is compared, and never retried. The namespace bumps
only when a documented path is removed, renamed, or changes meaning; the revision
bumps when a field set or an enum meaning changes; adding a field or enum value
bumps neither. `/healthz` sits outside the namespace because it is how a caller
learns what the engine speaks, and every response under `/v1` carries
`X-Kira-Contract-Version`.

FastAPI's generated `/openapi.json`, `/docs` and `/redoc` are switched off: the
contract document is hand-authored and describes endpoints the engine registers
as they land, while Swagger/Redoc load their JavaScript from a CDN — something a
loopback-only, offline-first engine can't promise. `/v1/openapi.json` (and its
`/openapi.json` alias) serve the contract itself, on loopback only.

The engine binds `127.0.0.1` only. The bearer token is compared with
`secrets.compare_digest`. History lives in SQLite (WAL) under `.kira-data/`.

### Tools and permissions

The model can call `list_dir`, `read_file`, `search_text`, `write_file` and
`run_command`, plus whatever declarative plugins load. Every path is resolved
inside one workspace — `data_dir/workspace` (`.kira-data/workspace` by default) —
and a path that escapes it, through `..` or a symlink, is refused before the tool
runs. Limits: 128 KB read, 256 KB write, 8 KB of command output.

Each tool has a risk (`read`, `write`, `exec`, `network`) and one of three
policies. The defaults are **read → allow**, **write / exec / network → ask**;
`allow` and `deny` are explicit, and a per-tool override from the Tools screen
wins over both. `ask` holds the turn open: the client receives an `approval`
chunk with the tool and its arguments, and the pending call only proceeds after
`POST /v1/kira/approvals/{id}` with the confirm secret. A denial is fed back to
the model as a tool result, so it explains the limitation instead of retrying.

`run_command` takes an argv list, never a string: there is no shell, no `&&`,
no redirection, and no command substitution. It defaults to a 30 s timeout
(120 s ceiling) and **is not checkpointed** — a command that changes files is
outside the undo story, which is why its policy is `ask`.

`write_file` checkpoints the files it is about to touch before writing, and the
checkpoint id lands in the turn's chain. (A plugin declares no local paths, so a
plugin is never checkpointed — which is why `network` defaults to `ask`.) Restore is confirm-gated and writes the snapshot back; if a file
moved since the checkpoint, the restore answers 409 and names it rather than
overwriting an edit the model never saw. History is pruned to the most recent
checkpoints, and a restore marks its snapshot so it cannot be undone twice.

Plugins are JSON files in `data_dir/plugins/` (`.kira-data/plugins/*.json`).
They describe one HTTP request (method, URL, timeout) mapped from the tool's
parameters; they carry **no code**, load at engine start (a new file needs a
restart), and name their secret through `secret_ref`, which is read from the
Windows Credential Locker at call time. A malformed file is skipped with the
reason kept so the Tools screen can show it.

A replayed tool call is not always the call the model made. Google's thinking
models sign each `functionCall` part with an opaque `thoughtSignature` and
answer a replay that drops it with `400 Function call is missing a
thought_signature` — measured live on `gemini-3.5-flash`, where the first
round-trip worked and the follow-up died. `ToolCall` therefore carries an
optional `signature` that the provider that minted it puts back on the wire. It
is provider plumbing only: it never reaches the HTTP contract, the UI, the
history or a checkpoint, so `API_VERSION` and `CONTRACT_VERSION` do not move
with it. `docs/qa/live-app-pass.md` records the turn that proved it.

## Skills

A skill is a Markdown file with YAML frontmatter — `name`, `description`, `kind`, then
the body. There are two kinds, and the kind is the whole distinction:

- **persona** — chosen by you. The screen's `use` button pins it, the tab remembers the
  choice in `sessionStorage`, and every turn sent from there carries `skill: <name>`.
  The body becomes the **first system message** of that turn. The memory block is
  appended after it, so the persona sets the voice and memory supplies the facts.
- **method** — chosen by the model. A method is never pinned; it is offered through one
  built-in `use_skill` tool, and the body only enters the prompt once the model asks for
  it. That keeps a procedure out of the tokens until it is needed. `use_skill` exists
  only when at least one method loaded, and it is `allow`/`read` — it reads its own
  file, nothing else. With **24 or fewer** methods the tool's enum is exactly that list,
  names and one-line descriptions in the schema. Past 24 the enum is dropped — an
  imported pack of 300 would otherwise put 300 names in front of the model on *every*
  turn — and a second `read`/`allow` tool, `search_skills`, becomes the way to find one.
  `use_skill` then takes any name and says so when it is not installed.

Two roots, in that order of precedence: the builtin pack at `kira-engine/skills/`
(`concise`, `reviewer`, `debug`, `research`, `rea` ship with the engine) and `data_dir/skills`
for yours. Both accept `name.md` and the folder form `name/SKILL.md` that published
packs use, with the folder's extra files (`references/`, `scripts/`) left on disk and
unread. A user skill **shadows** a builtin of the same name rather than colliding with
it; a duplicate inside one root keeps the first and reports the rest as skipped. A bad
file — wrong frontmatter, a name that is not `^[a-z][a-z0-9_-]{2,39}$`, an unknown
kind, an empty body, over 16 KB — is listed with its reason on `GET /v1/kira/skills` and
on `#/skills`, and **never** stops the engine.

`kira-engine skills install PATH` fills `data_dir/skills` from a `.zip` or a folder — a
pack someone else wrote, in the shape above. It reads only `<top>/skills/<name>/SKILL.md`
and the `LICENSE` files, so the same skill shipped for three harnesses lands once, and no
`.py`/`.js`/`.sh` from the archive is copied or run. A donor file with no `kind` gets
`kind: method` (a procedure the model pulls, not a voice you pin); one that already
declares a kind is left alone. Anything over the 16 KB cap is named and refused before it
is decompressed, a folder whose name is not a Kira name is skipped, and the licence that
came with the pack is copied next to the skills it covers. `--dry-run` reports and writes
nothing; a re-run says `unchanged` rather than duplicating, and `--force` replaces files
only when you ask for it. `kira-engine skills list` prints what the engine would load from
that directory, plus the builtin pack and every refusal — the same `load_skills` a turn
uses, so the CLI and the next turn cannot disagree.

`ChatRequest.skill` names a persona. A name that is not loaded is a `400 config_error`;
naming a **method** there is also a `400`, and the message says the model loads it with
`use_skill` — so a client cannot silently pin a procedure and call it progressive
disclosure. A turn without `skill` assembles exactly as it did before this existed.

A skill carries no code and no secret: it is text, and the only thing it can change is
what the model is told.

## Remote

**The engine never listens off loopback.** There is no LAN bind, no `0.0.0.0`, no flag that
adds one — a second listener in Kira's own process would be a second, weaker door to
`data_dir`, the workspace and the tool harness. A phone reaches the desktop through a
transport *you* run: Tailscale Serve, `cloudflared`, an SSH tunnel — anything that forwards
to `127.0.0.1:8901`. That tunnel is the network boundary, and running it is your decision.

Kira adds the part the tunnel does not: **a device must be paired, and its token is not the
engine token.** Two principals, and what each one can reach is the whole difference:

- **owner** — the engine token from first run. Everything.
- **device** — a token minted by pairing. Reads and chat turns.

There is no source-IP check, because behind a tunnel every request arrives from `127.0.0.1`
and an address test would be a lie. The boundary is the confirm secret instead: every
destructive mutation needs `X-Kira-Confirm`, a second Locker value that never leaves the
desktop, so provider settings, cooldowns, probes, history deletion, approvals, tool
policies, memory writes, checkpoint restore, pairing codes and revocation are closed to a
device **by construction**, not by a list someone has to maintain. Provider keys take the
other door — they demand the engine token itself (`owner`), which a device's `kd_` token
is not, so the key table can skip the dialog without ever opening the desktop's
credentials to a phone. `GET /v1/kira/devices`
and minting a code are owner-only too, because they are about the security surface itself.
A paired phone can start a turn, and that turn can use `allow` tools exactly as it can from
the desk; it cannot approve an `ask` tool or change a policy — those still happen at the
desk, which is the point.

**Pairing.** On the desktop, `#/remote` mints a code behind the confirm dialog: 8 characters
of Crockford-ish base32, **120 s**, single use, held in engine memory only, so a restart
invalidates it. The screen composes a link — the tunnel base you paste (default: the current
origin) plus `/chat/#/pair?code=…` — with a copy button. The phone opens it; `#/pair`
renders **before** the token gate, because it is the one page a device with no token may
reach. It asks for a name, posts `{code, name}` to `POST /v1/kira/pair` (no bearer) and
keeps the returned token in its own `localStorage`, with no base stored, so every request
resolves against the tunnel origin that served the page. The device table shows name, when
it paired and when it was last seen; revoke is confirm-gated.

Exchange is limited to **10 attempts per minute** per engine process, so a code cannot be
ground down even though 40 bits is a lot to guess. A per-code attempt counter would be the
wrong defence — guessing wrong codes never names the real one, so the only attempts that can
be attributed are the ones that already succeeded. The window bounds an attacker; the TTL
bounds the code. A refused code is a `400 pairing_refused` whose message does not say which
of expired, used or wrong it was.

A device token is `kd_` + 43 characters of `secrets.token_urlsafe(32)`, and only its
**SHA-256** is stored — a copy of the database is not a key to the engine. A revoked row
stays in the table, because "this device was paired and then revoked" is history, and the
token can never authenticate again.

**HTTPS, and the phone's microphone.** `getUserMedia` needs a secure context. A tunnel that
terminates TLS (Tailscale Serve, Cloudflare Tunnel) gives the phone HTTPS and `#/call`
works; a bare `http://192.168.1.20:8901` does not, and Kira will not serve that. `#/remote`
says so in one line rather than letting a user discover it when the microphone silently
refuses.

Not in this unit: no QR code, no LAN listener, no bundled tunnel, no per-device scopes, and
no CLI verb — minting a code is a desktop action while the desktop is open.

## Memory

Kira keeps two kinds of memory, both local, and `#/memory` is the screen that shows
both: a **facts** tab (search, keep, pin, edit, forget, and the three switches below)
and a **history** tab over `GET /v1/kira/memory/search`. `export` downloads the whole
store as `kira-memory-<date>.json` with `version: 1` and exactly the rows on screen.
Every write re-reads from the engine, so a row the engine refused never appears here.

**Facts** are rows you (or the model, via `remember`) chose to keep. They are injected into every
turn as a bounded block — pinned first, then BM25 matches for your last message, then recently used,
12 items or 1 500 characters at most. The block is **never** stored as a message: the Sessions screen
shows only what was said. `remember` is `allow` by default (one click on the Tools screen restores the
prompt); `capture: off` removes it from the model's tool list entirely.

**History** is the conversation already in SQLite, indexed in FTS5 and searchable over
`GET /v1/kira/memory/search`. Only `user` and `assistant` text is indexed — never tool
output, never an image.

The index tokenizer is chosen by probing the installed SQLite: `trigram` on 3.34+, which is the only
one of the two that can match CJK (a `unicode61` build treats a whole CJK run as one token and returns
nothing for `向量数据库`). `GET /v1/kira/memory/settings` says which one is live. Either way a query
that MATCH cannot see falls through to a `LIKE` tier, so a search is slow before it is ever empty.

Extraction (`extract`, default off) is one capped 200-token call after a completed chat turn, labelled
`origin: auto` with the tokens it spent, deduped, and added to the month's ledger. It never fails a turn.

## The dashboard

`http://127.0.0.1:8901/chat/` is one bundle with a hash route and a screen for every section.
The route survives a refresh, so a refusal can deep-link you to the screen that
fixes it:

| Route | Screen |
| --- | --- |
| `#/chat` | chat: composer, mode and model selects, the streaming turn, chain chips, usage line, recent sessions. The model select opens on `Auto · the router picks`, which sends no model at all; naming a row makes it the preference in `AUTO` and a pin in the other lanes, and the rows without a key say so |
| `#/call` | the live voice and video call: self-view, level meter, mute/camera/look, the spoken transcript, and what the local stack can actually do |
| `#/overview` | one month: turns, tokens, success rate, spend against cap per provider, a daily series, top models, recent trouble, and the refusals no turn row could record — shown even in a month that spent nothing |
| `#/providers` | `enabled`, `tier`, `priority`, `monthly_cap`, key, ledger and cooldown, and Test |
| `#/models` | every configured model with its provider, tier and month usage; "use in chat" hops to the composer |
| `#/prompts` | twelve starting instructions with a category filter and search; `{name}` placeholders ask for their value before use, and a custom prompt is saved in this browser only — using one fills the composer and hops to chat |
| `#/tools` | every tool with its risk, source, effective policy and override; plugin load status; recent checkpoints with restore |
| `#/skills` | every loaded persona and method with its kind and source, a search box and a kind filter (a 270-skill pack is not one list), how the model reaches a method this turn, every file that refused to load and why, and "use" for a persona — which pins it and hops to the composer |
| `#/memory` | facts over `GET /v1/kira/memory` with search, keep, pin, edit and forget; history search with bracketed `[hits]`; the `inject` / `capture` / `extract` switches and `export` |
| `#/remote` | the tunnel address, a pairing code minted behind the confirm dialog with the link a phone opens, and every paired device with when it was last seen and a revoke |
| `#/pair` | reached from that link, **before** the token gate: the code from the URL, a device name, and the token this browser keeps afterwards |
| `#/sessions` | session table with an id/mode filter, transcript with the same chain chips and a Markdown export, delete one, delete all |

**Ctrl/Cmd+K is the index for all of it.** The palette searches every rail label and four actions —
new chat, cycle appearance, open settings, refresh — with the arrow keys and Enter, so a route does
not require finding its group first. The chat header carries the same button; on a phone the
shortcut still works with a hardware keyboard. **A conversation leaves as Markdown.** The chat
header downloads the turns on screen once there is one, and a Sessions transcript downloads the
stored history; both include the provider and model that answered, because that is the part a
screenshot loses.

**The heavy screens arrive only when asked for.** Chat, the provider tables and session history are
in the first bundle; the 3D stage, the call and Studio are route chunks. That is 359 KB of
JavaScript raw (108 KB gzip) to open chat instead of 962 KB, with the 566 KB stage fetched only for a route that
draws it — and a pointer resting on its rail button starts the fetch before the click. Files under
`/chat/assets` are content-hashed and served `immutable` for a year; `index.html`, `sw.js` and the
manifest revalidate, so a rebuild cannot pin an old shell. The worker caches a route chunk after its
first online visit, which is what lets `#/avatar` or `#/studio` open again when the engine is gone.

Three rules hold every screen together:

- **Usage is derived; spend is a ledger.** Turn counts, tokens and the daily
  series come from the `messages` table over one half-open UTC month window, so
  history and Overview always agree. The monthly cap reads a separate
  `usage_ledger` row per `(month, provider)`, charged as each assistant row is
  written — so deleting a session removes the transcript but **not** the money,
  and a cap cannot be re-armed by clearing history. A budget row's `remaining`
  is the engine's own clamp: `0` means at or over cap, and the UI never does that
  subtraction a second time.
- **One merged view.** Overrides live in a SQLite `settings` table layered over
  `config.yaml`, which the dashboard never writes. The merge happens per request,
  so a toggle takes effect on the next turn without a restart, and `/v1/models`,
  the router and the panels read the same view — a screen cannot disagree with a
  route.
- **Four fields are tunable, the rest are YAML.** `enabled`, `priority`, `tier`
  and `monthly_cap` each have a baseline in `config.yaml` and an optional
  override in the table; the UI shows baseline vs effective, marks a tuned field
  with a dimmed `was …` line, and a `clear override` button sends an explicit
  `null` back to drop it to baseline. `name`, `kind`, `base_url` and `models` are
  YAML-only. Note the one naming seam: the YAML key is `monthly_token_cap`, while
  the override row, the API field and the panel all call it `monthly_cap`.

A month with no turns is a real state, not an error: Overview says
`nothing spent in 2026-10 yet — the month is empty, not broken.` and the bars sit
at zero. A provider with no key says `no key` and shows the box that stores one, and
a provider that asks for no credential at all — a local server on loopback, whose config
stanza has no `key_ref` — says `no key needed` and keeps the store box disabled. The
engine sends `key_present` and `needs_key` for exactly that distinction; the client reads
the pair in one place, `kira-chat/src/keying.ts`.
The same cell says `sees images` or `text only`, which is config.yaml's `vision:`
flag read back: it is the only way to know, before a call starts, whether a webcam
frame has anywhere to go or stays on this device.
A row whose write was refused stays exactly as it was, because the panel's
numbers come from the engine and nothing is updated optimistically.

## Two modes: Chat and Agent

The switch in the top-left corner changes how the same screens look and sit. It is a preference,
not a route: `#/providers` is the same place in both, and `kira.shell` remembers which you prefer.
`kira.theme` (seven), `kira.look` (glass, motion, caption size, scale, density) and `kira.sidebar`
(the agent sidebar's collapse) are the other three preferences. None of them is a secret, and the
storage claim above still holds: `grep -rn "localStorage" kira-chat/src/` now also returns `shell.ts`,
`theme.ts`, `look.ts`, `PromptsScreen.tsx` and `RemoteScreen.tsx`, and every key is one of those nine.

- **Chat** wears MYRAA's language: `#020205`, frosted panels, mono uppercase labels, a Space Grotesk
  caption for the answer, seven accent themes, and an options panel shaped like MYRAA's overlay.
- **Agent** wears ALTREX's geometry with PocketStrike's glass: a 240px sidebar collapsing to 56px, a
  48px top bar, a 780px conversation column, and an eight-tab work panel fed by the turn's chain:
  Changes, Terminal, Tests, Problems and Checkpoints read `tool_executed` / `tool_denied` /
  `checkpoint_created` records, Agents draws the chain as a timeline beside the live registry, and
  Context and Developer stay as they were. An empty tab says what will fill it, not just "no data".

Switching mid-answer keeps the streamed text: the turn lives above the shell branch. The engine is not
told about the mode; nothing about routing changes.

**The agent's turn reads as a turn.** Under each answer, `TurnTrace` folds the chain into one card whose
head says what happened (`Answered by mock_two after 1 provider was skipped · 1 failed · 2 steps`) and
whose rows are verbs, not event names: `Ran · npm test · 41 lines`, `Asked to run · run_command`,
`Couldn't call · demo_lookup · tool is denied by policy`, `Skipped · mock_one · over cap`. A running step
moves, and stops moving when you ask for no motion or the OS asks for reduced motion. A decision that has
already been made is history, not a pending clock.

**The composer answers to Enter.** Enter sends, Shift+Enter is a newline, Ctrl/Cmd+Enter still sends for
muscle memory, and neither sends while an input method is mid-composition. The box grows with its text up
to 180 px and then scrolls inside itself, so a pasted log cannot push the thread off the screen. One line
under the box is the status strip: `Enter sends · 2 models · AUTO` at rest, `Working for 12s · 2 steps`
while a turn is open. `send` and `stop` share one tile — the tile that exists is the next action.

## Web and mobile

One bundle, one engine, no second codebase. The phone gets a layout, not an app.

- **It installs.** `kira-chat/public/manifest.webmanifest` is served at `/chat/manifest.webmanifest`
  with `display: standalone`, `scope: /chat/`, and 192/512/maskable icons — all three drawn from the
  same `draw_icon` code as the tray icon, so the icon cannot drift from the brand. `theme-color` and the
  `apple-touch-icon` link are in the document.
- **It survives a dead engine, and says so.** A service worker (`kira-chat/public/sw.js`) answers
  navigations network-first and assets cache-first, under a cache name derived from the built
  `index.html` — so a new build cannot be shadowed by an old shell. It never caches `/v1`: the cache
  holds the shell, the manifest and one icon, then each script, stylesheet and route chunk after it is used; the offline page says
  `no answer from the engine at http://127.0.0.1:8901` rather than pretending there is nothing to talk
  to.
- **At 390 px** navigation moves to a bottom bar (Chat · Call · Sessions · Overview · Menu) with 44 px
  targets and the full rail behind Menu, the shell is `100dvh` with the thread as the only scroller, the
  session/provider strip is capped at a third of the screen, safe-area insets pad the bar and the
  composer, and every field iOS would otherwise zoom on focus is 16 px.
- **Reaching it from a phone is unit 12, not this.** The engine binds loopback and stays that way; a
  tunnel of your own forwards to it. Service workers and installability need a secure context, and
  `http://127.0.0.1` is one while a phone on the other end of a tunnel is not — so use a tunnel that
  terminates TLS (Tailscale Serve does).

## Voice and video call

`#/call` runs a live voice loop with the mic and speakers of this machine:
16 kHz PCM → server VAD → speech-to-text → the same router and agent loop as chat → one WAV per
sentence back. Speaking over the answer stops it.

- **Listen / speak are local-first.** `whisper.cpp` from a studio, `faster-whisper` (optional extra),
  Kokoro through a studio, and a Piper binary under `<data>/voice/piper` are used when present;
  `voice.stt_engine` / `voice.tts_engine` pin one (`auto` is the default). `kira-engine voice doctor`
  prints exactly what is installed and what the engine expects.
- **BYOK second.** `voice.stt: remote` / `voice.tts: remote` name an `openai_compat` provider and use
  its key from the Windows Credential Locker. The engine never silently falls back from local to
  remote.
- **Video is a self-view plus frames.** The webcam stays in the browser; one JPEG every 4 s is
  attached to the next thing you say, and only if the serving provider's stanza says `vision: true`.
  Frames are never written to disk or chat history.
- **No tools on a call.** An approval needs the confirm secret; a microphone is not a second factor.
  The loop runs with an empty registry, `max_steps=1` and no approvals or checkpoints.

The screen opens by asking `GET /v1/kira/voice` and printing the engine's own answer for each stage —
`faster-whisper is not installed — pip install -e ".[voice]"`, not a vague "unavailable" — and greys
*start call* only when both directions are `off`. A machine with no whisper and no piper says so before
you press anything. The `#/call` route is the only screen with its own socket; it does not share the
chat turn, because a call that is barged, muted and restarted has no business reusing a state machine
built for one streamed answer.

Everything the call sends or plays is decided on this machine: the PCM leaves the browser only while the
mic is unmuted, a barge-in is detected locally (the engine is deaf while it is thinking or speaking),
and typed input works with no microphone at all. The microphone is opened mono with
`echoCancellation`, `noiseSuppression` and `autoGainControl` and the capture context asks for 16 kHz —
the browser does the DSP, the worklet only turns 1600 samples into one base64 packet, and the engine
never has to guess what the room sounded like.

The transport is a WebSocket at `/v1/voice` — `ws://` on loopback, `wss://` if you ever front it — and
it deliberately has no row in the endpoint table above, because that table is what a test compares
against the engine's HTTP route table and a WebSocket has no method. Its bearer token travels in the
first frame (`hello`), not a header: a browser cannot set an Authorization header on a WebSocket. No
`hello` inside five seconds closes the socket with policy 4401, so an unauthenticated peer never reaches
the mic path.

## Checks

```bash
cd kira-engine && .venv/Scripts/python -m pytest -q   # 881 tests (+9 skipped), every provider faked; the live suite is skipped
cd kira-chat  && npm run check                        # tsc --noEmit, then vitest (55 files, 561 tests, jsdom), then vite build
node kira-contracts/check-drift.mjs                   # cross-language contract gate: v2, 86 schemas, 6 chunk types, 16 chain events
```

The engine suite includes `tests/test_docs_match_engine.py`, which fails when
this README's endpoint table, chain-event list, CLI verb list or tunable-field
list drifts from the code. Everything else in this file is prose, and prose is
checked by the hand proofs in `docs/plans/` — a claim with no command behind it
is a claim nobody verified.

`check-drift.mjs` compares the engine's exported `openapi.json` / `contract.json`
against the hand-written TS mirror and fails on any drift — a renamed field, a
dropped enum member, a `$ref` that no longer resolves, or an error code the
TypeScript side never learned about. Regenerate the engine side with
`kira-engine contracts`.

### Live providers (opt-in, spends real credits)

```bash
cd kira-engine
KIRA_LIVE=1 .venv/Scripts/python -m pytest tests/test_live_providers.py -q
```

The dashboard's Test button is the same honesty in miniature: it is the only click
that requests a completion, and `kira-engine models` and `?live=true` never do.

This is the only check that proves a provider actually answers over the wire. It
writes `docs/qa/live-providers.json` with real call counts per provider — the
file does not exist until you run it, and that is the honest state. Re-read it
before trusting a "tests pass" claim: `providers_tested: 0` means no live API was
ever called, and the fake-provider suite says nothing about your keys, your
quotas, or a provider that changed its schema.

Above it sits the app-level version: driving the built UI against your own running
engine in a headless browser, so a real model chooses a real tool and the verdict is
read back from the engine's stored rows instead of the bubble. `docs/qa/live-app-pass.md`
is that run; it is where the four defects behind `thought_signature`, the duplicate
`complete` row, the chip that renamed a failed turn and the invisible `empty_answer`
were found. It spends your quota, so read the quota section before pointing it at a
free-tier key.

## Deliberately not here

- **No local/offline model** yet — sub-project 5 (llama.cpp as another tier).
  Router modes are online tiers only; there is no `LOCAL` mode, and the dashboard
  never pretends otherwise. Live probes, by contrast, are built:
  `kira-engine models`, `GET /v1/models?live=true` and the Providers Test button
  all go through `probe.py`, and only the button spends.
- **No free-tier key scraping or shared-pool aggregation.** Bring your own key;
  a provider you didn't configure can't be reached.
- **No verbatim donor code.** This is a reimplementation; `PROVENANCE.md` records
  what was studied versus written.
