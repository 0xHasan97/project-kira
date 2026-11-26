"""Which engines a call actually gets, read straight from config plus what is installed.

The rule this module exists to enforce: local-first is a choice, not a fallback chain. A stage that
is configured `local` stays `local` and reports what is missing; it never quietly becomes a remote
call, and a remote stage is used only with the named provider's own key from the Locker.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import Config, VoiceConfig
from ..overrides import MergedView
from ..providers.registry import ProviderRegistry
from ..studio import Studio, find_studio
from .stt import LocalStt, OffStt, RemoteStt, SpeechToText, UnavailableStt, WhisperCppStt
from .tts import KokoroTts, LocalTts, OffTts, RemoteTts, TextToSpeech, UnavailableTts


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


def _whisper_binary(config: Config, studio: Studio | None) -> Path | None:
    explicit = os.environ.get("KIRA_WHISPER_BACKEND", "").strip()
    if explicit:
        path = Path(explicit).expanduser()
        return path if path.is_file() else None
    local = config.data_dir / "voice" / "whisper"
    if local.is_dir():
        for candidate in sorted(local.rglob("whisper-cli*")):
            if candidate.is_file():
                return candidate
    if studio is not None:
        engines = studio.whisper_engines()
        if engines:
            return engines[0]
    return None


def _whisper_model(config: Config, studio: Studio | None, wanted: str) -> Path | None:
    explicit = os.environ.get("KIRA_WHISPER_MODEL", "").strip()
    if explicit:
        path = Path(explicit).expanduser()
        return path if path.is_file() else None
    roots = [config.data_dir / "voice" / "models", config.data_dir / "voice" / "whisper" / "models"]
    found: list[Path] = []
    for root in roots:
        if root.is_dir():
            found += sorted(p for p in root.iterdir() if p.is_file() and p.suffix.lower() == ".bin")
    if studio is not None:
        found += studio.speech_models()
    if not found:
        return None
    # `base.en` names a faster-whisper model; the whisper.cpp twin is `ggml-base.en.bin`, so a
    # substring match is the honest join between the two naming schemes.
    for path in found:
        if wanted and (wanted in path.stem or wanted.replace(".", "-") in path.stem):
            return path
    return found[0]


def _whisper_cpp(config: Config, studio: Studio | None) -> WhisperCppStt | None:
    binary = _whisper_binary(config, studio)
    model = _whisper_model(config, studio, config.voice.stt_model)
    if binary is None and model is None:
        return None
    placeholder_bin = binary or (config.data_dir / "voice" / "whisper" / "whisper-cli")
    placeholder_model = model or (config.data_dir / "voice" / "whisper" / "ggml-base.en.bin")
    return WhisperCppStt(placeholder_bin, placeholder_model, config.data_dir / "voice" / "tmp")


def _build_stt(cfg: VoiceConfig, config: Config, registry: ProviderRegistry) -> SpeechToText:
    if cfg.stt == "off":
        return OffStt()
    if cfg.stt == "local":
        studio = find_studio(config.data_dir)
        if cfg.stt_engine in ("auto", "whisper_cpp"):
            whisper = _whisper_cpp(config, studio)
            if whisper is not None and whisper.available:
                return whisper
            if cfg.stt_engine == "whisper_cpp":
                return UnavailableStt("local", whisper.detail if whisper is not None else "whisper.cpp is not installed")
        return LocalStt(cfg.stt_model, config.data_dir / "voice")
    provider, problem = _remote_audio_provider(config, cfg.stt_provider)
    if provider is None:
        return UnavailableStt("remote", problem)
    key = registry.key_for(provider.name)
    if not key:
        return UnavailableStt("remote", f"provider '{provider.name}' has no key in the Locker")
    return RemoteStt(provider.name, provider.base_url, cfg.stt_remote_model, key, registry.client)


def _kokoro(config: Config, studio: Studio | None) -> KokoroTts | None:
    if studio is None:
        return None
    node = studio.node()
    if node is None:
        return None
    manifest = studio.kokoro_config()
    return KokoroTts(
        node,
        studio.kokoro_worker(),
        studio.tts_runtime(),
        studio.tts_cache_dir,
        config.data_dir / "voice" / "tmp",
        model_id=str(manifest.get("modelId") or "onnx-community/Kokoro-82M-v1.0-ONNX"),
        dtype=str(manifest.get("dtype") or "q8"),
        voice=config.voice.kokoro_voice,
    )


def _build_tts(cfg: VoiceConfig, config: Config, registry: ProviderRegistry) -> TextToSpeech:
    if cfg.tts == "off":
        return OffTts()
    if cfg.tts == "local":
        base = config.data_dir
        studio = find_studio(config.data_dir)
        if cfg.tts_engine in ("auto", "kokoro"):
            kokoro = _kokoro(config, studio)
            if kokoro is not None and kokoro.available:
                return kokoro
            if cfg.tts_engine == "kokoro":
                return UnavailableTts("local", kokoro.detail if kokoro is not None else "Kokoro is not installed")
        return LocalTts(base / cfg.piper_bin, base / cfg.piper_model, base / "voice" / "tmp")
    provider, problem = _remote_audio_provider(config, cfg.tts_provider)
    if provider is None:
        return UnavailableTts("remote", problem)
    key = registry.key_for(provider.name)
    if not key:
        return UnavailableTts("remote", f"provider '{provider.name}' has no key in the Locker")
    return RemoteTts(provider.name, provider.base_url, cfg.tts_model, cfg.tts_voice, key, registry.client)


def _pick_vision(config: Config, registry: ProviderRegistry, view: Callable[[], MergedView]) -> dict[str, str] | None:
    """The cheapest provider whose own stanza says it takes frames, that can actually be called."""
    for provider in sorted(view().providers, key=lambda item: (item.priority, item.name)):
        if not provider.enabled or not provider.base.vision or not provider.models:
            continue
        if provider.key_ref and not registry.key_for(provider.name):
            continue
        return {"provider": provider.name, "model": provider.models[0]}
    return None


def build_voice_stack(config: Config, registry: ProviderRegistry, view: Callable[[], MergedView]) -> VoiceStack:
    cfg = config.voice
    return VoiceStack(
        stt=_build_stt(cfg, config, registry),
        tts=_build_tts(cfg, config, registry),
        vision=_pick_vision(config, registry, view),
        limits={"max_utterance_s": cfg.max_utterance_s, "silence_ms": cfg.silence_ms},
    )
