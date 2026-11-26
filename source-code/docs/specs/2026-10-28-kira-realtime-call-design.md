# Kira sub-project 6 — realtime voice call, and the video half of a call

Date: 2026-10-28
Status: implemented and merged to `master` (`32cc337..77581e6`, Tasks 1–12 of
`docs/plans/2026-10-28-kira-realtime-call.md`, merge `8ff4e17`); browser pass in
`docs/qa/call-browser-pass.md`.
Depends on: sub-project 1 (spine), 2 (tool harness), 9 (dashboard), 10 (shell modes).
Sibling slices: desktop shell (3), memory (4), offline model (5), avatar (11), remote (12).
Project-level ordering and completion arithmetic: `docs/ROADMAP.md`.

## 1. What this is

The user's diagram is a call loop: a camera and a microphone, something that listens (Whisper),
something that thinks and answers (qwen3:1.7b), and something that speaks (Piper). On this machine
the Raspberry Pi is the desktop itself, the mic and webcam are its own, and "qwen" is whichever
provider the user's key names — or a local server through the same OpenAI-compatible path.

This sub-project builds that loop inside Kira:

- **A voice call.** Browser mic → server VAD → speech-to-text → the existing router and agent loop
  → text-to-speech → browser playback, with barge-in: speaking over the answer stops it.
- **Speech local-first, BYOK second.** `faster-whisper` and a Piper binary on this PC when they are
  installed; otherwise the user's own OpenAI-compatible key for `audio/transcriptions` and
  `audio/speech`. Never a silent downgrade — the chosen mode either works or says why not.
- **A video call in the only sense a text model can honestly offer.** The webcam is a self-view in
  the browser, and a small, rate-limited JPEG snapshot is attached to the *next* thing the user
  says, so "what am I holding?" has something to look at. Frames are never persisted.
- **A `#/call` screen** with self-view, level meter, live transcript, chain line, a typed fallback,
  and an honest readout of which half of the stack is installed.

The engine already has everything behind the LLM: `Router.plan` (`kira-engine/src/kira/router.py:61`),
`AgentRun` (`kira-engine/src/kira/loop.py`), persisted sessions, flow control, and the chain
recorder. This slice adds sound in front of it and behind it, not a second brain.

## 2. Explicitly not in this spec

| Not here | Why | Lands in |
|---|---|---|
| WebRTC / peer-to-peer media | Kira is one user on loopback; WS carries PCM fine and needs no STUN, DTLS or TURN. Revisit only when a second machine is a caller | #12 remote, if ever |
| Server-side video | A frame every few seconds is what a text model consumes; streaming video to the engine would be a pipeline with no consumer | never |
| Wake-word / always-listening | The call is an explicit screen with an explicit start; a hot mic on the desktop is a different product decision | #3 desktop shell would have to ask first |
| Phone number / PSTN, Twilio-style | BYOK ground rule; telephony is a broker, not a provider | never |
| Voice cloning or user-supplied voices | Piper voices are a chosen file; cloning is an ethical and legal surface this project does not need | never |
| Transcription of saved files | The call is live; uploading an mp3 is a different feature with a different UI | not planned |
| Speaking the approval dialog | An `ask` tool needs the confirm secret; a spoken "yes" is not a second factor and TTS reading the prompt invites yes-to-anything | refused on purpose, §4.4 |
| Push-to-talk | VAD plus a typed fallback covers noisy rooms; PTT adds a second segmentation path to maintain | reconsider if real use asks |
| Storing audio or frames | Ground rule; transcripts are text and belong to chat history, bytes do not | never |

## 3. What this borrows, and from where

Researched before designing; mechanisms are reimplemented, nothing is vendored.

| Claim | Source |
|---|---|
| Browser capture runs at a chosen sample rate with echo cancellation, noise suppression and auto-gain as `getUserMedia` constraints; a 16 kHz `AudioContext` resamples the mic for a speech pipeline | MDN `MediaTrackConstraints`, Web Audio `AudioContext` |
| `AudioWorklet` is the supported place to turn mic floats into fixed 20 ms frames without glitching the main thread | Web Audio `AudioWorkletProcessor` |
| faster-whisper runs Whisper on CPU with `compute_type="int8"`; short utterances land around 0.5–1.5 s, model files download once from Hugging Face | `SYSTRAN/faster-whisper` README |
| Piper is a standalone binary plus an `.onnx` voice; CPU real-time factor is well under 1 for the small voices; it writes WAV | `rhasspy/piper` |
| OpenAI-compatible servers expose `POST /audio/transcriptions` (wav accepted) and `POST /audio/speech` (`response_format: "wav"`), which Groq and local servers also implement | OpenAI audio API docs |
| Local loopback pages count as a secure context, so `getUserMedia` works on `http://127.0.0.1` without TLS | W3C secure contexts |

Kira's own additions: server-side VAD (one boundary for utterances), two-stage barge-in, sentence
chunking so first audio does not wait for the last token, and a vision path that is opt-in per
provider instead of assumed.

## 4. Decisions, with the alternatives they beat

### 4.1 WebSocket PCM, not WebRTC

A call between a page and its own engine on the same machine has no NAT to traverse and no second
peer. WebRTC would add DTLS, ICE, codec negotiation and a signalling path for a stream that is
already trusted and already loopback. The browser sends **PCM16 mono at 16 kHz**, 100 ms per frame,
base64 in JSON, and the server answers with WAV chunks. Cost measured on paper: 32 KB/s up and
similar down, trivial for loopback. When two machines must call each other (#12), WebRTC is the
right answer and this endpoint is not in its way.

### 4.2 One utterance boundary, owned by the server

The client could segment with its own energy detector, but then two clocks decide when a sentence
ended. The server owns segmentation (energy VAD, §5.2) and emits `speech_start` / `speech_end`. The
client owns exactly one job in this area: noticing the human started talking **while** Kira is
answering, and sending `barge` 0 ms later — see §4.5.

### 4.3 Local-first is a choice, not a fallback chain

`voice.stt` and `voice.tts` are each `local`, `remote` or `off`. If `local` is selected and the
import or binary is missing, the engine emits `stt_unavailable` / `tts_unavailable` with the exact
install line and **does not** quietly spend the user's key instead. Silent failover on a live call
spends money the user did not watch and makes the bill the discovery mechanism. `/call` shows the
same status before the call starts, so the choice is made with the facts on screen.

### 4.4 Voice turns run without tools

An `ask`-policy tool holds the stream open for a human decision that arrives with `X-Kira-Confirm`.
On a voice call the human is talking, not typing a secret; auto-allowing on voice would make a
microphone a permission bypass. So voice turns run `AgentRun` with an empty tool registry and no
approval broker — the same shape the non-streaming chat path uses. The model is told so in the
system prompt and answers "I can't use tools on a call" instead of pretending.

### 4.5 Barge-in in two stages, one debounce

Stage 1 is the client: a 20 ms analyser on the mic stream sees speech while state is
`thinking|speaking` → stop every queued `AudioBuffer` source immediately, send `barge`. Stage 2 is
the server: cancel the in-flight turn task and the TTS worker, persist what was said with
`status: "interrupted"`, emit `cancelled`, reset the VAD and resume listening on the next packet.
The client's own onset frames are not replayed: barge fires within about 60 ms of speech, so at most
one 100 ms packet is lost, and replaying the ring would risk feeding Kira's own voice back into the
microphone. Echo cancellation is the first defence against self-interruption; the 700 ms debounce
(§5.2) is the second.

### 4.6 Frames attach to the next thing said, they are not their own turn

Two alternatives were rejected: a periodic "look" turn (the model talks to itself, costs tokens,
and clutters the transcript) and holding a frame until the user types (defeats the point of a
camera). So the client keeps **one** latest frame, refreshes it every 4 s while the call is active
(one request in flight, paused when the tab is hidden), and the server attaches it to the next user
turn as an image content part. The `look` button captures now and immediately sends a text turn —
"what do you see?" — with that frame attached. A frame is cleared once used and never written to the
store.

### 4.7 Vision is declared per provider, not assumed

`Message.content` stays a `str` (`kira-engine/src/kira/types.py:17`); `Message` gains
`images: list[str]` (data URLs). All three provider kinds already build content blocks per message,
so the mapping is additive: `image_url` parts for `openai_compat`, `image` + base64 source for
`anthropic`, `inlineData` for `gemini`. A provider stanza gains `vision: true` when the user knows
their model accepts images. A turn carrying images is planned only across providers that declare
it; if none does, the images are dropped and the chain records `images_dropped` with the reason, so
the model answers ungrounded and the transcript says why.

## 5. The pipeline

```
 mic 16 kHz ─► Worklet (20 ms) ─► 100 ms frames ─► WS /v1/voice ─► VAD ─► WAV ─► STT
                                                                              │
 webcam ─► canvas 320×240 JPEG ─► latest frame (one slot) ────────────┐        │
                                                                      ▼        ▼
                                                  Router.plan(images) ─► AgentRun ─► deltas
                                                                                │
 speaker ◄─ WAV queue ◄─ audio_out ◄─ TTS worker ◄─ sentence buffer ◄────────────┘
```

### 5.1 Capture and playback (client)

- `getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true,
  channelCount: 1 } })`. Video is a separate `getUserMedia` call only when the self-view is on, so
  the mic can start without a camera prompt.
- One `AudioContext({ sampleRate: 16000 })` feeds an `AudioWorkletNode`; the worklet accumulates and
  posts a 1600-sample `Int16Array` every 100 ms. If the running context does not report 16000 Hz,
  the call refuses to start with a clear message rather than shipping a second resampler; Chromium
  and current Firefox/Safari accept the option.
- The same stream feeds an `AnalyserNode`; RMS drives the meter and stage-1 barge detection.
- Playback is a second `AudioContext` at the device rate; each `audio_out` WAV is decoded with
  `decodeAudioData` and queued; `barge`, `end call` and `turn_done` handling can stop all sources.
- Frame refresh is a client constant (4000 ms) in `frames.ts`, next to the pure due/not-due check;
  the server neither schedules captures nor knows the interval.

### 5.2 VAD (server)

`kira-engine/src/kira/voice/vad.py`, pure and unit-tested, no I/O:

- Input 20 ms frames (320 samples) of normalised float or Int16 → RMS.
- Speech starts after 3 consecutive frames above `max(vad_threshold, floor × 4)`, where `floor` is the
  minimum RMS over the last 3 s (so a noisy room raises its own bar); default `vad_threshold` 0.02.
- Speech ends after 700 ms below the bar (`voice.silence_ms`), or at 30 s (`voice.max_utterance_s`)
  whichever comes first. The 30 s is a wall clock over every frame since the utterance opened, not a sum
  of the frames that happened to be loud: audio that keeps crossing the bar without ever holding
  700 ms of silence — a fan, music bleeding through a headset — would otherwise hold an utterance open
  forever and the caller would never be answered. The utterance buffer `VoiceCall` fills is capped by
  the same arithmetic (`max_utterance_s` seconds of 16 kHz mono PCM16), as a backstop for any detector
  that fails to close.
- An utterance shorter than 300 ms is discarded with no STT call and no turn. An attempt that STT
  rejects, or that transcribes to an empty string, sends `cancelled` after the `error`: `speech_end`
  already told the client work had begun, and silence on that promise strands the screen on "thinking".
- A `barge` resets the detector: `speaking` clears, the floor window is dropped and the next packet
  starts a fresh utterance. While `speaking`, incoming audio is not fed to the detector at all.

### 5.3 Speech to text

`kira-engine/src/kira/voice/stt.py`:

- **local**: import `faster_whisper` lazily; a cached `WhisperModel(voice.stt_model, device="cpu",
  compute_type="int8", download_root=<data>/voice/models)`. The captured PCM is written to a temp
  WAV under `<data>/voice/tmp`, transcribed in `asyncio.to_thread`, and the file is deleted in a
  `finally`. First use downloads the model once — logged as a line the user can see, not silent.
- **remote**: an `openai_compat` provider named by `voice.stt_provider`; multipart
  `POST {base_url}/audio/transcriptions` with the WAV, `model=voice.stt_remote_model` (default
  `whisper-1`), `response_format=json`. The key comes from the Locker through `registry.key_for`,
  exactly like chat.
- **off**: the call is text-in, text-out; speaking produces a hint, not a turn.

### 5.4 Text to speech

`kira-engine/src/kira/voice/tts.py`:

- **local**: `asyncio.create_subprocess_exec(piper_bin, "--model", piper_model, "--output_file",
  <tmp>.wav)`, text on stdin, the WAV read back and the file deleted — a file rather than stdout so a
  Piper build that emits raw PCM cannot silently change the wire format. Killed on barge or timeout.
  Available only when both paths exist.
- **remote**: `POST {base_url}/audio/speech` with `model` (default `tts-1`), `voice` (default
  `alloy`), `input`, `response_format: "wav"`. Same key path as STT.
- The answer is synthesised **per sentence**: the delta stream is buffered and flushed at `.`, `!`,
  `?`, `…`, newline or 240 characters, whichever comes first, so the first audio starts after the
  first sentence rather than the last token. A TTS failure that turn is an `error`, not a dropped
  call — the text is already on screen.

### 5.5 The turn

1. Utterance ends → `speech_end` → STT → `transcript {final: true}`.
2. The user row is persisted (`store.add_message`, text only) and appended to the call's in-memory
   history. `hello.session_id` may name an existing session, in which case the last 12 messages are
   loaded once as context — the same "one sitting, many sessions" rule the rest of the app follows.
3. A voice system prompt is prepended: short spoken answers, no markdown, numbers written to be
   read aloud, tools are unavailable on a call.
4. `router.plan(model, mode)`, then `AgentRun` with `tools=ToolRegistry()`, `approvals=None`,
   `session_id`, and the pending frame (if any) on the last user message.
5. Deltas go to the client as `answer_delta` **and** to the sentence buffer feeding TTS.
6. Completion → assistant row persisted with provider, model, usage, chain → `turn_done` after the
   last `audio_out` is queued.
7. Barge at any point after step 4 cancels, persists `status: "interrupted"` with the text so far
   and an `aborted_mid_stream` chain record whose reason is "the user spoke over the answer".

## 6. The wire

`WS /v1/voice` (same host and port, loopback only; it mounts under the served `/v1`, so the version
middleware passes it through like any other v1 path).

**Auth.** Browsers cannot set headers on a WebSocket, so the first frame is
`{"type": "hello", "token": "…", "model": null, "mode": null, "session_id": null}`. The server
compares with `secrets.compare_digest` against `engine.token`; a wrong or missing hello within 5 s
closes with code **4401** and nothing else is read. The token never appears in the URL, so it never
appears in an access log, a referrer or a history entry. Frames are never logged.

| Client → server | Payload | Notes |
|---|---|---|
| `hello` | `token`, optional `model`, `mode`, `session_id` | first frame only; 5 s deadline |
| `audio` | `pcm`: base64 of 1600 Int16 samples | 100 ms cadence |
| `frame` | `jpeg`: base64, `mime`: `image/jpeg` | replaces the one pending frame; ≤ 512 KB decoded |
| `text` | `text` | typed fallback; same turn path, TTS still replies |
| `barge` | — | client heard speech during thinking/speaking |
| `close` | — | polite shutdown before the socket closes |

| Server → client | Payload | Notes |
|---|---|---|
| `ready` | `voice` status block, `session_id`, `limits` | after auth; no keys, no paths |
| `speech_start` | — | VAD opened |
| `speech_end` | `discarded`: bool | VAD closed; short noise sets `true` |
| `transcript` | `text`, `final` | one final per utterance |
| `thinking` | — | turn accepted |
| `answer_delta` | `text` | streamed answer |
| `audio_out` | `pcm`: base64 WAV, `seq`, `text` | one per sentence; `text` is the caption |
| `turn_done` | `session_id`, `usage`, `chain` | after last audio queued |
| `cancelled` | `reason` | barge, close, or an attempt that will not produce an answer |
| `error` | `code`, `message` | `bad_audio`, `stt_unavailable`, `stt_failed`, `tts_failed`, `no_provider`, `frame_rejected`, `voice_config` |

Limits: one in-flight turn per connection; one pending frame; 64 KB of PCM per audio packet
(two seconds at 16 kHz mono — a call sends 3.2 KB every 100 ms); 512 KB decoded per frame; 30 s
maximum utterance. The 4 s frame refresh is client-side and not a server limit.

`GET /v1/kira/voice` returns the status the `ready` frame carries, so `/call` can show the truth
before opening a socket:

```json
{
  "stt": {"mode": "local", "available": false, "detail": "faster-whisper is not installed — pip install -e \".[voice]\""},
  "tts": {"mode": "remote", "available": true, "detail": "openai · tts-1 · alloy"},
  "vision": {"provider": "openrouter", "model": "openai/gpt-4o-mini"},
  "limits": {"max_utterance_s": 30, "silence_ms": 700}
}
```

This is a new schema (`VoiceStatus`) and two new chain events (`images_attached`,
`images_dropped`). All three are additive: `API_VERSION` stays 1, `CONTRACT_VERSION` stays 2.

## 7. Configuration

A new optional block; absent keys take these defaults. Nothing secret lives here.

```yaml
voice:
  stt: local              # local | remote | off
  stt_model: base.en      # faster-whisper name, downloaded once under <data>/voice/models
  stt_provider: openai    # an openai_compat provider, used only when stt: remote
  stt_remote_model: whisper-1
  tts: local              # local | remote | off
  tts_provider: openai
  tts_model: tts-1
  tts_voice: alloy
  piper_bin: voice/piper/piper.exe
  piper_model: voice/piper/voice.onnx
  vad_threshold: 0.02
  silence_ms: 700
  max_utterance_s: 30
  temperature: 0.6
```

Provider stanzas accept `vision: true`. `SAMPLE_CONFIG` marks openrouter, anthropic and gemini with
it and leaves a comment for local vision servers. Existing configs without the key simply keep
frames on the device until the user adds it — `/call` says so.

Validation mirrors `Config`: modes in range, `silence_ms` 200–2000, `max_utterance_s` 5–120,
`temperature` 0–2, paths are strings (existence is a runtime status, not a startup error, so a
missing Piper binary does not stop chat from serving).

`kira-engine voice doctor` prints the same status the endpoint returns, plus the exact expected
paths and the two install lines (`pip install -e ".[voice]"`, Piper release page + voice file). It
never downloads the Piper binary itself. Optional dependency added to `pyproject.toml`:

```toml
[project.optional-dependencies]
voice = ["faster-whisper>=1.1"]
```

`websockets` is already in the venv (17.3, via `uvicorn[standard]`), so the endpoint adds no
dependency of its own.

## 8. Client surfaces

- `#/call` in `ROUTES` (`kira-chat/src/hash-route.ts`), a nav-rail entry with a mic glyph, and
  `CallScreen` works in both shells (the agent work panel stays; it has nothing to say about a call).
- **Pre-call**: the status from `/v1/kira/voice` as three honest rows (listen / speak / see), a
  start button disabled when both STT and TTS are `off`, and a one-line explanation of where audio
  goes when either half is remote.
- **In call**: self-view `<video muted playsinline>` (mirrored by CSS), level meter, state line
  (`listening` / `thinking` / `speaking` / `muted`), scrolling transcript with the same message
  styling as chat, chain line from `turn_done`, and buttons: mute, camera on/off, look, end call.
- **Typed fallback**: an input that sends `text` frames, so a call works with the mic off and so the
  browser pass has a deterministic path.
- `useCall` (`kira-chat/src/voice/useCall.ts`) owns the socket, capture, analyser, playback queue and
  state machine; `protocol.ts` holds the event types and guards; `frames.ts` holds the pure cadence
  decision; `capture-worklet.js` is a self-contained worklet (no imports).
- Status line for vision: "frames stay on this device" when no provider declares vision, otherwise
  "frames → provider · model"; the camera button carries the same sentence as a tooltip.

## 9. Invariants and failure handling

- No provider key, engine token or confirm secret ever reaches the client, a log line, a chain
  record or a URL. The WS token rides one frame, checked with `compare_digest`.
- Audio and frames are never written to the store or logs. The temp WAV is deleted in `finally`.
  Transcripts are ordinary chat messages; frames are not.
- `voice: off` is always a working call screen (text in, text out), never a broken one.
- A missing local package is `available: false` with a fix, not an exception at import time.
- A middle-of-answer TTS failure leaves the answer on screen; the call stays up.
- A barge persists the partial answer as `interrupted` — the transcript never claims completeness.
- Everything listens on loopback; `host` validation is unchanged.

## 10. Testing

Engine:

- `vad.py` is pure: feed synthetic frames and assert onset, offset, floor adaptation, min/max length.
- `stt.py` / `tts.py`: local paths are tested with the import/binary absent (status), and with a
  fake module/process (transcript, WAV bytes, kill-on-barge); remote paths use the existing scripted
  HTTP fake and assert multipart shape and that the key is only in the header.
- `test_message_images.py`: all three `to_wire`/`to_payload` mappings, and that a text-only message
  still serialises exactly as before.
- `test_voice_ws.py` (Starlette `TestClient` websockets): bad hello closes 4401; audio frames drive
  VAD → fake STT → fake router → fake TTS; `barge` cancels and persists `interrupted`; a frame
  attaches once and is cleared; a frame with no vision provider records `images_dropped`; a typed
  `text` frame completes a full turn with no audio in.
- `test_voice_status.py`: endpoint shape, `off` mode, missing-package detail strings, no secrets.
- Contract: `python -m kira contracts` regenerates `openapi.json`; `check-drift.mjs` stays green
  with the new schema and events.

Client:

- `protocol.test.ts`: guards reject unknown types and oversize payload fields.
- `frames.test.ts`: cadence function (due/not due, hidden tab, one-in-flight).
- `CallScreen.test.tsx`: fake WebSocket and fake media objects injected through props/params; start
  with both `off` disabled; transcript renders `answer_delta`; barge stops playback (spy); end call
  closes the socket and stops tracks.

The browser pass (`docs/qa/call-browser-pass.md`) uses Chromium with
`--use-fake-device-for-media-stream --use-fake-ui-for-media-stream` so the self-view renders a test
pattern and the mic yields a tone. The tone cannot prove transcription — with no local stage installed
the engine answers every utterance with `stt_unavailable` — so what the pass did prove is the capture
path on real browser audio: routing, the WS handshake, `hello`/`ready`, the packet cadence, VAD onset
and the 30 s cap on the browser's own recording, the commit that hands STT a wav, the typed turn with
its chain, frame cadence and the `images_dropped` refusal, the self-view, both shells, and what the
store kept. What it did not prove, and could not on this machine: any real model's accuracy, the
faster-whisper and Piper installs, `audio_out` ordering and barge-in over a *spoken* answer (both are
unit-tested instead, engine and client), a provider that declares `vision: true`, non-Chromium engines,
and a real room's echo. The uninstall-then-install check is manual and is what `voice doctor` prints.

## 11. Rollback

Everything is additive: a new route, a new endpoint, three new files under `voice/`, one new field
on `Message`, one on `ProviderConfig`, new chain events, a client route. Reverting the branch leaves
the engine and both shells exactly as they were; no store migration is required.

## 12. Milestones

1. `Message.images`, `vision` on provider config, mappings in all three kinds, tests.
2. `voice/vad.py` with its unit tests.
3. `voice/stt.py` (local + remote + off), tests.
4. `voice/tts.py` (local + remote + off), tests.
5. `voice/stack.py` (config, status, availability), `GET /v1/kira/voice`, `kira voice doctor`, tests.
6. `/v1/voice` endpoint: hello, audio, VAD loop, turn, sentence TTS, barge, frames; WS tests.
7. Contracts: `VoiceStatus`, `ProviderRow.vision`, two chain events, regenerate, drift green, TS types.
8. Client protocol + `useCall` + worklet + frames.
9. `CallScreen`, route, nav entry, tests.
10. README, PROVENANCE, ROADMAP, this spec's status line.
11. Browser pass, QA doc, findings fixed.
12. All three gates, build, merge.
