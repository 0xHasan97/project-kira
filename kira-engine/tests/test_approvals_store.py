from __future__ import annotations

import asyncio

import pytest

from kira.approvals import ApprovalBroker
from kira.store import Store


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "k.db")


def test_rows_go_pending_then_allowed(store):
    row = store.add_approval("s1", "write_file", {"path": "a.txt"}, "write", expires_at=999)
    assert row["status"] == "pending"
    assert store.pending_approvals()[0]["id"] == row["id"]
    decided = store.decide_approval(row["id"], "allow")
    assert decided["status"] == "allowed"
    assert store.decide_approval(row["id"], "deny") is None
    assert store.pending_approvals() == []


def test_restart_expires_pending(store):
    store.add_approval("s1", "run_command", {"argv": ["x"]}, "exec", expires_at=999)
    assert store.expire_pending_approvals() == 1
    assert store.pending_approvals() == []


def test_a_deny_without_a_reason_still_has_one(store):
    """The loop quotes the reason back to the model; an empty one reads as a broken sentence."""
    row = store.add_approval("s1", "write_file", {"path": "a.txt"}, "write", expires_at=999)
    decided = store.decide_approval(row["id"], "deny")
    assert decided["reason"] == "the user denied this call"
    assert store.decide_approval(row["id"], "deny", reason="asked twice") is None


def test_broker_resolves_allow(store):
    broker = ApprovalBroker(store, timeout_s=5)

    async def scenario():
        row = broker.open(session_id="s1", tool="write_file", arguments={"path": "a"}, risk="write")
        waiter = asyncio.create_task(broker.wait(row["id"]))
        await asyncio.sleep(0)
        broker.decide(row["id"], "allow")
        return await waiter

    assert asyncio.run(scenario()).allowed is True
    assert store.pending_approvals() == []


def test_broker_timeout_denies(store):
    broker = ApprovalBroker(store, timeout_s=0.05)

    async def scenario():
        row = broker.open(session_id="s1", tool="write_file", arguments={}, risk="write")
        return await broker.wait(row["id"])

    decision = asyncio.run(scenario())
    assert decision.allowed is False
    assert "timed out" in decision.reason


def test_cancel_denies_and_marks_expired(store):
    broker = ApprovalBroker(store, timeout_s=5)

    async def scenario():
        row = broker.open(session_id="s1", tool="write_file", arguments={}, risk="write")
        waiter = asyncio.create_task(broker.wait(row["id"]))
        await asyncio.sleep(0)
        broker.cancel(row["id"])
        return await waiter

    decision = asyncio.run(scenario())
    assert decision.allowed is False
    assert decision.reason == "the turn ended before a decision"
