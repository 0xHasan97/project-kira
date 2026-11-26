"""The local chat server: one child process, one provider, and a truthful stop."""

from __future__ import annotations

import os

import pytest

from kira.config import Config
from kira.llamacpp import LlmStartFailed, LlmUnavailable, LocalLlm


class FakeProc:
    def __init__(self, exit_code: int | None = None) -> None:
        self.pid = 4242
        self._exit = exit_code
        self.terminated = False

    def poll(self) -> int | None:
        return self._exit

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout: float | None = None) -> int:
        self.terminated = True
        return 0

    def kill(self) -> None:
        self.terminated = True


def setup_tree(tmp_path):
    config = Config(data_dir=tmp_path / "data")
    engine_dir = config.data_dir / "llm" / "engines"
    model_dir = config.data_dir / "llm" / "models"
    engine_dir.mkdir(parents=True)
    model_dir.mkdir(parents=True)
    engine = engine_dir / ("llama-server.exe" if os.name == "nt" else "llama-server")
    engine.write_bytes(b"fake")
    if os.name != "nt":
        engine.chmod(0o755)
    (model_dir / "tiny.gguf").write_bytes(b"gguf")
    return config


def test_start_adds_the_keyless_provider_and_stop_removes_it(tmp_path) -> None:
    config = setup_tree(tmp_path)
    llm = LocalLlm(
        config,
        spawn=lambda argv, env, log: FakeProc(),
        probe=lambda url, timeout: True,
        free_port=lambda: 8123,
    )
    status = llm.start("tiny")
    assert status["running"] is True
    assert status["url"] == "http://127.0.0.1:8123/v1"
    provider = config.by_name["local_llama"]
    assert provider.key_ref == ""
    assert provider.models == ["tiny"]
    assert provider.base_url == "http://127.0.0.1:8123/v1"

    stopped = llm.stop()
    assert stopped["running"] is False
    assert "local_llama" not in config.by_name


def test_start_without_a_model_is_a_503_with_the_folder_in_the_message(
    tmp_path,
) -> None:
    config = Config(data_dir=tmp_path / "data")
    llm = LocalLlm(config)
    with pytest.raises(LlmUnavailable, match="GGUF"):
        llm.start()


def test_a_child_that_exits_before_ready_fails_and_cleans_up(tmp_path) -> None:
    config = setup_tree(tmp_path)
    llm = LocalLlm(
        config,
        spawn=lambda argv, env, log: FakeProc(exit_code=1),
        probe=lambda url, timeout: False,
        free_port=lambda: 8124,
    )
    with pytest.raises(LlmStartFailed):
        llm.start()
    assert "local_llama" not in config.by_name
    assert llm.status()["running"] is False


def test_argv_keeps_layers_on_the_cpu_unless_the_machine_opts_in(
    tmp_path, monkeypatch
) -> None:
    config = setup_tree(tmp_path)
    llm = LocalLlm(config)
    model = llm.models()[0]
    monkeypatch.delenv("KIRA_LLAMA_NGL", raising=False)
    vulkan = llm._argv(tmp_path / "gpu" / "llama-server", model, 1)
    assert vulkan[vulkan.index("-ngl") + 1] == "0"
    monkeypatch.setenv("KIRA_LLAMA_NGL", "24")
    offloaded = llm._argv(tmp_path / "gpu" / "llama-server", model, 1)
    assert offloaded[offloaded.index("-ngl") + 1] == "24"
    assert "--alias" in vulkan and model.name in vulkan


def test_status_reports_the_model_that_died_instead_of_a_stale_running(
    tmp_path,
) -> None:
    config = setup_tree(tmp_path)
    proc = FakeProc()
    llm = LocalLlm(
        config, spawn=lambda *a: proc, probe=lambda *a: True, free_port=lambda: 8125
    )
    llm.start()
    proc._exit = 1
    status = llm.status()
    assert status["running"] is False
    assert "local_llama" not in config.by_name
