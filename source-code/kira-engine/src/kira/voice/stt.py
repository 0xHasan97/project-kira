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
        try:
            response = await self.client.post(
                f"{self.base_url}/audio/transcriptions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                files={"file": ("utterance.wav", wav, "audio/wav")},
                data={"model": self.model, "response_format": "json"},
                timeout=self.timeout_s,
            )
        except httpx.HTTPError as exc:
            raise VoiceError("stt_failed", f"{self.provider} transcription is unreachable: {type(exc).__name__}") from exc
        if response.status_code >= 400:
            # The status is the whole story: neither the key nor the body crosses into a message.
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


class WhisperCppStt:
    """whisper.cpp's own CLI, the engine Portable AI Studio ships.

    `prefix` is the same test seam `LocalTts` has: a fake worker can run through the interpreter
    while the argv shape the real `whisper-cli` takes stays unchanged.
    """

    mode = "local"

    def __init__(
        self,
        whisper_bin: Path,
        model: Path,
        tmp_dir: Path,
        timeout_s: float = 120.0,
        *,
        prefix: tuple[str, ...] = (),
    ) -> None:
        self.whisper_bin = whisper_bin
        self.model = model
        self.tmp_dir = tmp_dir
        self.timeout_s = timeout_s
        self.prefix = prefix
        tmp_dir.mkdir(parents=True, exist_ok=True)

    @property
    def available(self) -> bool:
        return self.whisper_bin.is_file() and self.model.is_file()

    @property
    def detail(self) -> str:
        if not self.available:
            return (
                "whisper.cpp is not installed — put whisper-cli and a ggml .bin under "
                "<data>/voice/whisper, or install Portable AI Studio beside the project"
            )
        return f"whisper.cpp · {self.model.stem}"

    def _argv(self, wav: Path, base: Path) -> list[str]:
        return [
            *self.prefix,
            str(self.whisper_bin),
            "-m",
            str(self.model),
            "-f",
            str(wav),
            "-otxt",
            "-of",
            str(base),
            "-nt",
        ]

    async def transcribe(self, wav: bytes) -> str:
        if not self.available:
            raise VoiceError("stt_unavailable", self.detail)
        stem = uuid4().hex
        wav_path = self.tmp_dir / f"{stem}.wav"
        base = self.tmp_dir / stem
        txt_path = base.with_suffix(".txt")
        wav_path.write_bytes(wav)
        process = await asyncio.create_subprocess_exec(
            *self._argv(wav_path, base),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), self.timeout_s)
        except asyncio.CancelledError:
            process.kill()
            raise
        except asyncio.TimeoutError as exc:
            process.kill()
            raise VoiceError("stt_failed", "whisper.cpp timed out") from exc
        finally:
            wav_path.unlink(missing_ok=True)
        try:
            if process.returncode != 0:
                detail = stderr.decode("utf-8", "replace").strip()[:200] or f"exit {process.returncode}"
                raise VoiceError("stt_failed", f"whisper.cpp failed: {detail}")
            text = txt_path.read_text(encoding="utf-8", errors="replace") if txt_path.is_file() else ""
            if not text.strip():
                text = stdout.decode("utf-8", "replace")
            return " ".join(text.split()).strip()
        finally:
            txt_path.unlink(missing_ok=True)
