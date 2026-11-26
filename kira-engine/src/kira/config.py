from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .errors import ConfigError

PROVIDER_KINDS = ("openai_compat", "anthropic", "gemini")
MODES = ("AUTO", "FAST", "POWERFUL", "CUSTOM")
TIERS = ("fast", "powerful")
VOICE_MODES = ("local", "remote", "off")
STT_ENGINES = ("auto", "faster_whisper", "whisper_cpp")
TTS_ENGINES = ("auto", "piper", "kokoro")

DEFAULT_PORT = 8901


@dataclass
class ProviderConfig:
    name: str
    kind: str
    base_url: str
    models: list[str]
    tier: str = "fast"
    key_ref: str = ""
    priority: int = 100
    monthly_token_cap: int | None = None
    #: True only when the user's stanza says the chosen model accepts image parts.
    vision: bool = False
    #: Context window size for the models this provider serves (tokens). Optional; if missing,
    #: the engine cannot compute a context meter. Only the first model's window is used.
    context_window: int | None = None

    def __post_init__(self) -> None:
        if self.kind not in PROVIDER_KINDS:
            raise ConfigError(f"provider '{self.name}' kind '{self.kind}' is not one of {PROVIDER_KINDS}")
        if not self.models:
            raise ConfigError(f"provider '{self.name}' declares no models")
        if self.tier not in TIERS:
            raise ConfigError(f"provider '{self.name}' tier '{self.tier}' is not one of {TIERS}")
        if not self.base_url.startswith(("http://", "https://")):
            raise ConfigError(f"provider '{self.name}' base_url must be http(s)")
        cap = self.monthly_token_cap
        if cap is not None and (isinstance(cap, bool) or not isinstance(cap, int) or cap <= 0):
            raise ConfigError(f"provider '{self.name}' monthly_token_cap must be a positive integer")
        if self.context_window is not None and (not isinstance(self.context_window, int) or self.context_window <= 0):
            raise ConfigError(f"provider '{self.name}' context_window must be a positive integer")


@dataclass
class VoiceConfig:
    """How a call listens and speaks. Nothing secret lives here: a remote stage names a provider,
    and that provider's key stays in the Locker. Existence of the local engines is a runtime status,
    never a startup error, so a missing Piper still leaves chat serving."""

    stt: str = "local"
    #: auto picks whisper.cpp when a studio provides it, then faster-whisper.
    stt_engine: str = "auto"
    stt_model: str = "base.en"
    stt_provider: str = "openai"
    stt_remote_model: str = "whisper-1"
    tts: str = "local"
    #: auto picks Kokoro when a studio provides its runtime, then Piper.
    tts_engine: str = "auto"
    tts_provider: str = "openai"
    tts_model: str = "tts-1"
    tts_voice: str = "alloy"
    kokoro_voice: str = "af_heart"
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
        if self.stt_engine not in STT_ENGINES:
            raise ConfigError(f"voice.stt_engine '{self.stt_engine}' is not one of {STT_ENGINES}")
        if self.tts_engine not in TTS_ENGINES:
            raise ConfigError(f"voice.tts_engine '{self.tts_engine}' is not one of {TTS_ENGINES}")
        if not (0.002 <= self.vad_threshold <= 0.5):
            raise ConfigError("voice.vad_threshold must be between 0.002 and 0.5")
        if not (200 <= self.silence_ms <= 2000):
            raise ConfigError("voice.silence_ms must be between 200 and 2000")
        if not (5 <= self.max_utterance_s <= 120):
            raise ConfigError("voice.max_utterance_s must be between 5 and 120")
        if not (0.0 <= self.temperature <= 2.0):
            raise ConfigError("voice.temperature must be between 0 and 2")


@dataclass
class Config:
    data_dir: Path
    host: str = "127.0.0.1"
    port: int = DEFAULT_PORT
    default_mode: str = "AUTO"
    max_agent_steps: int = 6
    request_timeout_s: float = 120.0
    workspace_dir: str = ""
    approval_timeout_s: float = 120.0
    checkpoint_retention: int = 50
    providers: list[ProviderConfig] = field(default_factory=list)
    voice: VoiceConfig = field(default_factory=VoiceConfig)

    def __post_init__(self) -> None:
        self.data_dir = Path(self.data_dir)
        if self.default_mode not in MODES:
            raise ConfigError(f"default_mode '{self.default_mode}' is not one of {MODES}")
        if self.host not in ("127.0.0.1", "localhost", "::1"):
            raise ConfigError("Kira binds loopback only; set host to 127.0.0.1")
        names = [p.name for p in self.providers]
        if len(names) != len(set(names)):
            raise ConfigError("provider names must be unique")
        if not (1 <= self.approval_timeout_s <= 600):
            raise ConfigError("approval_timeout_s must be between 1 and 600")
        if not (1 <= self.checkpoint_retention <= 500):
            raise ConfigError("checkpoint_retention must be between 1 and 500")
        workspace = self.workspace_path
        if workspace == Path(workspace.anchor):
            raise ConfigError("workspace_dir must not be the filesystem root")
        if workspace == self.data_dir.resolve():
            raise ConfigError("workspace_dir must not be the data directory")

    @property
    def by_name(self) -> dict[str, ProviderConfig]:
        return {p.name: p for p in self.providers}

    @property
    def db_path(self) -> Path:
        return self.data_dir / "kira.db"

    @property
    def workspace_path(self) -> Path:
        raw = Path(self.workspace_dir) if self.workspace_dir else Path("workspace")
        return (raw if raw.is_absolute() else self.data_dir / raw).resolve()

    @property
    def config_path(self) -> Path:
        return self.data_dir / "config.yaml"

    @property
    def log_path(self) -> Path:
        return self.data_dir / "logs" / "engine.log"

    @property
    def characters_dir(self) -> Path:
        """The character library, and deliberately not under `workspace_path`.

        A character is 45 MB of bytes the agent is not allowed to edit and the user did not ask the
        workspace to hold; the name matches `characters.CHARACTERS_FOLDER_NAME`, which is what writes it.
        """
        return self.data_dir / "characters"

    @property
    def skills_dir(self) -> Path:
        """The user's skill pack: `<data>/skills`, read at startup and shadowing the builtin pack by name.

        A skill is text, not code, so this is the one part of `data_dir` an imported pack may add files to
        without a workspace checkpoint or a licence question about binaries.
        """
        return self.data_dir / "skills"

    def supports_model(self, model: str) -> bool:
        return any(model in p.models for p in self.providers)


def resolve_data_dir(explicit: str | Path | None = None) -> Path:
    if explicit:
        return Path(explicit)
    env = os.environ.get("KIRA_DATA_DIR")
    if env:
        return Path(env)
    if getattr(sys, "frozen", False):
        # An installed copy must not write next to the exe (usually Program Files): the
        # checkout-relative default would resolve into the install folder.
        base = os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local"
        return Path(base) / "Kira"
    # src/kira/config.py -> kira-engine -> project root, the directory holding kira-chat.
    project_root = Path(__file__).resolve().parents[3]
    return project_root / ".kira-data"


def _optional_positive_int(value: Any, field: str) -> int | None:
    if value is None or value == 0:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{field} must be an integer, got {value!r}")
    if value < 0:
        raise ConfigError(f"{field} must be positive, got {value}")
    return int(value)


def _provider_from(raw: dict[str, Any]) -> ProviderConfig:
    missing = {"name", "kind", "base_url", "models"} - raw.keys()
    if missing:
        raise ConfigError(f"provider entry missing keys: {sorted(missing)}")
    return ProviderConfig(
        name=str(raw["name"]),
        kind=str(raw["kind"]),
        base_url=str(raw["base_url"]).rstrip("/"),
        models=[str(m) for m in raw["models"]],
        tier=str(raw.get("tier", "fast")),
        key_ref=str(raw.get("key_ref", "")),
        priority=int(raw.get("priority", 100)),
        monthly_token_cap=_optional_positive_int(raw.get("monthly_token_cap"), "monthly_token_cap"),
        vision=bool(raw.get("vision", False)),
        context_window=_optional_positive_int(raw.get("context_window"), "context_window"),
    )


def _voice_from(raw: dict[str, Any]) -> VoiceConfig:
    if not isinstance(raw, dict):
        raise ConfigError("voice must be a mapping")
    known = set(VoiceConfig.__dataclass_fields__)
    unknown = sorted(set(raw) - known)
    if unknown:
        raise ConfigError(f"unknown voice keys: {unknown}")
    try:
        return VoiceConfig(**raw)
    except TypeError as exc:
        # A `silence_ms: soon` in YAML must read as a config error, not a traceback at startup.
        raise ConfigError(f"voice block has a value of the wrong type: {exc}") from exc


def load_config(data_dir: str | Path | None = None) -> Config:
    directory = resolve_data_dir(data_dir)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "logs").mkdir(parents=True, exist_ok=True)
    path = directory / "config.yaml"
    if not path.exists():
        return Config(data_dir=directory, providers=[])
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ConfigError(f"{path} must contain a mapping")
    providers = [_provider_from(p) for p in raw.get("providers", [])]
    return Config(
        data_dir=directory,
        host=str(raw.get("host", "127.0.0.1")),
        port=int(raw.get("port", DEFAULT_PORT)),
        default_mode=str(raw.get("default_mode", "AUTO")),
        max_agent_steps=int(raw.get("max_agent_steps", 6)),
        request_timeout_s=float(raw.get("request_timeout_s", 120.0)),
        workspace_dir=str(raw.get("workspace_dir", "")),
        approval_timeout_s=float(raw.get("approval_timeout_s", 120.0)),
        checkpoint_retention=int(raw.get("checkpoint_retention", 50)),
        providers=providers,
        voice=_voice_from(raw.get("voice") or {}),
    )


SAMPLE_CONFIG = """\
# Kira engine config — non-secret values only.
# API keys live in the Windows Credential Locker (key_ref names below), never here.
host: 127.0.0.1
port: 8901
default_mode: AUTO
max_agent_steps: 6
request_timeout_s: 120

# Where the agent may read and write. Relative paths resolve against this data directory.
workspace_dir: workspace
# How long a tool awaiting approval may hold the stream open, in seconds.
approval_timeout_s: 120
# How many file checkpoints to keep before pruning the oldest.
checkpoint_retention: 50

# The call stack. Every key is optional; these are the defaults. Nothing secret lives here —
# a remote stage only names a provider, and that provider's key stays in the Credential Locker.
voice:
  stt: local              # local | remote | off
  stt_engine: auto        # auto | faster_whisper | whisper_cpp (auto prefers whisper.cpp when found)
  stt_model: base.en      # faster-whisper name, downloaded once under <data>/voice/models
  stt_provider: openai    # an openai_compat provider, used only when stt is remote
  stt_remote_model: whisper-1
  tts: local              # local | remote | off
  tts_engine: auto        # auto | piper | kokoro (auto prefers a studio's Kokoro runtime)
  tts_provider: openai
  tts_model: tts-1
  tts_voice: alloy
  kokoro_voice: af_heart
  piper_bin: voice/piper/piper.exe   # Kira never downloads this; it reports whether it is there
  piper_model: voice/piper/voice.onnx
  vad_threshold: 0.02
  silence_ms: 700
  max_utterance_s: 30
  temperature: 0.6

providers:
  - name: openrouter
    kind: openai_compat
    base_url: https://openrouter.ai/api/v1
    tier: powerful
    key_ref: provider/openrouter
    priority: 100
    # Frames from #/call go only to providers that say they can take them.
    vision: true
    # Tokens this provider's chosen model accepts. Optional: without it the chat's context meter
    # has nothing to measure against and shows "—". Only the first model's window is used.
    context_window: 200000
    models:
      - anthropic/claude-sonnet-4.5
      - openai/gpt-4o-mini

  - name: groq
    kind: openai_compat
    base_url: https://api.groq.com/openai/v1
    tier: fast
    key_ref: provider/groq
    priority: 50
    models:
      - llama-3.3-70b-versatile
    # Optional ceiling for this provider, tokens per calendar month. The router
    # stands the provider down once the month's derived spend reaches it.
    # Absent (or 0) means unlimited. Set it from the dashboard instead of here
    # unless you want it as the baseline every override resets to.
    # monthly_token_cap: 1000000

  - name: anthropic
    kind: anthropic
    base_url: https://api.anthropic.com
    tier: powerful
    key_ref: provider/anthropic
    priority: 120
    vision: true
    models:
      - claude-sonnet-4-5

  - name: gemini
    kind: gemini
    base_url: https://generativelanguage.googleapis.com
    tier: fast
    key_ref: provider/gemini
    priority: 80
    vision: true
    models:
      - gemini-3.5-flash-lite
"""


def write_sample_config(data_dir: str | Path | None = None) -> Path:
    directory = resolve_data_dir(data_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "config.yaml"
    path.write_text(SAMPLE_CONFIG, encoding="utf-8")
    return path
