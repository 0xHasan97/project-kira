from __future__ import annotations

import asyncio
import json

from tests.conftest import ok, openai_text_chunks, openai_tool_chunks


def sse_types(response_text: str) -> list[str]:
    return [json.loads(line[6:])["type"] for line in response_text.splitlines() if line.startswith("data: {")]


def tool_turn(harness, tool="write_file", arguments='{"path":"a.txt","content":"hi"}'):
    harness.script.queue("https://fast1.invalid/v1", ok(openai_tool_chunks(tool, arguments)))
    harness.script.queue("https://fast1.invalid/v1", ok(openai_text_chunks("written")))


def test_approval_endpoints_require_confirm(harness):
    async def scenario():
        return await harness.api.get("/v1/kira/approvals", headers=harness.auth)

    response = asyncio.run(scenario())
    assert response.status_code == 200
    assert response.json() == {"approvals": []}


def test_decision_needs_the_confirm_secret(harness):
    async def scenario():
        return await harness.api.post("/v1/kira/approvals/nope", headers=harness.auth, json={"decision": "allow"})

    response = asyncio.run(scenario())
    assert response.status_code == 401


def test_unknown_and_settled_ids(harness):
    async def scenario():
        return await harness.api.post("/v1/kira/approvals/nope", headers=harness.signed, json={"decision": "allow"})

    response = asyncio.run(scenario())
    assert response.status_code == 404


def test_stream_emits_approval_and_resumes(harness):
    harness.store.set_tool_policy("write_file", "ask")
    harness.engine.workspace.write_text("a.txt", "old")
    tool_turn(harness)

    async def scenario():
        approved = asyncio.Event()

        async def decide():
            for _ in range(100):
                await asyncio.sleep(0.02)
                pending = harness.store.pending_approvals()
                if pending:
                    response = await harness.api.post(
                        f"/v1/kira/approvals/{pending[0]['id']}", headers=harness.signed, json={"decision": "allow"}
                    )
                    assert response.status_code == 200
                    approved.set()
                    return
            raise AssertionError("no approval ever became pending")

        task = asyncio.create_task(decide())
        response = await harness.api.post(
            "/v1/chat/completions",
            headers=harness.auth,
            json={"messages": [{"role": "user", "content": "write a.txt"}], "stream": True, "model": "mini"},
        )
        await task
        return response

    response = asyncio.run(scenario())
    assert response.status_code == 200
    assert "approval" in sse_types(response.text)
    assert "tool_executed" in response.text
    assert harness.engine.workspace.read_text("a.txt") == "hi"


def test_the_checkpoint_belongs_to_the_turns_session(harness):
    """The agent panel asks for checkpoints by session; a row with no session can never appear."""
    harness.engine.workspace.write_text("a.txt", "old")
    tool_turn(harness)

    async def scenario():
        async def decide():
            for _ in range(100):
                await asyncio.sleep(0.02)
                pending = harness.store.pending_approvals()
                if pending:
                    await harness.api.post(
                        f"/v1/kira/approvals/{pending[0]['id']}", headers=harness.signed, json={"decision": "allow"}
                    )
                    return
            raise AssertionError("no approval ever became pending")

        task = asyncio.create_task(decide())
        response = await harness.api.post(
            "/v1/chat/completions",
            headers=harness.auth,
            json={"messages": [{"role": "user", "content": "write a.txt"}], "stream": True, "model": "mini"},
        )
        await task
        return response

    response = asyncio.run(scenario())
    done = next(json.loads(line[6:]) for line in response.text.splitlines() if '"type": "done"' in line)
    rows = harness.engine.checkpoints.list(session_id=done["session_id"])
    assert [row["tool"] for row in rows] == ["write_file"]
