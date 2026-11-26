"""whisper.cpp and Kokoro as voice stages, plus the studio-aware stack picks."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from kira.config import Config, VoiceConfig
from kira.voice.stt import WhisperCppStt
from kira.voice.tts import KokoroTts

PLATFORM = {"win32": "win", "linux": "linux", "darwin": "mac"}.get(
    os.sys.platform, "linux"
)


def test_whisper_cpp_reads_the_txt_the_cli_writes(tmp_path) -> None:
    script = tmp_path / "fake_whisper.py"
    script.write_text(
        "import pathlib, sys\n"
        "args = sys.argv[1:]\n"
        "base = args[args.index('-of') + 1]\n"
        "pathlib.Path(base + '.txt').write_text(' hello   from whisper.cpp ')\n",
        encoding="utf-8",
    )
    model = tmp_path / "ggml-base.en.bin"
    model.write_bytes(b"model")
    stt = WhisperCppStt(script, model, tmp_path / "tmp", prefix=(sys.executable,))
    assert stt.available is True
    assert "whisper.cpp" in stt.detail
    text = asyncio.run(stt.transcribe(b"RIFF-not-a-real-wav"))
    assert text == "hello from whisper.cpp"
    assert list((tmp_path / "tmp").iterdir()) == []


def test_whisper_cpp_without_a_model_names_what_is_missing(tmp_path) -> None:
    stt = WhisperCppStt(
        tmp_path / "whisper-cli", tmp_path / "ggml.bin", tmp_path / "tmp"
    )
    assert stt.available is False
    assert "whisper.cpp is not installed" in stt.detail


def test_kokoro_runs_the_worker_and_returns_its_wav(tmp_path) -> None:
    runtime = tmp_path / "runtime"
    (runtime / "node_modules" / "kokoro-js").mkdir(parents=True)
    worker = tmp_path / "worker.py"
    worker.write_text(
        "import json, sys, wave\n"
        "payload = json.load(sys.stdin)\n"
        "with wave.open(payload['output'], 'wb') as out:\n"
        "    out.setnchannels(1); out.setsampwidth(2); out.setframerate(24000)\n"
        "    out.writeframes(b'\\x00\\x00' * 240)\n"
        "print('{\"ok\": true}')\n",
        encoding="utf-8",
    )
    tts = KokoroTts(
        Path(sys.executable),
        worker,
        runtime,
        tmp_path / "cache",
        tmp_path / "tmp",
        voice="af_heart",
    )
    assert tts.available is True
    assert "kokoro" in tts.detail
    wav = asyncio.run(tts.speak("Hello there."))
    assert wav.startswith(b"RIFF")
    assert list((tmp_path / "tmp").iterdir()) == []


def _make_studio(root: Path) -> None:
    (root / "scripts" / "server").mkdir(parents=True)
    (root / "scripts" / "server" / "serve.cjs").write_text("//", encoding="utf-8")
    (root / "scripts" / "workers").mkdir(parents=True)
    (root / "scripts" / "workers" / "tts-kokoro-worker.mjs").write_text(
        "//", encoding="utf-8"
    )
    app = root / "app"
    (app / "speech-backend" / PLATFORM / "cpu").mkdir(parents=True)
    (app / "llm-backend" / PLATFORM / "vulkan").mkdir(parents=True)
    (app / "backend" / PLATFORM / "vulkan").mkdir(parents=True)
    (app / "speech-models").mkdir(parents=True)
    (app / "tts-models").mkdir(parents=True)
    (app / "tts-cache").mkdir(parents=True)
    (app / "tts-runtime" / "node_modules" / "kokoro-js").mkdir(parents=True)
    (app / "models").mkdir(parents=True)
    (app / "llm-models").mkdir(parents=True)
    node_dir = app / "tools" / f"node-{PLATFORM}"
    node_dir.mkdir(parents=True)
    whisper = (
        app
        / "speech-backend"
        / PLATFORM
        / "cpu"
        / ("whisper-cli.exe" if os.name == "nt" else "whisper-cli")
    )
    whisper.write_bytes(b"whisper")
    (node_dir / ("node.exe" if os.name == "nt" else "node")).write_bytes(b"node")
    (app / "speech-models" / "ggml-base.en.bin").write_bytes(b"model")
    (app / "tts-models" / "kokoro-onnx-q8.json").write_text(
        '{"modelId": "onnx-community/Kokoro-82M-v1.0-ONNX", "dtype": "q8"}',
        encoding="utf-8",
    )
    if os.name != "nt":
        whisper.chmod(0o755)


def test_the_stack_prefers_whisper_cpp_and_kokoro_when_a_studio_is_there(
    tmp_path, monkeypatch
) -> None:
    from kira.voice.stack import _build_stt, _build_tts

    studio = tmp_path / "studio"
    _make_studio(studio)
    monkeypatch.setenv("KIRA_STUDIO_DIR", str(studio))
    config = Config(data_dir=tmp_path / "data")
    stt = _build_stt(config.voice, config, None)  # type: ignore[arg-type]
    tts = _build_tts(config.voice, config, None)  # type: ignore[arg-type]
    assert isinstance(stt, WhisperCppStt)
    assert stt.available is True
    assert isinstance(tts, KokoroTts)
    assert tts.available is True


def test_forcing_piper_keeps_the_piper_path(tmp_path, monkeypatch) -> None:
    from kira.voice.stack import _build_tts
    from kira.voice.tts import LocalTts

    config = Config(data_dir=tmp_path / "data", voice=VoiceConfig(tts_engine="piper"))
    tts = _build_tts(config.voice, config, None)  # type: ignore[arg-type]
    assert isinstance(tts, LocalTts)
    assert "piper" in tts.detail
