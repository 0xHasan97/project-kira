from __future__ import annotations

import asyncio


def get(harness, path, **kwargs):
    async def scenario():
        return await harness.api.get(path, **kwargs)

    return asyncio.run(scenario())


def put(harness, path, **kwargs):
    async def scenario():
        return await harness.api.put(path, **kwargs)

    return asyncio.run(scenario())


def test_registry_lists_builtins(harness):
    response = get(harness, "/v1/kira/tools", headers=harness.auth)
    assert response.status_code == 200
    tools = {row["name"]: row for row in response.json()["tools"]}
    assert {"echo", "now", "list_dir", "read_file", "search_text", "write_file", "run_command"} <= set(tools)
    assert tools["write_file"]["policy"] == "ask"
    assert "plugins" in response.json()


def test_policy_write_needs_confirm_and_resets(harness):
    unsigned = put(harness, "/v1/kira/tools/write_file", headers=harness.auth, json={"policy": "deny"})
    assert unsigned.status_code == 401
    response = put(harness, "/v1/kira/tools/write_file", headers=harness.signed, json={"policy": "deny"})
    assert response.status_code == 200
    assert response.json()["tool"]["policy"] == "deny"
    assert harness.store.tool_policies() == {"write_file": "deny"}
    reset = put(harness, "/v1/kira/tools/write_file", headers=harness.signed, json={"policy": None})
    assert reset.status_code == 200
    assert harness.store.tool_policies() == {}


def test_policy_write_unknown_tool_and_bad_value(harness):
    assert put(harness, "/v1/kira/tools/nope", headers=harness.signed, json={"policy": "allow"}).status_code == 404
    bad = put(harness, "/v1/kira/tools/write_file", headers=harness.signed, json={"policy": "sometimes"})
    assert bad.status_code == 400
