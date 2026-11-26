# Studio integration — verification record — 2026-11-01

Portable AI Studio ships a complete local stack behind `scripts/server/serve.cjs`: stable-diffusion.cpp,
llama.cpp, whisper.cpp, Kokoro, four model folders, a gallery and a hardware report. Kira already
reused the binaries and checkpoints in place, but half of that API had no screen. This pass makes every
studio capability reachable from the Kira UI without re-implementing it.

The discipline is the repository's usual one: a claim below is either **observed** in a test or a live
run, or it is marked **inferred** and the inference is named. Nothing is called verified because it
compiles.

## Decision

Kira supervises the studio's Node server and forwards its API through an authenticated proxy. It does
not copy the studio SPA into Kira and does not reimplement the endpoints.

**Observed.** The studio SPA is built with absolute `/assets/...` and `/api/...` URLs, so serving it
under a Kira path prefix (`/studio/`) breaks every asset and every fetch. The server binds
`127.0.0.1` and has no auth of its own, so exposing it directly would put an unauthenticated local API
next to Kira's bearer-protected one.

**Inferred.** One process owner is enough: Kira spawns the server on demand, keeps it on loopback,
and kills the tree with the engine. A studio already started by `windows.bat` is detected and left
alone (`managed: false` means *stop* is a no-op), and `KIRA_STUDIO_URL` points Kira at a server it
did not start. The proxy forwards the caller's body and content type but never the `Authorization`
header.

## Feature matrix

| Studio capability | Studio route | Kira entry point | State |
| --- | --- | --- | --- |
| Text-to-image | `/api/generate`, `/api/image-status` | Images screen, own `sd-cli` | existing, unchanged |
| Image gallery + delete | `/api/outputs`, `/api/delete-output` | Images screen | existing, unchanged |
| Chat with a GGUF | `/api/chat`, `/chat/completions` | Kira chat + *start local model* | existing; the UI never calls the studio chat route |
| Image checkpoint folders | `/api/models` | Studio → models | **new** |
| Chat model folders | `/api/llm/models` | Studio → models | **new** |
| Whisper model folders | `/api/speech/models` | Studio → models and transcribe | **new** |
| Kokoro manifests | `/api/tts/models` | Studio → models | **new** |
| Delete a model file | `/api/{,llm/,speech/,tts/}delete-model` | Studio → models, confirm-gated | **new** |
| Transcribe a WAV | `POST /api/speech/transcribe` | Studio → transcribe | **new** |
| Transcription history | `/api/speech/transcriptions` | Studio → transcribe (recent list) | **new**, read-only |
| Voices | `/api/tts/status` | Studio → voice | **new** |
| Speak | `POST /api/tts/speak` | Studio → voice, audio element | **new** |
| Clips + delete | `/api/tts/outputs`, `/api/tts/delete-output` | Studio → voice, confirm-gated | **new** |
| Hardware report | `/api/health` | Studio → diagnostics | **new** |
| Image backend state | `/api/backend-status` | Studio → diagnostics | **new** |
| Start/stop the Node server | process, not HTTP | Studio → studio server card | **new** |
| Download a model | Hugging Face into a folder | Studio → download | existing, Kira-owned |

The studio's `/api/chat` remains technically inside the proxy allowlist (`/api/` is the whole
namespace), but Kira owns conversation, memory and tools, so no screen calls it. That is a product
boundary, not a security boundary.

## Evidence

| Claim | Command | Result |
| --- | --- | --- |
| Engine routes, supervision, allowlist, confirm | `python -m pytest tests/test_studio_server.py -q` | 20 passed |
| No engine regression | `python -m pytest -q` | 882 passed, 8 skipped |
| Contract, README and route table agree | `python -m pytest tests/test_docs_match_engine.py tests/test_versioning.py tests/test_units.py -q` | 38 passed |
| Every Kira screen still renders, new panel tests pass | `npx vitest run` | 538 passed (534 before, +4) |
| Types and bundle | `npx tsc --noEmit`, `npm run build` | clean; 954 kB bundle, `kira-build.json` stamped |

What the tests pin down, in words:

- **Supervision.** A healthy server at the configured port is attached, not spawned. A missing studio
  folder refuses with the `KIRA_STUDIO_DIR` sentence; a dark `KIRA_STUDIO_URL` refuses instead of
  spawning somewhere else. A start that never answers is killed, not left as an orphan.
- **Ownership.** `stop()` on an attached studio does nothing. The Windows kill uses `taskkill /F /T` so
  `node`'s children (llama-server, sd, whisper) do not outlive it.
- **The proxy.** Only `/api/`, `/tts-outputs/`, `/transcriptions/` and `/outputs/` are reachable; `..`
  is refused; only `GET` and `POST`; the response keeps the studio's status and content type, which is
  how a WAV comes back as a `Blob` and a JSON row comes back as JSON.
- **Confirm.** The typed secret is required for `app/start`, `app/stop`, and any forwarded `POST` whose
  path contains `delete` or `stop`. The bearer token is never forwarded.

A live smoke on 2026-11-01 (ports 1521/1522, the user's own studio folder) observed `found: true`,
a spawned `managed: true` child, `/api/tts/status` and `/api/speech/models` answering `200` through
the proxy, and the child process gone after *stop*. The engine's data dir kept the studio log under
`logs/studio.log`; studio models were not copied into Kira's folders.

## Not observed in this pass

- **A real transcript and a real Kokoro clip.** The panels were exercised against the fake engine; the
  live smoke only asked the server for its status and model lists. Whisper needs a 16 kHz WAV and
  Kokoro's first run downloads its ONNX model, so both stay one deliberate manual click away rather
  than a test that hides a network dependency.
- **Audio playback in a real browser.** The voice panel builds an object URL from the proxied WAV;
  jsdom has no audio pipeline, so only the request and the blob are asserted.
- **GPU behaviour.** This machine has no CUDA backend; the studio reports Vulkan and CPU. The
  diagnostics panel shows that report, but no pass here measured a GPU generation.
- **Deleting transcriptions.** The panel reads the recent list; the studio's deletion route, if it has
  one, is not wired. Deleting a model or a clip is.

## Reproducing by hand

1. `run-kira.bat`, open `#/studio`.
2. The **studio server** card reads `stopped`; *start studio server*, type the confirm secret. The
   badge turns `running` and the four tabs appear.
3. **Transcribe**: pick a WAV, pick a `ggml-*.bin`, *transcribe*. The text lands above the recent
   transcripts. The same request is `POST /v1/kira/studio/proxy?path=/api/speech/transcribe`.
4. **Voice**: type a sentence, pick a voice, *speak*; the player appears and the clip joins *recent
   clips*. Delete it and the confirm dialog names the file.
5. **Models**: four tables, one per folder; a delete asks for the secret and the row disappears after
   the re-read.
6. **Diagnostics**: the build line, any issues, the checks table and the image backend state.
7. *stop studio server*: the badge returns to `stopped`, and if you started the studio from
   `windows.bat` instead, the stop button is absent and the card says the process belongs to another
   launcher.