from __future__ import annotations

import asyncio
import sys

import pytest

from kira.limits import MAX_OUTPUT_BYTES, MAX_WRITE_BYTES
from kira.workspace import Workspace, WorkspaceError


@pytest.fixture
def ws(tmp_path):
    root = tmp_path / "ws"
    root.mkdir()
    return Workspace(root)


def test_write_creates_parents_and_reports_bytes(ws):
    written = ws.write_text("a/b/c.txt", "hello")
    assert written == 5
    assert (ws.root / "a" / "b" / "c.txt").read_text(encoding="utf-8") == "hello"


def test_write_refuses_oversize_and_escapes(ws):
    with pytest.raises(WorkspaceError, match="too large"):
        ws.write_text("big.txt", "x" * (MAX_WRITE_BYTES + 1))
    with pytest.raises(WorkspaceError, match="escapes"):
        ws.write_text("../x.txt", "x")


def test_command_returns_structured_output(ws):
    result = asyncio.run(ws.run_command([sys.executable, "-c", "print('hi')"]))
    assert result["exit_code"] == 0
    assert result["stdout"].strip() == "hi"
    assert result["stderr"] == ""
    assert isinstance(result["duration_ms"], int)


def test_command_reports_a_nonzero_exit_without_raising(ws):
    result = asyncio.run(ws.run_command([sys.executable, "-c", "raise SystemExit(3)"]))
    assert result["exit_code"] == 3


@pytest.mark.parametrize("shell", ["cmd", "cmd.exe", "powershell", "pwsh", "bash", "sh", "zsh", "wsl"])
def test_command_refuses_a_shell_as_argv_zero(ws, shell):
    with pytest.raises(WorkspaceError, match="shell"):
        asyncio.run(ws.run_command([shell, "-c", "echo hi"]))


def test_command_validates_argv_shape_and_timeout(ws):
    with pytest.raises(WorkspaceError, match="argv"):
        asyncio.run(ws.run_command([]))
    with pytest.raises(WorkspaceError, match="timeout"):
        asyncio.run(ws.run_command([sys.executable, "-c", "print(1)"], timeout_s=0))


def test_command_cwd_is_confined(ws):
    with pytest.raises(WorkspaceError, match="escapes"):
        asyncio.run(ws.run_command([sys.executable, "-c", "print(1)"], cwd=".."))


def test_command_output_is_capped(ws):
    result = asyncio.run(ws.run_command([sys.executable, "-c", f"print('x' * {MAX_OUTPUT_BYTES * 2})"]))
    assert result["truncated"] is True
    assert len(result["stdout"]) <= MAX_OUTPUT_BYTES


def test_command_does_not_inherit_lookalike_secrets(ws):
    result = asyncio.run(ws.run_command([sys.executable, "-c", "import os; print(os.environ.get('OPENAI_API_KEY', 'none'))"]))
    assert result["stdout"].strip() == "none"
