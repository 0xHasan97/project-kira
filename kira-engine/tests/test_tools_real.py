from __future__ import annotations

import asyncio
import json
import sys

import pytest

from kira.tools import ToolRegistry, register_demo_tools, register_workspace_tools
from kira.workspace import Workspace


@pytest.fixture
def registry(tmp_path):
    ws = Workspace(tmp_path / "ws")
    reg = ToolRegistry()
    register_demo_tools(reg)
    register_workspace_tools(reg, ws)
    return reg


def run(reg, name, **arguments):
    return asyncio.run(reg.execute(name, arguments))


def test_registry_lists_risk_source_and_defaults(registry):
    info = {tool["name"]: tool for tool in registry.info()}
    assert set(info) == {"echo", "now", "list_dir", "read_file", "search_text", "write_file", "run_command"}
    assert info["write_file"]["risk"] == "write"
    assert info["write_file"]["default_policy"] == "ask"
    assert info["read_file"]["default_policy"] == "allow"
    assert info["run_command"]["risk"] == "exec"
    assert info["read_file"]["source"] == "builtin"


def test_read_file_returns_content(registry):
    outcome = run(registry, "write_file", path="a.txt", content="hello")
    assert outcome.ok
    assert outcome.summary == "a.txt"
    outcome = run(registry, "read_file", path="a.txt")
    assert outcome.ok and outcome.content == "hello"


def test_errors_are_strings_not_exceptions(registry):
    outcome = run(registry, "read_file", path="../escape")
    assert not outcome.ok
    assert outcome.content.startswith("error: path escapes")


def test_write_reports_summary_and_checkpoint_paths(registry):
    tool = registry.get("write_file")
    assert tool is not None
    assert tool.summary({"path": "x/y.txt"}) == "x/y.txt"
    assert tool.checkpoint_paths({"path": "x/y.txt"}) == ["x/y.txt"]


def test_run_command_classifies_a_test_run(registry):
    outcome = run(registry, "run_command", argv=[sys.executable, "-m", "pytest", "--version"])
    assert outcome.ok
    assert outcome.kind == "test"
    assert outcome.summary.startswith("pytest") or "pytest" in outcome.summary


def test_run_command_classifies_a_plain_command(registry):
    outcome = run(registry, "run_command", argv=[sys.executable, "-c", "print(1)"])
    assert outcome.ok
    assert outcome.kind == "command"
    payload = json.loads(outcome.content)
    assert payload["exit_code"] == 0
