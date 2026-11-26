from pathlib import Path

import pytest

from kira import __main__ as cli


class FakeConfig:
    host = "127.0.0.1"
    port = 8901
    data_dir = Path("C:/tmp/kira-data")
    config_path = Path("C:/tmp/kira-data/config.yaml")
    providers = [object()]


class FakeVault:
    backend = "memory"

    def __init__(self, backend=None):
        self.asked = backend

    def get_or_create_engine_token(self):
        return "tok_desktop", True


def test_the_desktop_subcommand_parses_a_port_override():
    args = cli.build_parser().parse_args(["desktop", "--port", "8915"])
    assert args.cmd == "desktop"
    assert args.port == 8915
    assert args.func is cli.cmd_desktop


def test_desktop_refuses_before_starting_when_the_chat_bundle_is_missing(tmp_path, monkeypatch, capsys):
    # A window whose /chat/ 404s shows a blank pane and no explanation, so the missing bundle has to
    # stop this command while there is still a console to say why.
    monkeypatch.setenv("KIRA_CHAT_DIST", str(tmp_path / "dist"))
    monkeypatch.setattr(cli, "load_config", lambda data_dir: FakeConfig())
    monkeypatch.setattr(cli, "Vault", FakeVault)
    monkeypatch.setattr(cli, "create_app", lambda config, vault=None: object())

    args = cli.build_parser().parse_args(["desktop"])
    assert cli.cmd_desktop(args) == 2
    assert "--rebuild" in capsys.readouterr().err


def test_desktop_starts_from_the_configured_loopback_address_and_the_stored_token(tmp_path, monkeypatch):
    pytest.importorskip("pystray")
    pytest.importorskip("webview")
    pytest.importorskip("PIL")
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html>", encoding="utf-8")
    monkeypatch.setenv("KIRA_CHAT_DIST", str(dist))
    monkeypatch.setattr(cli, "load_config", lambda data_dir: FakeConfig())
    monkeypatch.setattr(cli, "Vault", FakeVault)
    monkeypatch.setattr(cli, "create_app", lambda config, vault=None: "the-app")

    seen: dict = {}

    def fake_run(app, **kwargs):
        seen["app"] = app
        seen.update(kwargs)
        return 0

    monkeypatch.setattr("kira.desktop.run", fake_run)

    args = cli.build_parser().parse_args(["desktop", "--backend", "memory", "--port", "8915"])
    assert cli.cmd_desktop(args) == 0
    assert seen["app"] == "the-app"
    assert (seen["host"], seen["port"]) == ("127.0.0.1", 8915)
    assert seen["token"] == "tok_desktop"
    assert seen["data_dir"] == FakeConfig.data_dir
    # No card unless asked for: the window the user double-clicked is the app, and a second one
    # appearing over the desktop uninvited is worse than not having the feature.
    assert seen["companion"] is False


def test_the_companion_flag_is_passed_to_the_shell_and_off_by_default():
    assert cli.build_parser().parse_args(["desktop"]).companion is False
    assert cli.build_parser().parse_args(["desktop", "--companion"]).companion is True


def test_a_frozen_build_finds_the_chat_bundle_inside_the_bundle(monkeypatch, tmp_path):
    # PyInstaller unpacks data files under sys._MEIPASS; the repo-relative walk
    # (src/kira/__main__.py -> up three) lands inside _internal and finds nothing.
    import sys

    monkeypatch.delenv("KIRA_CHAT_DIST", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "_internal"), raising=False)

    assert cli._chat_dist() == tmp_path / "_internal" / "kira-chat" / "dist"


def test_an_explicit_chat_dist_wins_over_the_bundle_default(monkeypatch, tmp_path):
    import sys

    monkeypatch.setenv("KIRA_CHAT_DIST", str(tmp_path / "custom-dist"))
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    assert cli._chat_dist() == tmp_path / "custom-dist"


def test_from_a_source_checkout_the_bundle_is_the_sibling_directory(monkeypatch):
    import sys

    monkeypatch.delenv("KIRA_CHAT_DIST", raising=False)
    monkeypatch.setattr(sys, "frozen", False, raising=False)

    dist = cli._chat_dist()
    assert dist.parent.name == "kira-chat"
    assert dist.name == "dist"


def test_serve_exports_the_bundle_path_create_app_mounts(tmp_path, monkeypatch):
    """A frozen `Kira.exe serve` must serve /chat/ from the bundle PyInstaller shipped.

    `create_app` reads `KIRA_CHAT_DIST`, and only `desktop` used to set it. The frozen serve then
    looked for `<localappdata>/kira-chat/dist` and answered 404 for every browser request.
    """
    import uvicorn

    dist = tmp_path / "bundle" / "kira-chat" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html>", encoding="utf-8")
    monkeypatch.delenv("KIRA_CHAT_DIST", raising=False)
    monkeypatch.setattr(cli, "_chat_dist", lambda: dist)
    monkeypatch.setattr(cli, "load_config", lambda data_dir: FakeConfig())
    monkeypatch.setattr(cli, "Vault", FakeVault)
    seen: dict = {}
    monkeypatch.setattr(cli, "create_app", lambda config, vault=None: "the-app")
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: seen.update(app=app, **kwargs))

    args = cli.build_parser().parse_args(["serve", "--port", "8916"])
    assert cli.cmd_serve(args) == 0
    assert seen["app"] == "the-app" and seen["port"] == 8916
    import os

    assert os.environ["KIRA_CHAT_DIST"] == str(dist)
