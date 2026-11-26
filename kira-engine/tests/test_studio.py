"""Studio discovery: the folder layout is the contract, so the tests build the layout."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from kira.studio import find_studio

PLATFORM = {"win32": "win", "linux": "linux", "darwin": "mac"}.get(
    os.sys.platform, "linux"
)
NODE = "node.exe" if os.name == "nt" else "node"
SD = "sd-vulkan.exe" if os.name == "nt" else "sd-vulkan"
LLAMA = "llama-server.exe" if os.name == "nt" else "llama-server"
WHISPER = "whisper-cli.exe" if os.name == "nt" else "whisper-cli"
APPIMAGE = ".exe" if os.name == "nt" else ""


def make_studio(root: Path) -> Path:
    (root / "scripts" / "server").mkdir(parents=True)
    (root / "scripts" / "server" / "serve.cjs").write_text(
        "// marker", encoding="utf-8"
    )
    app = root / "app"
    for directory in (
        app / "backend" / PLATFORM / "vulkan",
        app / "llm-backend" / PLATFORM / "vulkan",
        app / "speech-backend" / PLATFORM / "cpu",
        app / "models",
        app / "llm-models",
        app / "speech-models",
        app / "tts-models",
        app / "tts-runtime" / "node_modules" / "kokoro-js",
        app / "tools" / f"node-{PLATFORM}",
        root / "scripts" / "workers",
    ):
        directory.mkdir(parents=True)
    # The real studio has `llama-server-impl.dll` beside the exe; a glob must not call the shared
    # library the engine.
    (app / "llm-backend" / PLATFORM / "vulkan" / "llama-server-impl.dll").write_bytes(
        b"dll"
    )
    for path, payload in (
        (app / "backend" / PLATFORM / "vulkan" / SD, b"sd"),
        (app / "llm-backend" / PLATFORM / "vulkan" / LLAMA, b"llama"),
        (app / "speech-backend" / PLATFORM / "cpu" / WHISPER, b"whisper"),
    ):
        path.write_bytes(payload)
        if os.name != "nt":
            path.chmod(0o755)
    (app / "models" / "sd15.safetensors").write_bytes(b"ckpt")
    (app / "llm-models" / "qwen.gguf").write_bytes(b"gguf")
    (app / "speech-models" / "ggml-base.en.bin").write_bytes(b"bin")
    (app / "tts-models" / "kokoro-onnx-q8.json").write_text(
        '{"modelId": "onnx-community/Kokoro-82M-v1.0-ONNX", "dtype": "q8"}',
        encoding="utf-8",
    )
    (app / "tools" / f"node-{PLATFORM}" / NODE).write_bytes(b"node")
    (root / "scripts" / "workers" / "tts-kokoro-worker.mjs").write_text(
        "// worker", encoding="utf-8"
    )
    return root


def test_a_real_studio_layout_is_found_and_reported(tmp_path) -> None:
    root = make_studio(tmp_path / "Portable-Local-Studio-main")
    studio = find_studio(tmp_path / "data")
    assert studio is not None
    assert studio.root == root.resolve()

    status = studio.status()
    assert status["root"] == str(root.resolve())
    assert status["image"]["available"] is True
    assert status["image"]["models"][0]["filename"] == "sd15.safetensors"
    assert status["llm"]["models"][0]["filename"] == "qwen.gguf"
    assert not status["llm"]["engine"].endswith(".dll")
    assert status["stt"]["models"][0]["filename"] == "ggml-base.en.bin"
    assert status["tts"]["available"] is True
    assert "Kokoro" in status["tts"]["detail"]


def test_the_env_var_beats_a_sibling_folder(tmp_path, monkeypatch) -> None:
    sibling = make_studio(tmp_path / "Portable-Local-Studio-main")
    wanted = make_studio(tmp_path / "elsewhere" / "Portable-AI-Studio")
    monkeypatch.setenv("KIRA_STUDIO_DIR", str(wanted))
    studio = find_studio(tmp_path / "data")
    assert studio is not None
    assert studio.root == wanted.resolve()
    assert studio.root != sibling.resolve()


def test_a_folder_without_the_marker_is_not_a_studio(tmp_path) -> None:
    (tmp_path / "Portable-Local-Studio-main" / "app").mkdir(parents=True)
    assert find_studio(tmp_path / "data") is None


def test_the_status_route_answers_even_with_no_studio(harness) -> None:
    response = asyncio.run(harness.api.get("/v1/kira/studio", headers=harness.auth))
    assert response.status_code == 200
    body = response.json()
    assert body["available"] is False
    assert body["root"] is None
    assert set(body) >= {"root", "available", "image", "llm", "stt", "tts"}
    assert body["llm"]["running"] is False


def test_starting_the_local_model_without_one_is_a_503_behind_the_confirm(
    harness,
) -> None:
    unsigned = asyncio.run(
        harness.api.post(
            "/v1/kira/studio/llm/start", json={"model": None}, headers=harness.auth
        )
    )
    assert unsigned.status_code == 401
    signed = asyncio.run(
        harness.api.post(
            "/v1/kira/studio/llm/start", json={"model": None}, headers=harness.signed
        )
    )
    assert signed.status_code == 503
    assert signed.json()["error"]["code"] == "llm_unavailable"


def test_a_download_from_an_unlisted_host_is_refused_without_opening_a_socket(
    harness,
) -> None:
    response = asyncio.run(
        harness.api.post(
            "/v1/kira/studio/download",
            json={"kind": "llm", "url": "https://example.com/tiny.gguf"},
            headers=harness.signed,
        )
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "download_refused"
