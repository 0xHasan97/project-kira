# PROVENANCE

Kira is a personal-use reimplementation. No source text was copied from any
donor project; these entries record which donor's *design* each module
reimplements, so licensing questions can be answered later without archaeology.

| Kira module | Design influence from | Donor license | Copied source? |
|---|---|---|---|
| `router.py` (mode enum, provider-diverse fallback) | ALTREX `packages/core/src/router/router.ts` | none — all rights reserved | no |
| `contracts.py` (versioned single-source contract, codegen to typed client) | ALTREX `packages/contracts` (CONTRACT_VERSION, zod IPC) | none — all rights reserved | no |
| `app.py` `/v1` surface ordering (models, chat, anthropic + gemini wire compat) | FreeLLMAPI `server/src/app.ts` | MIT | no |
| `net.py` (cooldown / penalty / fallback ledger) | FreeLLMAPI router behaviour | MIT | no |
| `vault.py` (OS keyring for provider keys, nothing secret on disk) | Laya `security/keychain.py`; MYRAA `secrets/secretStore.ts` lesson | Apache-2.0 / none | no |
| `store.py` (append-only session/message/usage rows, WAL) | Laya storage patterns; ALTREX JSON state | Apache-2.0 / none | no |
| `providers/local` seam (deferred; OpenAI-compatible base URL) | Laya `llm/providers.py`; BrahmaEvo `core/local_brain.py` | Apache-2.0 / proprietary non-distribution | no |
| Provenance-per-answer (`provider_chain` reason codes) | ALTREX verification/evidence reporting | none — all rights reserved | no |
| Control dashboard (`kira-chat/src/screens/*`, `confirm.tsx`, `useWrite.ts`, `overrides.py`, `probe.py`, the derived-spend aggregates in `store.py`) | FreeLLMAPI dashboard (`Source code/freellmapi-main.zip`) — screen list, per-provider spend and key management UX | MIT | no |
| Shell switch and presentation (`shell.ts`, `theme.ts`, `look.ts`, `shell-switch.tsx`, `options-panel.tsx`, the two `[data-shell]` token blocks, `screens/AgentPanel.tsx`) | MYRAA visual language (`App.tsx:305`, `:522`, `:612-638`, `SettingsPanel.tsx:36-112`); ALTREX geometry and tokens (`styles.css:3-34`, `:56-59`, `WorkPanel.tsx:16-25`); PocketStrike glass and radii (`glass_tokens.dart:32-49`, `app_palette.dart:11-34`) | none / none / none | no — values read, CSS written here |
| Tool harness (`tools.py`, `workspace.py`, `policy.py`, `approvals.py`, `checkpoints.py`, `plugins.py`, `loop.py`'s policy branch, `limits.py`, `screens/ToolsScreen.tsx`, `components/ApprovalCard.tsx`) | MYRAA risk-0–4 confirmation gates → three policies with per-risk defaults, approval held mid-stream; ALTREX permission classifier + pre-write checkpoints → policy overrides + diff/restore; PocketStrike tool registry → the Tools screen; Ultron's shell control → rejected, replaced by an argv-only `run_command` with no shell | none / none / none / none | no — behaviour reimplemented from observed UX; no donor code, no donor assets |
| Real-time call (`voice/vad.py`, `voice/stt.py`, `voice/tts.py`, `voice/stack.py`, `voice/wav.py`, `voice/call.py`, the `hello` handshake and `WS /v1/voice` in `app.py`, `kira-chat/src/voice/*`, `screens/CallView.tsx`, `screens/CallScreen.tsx`) | The user's own reference diagram — Raspberry Pi + webcam → Whisper → local model → Piper — re-hosted as browser mic/camera → engine VAD + STT → Kira's existing router → TTS. The remote STT/TTS stages speak OpenAI's `/audio/transcriptions` and `/audio/speech` **wire shapes** (request body, response body, `Content-Type`), with no SDK and no copied code. MYRAA is a voice companion and its UX was seen as a product; none of its call code was read for this module, and no donor installer or donor code was ever executed. | n/a for the design; the remote endpoints are the user's own BYOK providers | no — nothing in the call path came from a donor |
| Memory and retrieval (`memory.py`, the v2 schema in `store.py`, `screens/MemoryScreen.tsx`) | laya `db/fts.py` (own-content FTS5 tables, trigger sync, `bm25()`, quoted MATCH builder, LIKE fallback) and `retrieval.py` (RRF, deferred); PocketStrike `hermes_memory_store.dart` (the fact/preference/note split, and its auto-evolve switch, inverted to off) | Apache-2.0 / none | no — SQL and behaviour written here; their tokenizer was measured and rejected |
| Skill pack import (`skills.py`'s folder loader, `install_pack`, the `search_skills` tool, `skills install|list` in `__main__.py`, the filter and `discovery` line in `SkillsScreen.tsx`) | ECC-main (`Source code/skills/ECC-main.zip`) — its `skills/<name>/SKILL.md` layout, its per-skill frontmatter, and its habit of carrying one skill once per host harness. The 16 KB prompt cap, the single `<top>/skills/` read, the `kind: method` default and the `INLINE_LIMIT = 24` switch to search are Kira's rules, not theirs | MIT (c) 2026 Affaan Mustafa — copied next to the skills it covers at `<data>/skills/LICENSE` | no — 266 of their skill **texts** land in the user's own data dir, by the user's own command, from a path the user named. No script, `.py`/`.js`/`.sh`, hook or installer in that archive was read, copied or executed, and nothing from it entered this repo |
| Prompt library (`screens/PromptsScreen.tsx` and its test) | project-Mia `core/prompts.py` / `data/prompts.json` and `core/automations.py` / `data/automations.json` — a card is a saved instruction, `{vars}` are filled before sending, and an automation is one click with no trigger; Kira adds no engine route and keeps custom prompts in this browser (`localStorage["kira.prompts"]`) | none — all rights reserved | no — the prompt texts and the fill-before-send behaviour were reimplemented; no donor code |
| REA method (`kira-engine/skills/rea.md`) | REA / `reverse-engineer-anything` (`Source code/skills/rea (skills)/rea-main.zip`) — route the target by format, work summary-first, label every claim seen/inferred/unknown, and never execute an unknown installer; Kira distils the method into a 2 KB skill because the donor's 23 KB `SKILL.md` is over the 16 KB prompt cap | MIT (c) 2026 morluto — notice kept in the skill's `license` frontmatter | no — the donor Markdown was read and its method paraphrased; its CLI, MCP server and native engines are neither vendored nor installed |

| Third-party asset | Design influence from | Licence | Vendored file? |
|---|---|---|---|
| Typefaces `@fontsource/space-grotesk`, `@fontsource/inter`, `@fontsource/jetbrains-mono` | MYRAA, ALTREX, laya and PocketStrike independently use Space Grotesk / Inter / a mono for chrome | SIL OFL 1.1 | no — npm dependencies, imported in `main.tsx`, emitted into `dist/assets` by Vite |
| Icons `lucide-react` | ALTREX and MYRAA both import lucide | ISC | no — npm dependency, tree-shaken at build |
| `faster-whisper` (the `voice` extra in `kira-engine/pyproject.toml`) | CTranslate2 reimplementation of OpenAI Whisper; used only as a pip dependency, imported lazily inside `voice/stt.py`, absent by default so chat never needs a 100 MB model | upstream — this repo vendors neither it nor its weights | no — `pip install -e ".[voice]"` is the user's command, and the engine never downloads anything |
| Piper | local speech synthesis, run as an **external binary by argv** (`piper.exe` plus a `.onnx` voice the user places under `<data>/voice/piper`); Kira ships no Piper code, no voice model, and no downloader | upstream | no — `voice/tts.py` only builds the argv list, writes the sentence to stdin, and reads the WAV Piper left at `--output_file` before unlinking it |

Not yet ported, with the reason on record:

- MYRAA's 81 desktop-control tools and risk 0–4 confirmation gates — the gates
  shipped as sub-project 2's three policies (see the row above); the 81 tools did
  not, because desktop control is out of scope and the donor has no license.
- ALTREX checkpoints and permission command-classifier — shipped as sub-project
  2's `checkpoints.py` and `policy.py` (see the row above).
- ALTREX Multi-AI Director and Codex CLI wrapper — rejected: overlaps the task
  engine, wraps an external unsigned binary.
- MYRAA 3D/MMD character engine — rejected: orthogonal to the agent, skins are
  non-redistributable. The real-time call deliberately borrows none of its voice
  pipeline either: no wake word, no lip-sync, no streaming avatar. Sub-project 11
  (the on-screen character) is where that decision gets revisited, and it still
  needs the user's own `.pmx`.
- BrahmaEvo auto-heal / skill-forge — deferred; license bars distribution.
- FreeLLMAPI free-provider catalog — rejected by decision (BYOK only, no ToS risk).
- Cloud-Play-X — not an AI agent (zero LLM references); no capability to carry.
- project-Mia (`Ai agents/project-Mia`) — audited read-only 2026-10-29. Its prompt library and
  one-click automations shipped as `#/prompts` (row above). Its four ungated tools remain unported:
  Kira's tool registry is gated and the donor's outputs are dropped from its stream. Its DeepSearch
  remains a decomposition prompt over a `web_search` tool Kira does not have. Its plaintext provider
  keys were neither read nor moved — see the audit and the rotate-them recommendation in `docs/ROADMAP.md`.
- project-Mia's `ALTREX/`, `paperclip/` and `rea/` — rejected: vendored third-party apps Mia shells out
  to, not Mia's design. Porting one would be porting a donor's dependency; the ALTREX director and Codex
  wrapper are already rejected above. The separate REA pack under `Source code/skills/` is represented
  only by the distilled `rea` method above; Mia's vendored copy was not used.

| Avatar stage (`pmx.ts`, `krm1.ts`, `load.ts`, `stage.ts`, `mesh.py`, `characters.py`) | MYRAA 3D voice companion PMX model format, character import concept | none — all rights reserved | no — format spec measured from donor archives, loader and renderer written from spec; no donor code executed or copied |
