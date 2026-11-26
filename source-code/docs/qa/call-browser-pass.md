# Real-time call browser pass — 2026-10-29 (UTC)

Engine: `kira-engine/.venv/Scripts/python kira-engine/tools/kira_lab.py --port 8918 --mock-port 8998
--data-dir %TEMP%\kira-lab-call3\.kira-data` — a fresh scratch directory, a **memory** vault holding
two fake provider keys, `tools/mock_openai.py` on `http://127.0.0.1:8998/v1` offering `mini` and
`small`, and the built chat bundle at `/chat/`. The token was printed once (`5sHCqg…`, 43 characters)
and lives in `localStorage.kira.token` and nowhere else; nothing in this run touched the Credential
Locker or a real provider.

Browser: the cached Playwright Chromium (`%LOCALAPPDATA%\ms-playwright\chromium-1248\chrome-win64\chrome.exe`),
headless over raw CDP from Node 24's global `fetch` and `WebSocket`, no npm packages, launched with
`--use-fake-device-for-media-stream --use-fake-ui-for-media-stream`. **No real microphone or camera was
read**: the fake device feeds Chromium's own generated tone and a rolling colour pattern, and the fake
UI auto-grants both prompts. `Emulation.setDeviceMetricsOverride` at **1440×900** (and 720×900 for the
breakpoint), device scale 1. Screenshots `01`–`08` and `report.json` are in the pass directory.

A second script recorded the PCM the browser actually put on the wire — 382 packets, every one 4268
characters of base64, i.e. exactly 3200 bytes of 16 kHz mono Int16, 1910 VAD frames over 38.2 s — and
that recording was replayed through the engine's own `EnergyVad`. That replay is where the pass's two
real defects were found, and both are fixed before the merge. The same recording now opens an utterance
at 0.5 s, closes it at 30.5 s with `duration_ms` 30000, and reopens at 30.6 s; before the fix it opened
once at 0.5 s and never closed.

## What was driven

Stack table before anyone speaks; the same screen at 720 px; `start call` on the fake mic; 40 s of that
mic held open; `camera on` and the self-view; six seconds of frame cadence; a typed turn with a frame
waiting; `look`; `mute`; `end call`; the same route in the agent shell; then what the engine kept.

| # | Check | Observed | Verdict |
| --- | --- | --- | --- |
| 1 | The screen at rest says what the call cannot do, before anyone speaks | `.call-head h2` = `Call`, phase chip `not connected`, stack rows read `listen` → `faster-whisper is not installed — pip install -e ".[voice]"`, `speak` → `piper is not installed — put piper.exe and a voice .onnx under <data>/voice/piper (README §Voice)`, `see` → `frames stay on this device`. `start call` enabled, meter `0%`, no transcript, no error. `localStorage` = exactly `kira.base`, `kira.token`. | matched |
| 2 | The two columns collapse to one at 720 px | `grid-template-columns` went from `380px 1002.41px` at 1440 to a single `663.406px` track at 720, with `scrollWidth` 705 against a `clientWidth` of 705 — no horizontal overflow at either width. | matched |
| 3 | `hello` is the first frame and carries no session | `sent hello` (117 bytes) → `model=mini mode=AUTO`, `session_id=null`; `recv ready` (434 bytes) → `session=2051043966ac4f93 stt=local/false tts=local/false vision=null`; the chip went to `listening` on that message, not before. | matched |
| 4 | Audio is a 100 ms cadence of fixed-size packets, and the meter reads the same stream | 429 `sent audio` frames in the 40 s window, `minLen == maxLen == 4293` bytes of JSON each — one 3200-byte PCM packet and nothing else (≈10.7 packets/s); the meter went `100% 100% 9% 100% 8% 9% 9% …` as the fake tone drifted, never stuck at 0. | matched |
| 5 | A sound that never holds 700 ms of silence still closes | On the wire: `speech_start` at 4.7 s of the call, then `speech_end discarded=false` 29.9 s later — the 30 s cap, not a pause — then `recv error stt_unavailable: faster-whisper is not installed — pip install -e ".[voice]"`, then `recv cancelled reason=transcription failed`. Before the fix, the browser's own tone produced one `speech_start` and nothing else in 25 s, with the buffer at 786 KB. | matched after findings 1 and 2 |
| 6 | The self-view is a mirrored 4:3 of the fake camera, and it is not the answer | `video.readyState` 4, `640×480`, track `live`, `hidden: false`; the element box was 380×285 (4:3) and `getComputedStyle(...).transform` = `matrix(-1, 0, 0, 1, 0, 0)`. The `<video>` is never `src`-ed from the engine — the pixels stayed on the device. | matched |
| 7 | Frames come out every four seconds and nowhere else | Two `sent frame` messages in six seconds (`4090` then `4570` bytes on the wire, ≈3 kB of JPEG each), and the store kept neither: the four persisted rows contain no `/9j/`, no `data:image` and no `image/jpeg` anywhere. | matched |
| 8 | A typed turn is a turn, with a chain, even when no voice works | `sent text` `"say hello in one short sentence"` → `transcript` (final) → `thinking` → five `answer_delta` (`"mock "`, `"answer, "`, `"scripted "`, `"by "`, `"tools/mock_openai.py "`) → `turn_done` whose chain was `images_dropped,attempt,served`. Two `tts_unavailable` errors arrived — one per sentence — and the caption and transcript still completed. `.call-chain` printed `mock_one · mini`. | matched |
| 9 | `look` sends one frame and the fixed prompt | `sent frame` (2894 bytes) then `sent text` `"what do you see?"` (41 bytes); the transcript list ended as `say hello in one short sentence`, `mock answer, scripted by tools/mock_openai.py`, `what do you see?`, `mock answer, scripted by tools/mock_openai.py`. | matched |
| 10 | `end call` really ends it | Phase `call ended`, meter back to `0%`, `video.readyState` 0 with `hidden: true`, the track list empty, one `sent close`, and the socket closed. `localStorage` was still exactly `kira.base`, `kira.token`. | matched |
| 11 | The same route under the other shell | `data-shell` flipped to `agent` with the work panel present, the body measured `380px 462.406px` against the chat shell's `380px 1002.41px`, no overflow at 900 px, and the same three stack rows and heading. | matched |
| 12 | What the engine kept | One session (`2051043966ac4f93`, AUTO) with four rows and 300 tokens: `user say hello in one short sentence` / `assistant mock answer…` / `user what do you see?` / `assistant mock answer…`, both assistants `provider=mock_one model=mini status=complete`, both chains opening with `images_dropped · no provider in this mode declares vision`. **Nothing from the microphone is in the database** — 40 s of captured audio produced no row at all. | matched |

Console errors and page exceptions across the whole run: none (both arrays empty in `report.json`).

## Findings

Two were real defects, each fixed in its own commit before this document.

- **`max_utterance_s` was not a cap on the call, it was a cap on loud frames**
  ([vad.py:87](file:///D:/1.%20Ai/project-kira%20%28kimi%29/Kira/kira-engine/src/kira/voice/vad.py#L87)).
  The end condition counted only frames at or above the bar, so audio that flickers across it — a fan,
  music through a headset, Chromium's fake tone — never accumulated 30 s of *anything* and never ended.
  The pass fed the browser's own recording to the engine's own VAD: 1255 frames, 25.1 s, one
  `speech_start`, no `speech_end`, `_below` stuck at 2. The same detector on the same kind of audio now
  ends the utterance at `_open_frames == 1500`, `duration_ms` 30000.
  Guards: `test_a_sound_that_never_quiets_closes_on_the_wall_clock`,
  `test_a_room_that_never_quiets_still_gets_an_answer`.
- **…and the buffer it was filling had no size**
  ([call.py:41](file:///D:/1.%20Ai/project-kira%20%28kimi%29/Kira/kira-engine/src/kira/voice/call.py#L41)).
  `MAX_AUDIO_BYTES` caps one packet at 64 KB; the utterance it joins was uncapped and reached 786,560
  bytes — 12× the per-packet limit — while the call held a turn open it would never run. An utterance is
  now at most `max_utterance_s` seconds of PCM (960,640 bytes at the default), with the bound enforced in
  `_feed` as a backstop for any future detector that fails to close. Guard:
  `test_the_utterance_buffer_stops_at_its_cap`.
- **A failed transcription left the screen on "thinking" over a call that had gone back to listening**
  ([call.py:186](file:///D:/1.%20Ai/project-kira%20%28kimi%29/Kira/kira-engine/src/kira/voice/call.py#L186)).
  `speech_end` promises the client work has begun; when STT then raised, or transcribed a cough to an
  empty string, nothing else was ever sent. In the browser the only escape was the fake microphone
  barging on itself — which is what the first run did, and why it looked alive. A failed or empty
  attempt now sends `cancelled`, the one message the client already reads as "back to listening".
  Guards: `test_a_transcription_that_fails_ends_the_attempt`,
  `test_an_utterance_that_transcribes_to_nothing_ends_the_attempt`.

Things the pass proved that are not defects, but are worth writing down:

- **The lab proves the plumbing, not the voices.** Every frame above crossed a real WebSocket from a
  real browser microphone, and not one word was transcribed or spoken: both stages report `available:
  false`, and `GET /v1/kira/voice` says so in the same words the screen prints. The call is honest about
  being mute, which is the behaviour the spec asked for.
- **A room that never quiets now costs one wasted transcription every 30 s.** That is what a cap buys:
  the engine reopens on the next flicker (two `speech_start` in the 40 s window) instead of jamming.
  The alternative — stop opening — is what the noise floor already does for a *steady* sound: after a
  `barge` or an end the floor window is dropped, so a source as loud as the one that just ended does not
  reopen until something quieter is heard (`test_a_closed_utterance_waits_for_a_quieter_frame_before_it_reopens`).
- **The vision gate is visible from the client side.** Both assistant rows begin with
  `images_dropped · no provider in this mode declares vision`, because the lab's providers are not
  declared `vision: true`. Frames still travelled the wire — which is the point: a frame is taken, sent
  and refused, never kept.
- **`tts_unavailable` arrives once per sentence, not once per turn.** Two sentences spoke, so two errors
  came back. The answer still read on screen because the caption does not depend on TTS.
- **Every call opens a session row** before anything is said, so an abandoned call leaves an empty
  session behind. That is `store.create_session` at `ready`; the Sessions screen deletes them one by one.
- **The AudioWorklet ships as a data URL.** `dist` has no separate worklet file, so nothing can 404 at
  `addModule()` — but that also means the module is invisible to a file listing, and `start call` is the
  only thing that proves it loaded.

Not a product defect: the pass script's own agent-shell check read `shell: "chat"` on its first run,
because `Page.navigate` to a URL differing only by hash does not reload and the app reads `kira.shell`
once at boot. `goto(…, { reload: true })` fixed the measurement; row 11 is the corrected one.

## Not exercised, and why

- **A real whisper and a real Piper.** Neither is installed on this machine, so no audio was ever
  transcribed and no answer was ever spoken. Everything past the STT boundary — the transcript's
  accuracy, sentence TTS latency, playback — is unverified here; `voice doctor` is how a user checks it
  on their own machine.
- **Barge-in over a spoken answer.** The client only interrupts audio it can hear, and with no TTS there
  was no audio to interrupt. The `barge` message, the `cancelled` reply and the `interrupted` row are
  covered by `test_voice_call.py` and `useCall.test.tsx`, not by this pass.
- **A declared-vision provider.** The lab's mock does not set `vision: true`, so the pass could only
  prove the refusal path (`images_dropped`). The attach path is proved by
  `test_a_frame_to_a_vision_provider_is_attached_and_sent_once`.
- **Non-Chromium engines.** Safari and Firefox disagree about `AudioContext({sampleRate: 16000})`,
  module-worklet URLs and `getUserMedia` constraints; none of that was touched.
- **A real room's echo.** Chromium's fake device has no speaker to cancel, so `echoCancellation` was
  asked for and never exercised. This is the case where the client-side barge threshold matters most.
- **Widths below 720 px**, and a phone's portrait orientation, where the self-view and the transcript
  share one column.
- **A >30 s monologue**, because the engine is deliberately deaf while thinking and speaking; the cap
  only ever applies to audio captured while listening.
