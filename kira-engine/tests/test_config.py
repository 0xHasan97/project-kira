from __future__ import annotations

import pytest

from kira.config import Config, load_config
from kira.errors import ConfigError


def test_workspace_defaults_beside_the_database(tmp_path):
    cfg = Config(data_dir=tmp_path)
    assert cfg.workspace_dir == ""
    assert cfg.workspace_path == (tmp_path / "workspace").resolve()


def test_workspace_relative_path_resolves_against_data_dir(tmp_path):
    cfg = Config(data_dir=tmp_path, workspace_dir="sandbox")
    assert cfg.workspace_path == (tmp_path / "sandbox").resolve()


def test_workspace_rejects_the_data_dir_itself(tmp_path):
    with pytest.raises(ConfigError, match="must not be the data directory"):
        Config(data_dir=tmp_path, workspace_dir=str(tmp_path))


def test_workspace_rejects_the_filesystem_root():
    with pytest.raises(ConfigError, match="must not be the filesystem root"):
        Config(
            data_dir="C:/kiradata" if __import__("os").name == "nt" else "/tmp/kiradata",
            workspace_dir="C:/" if __import__("os").name == "nt" else "/",
        )


def test_timeouts_and_retention_have_bounds(tmp_path):
    with pytest.raises(ConfigError, match="approval_timeout_s"):
        Config(data_dir=tmp_path, approval_timeout_s=0)
    with pytest.raises(ConfigError, match="checkpoint_retention"):
        Config(data_dir=tmp_path, checkpoint_retention=0)


def test_yaml_reads_the_three_keys(tmp_path):
    (tmp_path / "config.yaml").write_text(
        "workspace_dir: ws\napproval_timeout_s: 30\ncheckpoint_retention: 7\n", encoding="utf-8"
    )
    cfg = load_config(tmp_path)
    assert cfg.workspace_path == (tmp_path / "ws").resolve()
    assert cfg.approval_timeout_s == 30
    assert cfg.checkpoint_retention == 7


def test_a_provider_stanza_carries_its_context_window(tmp_path):
    (tmp_path / "config.yaml").write_text(
        "providers:\n"
        "  - name: local\n"
        "    kind: openai_compat\n"
        "    base_url: http://127.0.0.1:1234/v1\n"
        "    models: [llama3]\n"
        "    context_window: 131072\n",
        encoding="utf-8",
    )
    cfg = load_config(tmp_path)
    assert cfg.providers[0].context_window == 131072


def test_a_context_window_that_is_not_a_positive_integer_is_refused(tmp_path):
    (tmp_path / "config.yaml").write_text(
        "providers:\n"
        "  - name: local\n"
        "    kind: openai_compat\n"
        "    base_url: http://127.0.0.1:1234/v1\n"
        "    models: [llama3]\n"
        "    context_window: -1\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="context_window"):
        load_config(tmp_path)
