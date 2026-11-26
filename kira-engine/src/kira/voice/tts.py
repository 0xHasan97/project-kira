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
    """An OpenAI-compatible speech endpoint, with the user's own key from the Locker."""

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
            raise VoiceError("tts_failed", f"{self.provider} speech failed: HTTP {response.status_code}")
        return response.content


class UnavailableTts:
    """A configured voice that cannot run: the reason stays on screen."""

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


class KokoroTts:
    """Kokoro ONNX through Portable AI Studio's Node worker, with no cloud and no key.

    The worker is the studio's own: it reads one JSON payload on stdin, writes a WAV, and prints a
    small JSON summary. `kokoro-js` downloads the ONNX weights into `cache_dir` on the first call;
    Kira never fetches them itself and the status line says so before the first sentence.
    """

    mode = "local"

    def __init__(
        self,
        node: Path,
        worker: Path,
        runtime: Path,
        cache_dir: Path,
        tmp_dir: Path,
        *,
        model_id: str = "onnx-community/Kokoro-82M-v1.0-ONNX",
        dtype: str = "q8",
        voice: str = "af_heart",
        speed: float = 1.0,
        timeout_s: float = 300.0,
    ) -> None:
        self.node = node
        self.worker = worker
        self.runtime = runtime
        self.cache_dir = cache_dir
        self.tmp_dir = tmp_dir
        self.model_id = model_id
        self.dtype = dtype
        self.voice = voice
        self.speed = speed
        self.timeout_s = timeout_s
        tmp_dir.mkdir(parents=True, exist_ok=True)
        cache_dir.mkdir(parents=True, exist_ok=True)

    @property
    def available(self) -> bool:
        return (
            self.node.is_file()
            and self.worker.is_file()
            and (self.runtime / "node_modules" / "kokoro-js").is_dir()
        )

    @property
    def detail(self) -> str:
        if not self.available:
            return (
                "Kokoro is not installed — a Portable AI Studio's app/tts-runtime supplies it, or set "
                "voice.tts_engine: piper"
            )
        return f"kokoro · {self.model_id} · {self.voice}"

    async def speak(self, text: str) -> bytes:
        if not self.available:
            raise VoiceError("tts_unavailable", self.detail)
        out = self.tmp_dir / f"{uuid4().hex}.wav"
        payload = {
            "text": text,
            "output": str(out),
            "voice": self.voice,
            "modelId": self.model_id,
            "dtype": self.dtype,
            "speed": self.speed,
            "cacheDir": str(self.cache_dir),
        }
        import json
        import os

        env = dict(os.environ)
        env["TTS_RUNTIME"] = str(self.runtime)
        process = await asyncio.create_subprocess_exec(
            str(self.node),
            str(self.worker),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(json.dumps(payload).encode("utf-8")), self.timeout_s
            )
        except asyncio.CancelledError:
            process.kill()
            raise
        except asyncio.TimeoutError as exc:
            process.kill()
            raise VoiceError("tts_failed", "Kokoro timed out") from exc
        try:
            if process.returncode != 0 or not out.is_file():
                detail = stderr.decode("utf-8", "replace").strip()[-300:] or f"exit {process.returncode}"
                raise VoiceError("tts_failed", f"Kokoro failed: {detail}")
            wav = out.read_bytes()
            if not wav:
                raise VoiceError("tts_failed", "Kokoro produced no audio")
            return wav
        finally:
            out.unlink(missing_ok=True)
