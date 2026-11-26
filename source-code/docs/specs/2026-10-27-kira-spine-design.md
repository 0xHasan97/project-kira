# Kira spine — design spec (sub-project 1 of 8)

Date: 2026-10-27
Status: agreed in conversation, implemented same day
Scope: core engine + loopback API contract + provider routing + minimal chat.
Explicitly deferred to later sub-projects: OS-control tools, voice, retrieval
memory, checkpoints, skills packs, desktop shell (tray/hotkeys/PTT), mobile,
MCP exposure, and **local/offline inference**.

## Decisions locked with the user

| Decision | Choice |
|---|---|
| Build mode | Rebuild: one native codebase, reimplemented (not a fork, not a wrapper) |
| Language split | Hybrid — TypeScript front, Python engine |
| v1 surfaces | Desktop shell + loopback API (full multi-surface product decomposed into 8 sub-projects) |
| Model access | BYOK + any OpenAI-compatible endpoint. No free-tier aggregation or scraping |
| Offline/local model | **Later** (sub-project 5). Not in this spec |
| License stance | Personal use. Behaviour/architecture reimplemented from any donor, no verbatim source copying, provenance logged in PROVENANCE.md |

## Target machine (measured, not assumed)

Ryzen 5 5600G (12 threads), 24 GB RAM, Radeon RX 5500 4 GB (AMD — no CUDA),
Windows 11. `node` v24.20.0, `python` 3.12.10, `git` 2.56, `rg` 15 present;
`ollama`, `llama-server`, `ffmpeg`, `pnpm`, `dotnet` absent. C: 8.8 GB free,
D: 57 GB free → all data, venvs and caches go on **D:**.

Consequence for the deferred offline work: CPU-first inference, 3–4 B Q4 class
models. The provider seam ("OpenAI-compatible base URL") is kept so offline
later means lifecycle management plus model discovery, not new plumbing.

## Architecture

```
Kira/
  kira-engine/          Python 3.12, FastAPI, binds 127.0.0.1 only
    providers/          openai-compatible · anthropic · gemini · registry
    router.py           AUTO / FAST / POWERFUL / CUSTOM
    vault.py            Windows Credential Locker via keyring (service "kira")
    store.py            SQLite WAL — sessions, messages, usage, provider health
    net.py              fallback / cooldown / penalty ledger
    loop.py             agent turn loop + ToolRegistry interface
    app.py              /v1/chat/completions (SSE) · /v1/models · auth
    contracts.py        OpenAPI + CONTRACT_VERSION (single source of truth)
  kira-contracts/       generated TS client types (drift-checked in CI)
  kira-chat/            Vite + React + TS thin chat; becomes the Electron
                        renderer in sub-project 3, so it is not throwaway
```

Three packages, one contract. The engine is the only thing that talks to
providers; the UI is a client of the same public `/v1` surface that any later
surface (desktop, web, mobile) will use.

### Two versions, two jobs

The surface carries two numbers that answer two different questions, and they
are deliberately not the same integer:

- **`API_VERSION` / `API_PREFIX`** — the URL namespace (`/v1`). It bumps only when
  a documented method+path is removed, renamed, or its response changes meaning,
  i.e. when a caller that already parsed the old shape breaks. A request for a
  namespace this engine does not serve is answered `404 unsupported_version`
  before any credential is consulted, naming both the requested and the served
  prefix.
- **`CONTRACT_VERSION`** — the revision of the fields inside that namespace. It
  bumps when a schema's field set or an enum's *meaning* changes.

Adding a field, a schema or an enum value is additive and bumps neither, because
a reader that ignores what it has not seen keeps working.

`/healthz` is the one endpoint outside the namespace — it is how a caller finds
out which namespace this engine speaks — and it publishes both numbers. Every
response under `API_PREFIX` carries `X-Kira-Contract-Version`, the built bundle
records the pair it was built against in `dist/kira-build.json`, and the
launcher rebuilds the bundle when that stamp disagrees with the engine instead of
serving a stale UI forever. `check-drift.mjs` refuses a contract path outside the
namespace (except `/healthz`) and refuses a TS mirror whose `API_PREFIX` /
`API_VERSION` differ from the engine's.

## Data flow

chat UI → `POST /v1/chat/completions` (Bearer) → router picks provider by mode
and health → SSE stream back → message + usage + provider chain persisted →
UI renders the answer **and** the reason it came from that provider.

Provenance is mandatory on every response: `X-Kira-Provider-Chain` header plus a
`provider_chain` field carrying reason codes (e.g. `openai 5xx x2 -> cooled 120s
-> gemini served`).

## Storage and secrets

`.kira-data/` (gitignored, on D:): `kira.db`, `config.yaml`, `logs/engine.log`.
`config.yaml` holds only non-secret values (base URLs, model names, ports,
timeouts, budgets). API keys go to the Windows Credential Locker via `keyring`
and never touch disk — MYRAA documented plaintext Gemini keys in a dev `.env`
(`docs/FINAL-UPDATE-REPORT.md` §4.3); this design rejects that. First run
generates the engine bearer token, stores it in the Locker, prints it once.

## Error-handling rules

- No silent failover: every fallback is recorded with a reason code and surfaced
  to the client.
- All providers exhausted → `503 PROVIDERS_EXHAUSTED`. Never a canned apology
  passed off as an answer.
- 4xx (except 429) does not trigger failover — a bad request is not an unhealthy
  provider.
- Mid-stream failure → terminal SSE `error` event; partial message persisted
  with `status=interrupted`.
- Key-decrypt failure raises loudly. freellmapi buried `CREDENTIAL_DECRYPT_FAILED`
  under blanket "NOT TESTED" rows; that is the failure mode being avoided.

## Testing

- pytest over FastAPI ASGI transport with `httpx.MockTransport` fake providers:
  streaming, tool-calls, 429/5xx failover, mid-stream abort.
- Live provider checks are a **separate opt-in** suite (`KIRA_LIVE=1`) that
  writes real call counts to `docs/qa/live-providers.json`. Rationale: ALTREX
  shipped 683 passing tests while every live provider was `"NOT TESTED"`,
  `calls: 0` (`docs/qa/live-providers.json`).
- CI fails if `contracts.py` changed without regenerating the TS types.

## Tool interface (present, but empty by design)

`ToolRegistry` with name/description/JSON-schema parameters and an async
handler. Two demo tools (`echo`, `now`) prove the round-trip through at least
two providers. No `pyautogui`, no OS control — that is sub-project 2.

## Milestones

- **M1** skeleton, config, vault, SQLite, first-run token
- **M2** OpenAI-compatible provider + SSE + `/v1/models` + `/v1/chat/completions`
- **M3** Anthropic + Gemini adapters (translated to internal message types)
- **M4** router + fallback/cooldown/penalty + chain reporting
- **M5** agent loop + ToolRegistry + demo tool round-trip
- **M6** TS client (codegen types) + minimal chat UI + vitest
- **M7** live-provider suite + docs + PROVENANCE.md

## Out of scope for this spec

Local/offline inference and model lifecycle; OS-control tools; voice
(STT/TTS/wake-word); vector/hybrid memory and retrieval; checkpoints and
worktrees; skills packs; tray/hotkeys/overlay; mobile; MCP server exposure;
multi-agent tournaments and review/critic loops.
