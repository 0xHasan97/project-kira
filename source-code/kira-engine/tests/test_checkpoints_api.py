from __future__ import annotations

import asyncio


def seed(harness):
    ws = harness.engine.workspace
    ws.write_text("a.txt", "before")
    row = harness.engine.checkpoints.take(session_id="s1", tool="write_file", call_id="c1", paths=["a.txt"])
    ws.write_text("a.txt", "after")
    harness.engine.checkpoints.finalize(row["id"])
    return row["id"]


def get(harness, path, **kwargs):
    async def scenario():
        return await harness.api.get(path, **kwargs)

    return asyncio.run(scenario())


def post(harness, path, **kwargs):
    async def scenario():
        return await harness.api.post(path, **kwargs)

    return asyncio.run(scenario())


def test_list_and_detail(harness):
    checkpoint_id = seed(harness)
    listed = get(harness, "/v1/kira/checkpoints", headers=harness.auth)
    assert listed.status_code == 200
    rows = listed.json()["checkpoints"]
    assert rows[0]["id"] == checkpoint_id
    detail = get(harness, f"/v1/kira/checkpoints/{checkpoint_id}", headers=harness.auth)
    assert detail.status_code == 200
    assert detail.json()["files"][0]["diff"]


def test_restore_needs_confirm_and_round_trips(harness):
    checkpoint_id = seed(harness)
    unsigned = post(harness, f"/v1/kira/checkpoints/{checkpoint_id}/restore", headers=harness.auth, json={})
    assert unsigned.status_code == 401
    response = post(harness, f"/v1/kira/checkpoints/{checkpoint_id}/restore", headers=harness.signed, json={})
    assert response.status_code == 200
    assert harness.engine.workspace.read_text("a.txt") == "before"


def test_restore_conflict_is_409_and_force_wins(harness):
    checkpoint_id = seed(harness)
    harness.engine.workspace.write_text("a.txt", "later")
    conflict = post(harness, f"/v1/kira/checkpoints/{checkpoint_id}/restore", headers=harness.signed, json={})
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "checkpoint_conflict"
    forced = post(
        harness, f"/v1/kira/checkpoints/{checkpoint_id}/restore", headers=harness.signed, json={"force": True}
    )
    assert forced.status_code == 200
    assert harness.engine.workspace.read_text("a.txt") == "before"


def test_unknown_checkpoint_is_404(harness):
    assert get(harness, "/v1/kira/checkpoints/nope", headers=harness.auth).status_code == 404
