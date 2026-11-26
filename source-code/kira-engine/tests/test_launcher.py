"""The launcher's browser URL carries the token in a fragment, never in a request or a log."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def launcher():
    spec = importlib.util.spec_from_file_location("kira_launcher", ROOT / "run_kira.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_connect_url_keeps_the_token_out_of_the_request_target() -> None:
    url = launcher().connect_url("http://127.0.0.1:8901", "a b&c")
    assert url == "http://127.0.0.1:8901/chat/#/chat?token=a%20b%26c"
    assert url.split("#", 1)[0] == "http://127.0.0.1:8901/chat/"


def test_connect_url_without_a_token_still_lands_on_chat() -> None:
    assert launcher().connect_url("http://127.0.0.1:8901") == "http://127.0.0.1:8901/chat/"
