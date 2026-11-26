"""The frozen build is only as good as the three things it must get right: the entry point,
the chat bundle inside the bundle, and no console window. A spec typo costs a real build to
find, so these read the files instead."""

from __future__ import annotations

import tomllib
from pathlib import Path

PACKAGING = Path(__file__).resolve().parents[1] / "packaging"


def _spec() -> str:
    return (PACKAGING / "kira.spec").read_text(encoding="utf-8")


def test_the_spec_is_a_windowed_build_named_kira():
    spec = _spec()
    assert 'name="Kira"' in spec
    assert "console=False" in spec


def test_the_spec_puts_the_chat_bundle_where_the_cli_looks_for_it():
    # _chat_dist() reads sys._MEIPASS/kira-chat/dist, so the data target must match it.
    spec = _spec()
    assert '"kira-chat/dist"' in spec


def test_the_spec_ships_the_window_stack_as_hidden_imports():
    spec = _spec()
    for module in ("webview.platforms.winforms", "webview.platforms.edgechromium", "pystray._win32", "PIL.Image"):
        assert module in spec, module


def test_the_entry_point_is_the_same_cli():
    entry = (PACKAGING / "entry.py").read_text(encoding="utf-8")
    assert "from kira.__main__ import main" in entry
    assert "SystemExit(main())" in entry


def test_the_build_script_builds_the_client_first_and_uses_the_venv():
    script = (PACKAGING / "build.ps1").read_text(encoding="utf-8")
    assert "npm" in script and "run build" in script
    assert "PyInstaller" in script
    assert ".venv" in script


def test_the_build_tool_is_a_declared_extra():
    pyproject = tomllib.loads((PACKAGING.parent / "pyproject.toml").read_text(encoding="utf-8"))
    extras = pyproject["project"]["optional-dependencies"]
    assert any("pyinstaller" in dep.lower() for dep in extras.get("build", []))
