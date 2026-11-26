from __future__ import annotations

import asyncio

from kira.app import wire_usage
from kira.loop import AgentRun
from kira.tools import ToolRegistry
from kira.types import Completed, Delta, Message, Usage


class NoUsageRouter:
    async def events(self, plan, request, attempt):
        yield Delta("hello world")
        yield Completed("stop", Usage(0, 0))


def test_missing_usage_is_estimated_and_labelled():
    class Plan:
        choices = [type("C", (), {"model": "mini"})()]
        mode = "AUTO"
        skips: list = []

    run = AgentRun(
        router=NoUsageRouter(),
        tools=ToolRegistry(),
        plan=Plan(),
        messages=[Message("user", "hi")],
    )
    events = asyncio.run(_collect(run))
    assert run.state.usage.estimated is True
    assert run.state.usage.input_tokens >= 1
    assert run.state.usage.output_tokens >= 1
    assert any(getattr(e, "record", {}).get("event") == "usage_estimated" for e in events)


async def _collect(run):
    out = []
    async for event in run.events():
        out.append(event)
    return out


def test_wire_usage_carries_the_flag():
    assert wire_usage(Usage(3, 4, estimated=True)) == {
        "prompt_tokens": 3, "completion_tokens": 4, "estimated": True,
    }
    assert wire_usage(Usage(3, 4))["estimated"] is False
