# Kira realtime call (sub-project 6) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A working voice call (mic → VAD → STT → router → agent turn → TTS → speaker, with barge-in) and a camera self-view whose frames attach to the next spoken turn, local-first with BYOK fallback.

**Architecture:** One new loopback WebSocket (`/v1/voice`) in the existing FastAPI app; audio is PCM16/16 kHz in 100 ms packets, answers come back as text plus one WAV per sentence. The turn reuses `Router.plan` and `AgentRun` with tools off. Vision is additive: `Message.images` maps to image parts in all three provider kinds and is only sent to providers whose YAML stanza says `vision: true`. The client gets a new `#/call` screen.

**Tech Stack:** Python 3.12 / FastAPI (WebSocket via `websockets`, already installed 17.3), faster-whisper optional extra, Piper binary (detected, never installed by the engine), React 19 + TypeScript + Vite, Vitest/jsdom.

**Spec:** `docs/specs/2026-10-28-kira-realtime-call-design.md` — read it before starting; every task below implements a section of it.

## Global Constraints

- BYOK only. No key ever reaches the browser, a log line, a chain record, a URL or a test fixture's assertion message.
- Engine token is checked on the first WS frame with `secrets.compare_digest`; wrong/missing hello closes with code 4401. The token never goes in the URL.
- Audio and frames are never persisted. Transcripts are ordinary chat messages. Temp WAVs are deleted in `finally`.
- `host` stays loopback; never add `0.0.0.0`.
- `API_VERSION` stays 1, `CONTRACT_VERSION` stays 2 — everything here is additive.
- Never run `git config`. Commit with `git -c user.name="Kira" -c user.email="kira@localhost" commit -m "..."`.
- Live provider calls in tests only through the scripted `harness.script`; no real network.
- Client may only use `localStorage` keys `kira.base`, `kira.token`, `kira.shell`, `kira.theme`, `kira.look`, `kira.sidebar`. The call keeps nothing there.
- Commands run from `D:/1. Ai/project-kira (kimi)/Kira`. Engine venv: `kira-engine/.venv/Scripts/python`.

---

### Task 1: Vision plumbing — `Message.images`, `ProviderConfig.vision`, three wire mappings

**Files:**
- Modify: `kira-engine/src/kira/types.py:17-22`
- Modify: `kira-engine/src/kira/config.py:19-41`
- Modify: `kira-engine/src/kira/providers/base.py`
- Modify: `kira-engine/src/kira/providers/openai_compat.py:13-30`
- Modify: `kira-engine/src/kira/providers/anthropic.py:27-47`
- Modify: `kira-engine/src/kira/providers/gemini.py:20-52`
- Test: `kira-engine/tests/test_message_images.py`

**Interfaces:**
- Produces: `Message(role, content="", tool_calls=[], tool_call_id=None, name=None, images: list[str] = [])` where each image is a `data:image/...;base64,...` URL.
- Produces: `ProviderConfig(..., vision: bool = False)`.
- Produces: `split_data_url(value: str) -> tuple[str, str]` in `providers/base.py` (media type, base64 payload).

- [x] **Step 1: Write the failing test**

```python
from __future__ import annotations

from kira.providers import anthropic, gemini, openai_compat
from kira.providers.base import split_data_url
from kira.config import ProviderConfig
from kira.types import GenRequest, Message

DATA = "data:image/jpeg;base64,/9j/AAAA"


def test_split_data_url():
    assert split_data_url(DATA) == ("image/jpeg", "/9j/AAAA")


def test_openai_text_only_stays_a_string():
    wire = openai_compat.to_wire([Message(role="user", content="hi")])
    assert wire == [{"role": "user", "content": "hi"}]


def test_openai_attaches_image_parts():
    wire = openai_compat.to_wire([Message(role="user", content="look", images=[DATA])])
    assert wire[0]["content"] == [
        {"type": "text", "text": "look"},
        {"type": "image_url", "image_url": {"url": DATA}},
    ]


def test_anthropic_attaches_image_blocks():
    wire = anthropic.to_wire([Message(role="user", content="look", images=[DATA])])
    assert wire[0]["content"] == [
        {"type": "text", "text": "look"},
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "/9j/AAAA"}},
    ]


def test_gemini_attaches_inline_data():
    payload = gemini.to_payload(GenRequest(model="gemini-mock", messages=[Message(role="user", content="look", images=[DATA])]))
    assert payload["contents"][0]["parts"] == [
        {"text": "look"},
        {"inlineData": {"mimeType": "image/jpeg", "data": "/9j/AAAA"}},
    ]


def test_vision_defaults_off():
    provider = ProviderConfig(name="p", kind="openai_compat", base_url="https://p.invalid/v1", models=["m"])
    assert provider.vision is False
```

- [x] **Step 2: Run it and watch it fail**

Run: `cd kira-engine && .venv/Scripts/python -m pytest tests/test_message_images.py -q`
Expected: collection error — `Message` has no `images`, `split_data_url` does not exist.

- [x] **Step 3: Implement**

`types.py`:
```python
@dataclass
class Message:
    role: str  # system | user | assistant | tool
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None
    name: str | None = None
    #: Data URLs for a vision model. Never persisted; the call attaches them to one turn.
    images: list[str] = field(default_factory=list)
```

`config.py` — add to `ProviderConfig` after `monthly_token_cap`:
```python
    #: True only when the user's stanza says the chosen model accepts image parts.
    vision: bool = False
```
and in `_provider_from`: `vision=bool(raw.get("vision", False)),`.

`providers/base.py` — append:
```python
def split_data_url(value: str) -> tuple[str, str]:
    """`data:image/jpeg;base64,AAAA` -> (`image/jpeg`, `AAAA`). Raises ValueError on anything else."""
    header, _, payload = value.partition(",")
    if not header.startswith("data:") or ";base64" not in header or not payload:
        raise ValueError("image must be a base64 data URL")
    return header[len("data:"):].split(";", 1)[0], payload
```

`openai_compat.to_wire` — replace the `item` construction:
```python
        content: object = m.content or ""
        if m.images:
            content = [{"type": "text", "text": m.content or ""}] + [
                {"type": "image_url", "image_url": {"url": image}} for image in m.images
            ]
        item: dict = {"role": m.role, "content": content}
```

`anthropic.to_wire` — after the `if m.content:` block:
```python
        for image in m.images:
            media_type, data = split_data_url(image)
            blocks.append({"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}})
```
(import `split_data_url` from `.base`).

`gemini.to_payload` — after `if m.content:`:
```python
        for image in m.images:
            media_type, data = split_data_url(image)
            parts.append({"inlineData": {"mimeType": media_type, "data": data}})
```
(import `split_data_url` from `.base`).

- [x] **Step 4: Run tests**

Run: `cd kira-engine && .venv/Scripts/python -m pytest tests/test_message_images.py tests/test_providers.py -q`
Expected: PASS (existing provider tests prove text-only wire bodies did not change).

- [x] **Step 5: Commit**

```bash
git add kira-engine/src/kira/types.py kira-engine/src/kira/config.py kira-engine/src/kira/providers kira-engine/tests/test_message_images.py
git -c user.name="Kira" -c user.email="kira@localhost" commit -m "feat(engine): attach images to messages for vision-capable providers"
```

---

### Task 2: Energy VAD

**Files:**
- Create: `kira-engine/src/kira/voice/__init__.py` (empty)
- Create: `kira-engine/src/kira/voice/errors.py`
- Create: `kira-engine/src/kira/voice/vad.py`
- Test: `kira-engine/tests/test_voice_vad.py`

**Interfaces:**
- Produces: `VoiceError(code: str, message: str)` with `.code`, `.message`.
- Produces: `EnergyVad(VadConfig())` with `push(frame: bytes) -> list[VadEvent]`, `reset()`, `speaking: bool`.
- `VadEvent(kind: str, discarded: bool = False, duration_ms: int = 0)`, kind is `"start"` or `"end"`.
- Frames are exactly 640 bytes (320 Int16 samples = 20 ms at 16 kHz).

- [x] **Step 1: Write the failing test**

```python
from __future__ import annotations

import struct

from kira.voice.vad import EnergyVad, VadConfig

LOUD = struct.pack("<320h", *([8192] * 320))
QUIET = struct.pack("<320h", *([0] * 320))


def feed(vad, frame, times):
    events = []
    for _ in range(times):
        events.extend(vad.push(frame))
    return events


def test_onset_needs_three_frames_and_offset_needs_seven_hundred_ms():
    vad = EnergyVad(VadConfig(threshold=0.02, silence_ms=700))
    assert feed(vad, QUIET, 150) == []          # 3 s of floor
    assert [e.kind for e in feed(vad, LOUD, 2)] == []
    assert [e.kind for e in feed(vad, LOUD, 1)] == ["start"]
    assert vad.speaking
    assert feed(vad, LOUD, 14) == []            # 300 ms of speech
    events = feed(vad, QUIET, 35)               # 700 ms of silence
    assert [e.kind for e in events] == ["end"]
    assert events[0].discarded is False
    assert events[0].duration_ms == 17 * 20     # 3 onset frames + 14 loud; silence is not speech


def test_a_short_burst_is_discarded():
    vad = EnergyVad(VadConfig(threshold=0.02, silence_ms=700))
    feed(vad, QUIET, 150)
    feed(vad, LOUD, 3)
    feed(vad, QUIET, 34)
    events = feed(vad, QUIET, 1)
    assert [e.kind for e in events] == ["end"]
    assert events[0].discarded is True


def test_max_utterance_ends_on_its_own():
    vad = EnergyVad(VadConfig(threshold=0.02, max_utterance_s=1))
    feed(vad, QUIET, 150)
    feed(vad, LOUD, 3)
    events = feed(vad, LOUD, 47)
    assert [e.kind for e in events] == ["end"]
    assert events[0].duration_ms == 1000


def test_noise_floor_raises_the_bar():
    vad = EnergyVad(VadConfig(threshold=0.02))
    hiss = struct.pack("<320h", *([1000] * 320))    # rms ~0.03, so the bar lifts to ~0.12
    louder = struct.pack("<320h", *([2500] * 320))  # rms ~0.08: over the config floor, under the room
    feed(vad, hiss, 150)
    assert feed(vad, louder, 10) == []
    assert not vad.speaking
    assert [e.kind for e in feed(vad, LOUD, 3)] == ["start"]


def test_reset_clears_the_utterance():
    vad = EnergyVad(VadConfig(threshold=0.02))
    feed(vad, QUIET, 150)
    feed(vad, LOUD, 3)
    assert vad.speaking
    vad.reset()
    assert not vad.speaking
    assert feed(vad, QUIET, 1) == []
```

Note on frame counting: `duration_ms` reports speech, not wall clock. `_speech_frames` starts at 3 when `speaking` flips (all three onset frames were speech) and increments only on frames at or above the bar; trailing silence and mid-utterance gaps are excluded. So the first test ends at 3 + 14 = 17 frames = 340 ms, and the max-utterance test ends at 3 + 47 = 50 frames = 1000 ms. The exact code below does this; do not "fix" it to count silent frames.

- [x] **Step 2: Run it and watch it fail**

Run: `cd kira-engine && .venv/Scripts/python -m pytest tests/test_voice_vad.py -q`
Expected: `ModuleNotFoundError: kira.voice`.

- [x] **Step 3: Implement**

`voice/errors.py`:
```python
from __future__ import annotations


class VoiceError(Exception):
    """A voice-stage failure with a code the call screen can show. Never carries audio or keys."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
```

`voice/vad.py`:
```python
from __future__ import annotations

import math
from array import array
from collections import deque
from dataclasses import dataclass

FRAME_MS = 20
SAMPLE_RATE = 16000
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000  # 320
FRAME_BYTES = FRAME_SAMPLES * 2                 # 640
ONSET_FRAMES = 3
FLOOR_WINDOW = 3000 // FRAME_MS                 # keep three seconds of listening audio


@dataclass
class VadConfig:
    threshold: float = 0.02
    silence_ms: int = 700
    max_utterance_s: int = 30
    min_speech_ms: int = 300


@dataclass
class VadEvent:
    kind: str                    # start | end
    discarded: bool = False
    duration_ms: int = 0


def _rms(frame: bytes) -> float:
    samples = array("h")
    samples.frombytes(frame)
    if not samples:
        return 0.0
    total = sum(sample * sample for sample in samples)
    return math.sqrt(total / len(samples)) / 32768.0


class EnergyVad:
    """RMS gate over 20 ms frames. Every decision is a frame count so the tests can read them."""

    def __init__(self, config: VadConfig | None = None) -> None:
        self.config = config or VadConfig()
        self._floor: deque[float] = deque(maxlen=FLOOR_WINDOW)
        self.speaking = False
        self._above = 0
        self._below = 0
        self._speech_frames = 0

    def push(self, frame: bytes) -> list[VadEvent]:
        value = _rms(frame)
        if self.speaking:
            return self._push_speaking(frame, value)
        # The floor is the quietest recent frame, so a hissy room lifts its own bar. A full 3 s
        # window is not required: an empty deque means "use the config threshold".
        self._floor.append(value)
        bar = max(self.config.threshold, min(self._floor) * 4)
        self._above = self._above + 1 if value >= bar else 0
        if self._above < ONSET_FRAMES:
            return []
        self.speaking = True
        self._above = 0
        self._below = 0
        self._speech_frames = ONSET_FRAMES
        return [VadEvent("start")]

    def _push_speaking(self, frame: bytes, value: float) -> list[VadEvent]:
        bar = max(self.config.threshold, (min(self._floor) if self._floor else value) * 4)
        if value >= bar:
            self._speech_frames += 1
            self._below = 0
        else:
            self._below += 1
        duration_ms = self._speech_frames * FRAME_MS
        if duration_ms >= self.config.max_utterance_s * 1000:
            return [self._end(duration_ms)]
        if self._below >= self.config.silence_ms // FRAME_MS:
            return [self._end(duration_ms)]
        return []

    def _end(self, duration_ms: int) -> VadEvent:
        self.speaking = False
        self._below = 0
        self._floor.clear()
        return VadEvent("end", discarded=duration_ms < self.config.min_speech_ms, duration_ms=duration_ms)

    def reset(self) -> None:
        self.speaking = False
        self._above = self._below = self._speech_frames = 0
        self._floor.clear()
```

- [x] **Step 4: Run tests**

Run: `cd kira-engine && .venv/Scripts/python -m pytest tests/test_voice_vad.py -q`
Expected: PASS. If a duration assertion is off by a frame, re-derive the count from `_speech_frames` (onset 3 + above-bar frames only) rather than loosening the assertion.

- [x] **Step 5: Commit**

```bash
git add kira-engine/src/kira/voice kira-engine/tests/test_voice_vad.py
git -c user.name="Kira" -c user.email="kira@localhost" commit -m "feat(engine): energy VAD with adaptive floor and honest utterance bounds"
```

---

### Task 3: Speech to text (local, remote, off)

**Files:**
- Create: `kira-engine/src/kira/voice/wav.py`
- Create: `kira-engine/src/kira/voice/stt.py`
- Test: `kira-engine/tests/test_voice_stt.py`

**Interfaces:**
- Consumes: `VoiceError`.
- Produces: `pcm_to_wav(pcm: bytes, sample_rate: int = 16000) -> bytes` (16-bit mono).
- Produces: `SpeechToText` protocol: `mode: str`, `available: bool`, `detail: str`, `async transcribe(wav: bytes) -> str`.
- Produces: `LocalStt(model_name: str, root: Path)`, `RemoteStt(provider, base_url, model, api_key, client, timeout_s=60.0)`, `UnavailableStt(mode, detail)`, `OffStt()`.

- [x] **Step 1: Write the failing test**

```python
from __future__ import annotations

import asyncio
import io
import wave

import httpx
import pytest

from kira.voice.stt import LocalStt, OffStt, RemoteStt, UnavailableStt
from kira.voice.errors import VoiceError
from kira.voice.wav import pcm_to_wav

PCM = b"\x00\x01" * 1600


def test_pcm_to_wav_roundtrip():
    data = pcm_to_wav(PCM)
    with wave.open(io.BytesIO(data)) as wav:
        assert (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) == (1, 2, 16000)
        assert wav.readframes(10**9) == PCM


def test_local_reports_the_install_line_when_missing(tmp_path):
    stt = LocalStt("base.en", tmp_path)
    # faster-whisper is not a test dependency, so this is the branch CI always sees.
    assert stt.available is False
    assert 'pip install -e ".[voice]"' in stt.detail
    with pytest.raises(VoiceError) as caught:
        asyncio.run(stt.transcribe(pcm_to_wav(PCM)))
    assert caught.value.code == "stt_unavailable"


def test_off_says_so():
    with pytest.raises(VoiceError) as caught:
        asyncio.run(OffStt().transcribe(b""))
    assert caught.value.code == "stt_off"


def test_remote_posts_multipart_and_reads_text():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = request.content
        return httpx.Response(200, json={"text": " hello there "})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    stt = RemoteStt("openai", "https://openai.invalid/v1", "whisper-1", "sk-test", client)
    assert asyncio.run(stt.transcribe(pcm_to_wav(PCM))) == "hello there"
    assert seen["url"] == "https://openai.invalid/v1/audio/transcriptions"
    assert seen["auth"] == "Bearer sk-test"
    assert b'name="model"' in seen["body"] and b"whisper-1" in seen["body"]
    assert b"audio/wav" in seen["body"] or b'filename="utterance.wav"' in seen["body"]


def test_remote_failure_is_a_voice_error():
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(401, json={})))
    stt = RemoteStt("openai", "https://openai.invalid/v1", "whisper-1", "sk-test", client)
    with pytest.raises(VoiceError) as caught:
        asyncio.run(stt.transcribe(b"RIFF"))
    assert caught.value.code == "stt_failed"
    assert "401" in caught.value.message


def test_unavailable_carries_its_reason():
    stt = UnavailableStt("remote", "provider 'openai' has no key in the Locker")
    assert stt.available is False
    with pytest.raises(VoiceError) as caught:
        asyncio.run(stt.transcribe(b""))
    assert caught.value.code == "stt_unavailable"
```

- [x] **Step 2: Run it and watch it fail**

Run: `cd kira-engine && .venv/Scripts/python -m pytest tests/test_voice_stt.py -q`
Expected: `ImportError: cannot import name 'pcm_to_wav'`.

- [x] **Step 3: Implement**

`voice/wav.py`:
```python
from __future__ import annotations

import io
import wave


def pcm_to_wav(pcm: bytes, sample_rate: int = 16000) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(sample_rate)
        out.writeframes(pcm)
    return buffer.getvalue()
```

`voice/stt.py`:
```python
from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from typing import Protocol
from uuid import uuid4

import httpx

from .errors import VoiceError


class SpeechToText(Protocol):
    mode: str
    available: bool
    detail: str

    async def transcribe(self, wav: bytes) -> str: ...


class LocalStt:
    """faster-whisper on the CPU. Imported lazily so a machine without the extra still serves chat."""

    mode = "local"

    def __init__(self, model_name: str, root: Path) -> None:
        self.model_name = model_name
        self.root = root
        self._model = None
        (root / "models").mkdir(parents=True, exist_ok=True)
        (root / "tmp").mkdir(parents=True, exist_ok=True)

    @property
    def available(self) -> bool:
        return importlib.util.find_spec("faster_whisper") is not None

    @property
    def detail(self) -> str:
        if not self.available:
            return 'faster-whisper is not installed — pip install -e ".[voice]"'
        return f"faster-whisper · {self.model_name}"

    def _load(self):
        from faster_whisper import WhisperModel

        return WhisperModel(
            self.model_name,
            device="cpu",
            compute_type="int8",
            download_root=str(self.root / "models"),
        )

    def _run(self, path: Path) -> str:
        model = self._model or self._load()
        self._model = model
        segments, _info = model.transcribe(str(path), beam_size=1, vad_filter=False)
        return " ".join(segment.text.strip() for segment in segments).strip()

    async def transcribe(self, wav: bytes) -> str:
        if not self.available:
            raise VoiceError("stt_unavailable", self.detail)
        path = self.root / "tmp" / f"{uuid4().hex}.wav"
        path.write_bytes(wav)
        try:
            return await asyncio.to_thread(self._run, path)
        finally:
            path.unlink(missing_ok=True)


class RemoteStt:
    """An OpenAI-compatible transcription endpoint, with the user's own key from the Locker."""

    mode = "remote"

    def __init__(
        self,
        provider: str,
        base_url: str,
        model: str,
        api_key: str,
        client: httpx.AsyncClient,
        timeout_s: float = 60.0,
    ) -> None:
        self.provider = provider
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.client = client
        self.timeout_s = timeout_s
        self.available = True

    @property
    def detail(self) -> str:
        return f"{self.provider} · {self.model}"

    async def transcribe(self, wav: bytes) -> str:
        response = await self.client.post(
            f"{self.base_url}/audio/transcriptions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            files={"file": ("utterance.wav", wav, "audio/wav")},
            data={"model": self.model, "response_format": "json"},
            timeout=self.timeout_s,
        )
        if response.status_code >= 400:
            raise VoiceError("stt_failed", f"{self.provider} transcription failed: HTTP {response.status_code}")
        return str((response.json() or {}).get("text") or "").strip()


class UnavailableStt:
    """A configured engine that cannot run: keeps the reason on screen instead of guessing."""

    available = False

    def __init__(self, mode: str, detail: str) -> None:
        self.mode = mode
        self.detail = detail

    async def transcribe(self, wav: bytes) -> str:
        raise VoiceError("stt_unavailable", self.detail)


class OffStt:
    mode = "off"
    available = False
    detail = "listening is off for this call"

    async def transcribe(self, wav: bytes) -> str:
        raise VoiceError("stt_off", self.detail)
```

- [x] **Step 4: Run tests**

Run: `cd kira-engine && .venv/Scripts/python -m pytest tests/test_voice_stt.py -q`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add kira-engine/src/kira/voice/wav.py kira-engine/src/kira/voice/stt.py kira-engine/tests/test_voice_stt.py
git -c user.name="Kira" -c user.email="kira@localhost" commit -m "feat(engine): STT stage with local faster-whisper and BYOK transcription"
```

---

### Task 4: Text to speech (local Piper, remote, off) and sentence splitting

**Files:**
- Create: `kira-engine/src/kira/voice/tts.py`
- Test: `kira-engine/tests/test_voice_tts.py`

**Interfaces:**
- Produces: `split_sentences(text: str) -> tuple[list[str], str]` — complete sentences, remainder.
- Produces: `TextToSpeech` protocol: `mode`, `available`, `detail`, `async speak(text) -> bytes` (WAV).
- Produces: `LocalTts(piper_bin: Path, piper_model: Path, tmp_dir: Path, timeout_s=60.0, *, prefix: tuple[str, ...] = ())`, `RemoteTts(provider, base_url, model, voice, api_key, client, timeout_s=60.0)`, `UnavailableTts`, `OffTts`.

- [x] **Step 1: Write the failing test**

```python
from __future__ import annotations

import asyncio
import json
import sys

import httpx
import pytest

from kira.voice.errors import VoiceError
from kira.voice.tts import LocalTts, OffTts, RemoteTts, UnavailableTts, split_sentences


def test_split_sentences_keeps_the_tail():
    complete, rest = split_sentences("Hi. How are you? I am fine")
    assert complete == ["Hi.", "How are you?"]
    assert rest == " I am fine"


def test_split_long_run_without_punctuation():
    complete, rest = split_sentences("x" * 500)
    assert [len(chunk) for chunk in complete] == [240, 240]
    assert rest == "x" * 20


def test_local_reports_missing_piper(tmp_path):
    tts = LocalTts(tmp_path / "piper.exe", tmp_path / "voice.onnx", tmp_path)
    assert tts.available is False
    assert "piper" in tts.detail


def test_local_runs_the_binary_and_reads_the_wav(tmp_path):
    script = tmp_path / "fake_piper.py"
    script.write_text(
        "import sys, wave\n"
        "out = sys.argv[sys.argv.index('--output_file') + 1]\n"
        "sys.stdin.read()\n"
        "with wave.open(out, 'wb') as w:\n"
        "    w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)\n"
        "    w.writeframes(b'\\x00\\x01' * 160)\n"
    )
    model = tmp_path / "voice.onnx"
    model.write_bytes(b"not-a-real-voice")
    tts = LocalTts(script, model, tmp_path, prefix=(sys.executable,))
    # The argv shape is Piper's: <bin> --model <voice> --output_file <tmp>, with the text on stdin.
    wav = asyncio.run(tts.speak("hello"))
    assert wav.startswith(b"RIFF")
    assert not list(tmp_path.glob("*.wav"))


def test_remote_posts_json_and_reads_wav():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["json"] = request.read()
        return httpx.Response(200, content=b"RIFFxxxx", headers={"content-type": "audio/wav"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    tts = RemoteTts("openai", "https://openai.invalid/v1", "tts-1", "alloy", "sk-test", client)
    assert asyncio.run(tts.speak("hello")) == b"RIFFxxxx"
    assert seen["url"].endswith("/audio/speech")
    assert seen["auth"] == "Bearer sk-test"
    assert json.loads(seen["json"]) == {
        "model": "tts-1",
        "voice": "alloy",
        "input": "hello",
        "response_format": "wav",
    }


def test_remote_failure_is_a_voice_error():
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(500, json={})))
    tts = RemoteTts("openai", "https://openai.invalid/v1", "tts-1", "alloy", "sk-test", client)
    with pytest.raises(VoiceError) as caught:
        asyncio.run(tts.speak("hello"))
    assert caught.value.code == "tts_failed"


def test_local_failure_reports_the_binarys_own_words(tmp_path):
    script = tmp_path / "broken_piper.py"
    script.write_text("import sys\nsys.stderr.write('model file is corrupt')\nsys.exit(3)\n")
    model = tmp_path / "voice.onnx"
    model.write_bytes(b"not-a-real-voice")
    tts = LocalTts(script, model, tmp_path, prefix=(sys.executable,))
    with pytest.raises(VoiceError) as caught:
        asyncio.run(tts.speak("hello"))
    assert caught.value.code == "tts_failed"
    assert "corrupt" in caught.value.message
    assert not list(tmp_path.glob("*.wav"))


def test_a_failure_message_never_carries_the_key():
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(403, json={})))
    tts = RemoteTts("openai", "https://openai.invalid/v1", "tts-1", "alloy", "sk-secret-value", client)
    with pytest.raises(VoiceError) as caught:
        asyncio.run(tts.speak("hello"))
    assert "sk-secret-value" not in caught.value.message


def test_unavailable_carries_its_reason():
    tts = UnavailableTts("remote", "provider 'openai' has no key in the Locker")
    assert tts.available is False
    with pytest.raises(VoiceError) as caught:
        asyncio.run(tts.speak("hi"))
    assert caught.value.code == "tts_unavailable"


def test_off_says_so():
    with pytest.raises(VoiceError) as caught:
        asyncio.run(OffTts().speak("hi"))
    assert caught.value.code == "tts_off"
```

Note for the local tests: `prefix=(sys.executable,)` runs the fake script as if it were the binary, so
the argv the child sees is exactly Piper's shape (`<bin> --model <voice> --output_file <tmp>`) with the
text on stdin. The real Piper install passes no prefix. Temp WAVs are asserted away — `speak()` cleans
up on both the success and the failure path.

- [x] **Step 2: Run it and watch it fail**

Run: `cd kira-engine && .venv/Scripts/python -m pytest tests/test_voice_tts.py -q`
Expected: `ImportError: cannot import name 'split_sentences'`.

- [x] **Step 3: Implement**

`voice/tts.py`:
```python
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Protocol
from uuid import uuid4

import httpx

from .errors import VoiceError

TERMINATORS = ".!?…\n"
CHUNK_CHARS = 240


def split_sentences(text: str) -> tuple[list[str], str]:
    """Complete sentences and the tail not yet safe to speak."""
    complete: list[str] = []
    buffer = ""
    for char in text:
        buffer += char
        if char in TERMINATORS and len(buffer.strip()) >= 2:
            complete.append(buffer.strip())
            buffer = ""
        elif len(buffer) >= CHUNK_CHARS:
            complete.append(buffer.strip())
            buffer = ""
    return complete, buffer


class TextToSpeech(Protocol):
    mode: str
    available: bool
    detail: str

    async def speak(self, text: str) -> bytes: ...


class LocalTts:
    """Piper as an external binary: argv only, never imported, never installed by the engine.

    `prefix` exists for one reason: a voice can also be reached as `python -m piper`, and a test can
    run its fake binary through the interpreter. The argv shape Piper itself takes is unchanged.
    """

    mode = "local"

    def __init__(
        self,
        piper_bin: Path,
        piper_model: Path,
        tmp_dir: Path,
        timeout_s: float = 60.0,
        *,
        prefix: tuple[str, ...] = (),
    ) -> None:
        self.piper_bin = piper_bin
        self.piper_model = piper_model
        self.tmp_dir = tmp_dir
        self.timeout_s = timeout_s
        self.prefix = prefix
        tmp_dir.mkdir(parents=True, exist_ok=True)

    def _argv(self, out: Path) -> list[str]:
        return [*self.prefix, str(self.piper_bin), "--model", str(self.piper_model), "--output_file", str(out)]

    @property
    def available(self) -> bool:
        return self.piper_bin.is_file() and self.piper_model.is_file()

    @property
    def detail(self) -> str:
        if not self.available:
            return (
                "piper is not installed — put piper.exe and a voice .onnx under "
                "<data>/voice/piper (README §Voice)"
            )
        return f"piper · {self.piper_model.stem}"

    async def speak(self, text: str) -> bytes:
        if not self.available:
            raise VoiceError("tts_unavailable", self.detail)
        out = self.tmp_dir / f"{uuid4().hex}.wav"
        process = await asyncio.create_subprocess_exec(
            *self._argv(out),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, stderr = await asyncio.wait_for(process.communicate(text.encode("utf-8")), self.timeout_s)
        except asyncio.CancelledError:
            process.kill()
            raise
        except asyncio.TimeoutError as exc:
            process.kill()
            raise VoiceError("tts_failed", "piper timed out") from exc
        try:
            if process.returncode != 0 or not out.exists():
                detail = stderr.decode("utf-8", "replace").strip()[:200] or f"exit {process.returncode}"
                raise VoiceError("tts_failed", f"piper failed: {detail}")
            wav = out.read_bytes()
            if not wav:
                raise VoiceError("tts_failed", "piper produced no audio")
            return wav
        finally:
            out.unlink(missing_ok=True)


class RemoteTts:
    mode = "remote"

    def __init__(
        self,
        provider: str,
        base_url: str,
        model: str,
        voice: str,
        api_key: str,
        client: httpx.AsyncClient,
        timeout_s: float = 60.0,
    ) -> None:
        self.provider = provider
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.voice = voice
        self.api_key = api_key
        self.client = client
        self.timeout_s = timeout_s
        self.available = True

    @property
    def detail(self) -> str:
        return f"{self.provider} · {self.model} · {self.voice}"

    async def speak(self, text: str) -> bytes:
        try:
            response = await self.client.post(
                f"{self.base_url}/audio/speech",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": self.model, "voice": self.voice, "input": text, "response_format": "wav"},
                timeout=self.timeout_s,
            )
        except httpx.HTTPError as exc:
            raise VoiceError("tts_failed", f"{self.provider} speech is unreachable: {type(exc).__name__}") from exc
        if response.status_code >= 400 or not response.content:
            # The status is the whole story: neither the key nor the provider body crosses into a message.
            raise VoiceError("tts_failed", f"{self.provider} speech failed: HTTP {response.status_code}")
        return response.content


class UnavailableTts:
    available = False

    def __init__(self, mode: str, detail: str) -> None:
        self.mode = mode
        self.detail = detail

    async def speak(self, text: str) -> bytes:
        raise VoiceError("tts_unavailable", self.detail)


class OffTts:
    mode = "off"
    available = False
    detail = "speaking is off for this call"

    async def speak(self, text: str) -> bytes:
        raise VoiceError("tts_off", self.detail)
```

- [x] **Step 4: Run tests**

Run: `cd kira-engine && .venv/Scripts/python -m pytest tests/test_voice_tts.py -q`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add kira-engine/src/kira/voice/tts.py kira-engine/tests/test_voice_tts.py
git -c user.name="Kira" -c user.email="kira@localhost" commit -m "feat(engine): TTS stage with Piper, BYOK speech and sentence chunking"
```

---

### Task 5: Voice config, stack status, read endpoint, `voice doctor`

**Files:**
- Modify: `kira-engine/src/kira/config.py` (add `VoiceConfig`, `Config.voice`, loader, `SAMPLE_CONFIG`)
- Create: `kira-engine/src/kira/voice/stack.py`
- Modify: `kira-engine/src/kira/app.py` (Engine builds `self.voice`; add `GET /v1/kira/voice`)
- Modify: `kira-engine/src/kira/__main__.py` (command)
- Modify: `kira-engine/pyproject.toml` (optional extra)
- Test: `kira-engine/tests/test_voice_stack.py`
- Test: `kira-engine/tests/test_voice_api.py`

**Interfaces:**
- Produces: `VoiceConfig` with the fields and defaults from the spec §7.
- Produces: `build_voice_stack(config, registry, view) -> VoiceStack`; `VoiceStack.status()` returns the status dict; `.stt`, `.tts`, `.vision`, `.limits`.
- Produces: `engine.voice` on every `Engine`.
- Produces: `GET /v1/kira/voice` (bearer token) returning the same dict.
- Produces: `kira-engine voice doctor` printing `{"status": ..., "paths": ...}` as JSON, exit 0.

- [x] **Step 1: Write the failing tests**

`tests/test_voice_stack.py`:
```python
from __future__ import annotations

import asyncio

import pytest

from kira.config import Config, ConfigError, VoiceConfig
from kira.overrides import build_view
from kira.providers.registry import ProviderRegistry
from kira.vault import Vault
from kira.voice.stack import build_voice_stack
from tests.conftest import provider_configs


def stack_for(tmp_path, voice: VoiceConfig, providers=None):
    providers = providers or provider_configs()
    vault = Vault("memory")
    for provider in providers:
        vault.set(provider.key_ref, f"key-{provider.name}")
    config = Config(data_dir=tmp_path / ".kira-data", providers=providers, voice=voice)
    config.data_dir.mkdir(parents=True, exist_ok=True)
    registry = ProviderRegistry(config, vault, None)
    return build_voice_stack(config, registry, lambda: build_view(config, None))


def test_local_missing_is_reported_not_raised(tmp_path):
    status = stack_for(tmp_path, VoiceConfig()).status()
    assert status["stt"] == {
        "mode": "local",
        "available": False,
        "detail": 'faster-whisper is not installed — pip install -e ".[voice]"',
    }
    assert status["tts"]["mode"] == "local"
    assert status["tts"]["available"] is False
    assert status["vision"] is None


def test_remote_uses_the_named_provider_and_its_key(tmp_path):
    status = stack_for(tmp_path, VoiceConfig(stt="remote", stt_provider="fast_one", tts="remote", tts_provider="ant")).status()
    assert status["stt"] == {"mode": "remote", "available": True, "detail": "fast_one · whisper-1"}
    # anthropic has no audio endpoints; the stack must say what is wrong instead of calling it.
    assert status["tts"]["mode"] == "remote"
    assert status["tts"]["available"] is False
    assert "openai_compat" in status["tts"]["detail"]


def test_remote_without_key_is_unavailable(tmp_path):
    providers = provider_configs()
    config = Config(data_dir=tmp_path / ".kira-data", providers=providers, voice=VoiceConfig(stt="remote", stt_provider="fast_one"))
    registry = ProviderRegistry(config, Vault("memory"), None)
    status = build_voice_stack(config, registry, lambda: build_view(config, None)).status()
    assert status["stt"]["available"] is False
    assert "key" in status["stt"]["detail"]


def test_vision_picks_the_highest_priority_declared_provider(tmp_path):
    providers = provider_configs()
    providers[2].vision = True  # "big"
    status = stack_for(tmp_path, VoiceConfig(), providers).status()
    assert status["vision"] == {"provider": "big", "model": "max"}


def test_off_is_honest(tmp_path):
    status = stack_for(tmp_path, VoiceConfig(stt="off", tts="off")).status()
    assert status["stt"]["mode"] == "off" and status["stt"]["available"] is False
    assert "off" in status["stt"]["detail"]


def test_bad_voice_values_are_refused():
    with pytest.raises(ConfigError):
        VoiceConfig(stt="cloud")
    with pytest.raises(ConfigError):
        VoiceConfig(silence_ms=10)
    with pytest.raises(ConfigError):
        VoiceConfig(temperature=3)
```

`tests/test_voice_api.py`:
```python
import asyncio


def test_voice_status_needs_the_token(harness):
    response = asyncio.run(harness.api.get("/v1/kira/voice"))
    assert response.status_code == 401


def test_voice_status_shape(harness):
    response = asyncio.run(harness.api.get("/v1/kira/voice", headers=harness.auth))
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"stt", "tts", "vision", "limits"}
    assert body["stt"]["mode"] == "local"
    assert body["limits"] == {"max_utterance_s": 30, "silence_ms": 700}
    assert "key-" not in response.text
```

- [x] **Step 2: Run them and watch them fail**

Run: `cd kira-engine && .venv/Scripts/python -m pytest tests/test_voice_stack.py tests/test_voice_api.py -q`
Expected: `ImportError: kira.voice.stack` and `AttributeError: Engine has no attribute 'voice'`.

- [x] **Step 3: Implement config**

In `config.py`:
```python
VOICE_MODES = ("local", "remote", "off")


@dataclass
class VoiceConfig:
    stt: str = "local"
    stt_model: str = "base.en"
    stt_provider: str = "openai"
    stt_remote_model: str = "whisper-1"
    tts: str = "local"
    tts_provider: str = "openai"
    tts_model: str = "tts-1"
    tts_voice: str = "alloy"
    piper_bin: str = "voice/piper/piper.exe"
    piper_model: str = "voice/piper/voice.onnx"
    vad_threshold: float = 0.02
    silence_ms: int = 700
    max_utterance_s: int = 30
    temperature: float = 0.6

    def __post_init__(self) -> None:
        if self.stt not in VOICE_MODES:
            raise ConfigError(f"voice.stt '{self.stt}' is not one of {VOICE_MODES}")
        if self.tts not in VOICE_MODES:
            raise ConfigError(f"voice.tts '{self.tts}' is not one of {VOICE_MODES}")
        if not (0.002 <= self.vad_threshold <= 0.5):
            raise ConfigError("voice.vad_threshold must be between 0.002 and 0.5")
        if not (200 <= self.silence_ms <= 2000):
            raise ConfigError("voice.silence_ms must be between 200 and 2000")
        if not (5 <= self.max_utterance_s <= 120):
            raise ConfigError("voice.max_utterance_s must be between 5 and 120")
        if not (0.0 <= self.temperature <= 2.0):
            raise ConfigError("voice.temperature must be between 0 and 2")
```
Add to `Config`: `voice: VoiceConfig = field(default_factory=VoiceConfig)`. In `load_config`, pass `voice=_voice_from(raw.get("voice") or {})` and add:
```python
def _voice_from(raw: dict[str, Any]) -> VoiceConfig:
    known = set(VoiceConfig.__dataclass_fields__)
    unknown = sorted(set(raw) - known)
    if unknown:
        raise ConfigError(f"unknown voice keys: {unknown}")
    return VoiceConfig(**raw)
```
Add the `voice:` block from spec §7 to `SAMPLE_CONFIG`, and `vision: true` to the openrouter, anthropic and gemini stanzas.

- [x] **Step 4: Implement the stack**

`voice/stack.py`:
```python
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..config import Config, VoiceConfig
from ..overrides import MergedView
from ..providers.registry import ProviderRegistry
from .stt import LocalStt, OffStt, RemoteStt, SpeechToText, UnavailableStt
from .tts import LocalTts, OffTts, RemoteTts, TextToSpeech, UnavailableTts


@dataclass
class VoiceStack:
    stt: SpeechToText
    tts: TextToSpeech
    vision: dict[str, str] | None
    limits: dict[str, int]

    def status(self) -> dict[str, Any]:
        return {
            "stt": {"mode": self.stt.mode, "available": self.stt.available, "detail": self.stt.detail},
            "tts": {"mode": self.tts.mode, "available": self.tts.available, "detail": self.tts.detail},
            "vision": self.vision,
            "limits": self.limits,
        }


def _remote_audio_provider(config: Config, name: str):
    provider = config.by_name.get(name)
    if provider is None:
        return None, f"voice provider '{name}' is not in config.yaml"
    if provider.kind != "openai_compat":
        return None, f"provider '{name}' is {provider.kind}; audio needs an openai_compat provider"
    return provider, ""


def _build_stt(cfg: VoiceConfig, config: Config, registry: ProviderRegistry) -> SpeechToText:
    if cfg.stt == "off":
        return OffStt()
    if cfg.stt == "local":
        return LocalStt(cfg.stt_model, config.data_dir / "voice")
    provider, problem = _remote_audio_provider(config, cfg.stt_provider)
    if provider is None:
        return UnavailableStt("remote", problem)
    key = registry.key_for(provider.name)
    if not key:
        return UnavailableStt("remote", f"provider '{provider.name}' has no key in the Locker")
    return RemoteStt(provider.name, provider.base_url, cfg.stt_remote_model, key, registry.client)


def _build_tts(cfg: VoiceConfig, config: Config, registry: ProviderRegistry) -> TextToSpeech:
    if cfg.tts == "off":
        return OffTts()
    if cfg.tts == "local":
        base = config.data_dir
        return LocalTts(base / cfg.piper_bin, base / cfg.piper_model, base / "voice" / "tmp")
    provider, problem = _remote_audio_provider(config, cfg.tts_provider)
    if provider is None:
        return UnavailableTts("remote", problem)
    key = registry.key_for(provider.name)
    if not key:
        return UnavailableTts("remote", f"provider '{provider.name}' has no key in the Locker")
    return RemoteTts(provider.name, provider.base_url, cfg.tts_model, cfg.tts_voice, key, registry.client)


def build_voice_stack(config: Config, registry: ProviderRegistry, view: Callable[[], MergedView]) -> VoiceStack:
    cfg = config.voice
    vision = None
    for provider in sorted(view().providers, key=lambda item: item.priority):
        if not provider.enabled or not provider.base.vision or not provider.models:
            continue
        if provider.key_ref and not registry.key_for(provider.name):
            continue
        vision = {"provider": provider.name, "model": provider.models[0]}
        break
    return VoiceStack(
        stt=_build_stt(cfg, config, registry),
        tts=_build_tts(cfg, config, registry),
        vision=vision,
        limits={"max_utterance_s": cfg.max_utterance_s, "silence_ms": cfg.silence_ms},
    )
```
`ProviderRegistry` must expose `.client`; verify with a grep before implementing and use the actual attribute name.

- [x] **Step 5: Wire the engine, the endpoint and its contract entry**

In `app.py`, inside `Engine.__init__` after `self.router = Router(...)`:
```python
        self.voice = build_voice_stack(config, self.registry, self.view)
```
(import from `.voice.stack`). Add near the other read endpoints:
```python
    @app.get(f"{API_PREFIX}/kira/voice", dependencies=[auth])
    async def kira_voice() -> dict:
        """What a call would get: listen / speak / see, each with the reason it is missing."""
        return engine.voice.status()
```

**The route cannot land alone.** `tests/test_versioning.py::test_the_contract_and_the_route_table_agree_in_both_directions`
compares the live route table against `OPENAPI["paths"]` in both directions, so registering
`/v1/kira/voice` without documenting it fails the suite at once. Task 7's path/schema work is
therefore pulled forward here: `VoiceStage` + `VoiceStatus` schemas and
`f"{API_PREFIX}/kira/voice": {"get": _read(..., "VoiceStatus")}` go into `contracts.py` in this
task. The *artifacts* (`kira-contracts/openapi.json`, `contract.json`) are still not regenerated
here — the drift gate compares the committed artifacts to `types.ts`, and that pair stays in step
until Task 7 changes both sides at once. `test_docs_match_engine.py` also demands the README
endpoint row and the `kira-engine voice doctor` verb row in this same change.

- [x] **Step 6: Add the CLI command**

In `__main__.py` (`build_view` is already imported at module scope; `httpx`, the registry and the
stack builder are imported inside the function so `--help` stays fast):
```python
def cmd_voice(args: argparse.Namespace) -> int:
    """Report the speech stack the way `/call` sees it, plus the exact paths it looked for."""
    import httpx

    from .providers.registry import ProviderRegistry
    from .voice.stack import build_voice_stack

    config = load_config(_data_dir(args))
    vault = Vault(args.backend)

    async def check() -> dict:
        async with httpx.AsyncClient(timeout=5.0) as client:
            registry = ProviderRegistry(config, vault, client)
            return build_voice_stack(config, registry, lambda: build_view(config, None)).status()

    status = asyncio.run(check())
    print(json.dumps({"status": status, "paths": {...}, "install": [...]}, indent=2))
    return 0
```
`paths` carries `config`, `piper_bin`, `piper_model`, `whisper_models` (all absolute, all derived
from `config.data_dir`); `install` is the two lines the spec promises — the `pip install -e ".[voice]"`
one and the Piper release/voice one. The command never downloads anything and always exits 0: an
unavailable stage is a fact to report, not a failure of the doctor.
Parser:
```python
    voice = sub.add_parser("voice", parents=[common], help="report the speech stack a real-time call gets")
    vsub = voice.add_subparsers(dest="op", required=True)
    vsub.add_parser("doctor", parents=[common], help="print stage availability, expected paths and install lines").set_defaults(
        func=cmd_voice
    )
```

- [x] **Step 7: Add the optional dependency**

`pyproject.toml`:
```toml
[project.optional-dependencies]
dev = ["pytest>=8", "pytest-asyncio>=0.23", "anyio>=4"]
voice = ["faster-whisper>=1.1"]
```

- [x] **Step 8: Run the tests**

Run: `cd kira-engine && .venv/Scripts/python -m pytest tests/test_voice_stack.py tests/test_voice_api.py -q`
then the whole suite. Do **not** install the `voice` extra — the missing-import branch is the one
under test. Executed: 13 passed for the two files, `329 passed, 1 skipped` for the suite, and
`kira-engine voice doctor --backend memory --data-dir <tmp>` prints the JSON above with exit 0.

Two things the plan's own text got wrong, now fixed in the tests:
`VoiceConfig(silence_ms="soon")` raises `TypeError` *inside* `__post_init__`'s range check, which is
why `_voice_from` wraps the construction in `except TypeError` — a bare dataclass accepts any type.
And a `text.replace()` against `SAMPLE_CONFIG` must edit each voice line in place: appending a second
`silence_ms` leaves the sample's own line behind, and PyYAML keeps the last duplicate, so the edited
value silently loses to the default.

- [x] **Step 9: Commit**

```bash
git add kira-engine/src/kira/config.py kira-engine/src/kira/voice/stack.py kira-engine/src/kira/voice/stt.py kira-engine/src/kira/voice/tts.py kira-engine/src/kira/app.py kira-engine/src/kira/contracts.py kira-engine/src/kira/__main__.py kira-engine/pyproject.toml kira-engine/tests/test_voice_stack.py kira-engine/tests/test_voice_api.py README.md
git -c user.name="Kira" -c user.email="kira@localhost" commit -m "feat(engine): voice config, availability status, endpoint and doctor"
```

---

### Task 6: The `/v1/voice` WebSocket and the call state machine

**Files:**
- Create: `kira-engine/src/kira/voice/call.py`
- Modify: `kira-engine/src/kira/app.py` (websocket route)
- Test: `kira-engine/tests/test_voice_ws.py` (handshake over Starlette `TestClient`)
- Test: `kira-engine/tests/test_voice_call.py` (state machine with a fake socket)

**Interfaces:**
- Consumes: `EnergyVad`, `pcm_to_wav`, `split_sentences`, `VoiceError`, `VoiceStack`, `AgentRun`, `ToolRegistry`.
- Produces: `Hello(token, model=None, mode=None, session_id=None)`.
- Produces: `VoiceCall(engine, socket, hello)` with `async run()`; the socket needs `send_json(dict)` and `receive_json()`.
- WS messages exactly as spec §6.

**What changed while executing this task** (the code below the steps is the plan as written; these are
the deltas the repo forced, and the implementation follows them):

1. **`from tests.conftest import …` does not exist here.** `tests/` has no `__init__.py`, so every test
   imports the helpers as `from conftest import ok, openai_text_chunks` — that is the house style.
2. **The test audio needs a quiet lead-in.** `EnergyVad`'s bar is `max(threshold, floor × 4)` and the
   floor is the quietest recent frame, so a call that starts on `LOUD` has lifted its own bar and never
   opens an utterance. The scenarios feed five quiet packets (1 s of room) before the three loud ones.
   Real microphones always hand a pre-roll; a constant-amplitude synthetic packet does not.
3. **One assistant-row writer, not two.** `app.py` already had an `assistant_row` closure inside
   `create_app`. It is now `Engine.persist_assistant_row(session_id, run, status)`, which chat calls and
   `VoiceCall` calls — otherwise a call could silently start storing a different shape of history row.
4. **A frame is sent once.** The plan appended the image-carrying `Message` to `self.history`, so every
   later turn replayed the same JPEG. The request is now built as
   `[system, *history, user_with_frame]` while the history entry stays text-only.
5. **Task 7's chain-event work had to come forward.** `test_units.py` requires every published chain
   event to have a chip label in `ChainTrace.tsx`, and `test_docs_match_engine.py` requires the README
   to name exactly the published set — so emitting `images_attached` / `images_dropped` without
   publishing them fails the suite. `CHAIN_EVENTS` is now 15 (`test_contract_v2.py` counts them), both
   names have labels and tones, the README list carries them, and the docs test's own regex learned
   them. Task 7 keeps the regeneration, the `vision` flag and the TypeScript mirror.
6. **`bad_audio` is a seventh error code.** Spec §6 listed six; a non-base64 `pcm` needs its own answer.
   The spec table now lists `bad_audio` too.
7. **Four scenarios the plan did not have:** a discarded utterance never reaches STT or the provider, a
   typed turn never asks the microphone, a frame is attached to exactly one turn and never stored, and
   malformed audio or a PNG frame is answered with an `error` without ending the call.

- [x] **Step 1: Write the failing handshake test**

```python
from __future__ import annotations

from fastapi.testclient import TestClient


def test_bad_hello_closes_4401(harness):
    with TestClient(harness.app) as client:
        with client.websocket_connect("/v1/voice") as ws:
            ws.send_json({"type": "hello", "token": "wrong"})
            message = ws.receive()
            assert message["type"] == "websocket.close"
            assert message.get("code") == 4401


def test_hello_returns_ready(harness):
    with TestClient(harness.app) as client:
        with client.websocket_connect("/v1/voice") as ws:
            ws.send_json({"type": "hello", "token": "test-engine-token"})
            ready = ws.receive_json()
            assert ready["type"] == "ready"
            assert ready["session_id"]
            assert set(ready["voice"]) == {"stt", "tts", "vision", "limits"}
            assert "test-engine-token" not in str(ready)
```

- [x] **Step 2: Write the failing state-machine test**

```python
from __future__ import annotations

import asyncio
import base64
import struct

from kira.voice.call import Hello, VoiceCall

LOUD = base64.b64encode(struct.pack("<1600h", *([8192] * 1600))).decode()
QUIET = base64.b64encode(struct.pack("<1600h", *([0] * 1600))).decode()


class FakeSocket:
    def __init__(self) -> None:
        self.inbox: asyncio.Queue = asyncio.Queue()
        self.sent: list[dict] = []
        self.closed = None

    async def receive_json(self):
        item = await self.inbox.get()
        if item is None:
            raise RuntimeError("closed")
        return item

    async def send_json(self, payload):
        self.sent.append(payload)

    async def close(self, code: int = 1000):
        self.closed = code


class FakeStt:
    mode = "local"
    available = True
    detail = "fake"

    def __init__(self, text="hello kira"):
        self.text = text
        self.wavs = []

    async def transcribe(self, wav):
        self.wavs.append(wav)
        return self.text


class FakeTts:
    mode = "local"
    available = True
    detail = "fake"

    def __init__(self):
        self.spoken = []
        self.gate = None                     # set to an Event to hold the worker mid-speech
        self.started = asyncio.Event()       # so a test knows when speech really began

    async def speak(self, text):
        self.spoken.append(text)
        self.started.set()
        if self.gate is not None:
            await self.gate.wait()
        return b"RIFF" + text.encode()


class Stack:
    def __init__(self, stt, tts):
        self.stt = stt
        self.tts = tts

    def status(self):
        return {
            "stt": {"mode": "local", "available": True, "detail": "fake"},
            "tts": {"mode": "local", "available": True, "detail": "fake"},
            "vision": None,
            "limits": {"max_utterance_s": 30, "silence_ms": 700},
        }


def drive(harness, socket, frames):
    for payload in frames:
        socket.inbox.put_nowait(payload)


async def wait_for(socket, kind, timeout=2.0):
    for _ in range(int(timeout / 0.01)):
        for message in socket.sent:
            if message["type"] == kind:
                return message
        await asyncio.sleep(0.01)
    raise AssertionError(f"no {kind} in {[m['type'] for m in socket.sent]}")


async def wait_for_count(socket, kind, count, timeout=2.0):
    for _ in range(int(timeout / 0.01)):
        if sum(1 for message in socket.sent if message["type"] == kind) >= count:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"wanted {count} {kind}, saw {[m['type'] for m in socket.sent]}")


def test_utterance_runs_a_turn(harness):
    from tests.conftest import ok, openai_text_chunks

    harness.script.queue("https://fast1.invalid/v1", ok(openai_text_chunks("Hi. How are you?")))
    stt = FakeStt()
    tts = FakeTts()
    harness.engine.voice = Stack(stt, tts)

    async def scenario():
        socket = FakeSocket()
        call = VoiceCall(harness.engine, socket, Hello(token="test-engine-token"))
        task = asyncio.create_task(call.run())
        await wait_for(socket, "ready")
        socket.inbox.put_nowait({"type": "audio", "pcm": LOUD})
        for _ in range(7):
            socket.inbox.put_nowait({"type": "audio", "pcm": QUIET})
        await wait_for(socket, "turn_done")
        socket.inbox.put_nowait({"type": "close"})
        await asyncio.wait_for(task, 2.0)
        return socket

    socket = asyncio.run(scenario())
    kinds = [m["type"] for m in socket.sent]
    assert kinds[:4] == ["ready", "speech_start", "speech_end", "transcript"]
    assert "thinking" in kinds and "turn_done" in kinds
    assert [m["text"] for m in socket.sent if m["type"] == "audio_out"] == ["Hi.", "How are you?"]
    assert stt.wavs and stt.wavs[0].startswith(b"RIFF")
    assert tts.spoken == ["Hi.", "How are you?"]
    rows = harness.store.messages(socket.sent[0]["session_id"])
    assert [row["role"] for row in rows] == ["user", "assistant"]
    assert rows[0]["content"] == "hello kira"
    assert rows[1]["content"] == "Hi. How are you?"
    chain_events = [record["event"] for record in rows[1]["chain"]]
    assert "served" in chain_events


def test_barge_persists_an_interrupted_answer(harness):
    from tests.conftest import ok, openai_text_chunks

    harness.script.queue("https://fast1.invalid/v1", ok(openai_text_chunks("One. Two.")))
    stt = FakeStt()
    tts = FakeTts()
    tts.gate = asyncio.Event()
    harness.engine.voice = Stack(stt, tts)

    async def scenario():
        socket = FakeSocket()
        call = VoiceCall(harness.engine, socket, Hello(token="test-engine-token"))
        task = asyncio.create_task(call.run())
        await wait_for(socket, "ready")
        socket.inbox.put_nowait({"type": "audio", "pcm": LOUD})
        for _ in range(7):
            socket.inbox.put_nowait({"type": "audio", "pcm": QUIET})
        await asyncio.wait_for(tts.started.wait(), 2.0)   # speech is now blocked inside speak()
        socket.inbox.put_nowait({"type": "barge"})
        await wait_for(socket, "cancelled")
        socket.inbox.put_nowait({"type": "close"})
        await asyncio.wait_for(task, 2.0)
        return socket

    socket = asyncio.run(scenario())
    session_id = socket.sent[0]["session_id"]
    rows = harness.store.messages(session_id)
    assert [row["role"] for row in rows] == ["user", "assistant"]
    assert rows[1]["status"] == "interrupted"
    assert any(record["event"] == "aborted_mid_stream" for record in rows[1]["chain"])


def test_typed_turn_needs_no_audio(harness):
    from tests.conftest import ok, openai_text_chunks

    harness.script.queue("https://fast1.invalid/v1", ok(openai_text_chunks("Just text.")))
    harness.engine.voice = Stack(FakeStt(), FakeTts())

    async def scenario():
        socket = FakeSocket()
        call = VoiceCall(harness.engine, socket, Hello(token="test-engine-token"))
        task = asyncio.create_task(call.run())
        await wait_for(socket, "ready")
        socket.inbox.put_nowait({"type": "text", "text": "hello by hand"})
        await wait_for(socket, "turn_done")
        socket.inbox.put_nowait({"type": "close"})
        await asyncio.wait_for(task, 2.0)
        return socket

    socket = asyncio.run(scenario())
    assert any(m["type"] == "transcript" and m["text"] == "hello by hand" for m in socket.sent)
    assert [m["text"] for m in socket.sent if m["type"] == "audio_out"] == ["Just text."]


def test_frame_is_attached_once_or_dropped_with_a_reason(harness):
    from tests.conftest import ok, openai_text_chunks

    harness.script.queue("https://fast1.invalid/v1", ok(openai_text_chunks("I see.")))
    harness.script.queue("https://fast1.invalid/v1", ok(openai_text_chunks("Still text.")))
    harness.engine.voice = Stack(FakeStt(), FakeTts())

    async def scenario():
        socket = FakeSocket()
        call = VoiceCall(harness.engine, socket, Hello(token="test-engine-token"))
        task = asyncio.create_task(call.run())
        await wait_for(socket, "ready")
        jpeg = base64.b64encode(b"\xff\xd8\xff\xe0fakejpeg").decode()
        socket.inbox.put_nowait({"type": "frame", "jpeg": jpeg, "mime": "image/jpeg"})
        socket.inbox.put_nowait({"type": "text", "text": "what is this"})
        await wait_for_count(socket, "turn_done", 1)
        socket.inbox.put_nowait({"type": "text", "text": "and now"})
        await wait_for_count(socket, "turn_done", 2)
        socket.inbox.put_nowait({"type": "close"})
        await asyncio.wait_for(task, 2.0)
        return socket

    socket = asyncio.run(scenario())
    session_id = socket.sent[0]["session_id"]
    rows = harness.store.messages(session_id)
    # Default providers declare no vision: the frame never leaves the device and the chain says so.
    events = [record["event"] for row in rows if row["role"] == "assistant" for record in row["chain"]]
    assert events.count("images_dropped") == 1
    assert events.count("images_attached") == 0
    # Both turns reached the provider with plain string content: the frame never left the device.
    assert harness.script.bodies
    assert all(
        not isinstance(message["content"], list)
        for _, payload in harness.script.bodies
        for message in payload["messages"]
    )
```

- [x] **Step 3: Implement `voice/call.py`**

```python
from __future__ import annotations

import asyncio
import base64
import binascii
from dataclasses import dataclass
from typing import Any

from ..errors import KiraError
from ..loop import AgentRun
from ..tools import ToolRegistry
from ..types import Delta, Message
from .errors import VoiceError
from .tts import split_sentences
from .vad import FRAME_BYTES, EnergyVad, VadConfig
from .wav import pcm_to_wav

VOICE_SYSTEM_PROMPT = (
    "You are on a live voice call. Your reply is read aloud: keep it to one to three short "
    "sentences, no markdown, no lists, and write numbers the way they are spoken. Tools are not "
    "available on a call; if asked to do something that needs one, say so briefly."
)
MAX_FRAME_BYTES = 512 * 1024
MAX_HISTORY = 20


@dataclass
class Hello:
    token: str
    model: str | None = None
    mode: str | None = None
    session_id: str | None = None


class VoiceCall:
    """One WebSocket, one call. Audio in, turns out, speaking can be interrupted."""

    def __init__(self, engine, socket, hello: Hello) -> None:
        self.engine = engine
        self.socket = socket
        self.hello = hello
        cfg = engine.config.voice
        self.vad = EnergyVad(
            VadConfig(
                threshold=cfg.vad_threshold,
                silence_ms=cfg.silence_ms,
                max_utterance_s=cfg.max_utterance_s,
            )
        )
        self.session_id: str | None = None
        self.history: list[Message] = []
        self.pending_frame: str | None = None
        self.turn: asyncio.Task | None = None
        self.active_run: AgentRun | None = None
        self.phase = "listening"          # listening | thinking | speaking
        self._utterance = bytearray()
        self._send_lock = asyncio.Lock()

    async def _send(self, payload: dict) -> None:
        try:
            async with self._send_lock:
                await self.socket.send_json(payload)
        except Exception:  # noqa: BLE001 - a dead socket is a finished call
            pass

    async def run(self) -> None:
        cfg = self.engine.config.voice
        mode = (self.hello.mode or self.engine.config.default_mode).upper()
        self.session_id = self.engine.store.create_session(mode, self.hello.session_id)
        if self.hello.session_id:
            for row in self.engine.store.messages(self.session_id, limit=12):
                if row["role"] in ("user", "assistant") and row["content"]:
                    self.history.append(Message(role=row["role"], content=row["content"]))
        await self._send(
            {
                "type": "ready",
                "session_id": self.session_id,
                "voice": self.engine.voice.status(),
                "limits": {
                    "max_utterance_s": cfg.max_utterance_s,
                    "silence_ms": cfg.silence_ms,
                },
            }
        )
        try:
            while True:
                message = await self.socket.receive_json()
                if message.get("type") == "close":
                    break
                await self._dispatch(message)
        except Exception:  # noqa: BLE001 - disconnect, malformed frame, anything ends the call
            pass
        finally:
            await self._shutdown()

    async def _dispatch(self, message: dict) -> None:
        kind = message.get("type")
        if kind == "audio":
            await self._on_audio(message)
        elif kind == "frame":
            await self._on_frame(message)
        elif kind == "text":
            await self._on_text(message)
        elif kind == "barge":
            await self._on_barge()

    def _feed(self, frame: bytes) -> list:
        if self.phase != "listening":
            return []
        events = self.vad.push(frame)
        if any(event.kind == "start" for event in events):
            self._utterance = bytearray()
        if self.vad.speaking:
            self._utterance.extend(frame)
        return events

    async def _on_audio(self, message: dict) -> None:
        try:
            pcm = base64.b64decode(str(message.get("pcm") or ""), validate=True)
        except (ValueError, binascii.Error):
            await self._send({"type": "error", "code": "bad_audio", "message": "audio must be base64"})
            return
        events = []
        for offset in range(0, len(pcm) - FRAME_BYTES + 1, FRAME_BYTES):
            events.extend(self._feed(pcm[offset:offset + FRAME_BYTES]))
        for event in events:
            if event.kind == "start":
                await self._send({"type": "speech_start"})
            else:
                await self._send({"type": "speech_end", "discarded": event.discarded})
                if not event.discarded:
                    await self._commit_utterance()

    async def _commit_utterance(self) -> None:
        wav = pcm_to_wav(bytes(self._utterance))
        self._utterance = bytearray()
        try:
            text = (await self.engine.voice.stt.transcribe(wav)).strip()
        except VoiceError as exc:
            await self._send({"type": "error", "code": exc.code, "message": exc.message})
            return
        if not text:
            return
        await self._send({"type": "transcript", "text": text, "final": True})
        self._start_turn(text)

    async def _on_text(self, message: dict) -> None:
        text = str(message.get("text") or "").strip()
        if not text:
            return
        if self.turn is not None:
            await self._cancel_turn("the user typed over the answer")
        await self._send({"type": "transcript", "text": text, "final": True})
        self._start_turn(text)

    async def _on_frame(self, message: dict) -> None:
        mime = str(message.get("mime") or "image/jpeg")
        raw = str(message.get("jpeg") or "")
        try:
            data = base64.b64decode(raw, validate=True)
        except (ValueError, binascii.Error):
            data = b""
        if mime != "image/jpeg" or not data or len(data) > MAX_FRAME_BYTES:
            await self._send(
                {"type": "error", "code": "frame_rejected", "message": "frames must be JPEG under 512 KB"}
            )
            return
        self.pending_frame = f"data:image/jpeg;base64,{raw}"

    async def _on_barge(self) -> None:
        if self.turn is not None:
            await self._cancel_turn("the user spoke over the answer")
        self.vad.reset()
        self._utterance = bytearray()
        self.phase = "listening"

    def _start_turn(self, text: str) -> None:
        self.turn = asyncio.create_task(self._run_turn(text))

    async def _run_turn(self, text: str) -> None:
        engine = self.engine
        cfg = engine.config.voice
        self.phase = "thinking"
        await self._send({"type": "thinking"})
        frame, self.pending_frame = self.pending_frame, None
        user = Message(role="user", content=text, images=[frame] if frame else [])
        run: AgentRun | None = None
        try:
            plan = engine.router.plan(model=self.hello.model, mode=self.hello.mode)
            note: dict[str, Any] | None = None
            if frame:
                vision = [c for c in plan.choices if engine.view().by_name[c.provider].base.vision]
                if vision:
                    plan.choices = vision
                    note = {
                        "provider": vision[0].provider,
                        "event": "images_attached",
                        "reason": "1 frame attached",
                    }
                else:
                    user.images = []
                    note = {"event": "images_dropped", "reason": "no provider in this mode declares vision"}
            engine.store.add_message(self.session_id, "user", text)
            self.history.append(user)
            run = AgentRun(
                router=engine.router,
                tools=ToolRegistry(),
                plan=plan,
                messages=[Message(role="system", content=VOICE_SYSTEM_PROMPT), *self.history[-12:]],
                max_steps=1,
                temperature=cfg.temperature,
                approvals=None,
                checkpoints=None,
                policies={},
                session_id=self.session_id,
            )
            if note:
                run.attempt.chain.append(note)
            self.active_run = run
            await self._stream(run)
            self.history.append(Message(role="assistant", content=run.state.text))
            self.history = self.history[-MAX_HISTORY:]
            self._persist(run, run.state.status)
            await self._send(
                {
                    "type": "turn_done",
                    "session_id": self.session_id,
                    "usage": {
                        "prompt_tokens": run.state.usage.input_tokens,
                        "completion_tokens": run.state.usage.output_tokens,
                    },
                    "chain": run.attempt.chain,
                }
            )
        except asyncio.CancelledError:
            if run is not None:
                run.attempt.chain.append(
                    {
                        "provider": run.attempt.served_by,
                        "event": "aborted_mid_stream",
                        "reason": "the user spoke over the answer",
                    }
                )
                self.history.append(Message(role="assistant", content=run.state.text))
                self._persist(run, "interrupted")
            await self._send({"type": "cancelled", "reason": "barge"})
        except (VoiceError, KiraError) as exc:
            await self._send({"type": "error", "code": getattr(exc, "code", "voice_failed"), "message": str(exc)})
        except Exception as exc:  # noqa: BLE001 - one bad turn must not end the call
            await self._send({"type": "error", "code": "voice_failed", "message": str(exc)})
        finally:
            self.active_run = None
            self.phase = "listening"
            self.turn = None

    def _persist(self, run: AgentRun, status: str) -> None:
        self.engine.store.add_message(
            self.session_id,
            "assistant",
            run.state.text,
            provider=run.attempt.served_by,
            model=run.attempt.served_model,
            finish_reason=run.state.finish_reason,
            status=status,
            tool_calls=[],
            usage={
                "input_tokens": run.state.usage.input_tokens,
                "output_tokens": run.state.usage.output_tokens,
                "estimated": run.state.usage.estimated,
            },
            chain=run.attempt.chain,
        )

    async def _stream(self, run: AgentRun) -> None:
        queue: asyncio.Queue[str | None] = asyncio.Queue()
        worker = asyncio.create_task(self._speak(queue))
        buffer = ""
        try:
            async for event in run.events():
                if not isinstance(event, Delta):
                    continue
                self.phase = "speaking"
                buffer += event.text
                await self._send({"type": "answer_delta", "text": event.text})
                complete, buffer = split_sentences(buffer)
                for sentence in complete:
                    queue.put_nowait(sentence)
            if buffer.strip():
                queue.put_nowait(buffer.strip())
            queue.put_nowait(None)
            await worker
        finally:
            if not worker.done():
                worker.cancel()
                await asyncio.gather(worker, return_exceptions=True)

    async def _speak(self, queue: asyncio.Queue[str | None]) -> None:
        seq = 0
        while True:
            sentence = await queue.get()
            if sentence is None:
                return
            try:
                wav = await self.engine.voice.tts.speak(sentence)
            except VoiceError as exc:
                await self._send({"type": "error", "code": exc.code, "message": exc.message})
                continue
            seq += 1
            await self._send(
                {
                    "type": "audio_out",
                    "pcm": base64.b64encode(wav).decode("ascii"),
                    "seq": seq,
                    "text": sentence,
                }
            )

    async def _cancel_turn(self, reason: str) -> None:
        task = self.turn
        self.turn = None
        if task is None:
            return
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def _shutdown(self) -> None:
        task = self.turn
        self.turn = None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
```

- [x] **Step 4: Add the route**

In `app.py` (imports: `asyncio`, `WebSocket`, `VoiceCall`, `Hello`):
```python
    @app.websocket(f"{API_PREFIX}/voice")
    async def voice_socket(websocket: WebSocket) -> None:
        await websocket.accept()
        try:
            raw = await asyncio.wait_for(websocket.receive_json(), timeout=5.0)
        except (asyncio.TimeoutError, RuntimeError, ValueError, WebSocketDisconnect):
            try:
                await websocket.close(code=4401)
            except RuntimeError:
                pass  # already gone; there is no one left to tell
            return
        hello = raw if isinstance(raw, dict) else {}
        token = hello.get("token")
        if hello.get("type") != "hello" or not isinstance(token, str) or not secrets.compare_digest(token, engine.token):
            await websocket.close(code=4401)
            return

        def opt(name: str) -> str | None:
            value = hello.get(name)
            return value if isinstance(value, str) and value else None

        await VoiceCall(
            engine,
            websocket,
            Hello(token=token, model=opt("model"), mode=opt("mode"), session_id=opt("session_id")),
        ).run()
```

- [x] **Step 5: Run the tests**

Run: `cd kira-engine && .venv/Scripts/python -m pytest tests/test_voice_ws.py tests/test_voice_call.py -q`
Expected: PASS. If `TestClient` cannot mount the app because `kira-chat/dist` is absent, set `KIRA_CHAT_DIST` to any existing directory in the test or skip only the static mount — do not change the route.

- [x] **Step 6: Run the whole engine suite**

Run: `cd kira-engine && .venv/Scripts/python -m pytest -q`
Expected: all previous tests still pass.

- [x] **Step 7: Commit**

```bash
git add kira-engine/src/kira/voice/call.py kira-engine/src/kira/app.py kira-engine/tests/test_voice_ws.py kira-engine/tests/test_voice_call.py
git -c user.name="Kira" -c user.email="kira@localhost" commit -m "feat(engine): /v1/voice websocket with VAD turns, sentence TTS and barge-in"
```

---

### Task 7: Contracts — schema, events, provider flag, regeneration

**Files:**
- Modify: `kira-engine/src/kira/contracts.py` (`CHAIN_EVENTS`, `ProviderRow`, `VoiceStatus`, path entry)
- Modify: `kira-engine/src/kira/app.py` (providers payload `vision`)
- Modify: `kira-contracts/types.ts`
- Regenerate: `kira-contracts/openapi.json`, `contract.json`
- Test: existing `kira-contracts/check-drift.mjs` plus `kira-engine/tests/test_contracts.py` (if present) and `tests/test_voice_api.py` (add a providers assertion)

**Interfaces:**
- Produces: chain events `images_attached`, `images_dropped`; `ProviderRow.vision: boolean`; `VoiceStatus`/`VoiceStage` schemas; `/v1/kira/voice` in OpenAPI; TS `VoiceStatus`, `VoiceStage`.

- [x] **Step 1: Add the failing assertions**

Append to `tests/test_voice_api.py`:
```python
def test_providers_carry_vision(harness):
    response = asyncio.run(harness.api.get("/v1/kira/providers", headers=harness.auth))
    assert response.status_code == 200
    assert all("vision" in row for row in response.json()["providers"])
```
`providers_payload` returns `{"providers": rows, "orphan_settings": [...], "month": label}`; the rows are what the assertion reads.

Run: `cd kira-engine && .venv/Scripts/python -m pytest tests/test_voice_api.py -q`
Expected: FAIL — no `vision` key.

- [x] **Step 2: Implement**

- `CHAIN_EVENTS`: append `"images_attached"`, `"images_dropped"` at the end.
- `providers_payload`: add `"vision": p.base.vision,` beside `"key_present"`.
- In the OpenAPI components: add `"vision": {"type": "boolean"}` to the provider row schema (find the schema with `key_present`). `VoiceStage` / `VoiceStatus` and the `{API_PREFIX}/kira/voice` path entry are already in `contracts.py` — Task 5 had to add them because the route table and the contract are checked against each other.

- [x] **Step 3: Regenerate and check the drift gate**

```bash
cd kira-engine && .venv/Scripts/python -m kira contracts --out ../kira-contracts
cd .. && node kira-contracts/check-drift.mjs
```
Expected: `kira-contracts OK — v2, <n> schemas, 6 chunk types, 15 chain events`.

- [x] **Step 4: Update the TS mirror**

`kira-contracts/types.ts`: add one field to the existing `ProviderView` interface, directly after
`key_present: boolean;`:

```ts
  vision: boolean;
```

Then add these types, next to the other response types rather than at the very end of the file:
```ts
export type VoiceMode = "local" | "remote" | "off";

export interface VoiceStage {
  mode: VoiceMode;
  available: boolean;
  detail: string;
}

export interface VoiceStatus {
  stt: VoiceStage;
  tts: VoiceStage;
  vision: { provider: string; model: string } | null;
  limits: { max_utterance_s: number; silence_ms: number };
}
```

- [x] **Step 5: Run engine tests, typecheck and drift**

```bash
cd kira-engine && .venv/Scripts/python -m pytest -q
cd ../kira-chat && npm run check
cd .. && node kira-contracts/check-drift.mjs
```
Expected: PASS / OK.

- [x] **Step 6: Commit**

```bash
git add kira-engine/src/kira/contracts.py kira-engine/src/kira/app.py kira-engine/tests/test_voice_api.py kira-contracts
git -c user.name="Kira" -c user.email="kira@localhost" commit -m "feat(contracts): voice status, vision flag and image chain events"
```

**What changed while executing this task**

1. **`contract.ts` had to gain the two events too**, and the plan's Step 4 only named `types.ts`.
   `check-drift.mjs` compares `CHAIN_EVENTS` in `contract.ts` against `contract.json` as a set, so
   regenerating the artifacts without the mirror fails the gate with
   `CHAIN_EVENTS drifted from contract.json chain_events`. Five problems appeared on the first run —
   the events, `ProviderView` missing `vision` twice (property and required), and the two absent voice
   types — which is the gate doing its job: it listed exactly the edits Steps 3 and 4 make.
2. **Step 5's `npx tsc --noEmit` in `kira-contracts` is a no-op**, not a check: that directory has no
   TypeScript dependency, so `npx` offers to install one. The real typecheck is the client's —
   `kira-chat/src/contracts.ts` re-exports `../../kira-contracts/index.ts`, so `npm run check` compiles
   the mirror. The command above reflects that.
3. **The vision flag is config-only, and now has a test that keeps it that way.** PUTting
   `{"vision": true}` to `/v1/kira/providers/{name}/settings` is refused with a 400 naming the field and
   stores nothing, because the settings table can only tune what `overrides.py` merges — and whether an
   endpoint accepts images is a fact about the model, not a preference. Writing the assertion the plan's
   Step 1 way (`"vision" in row`) would have passed against a row that always said `false`, so the test
   also flips a config stanza and reads `true` back.
4. **The flag is visible where it is decided.** `kira-chat/src/fake-engine.ts` gained `vision` on both
   fixture rows (groq `false`, openrouter `true`) and the Providers row now shows `sees images` /
   `text only` beside the key badge, with an assertion in `App.test.tsx`. A call's "look" button is only
   honest if the same table that shows the key shows whether the camera has anywhere to go; leaving it
   engine-only meant the UI could never explain why frames stayed on the device.
5. Final counts: engine **342 passed, 1 skipped**; `npm run check` green; drift **v2, 56 schemas, 6 chunk
   types, 15 chain events**.

---

### Task 8: Client protocol, frames, socket, and the call hook

**Files:**
- Create: `kira-chat/src/voice/protocol.ts`
- Create: `kira-chat/src/voice/protocol.test.ts`
- Create: `kira-chat/src/voice/frames.ts`
- Create: `kira-chat/src/voice/frames.test.ts`
- Create: `kira-chat/src/voice/capture-worklet.js`
- Create: `kira-chat/src/voice/audio.ts`
- Create: `kira-chat/src/voice/useCall.ts`
- Create: `kira-chat/src/voice/useCall.test.tsx`
- Modify: `kira-chat/src/api.ts` (add `voice()`)

**Interfaces:**
- Produces: `parseEvent(raw: unknown): CallEvent | null`; `voiceUrl(baseUrl: string): string`; `encodePcm(samples: Int16Array): string`.
- Produces: `frameDue(lastSentAt: number, now: number, hidden: boolean, interval = 4000): boolean`.
- Produces: `CallAudioLike` (the media seam) and `CallAudio` (the Web Audio implementation).
- Produces: `useCall(options, deps?)` returning `CallState`. `deps` is injectable so jsdom tests never touch `AudioContext` or `getUserMedia`.

- [x] **Step 1: Write the failing unit tests**

`protocol.test.ts`:
```ts
import { describe, expect, it } from "vitest";
import { parseEvent, voiceUrl } from "./protocol.ts";

it("builds a ws url from the engine base", () => {
  expect(voiceUrl("http://127.0.0.1:8901")).toBe("ws://127.0.0.1:8901/v1/voice");
  expect(voiceUrl("https://kira.example")).toBe("wss://kira.example/v1/voice");
});

it("rejects unknown and malformed events", () => {
  expect(parseEvent({ type: "nope" })).toBeNull();
  expect(parseEvent({ type: "audio_out" })).toBeNull();
  expect(parseEvent("hello")).toBeNull();
});

it("accepts the documented events", () => {
  expect(parseEvent({ type: "speech_end", discarded: false })?.type).toBe("speech_end");
  expect(parseEvent({ type: "transcript", text: "hi", final: true })?.type).toBe("transcript");
  expect(parseEvent({ type: "audio_out", pcm: "AAA", seq: 1, text: "Hi." })?.type).toBe("audio_out");
});
```

`frames.test.ts`:
```ts
import { expect, it } from "vitest";
import { frameDue } from "./frames.ts";

it("is due four seconds after the last frame", () => {
  expect(frameDue(1000, 4999)).toBe(false);
  expect(frameDue(1000, 5000)).toBe(true);
});

it("pauses while the tab is hidden", () => {
  expect(frameDue(1000, 9000, true)).toBe(false);
});
```

`useCall.test.tsx` — the media lives behind an injected seam, so these tests run in jsdom without
`AudioContext`, `AudioWorkletNode` or `navigator.mediaDevices`:

```tsx
import { act, fireEvent, render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { useCall } from "./useCall.ts";
import type { CallAudioLike } from "./audio.ts";

class FakeSocket {
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  readyState = 1;
  constructor(public url: string) {}
  send(data: string) { this.sent.push(data); }
  close() { this.readyState = 3; this.onclose?.(); }
  emit(payload: unknown) { this.onmessage?.({ data: JSON.stringify(payload) } as MessageEvent); }
  last() { return JSON.parse(this.sent[this.sent.length - 1]); }
}

class FakeAudio implements CallAudioLike {
  played: string[] = [];
  micStarted = false;
  stopped = false;
  level: ((value: number) => void) | null = null;
  async startMic(_onPacket: (pcm: string) => void, onLevel: (value: number) => void) {
    this.micStarted = true;
    this.level = onLevel;
  }
  async startCamera() {}
  stopCamera() {}
  frame() { return "aGVsbG8="; }
  async play(pcm: string) { this.played.push(pcm); }
  stopPlayback() {}
  setMuted() {}
  stopAll() { this.stopped = true; }
}

const READY = {
  type: "ready",
  session_id: "s1",
  voice: {
    stt: { mode: "local", available: false, detail: "faster-whisper is not installed" },
    tts: { mode: "local", available: false, detail: "piper is not installed" },
    vision: null,
    limits: { max_utterance_s: 30, silence_ms: 700 },
  },
  limits: { max_utterance_s: 30, silence_ms: 700 },
};

function Probe({ socket, audio }: { socket: FakeSocket; audio: FakeAudio }) {
  const call = useCall(
    { baseUrl: "http://127.0.0.1:8901", token: "t", model: "", mode: "AUTO" },
    { connect: () => socket as unknown as WebSocket, audio },
  );
  return (
    <div>
      <span data-testid="phase">{call.phase}</span>
      <span data-testid="live">{call.live}</span>
      <span data-testid="error">{call.error ?? ""}</span>
      <span data-testid="transcript">{call.entries.map((entry) => `${entry.role}:${entry.text}`).join(" ")}</span>
      <button onClick={() => void call.start()}>start</button>
      <button onClick={() => call.say("hello")}>say</button>
      <button onClick={() => call.look()}>look</button>
      <button onClick={() => call.end()}>end</button>
    </div>
  );
}

function openCall() {
  const socket = new FakeSocket("ws://127.0.0.1:8901/v1/voice");
  const audio = new FakeAudio();
  render(<Probe socket={socket} audio={audio} />);
  fireEvent.click(screen.getByText("start"));
  expect(socket.url).toBe("ws://127.0.0.1:8901/v1/voice");
  act(() => socket.onopen?.());
  act(() => socket.emit(READY));
  return { socket, audio };
}

it("greets with hello and carries typed turns both ways", () => {
  const { socket } = openCall();
  expect(JSON.parse(socket.sent[0])).toEqual({ type: "hello", token: "t", model: null, mode: "AUTO", session_id: null });
  expect(screen.getByTestId("phase").textContent).toBe("listening");
  fireEvent.click(screen.getByText("say"));
  expect(JSON.parse(socket.sent[1])).toEqual({ type: "text", text: "hello" });
  act(() => socket.emit({ type: "transcript", text: "hello", final: true }));
  act(() => socket.emit({ type: "answer_delta", text: "Hi " }));
  act(() => socket.emit({ type: "answer_delta", text: "there." }));
  expect(screen.getByTestId("live").textContent).toBe("Hi there.");
  expect(screen.getByTestId("phase").textContent).toBe("speaking");
  act(() => socket.emit({ type: "turn_done", session_id: "s1", usage: { prompt_tokens: 1, completion_tokens: 2 }, chain: [{ event: "served", provider: "gemini", model: "gemini-2.5-flash" }] }));
  expect(screen.getByTestId("phase").textContent).toBe("listening");
  expect(screen.getByTestId("transcript").textContent).toBe("user:hello assistant:Hi there.");
});

it("plays sentences, barges on speech and looks on request", () => {
  const { socket, audio } = openCall();
  act(() => socket.emit({ type: "audio_out", pcm: "AAAA", seq: 1, text: "Hi." }));
  expect(audio.played).toEqual(["AAAA"]);
  act(() => socket.emit({ type: "answer_delta", text: "Hi." }));
  expect(screen.getByTestId("phase").textContent).toBe("speaking");
  act(() => audio.level?.(0.5));
  expect(socket.last()).toEqual({ type: "barge" });
  expect(screen.getByTestId("phase").textContent).toBe("listening");
  act(() => socket.emit({ type: "cancelled", reason: "barge" }));
  expect(screen.getByTestId("live").textContent).toBe("");
  const before = socket.sent.length;
  fireEvent.click(screen.getByText("look"));
  expect(JSON.parse(socket.sent[before])).toEqual({ type: "frame", jpeg: "aGVsbG8=", mime: "image/jpeg" });
  expect(JSON.parse(socket.sent[before + 1])).toEqual({ type: "text", text: "what do you see?" });
  fireEvent.click(screen.getByText("end"));
  expect(audio.stopped).toBe(true);
  expect(screen.getByTestId("phase").textContent).toBe("ended");
});

it("keeps a call usable when the mic refuses", async () => {
  const socket = new FakeSocket("ws://x");
  const audio = new FakeAudio();
  audio.startMic = () => Promise.reject(new Error("Permission denied"));
  render(<Probe socket={socket} audio={audio} />);
  fireEvent.click(screen.getByText("start"));
  act(() => socket.onopen?.());
  await act(async () => { await Promise.resolve(); });
  expect(screen.getByTestId("error").textContent).toBe("Permission denied");
  act(() => socket.emit(READY));
  fireEvent.click(screen.getByText("say"));
  expect(socket.last()).toEqual({ type: "text", text: "hello" });
});
```

`barge` twice inside 700 ms is the debounce the spec asks for; add a fourth case only if the
implementation and the first three tests are green and the debounce is still unproven.

- [x] **Step 2: Run them and watch them fail**

Run: `cd kira-chat && npx vitest run src/voice`
Expected: cannot resolve `./protocol.ts`.

- [x] **Step 3: Implement `protocol.ts`**

```ts
import type { ChainRecord, VoiceStatus } from "../contracts.ts";

export type CallEvent =
  | { type: "ready"; session_id: string; voice: VoiceStatus; limits: { max_utterance_s: number; silence_ms: number } }
  | { type: "speech_start" }
  | { type: "speech_end"; discarded: boolean }
  | { type: "transcript"; text: string; final: boolean }
  | { type: "thinking" }
  | { type: "answer_delta"; text: string }
  | { type: "audio_out"; pcm: string; seq: number; text: string }
  | { type: "turn_done"; session_id: string; usage: { prompt_tokens: number; completion_tokens: number }; chain: ChainRecord[] }
  | { type: "cancelled"; reason: string }
  | { type: "error"; code: string; message: string };

export type CallCommand =
  | { type: "hello"; token: string; model: string | null; mode: string | null; session_id: string | null }
  | { type: "audio"; pcm: string }
  | { type: "frame"; jpeg: string; mime: "image/jpeg" }
  | { type: "text"; text: string }
  | { type: "barge" }
  | { type: "close" };

const REQUIRED: Record<CallEvent["type"], string[]> = {
  ready: ["session_id", "voice", "limits"],
  speech_start: [],
  speech_end: ["discarded"],
  transcript: ["text", "final"],
  thinking: [],
  answer_delta: ["text"],
  audio_out: ["pcm", "seq", "text"],
  turn_done: ["session_id", "usage", "chain"],
  cancelled: ["reason"],
  error: ["code", "message"],
};

export function parseEvent(raw: unknown): CallEvent | null {
  if (typeof raw === "string") {
    try {
      raw = JSON.parse(raw);
    } catch {
      return null;
    }
  }
  if (!raw || typeof raw !== "object") return null;
  const candidate = raw as Record<string, unknown>;
  const type = candidate.type;
  if (typeof type !== "string" || !(type in REQUIRED)) return null;
  for (const key of REQUIRED[type as CallEvent["type"]]) {
    if (!(key in candidate)) return null;
  }
  return candidate as CallEvent;
}

export function voiceUrl(baseUrl: string): string {
  const url = new URL(baseUrl || window.location.origin);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.pathname = "/v1/voice";
  url.search = "";
  return url.toString();
}

export function encodePcm(samples: Int16Array): string {
  const bytes = new Uint8Array(samples.buffer, samples.byteOffset, samples.byteLength);
  let binary = "";
  for (let index = 0; index < bytes.length; index += 1) binary += String.fromCharCode(bytes[index]);
  return btoa(binary);
}
```

- [x] **Step 4: Implement `frames.ts` and the worklet**

`frames.ts`:
```ts
export const FRAME_INTERVAL_MS = 4000;

export function frameDue(lastSentAt: number, now: number, hidden = false, interval = FRAME_INTERVAL_MS): boolean {
  return !hidden && now - lastSentAt >= interval;
}

export function jpegFromVideo(video: HTMLVideoElement, canvas: HTMLCanvasElement): string | null {
  if (!video.videoWidth || !video.videoHeight) return null;
  canvas.width = 320;
  canvas.height = 240;
  const context = canvas.getContext("2d");
  if (!context) return null;
  context.drawImage(video, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL("image/jpeg", 0.6).split(",", 2)[1] ?? null;
}
```

`capture-worklet.js`:
```js
class KiraCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.buffer = new Float32Array(1600);
    this.offset = 0;
  }
  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (!channel) return true;
    for (let index = 0; index < channel.length; index += 1) {
      this.buffer[this.offset] = channel[index];
      this.offset += 1;
      if (this.offset === this.buffer.length) {
        const out = new Int16Array(this.buffer.length);
        for (let at = 0; at < out.length; at += 1) {
          out[at] = Math.max(-32768, Math.min(32767, Math.round(this.buffer[at] * 32767)));
        }
        this.port.postMessage(out, [out.buffer]);
        this.offset = 0;
      }
    }
    return true;
  }
}
registerProcessor("kira-capture", KiraCapture);
```

- [x] **Step 5: Implement `audio.ts` — the media seam and its Web Audio class**

```ts
import { encodePcm } from "./protocol.ts";
import { jpegFromVideo } from "./frames.ts";

export interface CallAudioLike {
  startMic(onPacket: (pcm: string) => void, onLevel: (level: number) => void): Promise<void>;
  startCamera(video: HTMLVideoElement | null): Promise<void>;
  stopCamera(): void;
  frame(): string | null;
  play(pcm: string): Promise<void>;
  stopPlayback(): void;
  setMuted(muted: boolean): void;
  stopAll(): void;
}

const MIC: MediaStreamConstraints = {
  audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
  video: false,
};

const BARGE_LEVEL = 0.04;
export const LEVEL_WINDOW = 1024;

function unbase64(text: string): Uint8Array {
  const binary = atob(text);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
  return bytes;
}

export class CallAudio implements CallAudioLike {
  private capture: AudioContext | null = null;
  private micStream: MediaStream | null = null;
  private analyser: AnalyserNode | null = null;
  private meter: number | null = null;
  private meterHandle: number | null = null;
  private ticks = 0;
  private onLevel: ((level: number) => void) | null = null;
  private muted = false;

  private speaker: AudioContext | null = null;
  private queue: Promise<void> = Promise.resolve();
  private sources = new Set<AudioBufferSourceNode>();

  private videoEl: HTMLVideoElement | null = null;
  private cameraStream: MediaStream | null = null;
  private canvas: HTMLCanvasElement | null = null;

  async startMic(onPacket: (pcm: string) => void, onLevel: (level: number) => void): Promise<void> {
    const stream = await navigator.mediaDevices.getUserMedia(MIC);
    if (!stream.getAudioTracks().length) throw new Error("no microphone is available");
    const context = new AudioContext({ sampleRate: 16000 });
    await context.audioWorklet.addModule(new URL("./capture-worklet.js", import.meta.url));
    const source = context.createMediaStreamSource(stream);
    const node = new AudioWorkletNode(context, "kira-capture");
    node.port.onmessage = (event: MessageEvent<Int16Array>) => {
      if (!this.muted) onPacket(encodePcm(event.data));
    };
    // A zero-gain sink keeps the worklet pulled without ever leaking mic sound to the speakers.
    const sink = context.createGain();
    sink.gain.value = 0;
    source.connect(node);
    node.connect(sink);
    sink.connect(context.destination);

    const analyser = context.createAnalyser();
    analyser.fftSize = LEVEL_WINDOW;
    source.connect(analyser);

    this.capture = context;
    this.micStream = stream;
    this.analyser = analyser;
    this.onLevel = onLevel;
    this.pumpMeter();
  }

  private pumpMeter() {
    const analyser = this.analyser;
    if (!analyser) return;
    const data = new Float32Array(analyser.fftSize);
    const tick = () => {
      if (!this.analyser) return;
      this.analyser.getFloatTimeDomainData(data);
      let total = 0;
      for (const sample of data) total += sample * sample;
      const rms = Math.sqrt(total / data.length);
      // Report every crossing of the barge bar, and otherwise throttle so React re-renders the
      // level meter at ~15 fps instead of 60.
      const hot = rms >= BARGE_LEVEL;
      const wasHot = (this.meter ?? 0) >= BARGE_LEVEL;
      this.meter = rms;
      if (hot !== wasHot || this.ticks++ % 4 === 0) this.onLevel?.(rms);
      this.meterHandle = requestAnimationFrame(tick);
    };
    this.meterHandle = requestAnimationFrame(tick);
  }

  async startCamera(video: HTMLVideoElement | null): Promise<void> {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: false, video: { width: 640, height: 480 } });
    if (!video) throw new Error("no video element to attach the camera to");
    this.videoEl = video;
    this.cameraStream = stream;
    video.srcObject = stream;
    video.hidden = false;
    await video.play();
  }

  stopCamera(): void {
    for (const track of this.cameraStream?.getTracks() ?? []) track.stop();
    this.cameraStream = null;
    if (this.videoEl) this.videoEl.srcObject = null;
  }

  frame(): string | null {
    if (!this.cameraStream || !this.videoEl) return null;
    this.canvas ??= document.createElement("canvas");
    return jpegFromVideo(this.videoEl, this.canvas);
  }

  play(pcm: string): Promise<void> {
    const run = this.queue.then(() => this.speak(pcm));
    // A decode failure must not poison the queue: later sentences still play.
    this.queue = run.catch(() => undefined);
    return run;
  }

  private async speak(pcm: string): Promise<void> {
    const context = this.speaker ?? (this.speaker = new AudioContext());
    if (context.state === "suspended") await context.resume();
    const bytes = unbase64(pcm);
    const buffer = await context.decodeAudioData(bytes.buffer as ArrayBuffer);
    const source = context.createBufferSource();
    source.buffer = buffer;
    source.connect(context.destination);
    const done = new Promise<void>((resolve) => {
      source.onended = () => {
        this.sources.delete(source);
        resolve();
      };
    });
    this.sources.add(source);
    source.start();
    return done;
  }

  stopPlayback(): void {
    for (const source of this.sources) {
      try {
        source.stop();
      } catch {
        this.sources.delete(source);
      }
    }
  }

  setMuted(muted: boolean): void {
    this.muted = muted;
    for (const track of this.micStream?.getAudioTracks() ?? []) track.enabled = !muted;
  }

  stopAll(): void {
    if (this.meterHandle !== null) cancelAnimationFrame(this.meterHandle);
    this.meterHandle = null;
    this.onLevel = null;
    this.analyser = null;
    this.stopPlayback();
    this.stopCamera();
    for (const track of this.micStream?.getTracks() ?? []) track.stop();
    this.micStream = null;
    void this.capture?.close().catch(() => undefined);
    this.capture = null;
    void this.speaker?.close().catch(() => undefined);
    this.speaker = null;
    this.queue = Promise.resolve();
  }
}
```

Declare `private meterHandle: number | null = null;` and `private ticks = 0;` with the other fields.
`stopPlayback()` is what the barge path calls: `source.stop()` fires each `onended`, which resolves
the queued `play()` promise and clears the set, so nothing hangs. `stopAll()` is idempotent and safe
to call before anything ever started.

- [x] **Step 6: Implement `useCall.ts`**

Every value the tests read is set here; `deps.audio` and `deps.connect` are the only seams.

```ts
import { useCallback, useEffect, useRef, useState } from "react";
import type { ChainRecord, Mode, VoiceStatus } from "../contracts.ts";
import { parseEvent, voiceUrl } from "./protocol.ts";
import type { CallCommand, CallEvent } from "./protocol.ts";
import { FRAME_INTERVAL_MS, frameDue } from "./frames.ts";
import { CallAudio } from "./audio.ts";
import type { CallAudioLike } from "./audio.ts";

export type CallPhase = "idle" | "connecting" | "listening" | "thinking" | "speaking" | "ended" | "error";

export interface CallOptions {
  baseUrl: string;
  token: string;
  model: string;
  mode: Mode;
}

export interface CallDeps {
  connect?: (url: string) => WebSocket;
  audio?: CallAudioLike;
}

export interface CallEntry {
  id: number;
  role: "user" | "assistant";
  text: string;
}

export interface CallState {
  phase: CallPhase;
  voice: VoiceStatus | null;
  entries: CallEntry[];
  live: string;
  error: string | null;
  muted: boolean;
  camera: boolean;
  level: number;
  sessionId: string | null;
  chain: ChainRecord[];
  videoRef: React.RefObject<HTMLVideoElement | null>;
  start(): Promise<void>;
  end(): void;
  toggleMute(): void;
  toggleCamera(): Promise<void>;
  look(): void;
  say(text: string): void;
}

const SOCKET_OPEN = 1;
const BARGE_RMS = 0.04;
const BARGE_DEBOUNCE_MS = 700;
const LOOK_PROMPT = "what do you see?";

export function useCall(options: CallOptions, deps: CallDeps = {}): CallState {
  const [phase, setPhase] = useState<CallPhase>("idle");
  const [voice, setVoice] = useState<VoiceStatus | null>(null);
  const [entries, setEntries] = useState<CallEntry[]>([]);
  const [live, setLive] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [muted, setMuted] = useState(false);
  const [camera, setCamera] = useState(false);
  const [level, setLevel] = useState(0);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [chain, setChain] = useState<ChainRecord[]>([]);

  const socket = useRef<WebSocket | null>(null);
  const audio = useRef<CallAudioLike | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const liveRef = useRef("");
  const nextId = useRef(1);
  const bargeAt = useRef(0);
  const lastFrame = useRef(0);
  const playing = useRef(0);
  const waitingTurnDone = useRef(false);
  const timer = useRef<number | null>(null);
  const phaseRef = useRef<CallPhase>("idle");
  const cameraRef = useRef(false);

  const config = useRef(options);
  config.current = options;
  const seams = useRef(deps);
  seams.current = deps;

  phaseRef.current = phase;
  cameraRef.current = camera;

  const media = () => {
    if (!audio.current) audio.current = seams.current.audio ?? new CallAudio();
    return audio.current;
  };

  const send = useCallback((command: CallCommand) => {
    const active = socket.current;
    if (active && active.readyState === SOCKET_OPEN) active.send(JSON.stringify(command));
  }, []);

  const push = useCallback((role: CallEntry["role"], text: string) => {
    if (!text.trim()) return;
    setEntries((list) => [...list, { id: nextId.current++, role, text }]);
  }, []);

  const speak = useCallback(async (pcm: string) => {
    playing.current += 1;
    try {
      await media().play(pcm);
    } finally {
      playing.current = Math.max(0, playing.current - 1);
      if (playing.current === 0 && waitingTurnDone.current) {
        waitingTurnDone.current = false;
        setPhase("listening");
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const barged = useCallback(() => {
    bargeAt.current = Date.now();
    playing.current = 0;
    waitingTurnDone.current = false;
    media().stopPlayback();
    send({ type: "barge" });
    setPhase("listening");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [send]);

  const heard = useCallback((rms: number) => {
    setLevel(Math.min(1, rms * 4));
    const now = phaseRef.current;
    if (rms > BARGE_RMS && (now === "thinking" || now === "speaking") && Date.now() - bargeAt.current > BARGE_DEBOUNCE_MS) {
      barged();
    }
  }, [barged]);

  const handle = useCallback((event: CallEvent) => {
    switch (event.type) {
      case "ready":
        setVoice(event.voice);
        setSessionId(event.session_id);
        setPhase("listening");
        break;
      case "speech_start":
        setPhase("listening");
        break;
      case "speech_end":
        if (!event.discarded) setPhase("thinking");
        break;
      case "transcript":
        if (event.final) {
          push("user", event.text);
          setPhase("thinking");
        }
        break;
      case "thinking":
        setPhase("thinking");
        break;
      case "answer_delta":
        liveRef.current += event.text;
        setLive(liveRef.current);
        setPhase("speaking");
        break;
      case "audio_out":
        void speak(event.pcm);
        break;
      case "turn_done": {
        push("assistant", liveRef.current);
        liveRef.current = "";
        setLive("");
        setChain(event.chain);
        setSessionId(event.session_id);
        if (playing.current > 0) waitingTurnDone.current = true;
        else setPhase("listening");
        break;
      }
      case "cancelled":
        liveRef.current = "";
        setLive("");
        playing.current = 0;
        waitingTurnDone.current = false;
        setPhase("listening");
        break;
      case "error":
        setError(`${event.code}: ${event.message}`);
        break;
    }
  }, [push, speak]);

  const stopTimers = useCallback(() => {
    if (timer.current !== null) {
      clearInterval(timer.current);
      timer.current = null;
    }
  }, []);

  const tick = useCallback(() => {
    if (!cameraRef.current || phaseRef.current === "idle" || phaseRef.current === "ended") return;
    if (!frameDue(lastFrame.current, Date.now(), document.hidden, FRAME_INTERVAL_MS)) return;
    const jpeg = media().frame();
    if (!jpeg) return;
    lastFrame.current = Date.now();
    send({ type: "frame", jpeg, mime: "image/jpeg" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [send]);

  const start = useCallback(async () => {
    const now = phaseRef.current;
    if (now === "connecting" || now === "listening" || now === "thinking" || now === "speaking") return;
    setError(null);
    setPhase("connecting");
    const url = voiceUrl(config.current.baseUrl);
    const active = (seams.current.connect ?? ((target: string) => new WebSocket(target)))(url);
    socket.current = active;
    active.onopen = () => {
      send({
        type: "hello",
        token: config.current.token,
        model: config.current.model || null,
        mode: config.current.mode || null,
        session_id: null,
      });
      void media()
        .startMic((pcm) => send({ type: "audio", pcm }), heard)
        .catch((reason: unknown) => {
          setError(reason instanceof Error ? reason.message : String(reason));
        });
    };
    active.onmessage = (message: MessageEvent) => {
      const event = parseEvent(message.data);
      if (event) handle(event);
    };
    active.onerror = () => {
      if (phaseRef.current !== "ended") setError("the voice connection dropped; start the call again");
    };
    active.onclose = () => {
      stopTimers();
      if (phaseRef.current !== "ended" && phaseRef.current !== "idle") setPhase("error");
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [handle, heard, send, stopTimers]);

  const end = useCallback(() => {
    stopTimers();
    send({ type: "close" });
    media().stopAll();
    const active = socket.current;
    socket.current = null;
    if (active && active.readyState === SOCKET_OPEN) {
      active.onclose = null;
      active.close();
    }
    setCamera(false);
    setMuted(false);
    setLevel(0);
    setPhase("ended");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [send, stopTimers]);

  const toggleMute = useCallback(() => {
    const next = !muted;
    setMuted(next);
    media().setMuted(next);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [muted]);

  const toggleCamera = useCallback(async () => {
    if (camera) {
      media().stopCamera();
      setCamera(false);
      stopTimers();
      return;
    }
    try {
      await media().startCamera(videoRef.current);
      setCamera(true);
      lastFrame.current = 0;
      stopTimers();
      timer.current = window.setInterval(tick, 1000);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [camera, stopTimers, tick]);

  const look = useCallback(() => {
    const jpeg = media().frame();
    if (jpeg) {
      lastFrame.current = Date.now();
      send({ type: "frame", jpeg, mime: "image/jpeg" });
    }
    send({ type: "text", text: LOOK_PROMPT });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [send]);

  const say = useCallback((text: string) => send({ type: "text", text }), [send]);

  useEffect(() => () => {
    stopTimers();
    audio.current?.stopAll();
    socket.current?.close();
  }, [stopTimers]);

  return { phase, voice, entries, live, error, muted, camera, level, sessionId, chain, videoRef, start, end, toggleMute, toggleCamera, look, say };
}
```

`media()` and `tick`/`speak` are deliberately outside the dependency arrays (the `eslint-disable`
comments mark them): they close over refs only, so the socket wiring never changes identity. The
`error` phase is reachable — a dropped socket sets it, and `start()` resets it, so a failed call can
be retried without reloading.

- [x] **Step 7: Add `voice()` to the API client**

```ts
voice(): Promise<VoiceStatus> {
  return this.request<VoiceStatus>(`${API_PREFIX}/kira/voice`);
}
```
with `VoiceStatus` added to the imports from `./contracts.ts`.

- [x] **Step 8: Run the tests and typecheck**

```bash
cd kira-chat && npx vitest run src/voice && npx tsc --noEmit
```
Expected: PASS. Fix the hook until both are green.

- [x] **Step 9: Commit**

```bash
git add kira-chat/src/voice kira-chat/src/api.ts
git -c user.name="Kira" -c user.email="kira@localhost" commit -m "feat(chat): voice protocol, frame cadence and call hook"
```

**What changed while executing this task**

1. **The turn-usage type is `WireUsage`, not `Usage`.** Step 3's `CallEvent` named a type that does
   not exist in the published mirror; `tsc` said so immediately. `/v1/voice`'s `turn_done` carries
   `{prompt_tokens, completion_tokens}`, which is exactly `WireUsage` with the optional `estimated`
   left off, so the event now borrows the contract's own name instead of inventing one.
2. **`voiceUrl` uses `API_PREFIX`** rather than the literal `/v1/voice`. The whole point of the drift
   gate is that a version bump moves every caller; a hardcoded socket path would have been the one
   place left behind.
3. **A fifth `look`/`barge` case became a real test.** Step 1's closing line offered a fourth case "if
   the debounce is still unproven" — it was, and the debounce is the spec's answer to a cough
   interrupting a sentence twice. The added case freezes `Date.now` with fake timers, proves one
   `barge` per 700 ms window and then a second after it, which also proves the phase gate: the level
   only interrupts while `thinking` or `speaking`.
4. **`CallAudio` needed a playback generation.** Step 5's `play()` chains every sentence onto a
   promise queue, so `stopPlayback()` silenced only the sentence already sounding — the three still
   queued began right after the user spoke over the answer, which is the exact behaviour barge-in
   exists to prevent. `epoch` bumps on stop and a queued `speak()` returns without playing. Same fix
   shape in `startCamera`: when there is no video element to attach to, the tracks are stopped before
   the throw, so a refused camera does not leave the indicator light on.
5. **The media seam stayed a seam.** Tests inject `deps.connect` and `deps.audio`, so nothing in jsdom
   ever touches `AudioContext`, `AudioWorkletNode` or `navigator.mediaDevices`; the two spans that
   read `phase`/`live`/`error` are the only surface they assert on. 11 voice tests, then the full
   client gate: **23 files, 191 tests**, `tsc --noEmit` clean, build stamped.
6. **Still open, deliberately:** `capture-worklet.js` is only reachable through
   `new URL(…, import.meta.url)`, and nothing imports `useCall` yet, so the module graph — and with it
   the worklet asset — is not in `dist` today. Task 9 wires the screen; the build must then contain the
   worklet, and the browser pass (Task 11) is what proves `addModule` can fetch it. If Vite does not
   emit it, the fix is an explicit `?url` import, not a guess.

---

### Task 9: `#/call` screen, route, nav entry, styles

**Files:**
- Create: `kira-chat/src/screens/CallView.tsx`
- Create: `kira-chat/src/screens/CallScreen.tsx`
- Create: `kira-chat/src/screens/CallView.test.tsx`
- Modify: `kira-chat/src/hash-route.ts` (`ROUTES`)
- Modify: `kira-chat/src/App.tsx` (import, icon, label, screen branch)
- Modify: `kira-chat/src/styles.css` (the `.call-*` block)
- Test: `kira-chat/src/hash-route.test.ts` (route list)

**Interfaces:**
- Consumes: `useCall`, `CallState`, `KiraClient.voice()`.
- Produces: `CallView({ call, status })` — pure presentation; every action comes off `call`, so the view test can drive it with a fixture.
- Produces: `CallScreen({ client, token, model, mode })`.

- [x] **Step 1: Write the failing view test**

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { CallView } from "./CallView.tsx";
import type { CallState } from "../voice/useCall.ts";

function state(overrides: Partial<CallState> = {}): CallState {
  return {
    phase: "idle",
    voice: null,
    entries: [],
    live: "",
    error: null,
    muted: false,
    camera: false,
    level: 0,
    sessionId: null,
    chain: [],
    videoRef: { current: null },
    start: vi.fn(),
    end: vi.fn(),
    toggleMute: vi.fn(),
    toggleCamera: vi.fn(),
    look: vi.fn(),
    say: vi.fn(),
    ...overrides,
  };
}

it("is honest about an off stack and disables start", () => {
  render(
    <CallView
      call={state()}
      status={{
        stt: { mode: "off", available: false, detail: "listening is off for this call" },
        tts: { mode: "off", available: false, detail: "speaking is off for this call" },
        vision: null,
        limits: { max_utterance_s: 30, silence_ms: 700 },
      }}
    />,
  );
  expect(screen.getByText("listen")).toBeTruthy();
  expect(screen.getByText("listening is off for this call")).toBeTruthy();
  expect((screen.getByRole("button", { name: "start call" }) as HTMLButtonElement).disabled).toBe(true);
});

it("starts, shows the transcript and sends typed turns", () => {
  const call = state({ phase: "listening", entries: [{ id: 1, role: "user", text: "hello" }], live: "Hi." });
  render(<CallView call={call} status={null} />);
  fireEvent.click(screen.getByRole("button", { name: "start call" }));
  expect(call.start).toHaveBeenCalled();
  expect(screen.getByText("hello")).toBeTruthy();
  expect(screen.getByText("Hi.")).toBeTruthy();
  fireEvent.change(screen.getByLabelText("typed message"), { target: { value: "a question" } });
  fireEvent.submit(screen.getByLabelText("typed message").closest("form")!);
  expect(call.say).toHaveBeenCalledWith("a question");
});

it("ends the call", () => {
  const call = state({ phase: "speaking" });
  render(<CallView call={call} status={null} />);
  fireEvent.click(screen.getByRole("button", { name: "end call" }));
  expect(call.end).toHaveBeenCalled();
});
```

- [x] **Step 2: Run it and watch it fail**

Run: `cd kira-chat && npx vitest run src/screens/CallView.test.tsx`
Expected: cannot resolve `./CallView.tsx`.

- [x] **Step 3: Implement `CallView.tsx`**

Structure (complete):
```tsx
import { useState } from "react";
import type { FormEvent } from "react";
import type { VoiceStatus } from "../contracts.ts";
import type { CallState } from "../voice/useCall.ts";

const PHASE_LABEL: Record<string, string> = {
  idle: "not connected",
  connecting: "connecting",
  listening: "listening",
  thinking: "thinking",
  speaking: "speaking",
  ended: "call ended",
  error: "needs attention",
};

export function CallView({ call, status }: { call: CallState; status: VoiceStatus | null }) {
  const [draft, setDraft] = useState("");
  const live = call.phase === "connecting" || call.phase === "listening" || call.phase === "thinking" || call.phase === "speaking";
  // An "off" stack cannot carry a conversation in either direction; anything else can, even partly.
  const cannotStart = status !== null && status.stt.mode === "off" && status.tts.mode === "off";

  function submit(event: FormEvent) {
    event.preventDefault();
    const text = draft.trim();
    if (!text) return;
    call.say(text);
    setDraft("");
  }

  return (
    <section className="call">
      <header className="call-head">
        <h2>Call</h2>
        <span className="call-phase mono" data-phase={call.phase}>{PHASE_LABEL[call.phase] ?? call.phase}</span>
        <span className="spacer" />
        <button type="button" onClick={() => void call.start()} disabled={cannotStart}>
          start call
        </button>
      </header>

      <div className="call-body">
        <div className="call-stage">
          <video ref={call.videoRef} className="call-self" muted playsInline hidden={!call.camera} />
          {!call.camera && <div className="call-self-empty">camera off</div>}
          <div className="call-meter" aria-label="microphone level">
            <span style={{ width: `${Math.round(call.level * 100)}%` }} />
          </div>
          <div className="call-controls">
            <button type="button" onClick={call.toggleMute} aria-pressed={call.muted}>{call.muted ? "unmute" : "mute"}</button>
            <button type="button" onClick={() => void call.toggleCamera()} aria-pressed={call.camera}>{call.camera ? "camera off" : "camera on"}</button>
            <button type="button" onClick={call.look} disabled={!call.camera || !live}>look</button>
            <button type="button" onClick={call.end} disabled={!live}>end call</button>
          </div>
          {status && (
            <dl className="call-stack">
              <dt>listen</dt><dd>{status.stt.detail}</dd>
              <dt>speak</dt><dd>{status.tts.detail}</dd>
              <dt>see</dt><dd>{status.vision ? `frames → ${status.vision.provider} · ${status.vision.model}` : "frames stay on this device"}</dd>
            </dl>
          )}
        </div>

        <div className="call-transcript">
          {call.entries.map((entry) => (
            <article key={entry.id} className={`call-msg call-${entry.role}`}>{entry.text}</article>
          ))}
          {call.live && <article className="call-msg call-assistant call-live">{call.live}</article>}
          {call.error && <p className="call-error">{call.error}</p>}
        </div>
      </div>

      <form className="call-typed" onSubmit={submit}>
        <input aria-label="typed message" value={draft} onChange={(event) => setDraft(event.target.value)} placeholder="type instead" />
        <button type="submit" disabled={!live}>send</button>
      </form>
      {call.chain.length > 0 && (
        <p className="call-chain mono">
          {call.chain.filter((record) => record.event === "served").map((record) => `${record.provider} · ${record.model}`).join(" ")}
        </p>
      )}
    </section>
  );
}
```
`cannotStart` is the only thing that greys the start button out: with a live call already running the
hook's own re-entry guard (Task 8 Step 6) ignores a second start, so the button stays honest and a
call that hit `error` can be restarted without reloading. `live` drives the end/look/send buttons and
deliberately excludes `error` and `ended`.

- [x] **Step 4: Implement `CallScreen.tsx`**

```tsx
import { useEffect, useState } from "react";
import type { KiraClient } from "../api.ts";
import type { Mode, VoiceStatus } from "../contracts.ts";
import { useCall } from "../voice/useCall.ts";
import { CallView } from "./CallView.tsx";

export function CallScreen({ client, token, model, mode }: { client: KiraClient; token: string; model: string; mode: Mode }) {
  const [status, setStatus] = useState<VoiceStatus | null>(null);
  const call = useCall({ baseUrl: client.baseUrl, token, model, mode });

  useEffect(() => {
    client.voice().then(setStatus).catch(() => setStatus(null));
  }, [client]);

  return <CallView call={call} status={status ?? call.voice} />;
}
```
If `client.baseUrl` is empty the hook's `voiceUrl` uses the page origin — that is the engine's own static host.

- [x] **Step 5: Route and nav**

`hash-route.ts`: `export const ROUTES = ["chat", "call", "overview", "providers", "models", "sessions", "tools"] as const;`
`App.tsx`: import `Phone` from lucide (already dependent), add `call: Phone` to `NAV_ICONS`, `call: "Call"` to `NAV_LABELS`, import `CallScreen`, and insert the branch before `overview`:
```tsx
          ) : route === "call" ? (
            <CallScreen client={client} token={token} model={model} mode={mode} />
```
Update `hash-route.test.ts` if it enumerates routes.

- [x] **Step 6: Styles**

Append a `.call-*` block to `styles.css`: two-column body above 60rem (stage 380px, transcript flexible), one column below; `.call-self` aspect-ratio 4/3, mirrored (`transform: scaleX(-1)`), border `1px solid var(--line)`, radius 12px; `.call-meter` a 6px track with the accent fill; `.call-msg` reuse the chat bubble look with `max-width: 46rem`; `.call-user` aligned right with `--panel-2`, `.call-assistant` left; `.call-live::after` a blinking caret only when `data-motion="on"`; `.call-stack` a two-column `dt/dd` grid in `--muted`; `.call-error` in `--bad`; `.call-typed` a bottom row matching the chat composer.

- [x] **Step 7: Run the client gates**

```bash
cd kira-chat && npx vitest run && npx tsc --noEmit
```
Expected: all tests pass, including the new view test.

- [x] **Step 8: Commit**

```bash
git add kira-chat/src/screens/CallView.tsx kira-chat/src/screens/CallScreen.tsx kira-chat/src/screens/CallView.test.tsx kira-chat/src/hash-route.ts kira-chat/src/hash-route.test.ts kira-chat/src/App.tsx kira-chat/src/styles.css kira-chat/src/fake-engine.ts kira-chat/src/App.test.tsx kira-chat/src/styles.test.ts
git -c user.name="Kira" -c user.email="kira@localhost" commit -m "feat(chat): call screen with self-view, transcript and honest stack status"
```

### Task 9 execution notes

Written during execution; each delta is the reason the plan and the code differ.

1. **The `.call-*` block went in `styles.css`, not a sibling file.** It was first drafted as
   `styles-call.css`, which built and passed every test while shipping the call screen unstyled —
   `main.tsx` imports `./styles.css` and nothing else, and no test looked at the second file. The
   block is now the tail of `styles.css`, and `styles.test.ts` gained a `call screen` describe that
   reads the same `readFileSync("src/styles.css")` the build consumes: the mirrored 4/3 self-view, the
   fixed 380px stage column, the motion-off caret rule, and "no literal colour in the call block",
   which is what makes the seven themes and the agent shell apply to it.
2. **`CallView.test.tsx` has six tests, not three.** Beyond the plan's off-stack/transcript/end
   cases: `see` names the provider a frame would go to while `look` stays disabled without a camera;
   an `error` phase prints its own sentence and keeps `start call` enabled while `end call` is dead
   (that is the hook's restart path, and the view must not trap the user); the chain line prints the
   `served` row and hides every other event.
3. **`fake-engine.ts` grew `voiceFixture()`** with the engine's two verbatim missing-install strings,
   and `App.test.tsx` asserts `#/call` is one of the routes rendered in both shells *and* that the
   screen asks `GET {API_PREFIX}/kira/voice` before anyone speaks — the screen must not promise a
   call to a machine that has no whisper or piper.
4. **`styles.test.ts` is 41 tests, `npm run check` is 24 files / 199 tests**, and the built CSS is
   46.02 kB with the call block inside it.
5. **The worklet ships inlined.** Vite answers `new URL("./capture-worklet.js", import.meta.url)`
   under the asset inline limit with a `data:text/javascript;base64,` URL, so there is no separate
   `dist/assets/*-worklet.js`. `audioWorklet.addModule` accepts it in Chromium; the browser pass
   (Task 11) is the first place that is actually proven, and it is the one thing here a unit test
   cannot cover.

---

### Task 10: Documentation

**Files:**
- Modify: `README.md` (a Voice & call section; refresh the gate line)
- Modify: `docs/PROVENANCE.md` (mechanism table rows)
- Modify: `docs/ROADMAP.md` (sub-project 6 status, completion arithmetic)
- Modify: `docs/specs/2026-10-28-kira-realtime-call-design.md` (Status line → implemented)

- [x] **Step 1: README**

Add after the tools/agent section:
```markdown
## Voice and video call

`#/call` runs a live voice loop with the mic and speakers of this machine:
16 kHz PCM → server VAD → speech-to-text → the same router and agent loop as chat → one WAV per
sentence back. Speaking over the answer stops it.

- **Listen / speak are local-first.** `faster-whisper` (optional extra) and a Piper binary under
  `<data>/voice/piper` are used when present. `kira-engine voice doctor` prints exactly what is
  installed and what the engine expects.
- **BYOK second.** `voice.stt: remote` / `voice.tts: remote` name an `openai_compat` provider and use
  its key from the Windows Credential Locker. The engine never silently falls back from local to
  remote.
- **Video is a self-view plus frames.** The webcam stays in the browser; one JPEG every 4 s is
  attached to the next thing you say, and only if the serving provider's stanza says `vision: true`.
  Frames are never written to disk or chat history.
- **No tools on a call.** An approval needs the confirm secret; a microphone is not a second factor.
```

Update the verification line with the real counts after Task 11 (placeholders are not allowed, so write the numbers from the gate output).

- [x] **Step 2: PROVENANCE**

Add rows: energy VAD (own implementation, threshold + floor arithmetic from the spec); faster-whisper (optional dependency, no code copied); Piper (external binary invoked by argv, no code copied); OpenAI audio endpoints (wire shape only, no SDK); Web Audio worklet (browser API). State explicitly that no donor project's call code was read or reused.

- [x] **Step 3: ROADMAP**

Mark sub-project 6 **done** with its commit range; note that the video half is "self-view + vision frames", and that avatar (#11) remains separate. Update the completion percentage arithmetic at the bottom using the line the file already uses.

- [x] **Step 4: Spec status**

Change the Status line to `Status: implemented on feat/realtime-call; browser pass in docs/qa/call-browser-pass.md.`

- [x] **Step 5: Commit**

```bash
git add README.md docs/PROVENANCE.md docs/ROADMAP.md docs/specs/2026-10-28-kira-realtime-call-design.md
git -c user.name="Kira" -c user.email="kira@localhost" commit -m "docs: voice and video call — stack, privacy and how to install it"
```

### Task 10 execution notes

1. **`PROVENANCE.md` is at the repo root, not `docs/PROVENANCE.md`.** The `git add` line above would
   have committed nothing; the real path is what `README.md`'s "no verbatim donor code" bullet points
   at, and that link is the only one a reader follows.
2. **The README grew past the plan's draft** with the three claims a unit test cannot check but a
   reader needs: the WebSocket has no endpoint-table row *because* `test_the_readme_endpoint_table_matches_the_app`
   compares that table to `APIRoute.methods`, and a `WebSocketRoute` has none — so documenting the
   handshake there would fail the gate that proves the rest of the table; the token rides the `hello`
   frame and is closed with 4401 after five seconds (`app.py:563`); and the mic is opened mono with
   `echoCancellation`/`noiseSuppression`/`autoGainControl` at a 16 kHz capture context (`voice/audio.ts:24,66`).
3. **ROADMAP arithmetic corrected in place, on the record.** The line this replaced printed `21 / 42`
   while its own remaining-estimate list summed to 22, i.e. 43. With unit 6's three milestones
   delivered the honest pair is **24 / 43 ≈ 56 %**, and the note says the percentage is provisional on
   Task 11 — nothing in unit 6 has ever touched a real microphone, because neither faster-whisper nor
   Piper is installed on this machine.
4. **Two deductions written rather than glossed:** wake word did not ship (push-to-start instead, with
   the privacy reason and the two named models that would change that decision), and #6 ran before #4,
   so the call keeps a `HISTORY_TURNS` window per socket and writes transcripts to `messages` but
   recalls nothing.
5. **Screens are seven now**, in both the dashboard table and the shell-modes prose; the stale "five
   screens" sentence in §Two modes went with it. Gate line reads 342 (+1 skipped) / 24 files, 199 tests
   / `v2, 56 schemas, 6 chunk types, 15 chain events` — copied from the runs, not predicted.

---

### Task 11: The browser pass

**Files:**
- Create: `docs/qa/call-browser-pass.md`

**Setup:** the lab from previous passes, with fake media devices:
```bash
cd "D:/1. Ai/project-kira (kimi)/Kira"
kira-engine/.venv/Scripts/python tools/kira_lab.py --port 8916 --mock-port 8996 --data-dir "$TEMP/kira-lab-call/.kira-data"
```
Chromium flags: `--use-fake-device-for-media-stream --use-fake-ui-for-media-stream`
plus the usual `--remote-debugging-port`, headless if the build supports fake devices headless
(if `getUserMedia` fails headless, run headed and record that in the doc).

- [x] **Step 1: Seed and load**

Seed only `kira.base` and `kira.token` in `localStorage` (the sanctioned keys), reload, open `#/call`. Record the three status rows verbatim.

- [x] **Step 2: Start with the fake mic**

Click **start call**. Expected: the browser prompt is auto-accepted by the flag; phase becomes
`listening`; the meter moves with the fake tone. The tone crosses the VAD bar, so `speech_start`
arrives, then after 30 s the utterance commits and the engine answers with
`stt_unavailable` (local faster-whisper is not installed in the lab). Record the exact error code and
message. This proves the mic → worklet → WS → VAD path on real browser audio.

- [x] **Step 3: Typed path**

Send "say hello" from the typed input. Expected: user entry, assistant entry, and either
`audio_out` (if Piper is present) or `tts_unavailable` followed by the answer still on screen.
Record which.

- [x] **Step 4: Camera and frames**

Turn the camera on. Expected: the self-view shows Chromium's test pattern (mirrored by CSS). Send a
frame by waiting 4 s, then inspect the engine's chain for `images_dropped` (no provider declares
vision in the lab) or `images_attached` (if the lab config declares it). Record the chain line.

- [x] **Step 5: Barge and end**

While an answer is streaming (use a slow mock route or a held stream), speak into the fake device;
expected: playback stops, transcript shows the partial answer as `interrupted` in `#/sessions`, and
the phase returns to `listening`. End the call; expected: socket closed, tracks stopped (the meter
stops), no `localStorage` keys added beyond the sanctioned ones.

- [x] **Step 6: Write the doc**

`docs/qa/call-browser-pass.md` with: engine/lab command, browser build, viewport, the table of
checks with observed values (exact strings), findings (fix each in its own commit), and a "Not
exercised" section: real STT/TTS models, non-Chromium browsers, widths below 1440 px, echo in a real
room, >30 s monologues.

- [x] **Step 7: Commit**

```bash
git add docs/qa/call-browser-pass.md
git -c user.name="Kira" -c user.email="kira@localhost" commit -m "qa: call browser pass — fake devices, VAD, typed turn, frames, barge"
```

### Task 11 execution notes

1. **Step 2's expectation was wrong, and the browser's own audio is what said so.** The plan predicted
   `speech_start`, then a commit at 30 s, then `stt_unavailable`. What actually happened was
   `speech_start` and then nothing for 25 s. A second script recorded the PCM the page put on the wire
   (429 packets, each exactly 3200 bytes of 16 kHz mono Int16) and replayed it into `EnergyVad`: the
   detector counted only frames *above the bar* toward `max_utterance_s`, so audio that flickers across
   it — which is exactly what Chromium's tone does — never accumulated 30 s of anything and the
   utterance stayed open forever. The cap is now a wall clock over every frame since the opening
   (`ce240de`, vad.py:87), and the buffer it was filling, which had reached 786 KB with a 64 KB
   per-packet limit, is capped by the same arithmetic (`max_utterance_bytes`, call.py:41).
2. **Step 2's other half was a client-visible strand.** When the capped utterance finally committed and
   STT raised, the engine sent `error` and stopped: `speech_end` had already promised work, so the
   screen sat on "thinking" over a call that had gone back to listening. A failed or empty attempt now
   ends with `cancelled` — the one message `useCall` reads as "back to listening" (`19fdf36`,
   call.py:186). Recorded in the spec's §5.2 and the wire table, where `cancelled` used to mean only
   "barge or close".
3. **25 s of capture cannot demonstrate a 30 s cap.** The first recording was too short to prove the
   fixed detector's boundary, so the pass re-ran with a 42 s hold and replayed it: `start` at 0.5 s,
   `end` at 30.5 s with `duration_ms` 30000, `start` again at 30.6 s. That reopen is deliberate and is
   the reason a noisy room now costs one wasted transcription per 30 s instead of a jammed call.
4. **Fake devices need a reload, not a hash navigate.** `Page.navigate` to a URL differing only by
   hash leaves the page — and the app's one-time read of `kira.base` / `kira.token` / `kira.shell` —
   untouched, so seeded localStorage appeared to do nothing and the first agent-shell row measured
   `shell: "chat"`. `Page.reload` after seeding fixed both; the row in the doc is the corrected
   measurement, and the doc labels it as a script defect, not a product one.
5. **The barge row could not be exercised as written** (Step 5): with no TTS installed there is no
   answer audio for the client to interrupt, so the pass recorded what *did* happen — the fake mic
   barging on itself, which is how the strand in note 2 surfaced — and left barge-in over a spoken
   answer in the "Not exercised" list, covered by `test_voice_call.py` and `useCall.test.tsx`.
6. **The privacy claim was checked in the database, not asserted.** After 40 s of real captured audio
   and two frames, the store held one session, four rows (both typed turns), and no row containing
   `/9j/`, `data:image` or `image/jpeg`; `messages` has no images column at all, and `voice/models` and
   `voice/tmp` were empty. That, plus `images_dropped` opening both assistant chains, is row 12.
7. **Gate line after the pass:** 348 engine tests (+1 skipped) · 203 chat tests across 24 files ·
   `v2, 56 schemas, 6 chunk types, 15 chain events`. The README's Checks block and the ROADMAP's
   header row now print those numbers.

---

### Task 12: Gates, build, and merge

- [x] **Step 1: Engine**

```bash
cd kira-engine && .venv/Scripts/python -m pytest -q
```
Expected: all pass, 1 skipped (the live suite).

- [x] **Step 2: Client + build**

```bash
cd ../kira-chat && npm run check
```
Expected: tsc clean, all vitest files pass, Vite build writes `dist` and `kira-build.json`.

- [x] **Step 3: Drift**

```bash
cd .. && node kira-contracts/check-drift.mjs
```
Expected: `kira-contracts OK — v2, N schemas, 6 chunk types, 15 chain events`.

- [x] **Step 4: Merge**

```bash
git switch master
git -c user.name="Kira" -c user.email="kira@localhost" merge --no-ff feat/realtime-call
```
Re-run all three gates on the merged tree. Then delete the branch. Never push.

### Task 12 execution notes

1. **All three gates ran twice — once on the branch before the merge, once on `master` after it** — and
   printed the same numbers both times: `348 passed, 1 skipped` (engine), `24 files, 203 tests` plus a
   clean `tsc --noEmit` and a `dist` build stamped `{"api_version":1,"contract_version":2,"api_prefix":"/v1"}`
   (client), `v2, 56 schemas, 6 chunk types, 15 chain events` (drift). The README Checks block, the
   ROADMAP header row and the spec Status line carry those numbers.
2. **`git merge --no-ff feat/realtime-call` with the branch name as an argument.** The plan's literal
   command relies on the branch being the merge target already; run without it and git looks for an
   upstream and dies with `fatal: No remote for the current branch` — this repo has no remote, by design.
3. **The merge is `8ff4e17`, 15 commits from `afb98f4`.** Nothing in it touches the contract version or
   `API_VERSION`; `WS /v1/voice` is still prose, not a route row, so the README-vs-engine gate is
   unaffected. `feat/realtime-call` is deleted after the merge; the work lives on `master`.
4. **Not pushed, and not to be.** No remote is configured, and the ground rules in `docs/ROADMAP.md`
   keep the engine on loopback only.

---

## Self-review notes

- Spec §2 promises no server-side video; Task 6 stores one JPEG in memory per call and never writes it.
- Spec §4.4 tools off: Task 6 passes an empty `ToolRegistry` and `approvals=None`.
- Spec §5.3 local model download: Task 3 downloads into `<data>/voice/models` on first transcription; the status detail only names the missing package.
- Spec §6 status shape: Tasks 5 and 7 produce and publish it; `voice doctor` prints the same dict.
- Spec §9 invariants: token check is Task 6; framing of temp files in Tasks 3/4; nothing secret in status.
- The one place this plan knowingly leaves a step as prose is Task 8's hook body — that is deliberate: the hook is written against the test in the same task, and `tsc` plus the test are the completion bar. Every other step carries runnable code.
