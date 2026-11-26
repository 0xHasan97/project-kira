from __future__ import annotations

import hashlib
import sqlite3

import httpx
import pytest

from conftest import TEST_CONFIRM, TEST_TOKEN, Harness

USER = {"role": "user", "content": "hi"}


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def mint(harness: Harness) -> str:
    response = await harness.api.post("/v1/kira/pairing-code", headers=harness.signed)
    assert response.status_code == 200, response.text
    return response.json()["code"]


async def pair(harness: Harness, code: str, name: str = "phone") -> dict:
    response = await harness.api.post("/v1/kira/pair", json={"code": code, "name": name})
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.anyio
async def test_a_code_mints_a_device_token_that_reads_but_cannot_write(harness):
    code = await mint(harness)
    answer = await pair(harness, code)

    token = answer["token"]
    assert token.startswith("kd_")
    assert answer["device"]["name"] == "phone"
    device_auth = {"Authorization": f"Bearer {token}"}

    assert (await harness.api.get("/v1/models", headers=device_auth)).status_code == 200
    # A mutation needs the confirm secret, which never leaves the desktop.
    refused = await harness.api.post("/v1/kira/memory", headers=device_auth, json={"text": "kept"})
    assert refused.status_code == 401
    assert refused.json()["error"]["code"] == "unauthorized"


@pytest.mark.anyio
async def test_a_device_cannot_mint_a_code_or_list_devices(harness):
    answer = await pair(harness, await mint(harness))
    device_auth = {"Authorization": f"Bearer {answer['token']}"}

    assert (await harness.api.post("/v1/kira/pairing-code", headers=device_auth)).status_code == 401
    assert (await harness.api.get("/v1/kira/devices", headers=device_auth)).status_code == 401


@pytest.mark.anyio
async def test_the_owner_lists_devices_and_the_token_never_appears_in_a_row(harness):
    answer = await pair(harness, await mint(harness), "pixel")
    listing = await harness.api.get("/v1/kira/devices", headers=harness.auth)
    assert listing.status_code == 200
    devices = listing.json()["devices"]
    assert [device["name"] for device in devices] == ["pixel"]
    assert set(devices[0]) == {"id", "name", "created_at", "last_seen_at"}
    assert answer["token"] not in listing.text

    row = harness.store.conn.execute("SELECT * FROM devices").fetchone()
    assert row["token_hash"] == token_hash(answer["token"])
    assert answer["token"] not in dict(row).values()


@pytest.mark.anyio
async def test_revoking_a_device_locks_it_out_and_stops_listing_it(harness):
    answer = await pair(harness, await mint(harness))
    device_auth = {"Authorization": f"Bearer {answer['token']}"}
    device_id = answer["device"]["id"]

    revoked = await harness.api.delete(f"/v1/kira/devices/{device_id}", headers=harness.signed)
    assert revoked.status_code == 200
    assert (await harness.api.get("/v1/models", headers=device_auth)).status_code == 401
    assert (await harness.api.get("/v1/kira/devices", headers=harness.auth)).json()["devices"] == []


@pytest.mark.anyio
async def test_a_device_shows_when_it_was_last_seen(harness):
    answer = await pair(harness, await mint(harness))
    device_auth = {"Authorization": f"Bearer {answer['token']}"}
    before = answer["device"]["last_seen_at"]
    assert (await harness.api.get("/v1/models", headers=device_auth)).status_code == 200
    after = (await harness.api.get("/v1/kira/devices", headers=harness.auth)).json()["devices"][0]
    assert after["last_seen_at"] >= before


@pytest.mark.anyio
async def test_a_code_is_spent_by_the_first_device(harness):
    code = await mint(harness)
    await pair(harness, code)
    second = await harness.api.post("/v1/kira/pair", json={"code": code, "name": "second"})
    assert second.status_code == 400
    assert second.json()["error"]["code"] == "pairing_refused"


@pytest.mark.anyio
async def test_a_wrong_code_and_an_unknown_device_get_the_same_401_shape(harness):
    wrong = await harness.api.post("/v1/kira/pair", json={"code": "ZZZZZZZZ", "name": "phone"})
    assert wrong.status_code == 400
    assert "not valid" in wrong.json()["error"]["message"]
    unknown = await harness.api.get("/v1/models", headers={"Authorization": "Bearer kd_nope"})
    assert unknown.status_code == 401


@pytest.mark.anyio
async def test_a_pairing_code_needs_the_confirm_secret(harness):
    just_bearer = await harness.api.post(
        "/v1/kira/pairing-code", headers={"Authorization": f"Bearer {TEST_TOKEN}"}
    )
    assert just_bearer.status_code == 401
    with_confirm = await harness.api.post(
        "/v1/kira/pairing-code",
        headers={"Authorization": f"Bearer {TEST_TOKEN}", "X-Kira-Confirm": TEST_CONFIRM},
    )
    assert with_confirm.status_code == 200
    assert set(with_confirm.json()) == {"code", "expires_at"}


@pytest.mark.anyio
async def test_a_name_is_required_and_bounded(harness):
    code = await mint(harness)
    empty = await harness.api.post("/v1/kira/pair", json={"code": code, "name": "  "})
    assert empty.status_code == 400
    long = await harness.api.post("/v1/kira/pair", json={"code": code, "name": "x" * 41})
    assert long.status_code == 400
    # Neither refusal spent the code: it was never exchanged.
    assert (await harness.api.post("/v1/kira/pair", json={"code": code, "name": "phone"})).status_code == 200


def test_a_v2_database_gains_the_devices_table_and_keeps_its_messages(tmp_path):
    from kira.store import Store

    path = tmp_path / "old.sqlite"
    first = Store(path)
    first.add_message(first.create_session("AUTO"), "user", "kept across the upgrade")
    first._conn.execute("DROP TABLE devices")
    first._conn.execute("PRAGMA user_version=2")
    first._conn.commit()
    first._conn.close()

    reopened = Store(path)
    assert reopened.conn.execute("PRAGMA user_version").fetchone()[0] == 3
    assert reopened.conn.execute("SELECT COUNT(*) FROM devices").fetchone()[0] == 0
    assert reopened.conn.execute("SELECT content FROM messages").fetchone()[0] == "kept across the upgrade"


@pytest.mark.anyio
async def test_an_unknown_device_cannot_be_revoked(harness):
    answer = await harness.api.delete("/v1/kira/devices/nope", headers=harness.signed)
    assert answer.status_code == 404
