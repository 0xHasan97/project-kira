from __future__ import annotations

import asyncio

from kira.approvals import ApprovalBroker
from kira.loop import AgentRun
from kira.router import Note
from kira.store import Store
from kira.tools import ToolDef, ToolOutcome, ToolRegistry
from kira.types import ApprovalRequest, Delta, Message


class FakeRouter:
    """Returns one tool call, then a plain completion. Ignores the plan entirely."""

    def __init__(self, call):
        self.call = call
        self.calls = 0

        class Attempt:
            chain: list = []
            served_by = "fast_one"
            served_model = "mini"

        self.attempt = Attempt()

    async def events(self, plan, request, attempt):
        from kira.types import Completed, ToolCallEvent, Usage

        self.calls += 1
        if self.calls == 1:
            yield ToolCallEvent(self.call)
            yield Completed("tool_calls", Usage(1, 1))
        else:
            yield Delta("done")
            yield Completed("stop", Usage(1, 1))


def build(tmp_path, policy, broker=None):
    store = Store(tmp_path / "k.db")
    reg = ToolRegistry()
    seen = []

    def handler(args):
        seen.append(args)
        return ToolOutcome(ok=True, content="ok", summary="x")

    reg.register(ToolDef("write_file", "d", {}, handler, risk="write", default_policy="ask"))
    from kira.types import ToolCall

    class Plan:
        choices = [type("C", (), {"model": "mini"})()]
        mode = "AUTO"
        skips: list = []

    run = AgentRun(
        router=FakeRouter(ToolCall("c1", "write_file", {"path": "a.txt"})),
        tools=reg,
        plan=Plan(),
        messages=[Message("user", "write it")],
        policies={"write_file": policy},
        approvals=broker,
    )
    return run, seen, store


def collect(run):
    async def go():
        events = []
        async for event in run.events():
            events.append(event)
        return events

    return asyncio.run(go())


def test_deny_executes_nothing_and_tells_the_model(tmp_path):
    run, seen, store = build(tmp_path, "deny")
    events = collect(run)
    assert seen == []
    assert any(isinstance(e, Note) and e.record["event"] == "tool_denied" for e in events)
    tool_message = [m for m in run.messages if m.role == "tool"]
    assert tool_message == []  # messages list is the input; conversation is internal
    assert run.state.status == "complete"


def test_allow_executes_and_records_rich_fields(tmp_path):
    run, seen, store = build(tmp_path, "allow")
    events = collect(run)
    assert seen == [{"path": "a.txt"}]
    executed = [e.record for e in events if isinstance(e, Note) and e.record["event"] == "tool_executed"]
    assert executed[0]["summary"] == "x"
    assert executed[0]["risk"] == "write"


def test_ask_without_a_channel_denies(tmp_path):
    run, seen, store = build(tmp_path, "ask", broker=None)
    events = collect(run)
    assert seen == []
    denied = [e.record for e in events if isinstance(e, Note) and e.record["event"] == "tool_denied"]
    assert "non-streaming" in denied[0]["reason"]


def test_ask_emits_approval_then_runs_on_allow(tmp_path):
    store = Store(tmp_path / "k.db")
    broker = ApprovalBroker(store, timeout_s=5)
    run, seen, store2 = build(tmp_path, "ask", broker=broker)

    async def go():
        events = []
        async for event in run.events():
            events.append(event)
            if isinstance(event, ApprovalRequest):
                broker.decide(event.id, "allow")
        return events

    events = asyncio.run(go())
    assert any(isinstance(e, ApprovalRequest) for e in events)
    assert seen == [{"path": "a.txt"}]
    requested = [e.record for e in events if isinstance(e, Note) and e.record["event"] == "tool_approval_requested"]
    assert requested and requested[0]["risk"] == "write"


def test_ask_denied_by_human_stops_the_call(tmp_path):
    store = Store(tmp_path / "k.db")
    broker = ApprovalBroker(store, timeout_s=5)
    run, seen, store2 = build(tmp_path, "ask", broker=broker)

    async def go():
        async for event in run.events():
            if isinstance(event, ApprovalRequest):
                broker.decide(event.id, "deny")

    asyncio.run(go())
    assert seen == []
