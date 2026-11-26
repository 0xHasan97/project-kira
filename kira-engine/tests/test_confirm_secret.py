from __future__ import annotations

import json

from kira.__main__ import main
from kira.app import Engine
from kira.config import Config, write_sample_config
from kira.vault import ENGINE_CONFIRM_REF, ENGINE_TOKEN_REF, Vault


def _bare_config(tmp_path) -> Config:
    data_dir = tmp_path / ".kira-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return Config(data_dir=data_dir, providers=[])


def test_the_confirm_secret_is_its_own_ref_and_its_own_value() -> None:
    vault = Vault("memory")
    token, _ = vault.get_or_create_engine_token()
    confirm, _ = vault.get_or_create_confirm()
    assert confirm != token
    assert vault.get(ENGINE_CONFIRM_REF) == confirm
    assert vault.get(ENGINE_TOKEN_REF) == token


def test_both_secrets_are_minted_once_and_stable() -> None:
    vault = Vault("memory")
    token, first = vault.get_or_create_engine_token()
    token_again, second = vault.get_or_create_engine_token()
    assert first is True and second is False and token_again == token
    confirm, confirm_first = vault.get_or_create_confirm()
    assert confirm_first is True
    assert vault.get_or_create_confirm()[1] is False
    assert len(confirm) >= 32


def test_the_engine_carries_the_secret_the_vault_holds(tmp_path) -> None:
    vault = Vault("memory")
    vault.set("engine/confirm", "a-stored-confirm")
    engine = Engine(_bare_config(tmp_path), vault=vault)
    assert engine.confirm == "a-stored-confirm"


def test_a_first_run_prints_both_secrets_and_a_second_run_prints_neither(tmp_path, capsys) -> None:
    vault = Vault("memory")
    Engine(_bare_config(tmp_path), vault=vault)
    first = capsys.readouterr().err
    assert "engine token" in first
    assert "confirm secret" in first

    Engine(_bare_config(tmp_path), vault=vault)
    assert capsys.readouterr().err == ""


def test_the_token_command_keeps_stdout_to_the_bearer_token(monkeypatch, capsys) -> None:
    monkeypatch.setenv("KIRA_VAULT", "memory")
    assert main(["token"]) == 0
    captured = capsys.readouterr()
    token = captured.out.strip()
    assert captured.out.count("\n") == 1, "a second stdout line breaks `TOKEN=$(kira-engine token)`"
    assert token and not token.startswith("[kira]")
    assert "confirm secret" in captured.err
    assert token not in captured.err


def test_keys_list_reports_the_confirm_ref_without_its_value(tmp_path, capsys) -> None:
    write_sample_config(tmp_path)
    assert main(["keys", "list", "--backend", "memory", "--data-dir", str(tmp_path)]) == 0
    payload = json.loads(capsys.readouterr().out)
    by_ref = {row["ref"]: row for row in payload["secrets"]}
    assert by_ref[ENGINE_CONFIRM_REF]["present"] is False
    assert by_ref[ENGINE_TOKEN_REF]["present"] is False
    assert all(set(row) == {"ref", "purpose", "present"} for row in payload["secrets"])


def test_serve_honours_the_backend_flag_and_stays_on_loopback(tmp_path, monkeypatch) -> None:
    import uvicorn

    write_sample_config(tmp_path)
    started: dict = {}

    def fake_run(app, **kwargs) -> None:
        started["app"] = app
        started.update(kwargs)

    monkeypatch.setattr(uvicorn, "run", fake_run)
    assert main(["serve", "--backend", "memory", "--data-dir", str(tmp_path)]) == 0
    # A `--backend memory` serve that still built a keyring vault would mint both secrets into
    # the real Locker as a side effect of someone poking at the engine.
    assert started["app"].state.engine.vault.backend == "memory"
    assert started["host"] == "127.0.0.1"
