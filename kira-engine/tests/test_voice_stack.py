from __future__ import annotations

import importlib.util

import pytest

from conftest import provider_configs
from kira.config import Config, ConfigError, VoiceConfig
from kira.overrides import build_view
from kira.providers.registry import ProviderRegistry
from kira.vault import Vault
from kira.voice.stack import build_voice_stack


def stack_for(tmp_path, voice: VoiceConfig, providers=None):
    providers = providers or provider_configs()
    vault = Vault("memory")
    for provider in providers:
        vault.set(provider.key_ref, f"key-{provider.name}")
    config = Config(data_dir=tmp_path / ".kira-data", providers=providers, voice=voice)
    config.data_dir.mkdir(parents=True, exist_ok=True)
    registry = ProviderRegistry(config, vault, None)
    return build_voice_stack(config, registry, lambda: build_view(config, None))


@pytest.fixture
def without_faster_whisper(monkeypatch):
    real = importlib.util.find_spec
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda name, *args, **kwargs: None
        if name == "faster_whisper"
        else real(name, *args, **kwargs),
    )


def test_local_missing_is_reported_not_raised(tmp_path, without_faster_whisper):
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
    status = stack_for(
        tmp_path, VoiceConfig(stt="remote", stt_provider="fast_one", tts="remote", tts_provider="ant")
    ).status()
    assert status["stt"] == {"mode": "remote", "available": True, "detail": "fast_one · whisper-1"}
    # anthropic has no audio endpoints; the stack must say what is wrong instead of calling it.
    assert status["tts"]["mode"] == "remote"
    assert status["tts"]["available"] is False
    assert "openai_compat" in status["tts"]["detail"]


def test_remote_without_key_is_unavailable(tmp_path):
    providers = provider_configs()
    config = Config(
        data_dir=tmp_path / ".kira-data",
        providers=providers,
        voice=VoiceConfig(stt="remote", stt_provider="fast_one"),
    )
    config.data_dir.mkdir(parents=True, exist_ok=True)
    registry = ProviderRegistry(config, Vault("memory"), None)
    status = build_voice_stack(config, registry, lambda: build_view(config, None)).status()
    assert status["stt"]["available"] is False
    assert "key" in status["stt"]["detail"]


def test_remote_provider_that_is_not_configured_is_named(tmp_path):
    status = stack_for(tmp_path, VoiceConfig(stt="remote", stt_provider="nowhere")).status()
    assert status["stt"]["available"] is False
    assert "nowhere" in status["stt"]["detail"]


def test_vision_picks_the_highest_priority_declared_provider(tmp_path):
    providers = provider_configs()
    providers[2].vision = True  # "big"
    status = stack_for(tmp_path, VoiceConfig(), providers).status()
    assert status["vision"] == {"provider": "big", "model": "max"}


def test_vision_skips_a_provider_whose_key_is_missing(tmp_path):
    providers = provider_configs()
    providers[0].vision = True
    providers[0].key_ref = "provider/not-in-the-locker"
    providers[2].vision = True
    vault = Vault("memory")
    for provider in providers[1:]:
        vault.set(provider.key_ref, f"key-{provider.name}")
    config = Config(data_dir=tmp_path / ".kira-data", providers=providers, voice=VoiceConfig())
    config.data_dir.mkdir(parents=True, exist_ok=True)
    registry = ProviderRegistry(config, vault, None)
    status = build_voice_stack(config, registry, lambda: build_view(config, None)).status()
    # fast_one declares vision first but has no key, so the engine cannot serve a frame to it.
    assert status["vision"] == {"provider": "big", "model": "max"}


def test_off_is_honest(tmp_path):
    status = stack_for(tmp_path, VoiceConfig(stt="off", tts="off")).status()
    assert status["stt"]["mode"] == "off" and status["stt"]["available"] is False
    assert "off" in status["stt"]["detail"]
    assert status["tts"]["mode"] == "off" and status["tts"]["available"] is False
    assert "off" in status["tts"]["detail"]


def test_limits_are_the_tunables_the_call_reads_back(tmp_path):
    status = stack_for(tmp_path, VoiceConfig(silence_ms=900, max_utterance_s=20)).status()
    assert status["limits"] == {"max_utterance_s": 20, "silence_ms": 900}


def test_bad_voice_values_are_refused():
    with pytest.raises(ConfigError):
        VoiceConfig(stt="cloud")
    with pytest.raises(ConfigError):
        VoiceConfig(tts="cloud")
    with pytest.raises(ConfigError):
        VoiceConfig(silence_ms=10)
    with pytest.raises(ConfigError):
        VoiceConfig(vad_threshold=0.9)
    with pytest.raises(ConfigError):
        VoiceConfig(max_utterance_s=2)
    with pytest.raises(ConfigError):
        VoiceConfig(temperature=3)


def test_config_yaml_voice_block_is_read_and_unknown_keys_refused(tmp_path):
    from kira.config import load_config, write_sample_config

    write_sample_config(tmp_path)
    text = (tmp_path / "config.yaml").read_text(encoding="utf-8")
    assert "voice:" in text, "the sample config must show the voice block"
    assert "vision: true" in text, "the sample config must show how a provider declares vision"
    assert load_config(tmp_path).voice.silence_ms == 700, "the sample must parse with the defaults"

    # Edit the two lines separately: inserting a second `silence_ms` would leave the
    # sample's own line in place, and PyYAML keeps the last duplicate, not the first.
    edited = text.replace("  vad_threshold: 0.02", "  vad_threshold: 0.05").replace(
        "  silence_ms: 700", "  silence_ms: 900"
    )
    assert edited != text, "the sample config's voice lines moved; this test's anchors are stale"
    (tmp_path / "config.yaml").write_text(edited, encoding="utf-8")
    voice = load_config(tmp_path).voice
    assert (voice.vad_threshold, voice.silence_ms) == (0.05, 900)

    (tmp_path / "config.yaml").write_text(
        text.replace("  vad_threshold: 0.02", "  stt_mode: remote"), encoding="utf-8"
    )
    with pytest.raises(ConfigError):
        load_config(tmp_path)

    (tmp_path / "config.yaml").write_text(
        text.replace("  silence_ms: 700", "  silence_ms: soon"), encoding="utf-8"
    )
    with pytest.raises(ConfigError):
        load_config(tmp_path)
