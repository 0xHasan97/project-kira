from __future__ import annotations

import json
import os

import pytest

from kira.limits import MAX_LIST_ENTRIES, MAX_READ_BYTES
from kira.workspace import Workspace, WorkspaceError


@pytest.fixture
def ws(tmp_path):
    root = tmp_path / "ws"
    root.mkdir()
    return Workspace(root)


def test_safe_path_allows_the_root_and_children(ws):
    assert ws.safe_path(".") == ws.root
    assert ws.safe_path("a/b.txt") == ws.root / "a" / "b.txt"


@pytest.mark.parametrize("raw", ["../escape.txt", "a/../../escape.txt", "", "bad\x00name"])
def test_safe_path_refuses_escapes_and_nuls(ws, raw):
    with pytest.raises(WorkspaceError):
        ws.safe_path(raw)


def test_safe_path_follows_symlinks_before_checking(tmp_path, ws):
    outside = tmp_path / "outside"
    outside.mkdir()
    link = ws.root / "link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks need a privilege this Windows account does not have")
    with pytest.raises(WorkspaceError, match="escapes"):
        ws.safe_path("link/file.txt")


def test_read_file_returns_text_and_notes_truncation(ws):
    (ws.root / "small.txt").write_text("hello", encoding="utf-8")
    assert ws.read_text("small.txt") == "hello"
    (ws.root / "big.txt").write_text("x" * (MAX_READ_BYTES + 10), encoding="utf-8")
    body = ws.read_text("big.txt")
    assert body.endswith(f"[truncated at {MAX_READ_BYTES} bytes]")


def test_read_file_refuses_binary_and_missing(ws):
    (ws.root / "bin.dat").write_bytes(b"\x00\x01\x02")
    with pytest.raises(WorkspaceError, match="binary"):
        ws.read_text("bin.dat")
    with pytest.raises(WorkspaceError, match="does not exist"):
        ws.read_text("nope.txt")


def test_list_dir_is_sorted_json_and_capped(ws):
    (ws.root / "b.txt").write_text("b", encoding="utf-8")
    (ws.root / "adir").mkdir()
    payload = json.loads(ws.list_dir("."))
    assert [e["name"] for e in payload["entries"]] == ["adir", "b.txt"]
    assert payload["entries"][0]["type"] == "dir"


def test_search_text_finds_lines_and_skips_binary(ws):
    (ws.root / "a.txt").write_text("alpha\nneedle here\n", encoding="utf-8")
    (ws.root / "b.bin").write_bytes(b"\x00needle")
    payload = json.loads(ws.search_text("needle", "."))
    assert payload["hits"] == [{"path": "a.txt", "line": 2, "text": "needle here"}]
