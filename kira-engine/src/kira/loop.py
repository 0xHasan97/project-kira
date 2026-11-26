from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from .approvals import ApprovalBroker
from .checkpoints import CheckpointManager
from .policy import effective_policy
from .router import AttemptState, Note, Plan, Routed, Router
from .tools import ToolRegistry
from .types import ApprovalRequest, Completed, Delta, GenRequest, Message, ToolCall, ToolCallEvent, Usage


def _estimate_usage(conversation: list[Message], text: str) -> Usage:
    """Four characters per token, the usual English rule of thumb. A labelled guess keeps
    the ledger honest when a provider sends no usage; a silent zero spends nothing."""
    prompt_chars = sum(
        len(message.content)
        + sum(len(call.name) + len(json.dumps(call.arguments)) for call in message.tool_calls)
        for message in conversation
    )
    return Usage(
        input_tokens=max(1, prompt_chars // 4),
        output_tokens=max(1, len(text) // 4),
        estimated=True,
    )


@dataclass
class TurnState:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    finish_reason: str = "stop"
    steps: int = 0
    status: str = "complete"  # complete | max_steps | interrupted


@dataclass
class AgentRun:
    """Streams one agent turn: model output, tool executions, then the follow-up."""

    router: Router
    tools: ToolRegistry
    plan: Plan
    messages: list[Message]
    max_steps: int = 6
    temperature: float = 1.0
    max_output_tokens: int | None = None
    approvals: ApprovalBroker | None = None
    checkpoints: CheckpointManager | None = None
    policies: dict[str, str] | None = None
    session_id: str | None = None
    state: TurnState = field(default_factory=TurnState)
    attempt: AttemptState = field(default_factory=AttemptState)

    async def events(self) -> AsyncIterator[Routed]:
        conversation = list(self.messages)

        for _step in range(self.max_steps):
            self.state.steps += 1
            request = GenRequest(
                model=self.plan.choices[0].model,
                messages=list(conversation),
                tools=self.tools.schemas(),
                temperature=self.temperature,
                max_output_tokens=self.max_output_tokens,
            )
            text_parts: list[str] = []
            calls: list[ToolCall] = []
            self.state.text = ""
            estimated = False

            async for event in self.router.events(self.plan, request, self.attempt):
                if isinstance(event, Delta):
                    text_parts.append(event.text)
                    # Accumulate live: if the stream dies mid-way the partial is all we have.
                    self.state.text = "".join(text_parts)
                elif isinstance(event, ToolCallEvent):
                    calls.append(event.call)
                elif isinstance(event, Completed):
                    usage = event.usage
                    if usage.input_tokens == 0 and usage.output_tokens == 0 and self.state.text:
                        usage = _estimate_usage(conversation, self.state.text)
                        estimated = True
                    self.state.usage.input_tokens += usage.input_tokens
                    self.state.usage.output_tokens += usage.output_tokens
                    self.state.usage.estimated = self.state.usage.estimated or usage.estimated
                    self.state.finish_reason = event.finish_reason
                yield event

            if estimated:
                # After the stream, not inside it: the router names the provider that served
                # only once it resumes past `Completed`, and an unattributed record is half a fact.
                record = {"event": "usage_estimated", "provider": self.attempt.served_by, "model": self.attempt.served_model}
                self.attempt.chain.append(record)
                yield Note(record)

            if not calls:
                self.state.status = "complete"
                return

            self.state.tool_calls = calls
            conversation.append(
                Message(role="assistant", content=self.state.text, tool_calls=calls)
            )
            for call in calls:
                tool = self.tools.get(call.name)
                policy = effective_policy(tool, self.policies or {}) if tool is not None else "deny"
                if policy == "deny":
                    reason = "tool is denied by policy"
                    record = {"event": "tool_denied", "tool": call.name, "call_id": call.id, "reason": reason}
                    self.attempt.chain.append(record)
                    yield Note(record)
                    conversation.append(Message(
                        role="tool",
                        content=f"The user denied permission to run \"{call.name}\". {reason}. Do not retry; explain the limitation instead.",
                        tool_call_id=call.id,
                        name=call.name,
                    ))
                    continue
                if policy == "ask" and self.approvals is not None:
                    pending = self.approvals.open(
                        session_id=self.session_id,
                        tool=call.name,
                        arguments=call.arguments,
                        risk=tool.risk if tool else "unknown",
                    )
                    record = {
                        "event": "tool_approval_requested",
                        "tool": call.name,
                        "call_id": call.id,
                        "approval_id": pending["id"],
                        "risk": tool.risk if tool else "unknown",
                    }
                    self.attempt.chain.append(record)
                    yield Note(record)
                    yield ApprovalRequest(pending["id"], call.name, tool.risk if tool else "unknown", call.arguments)
                    decision = await self.approvals.wait(pending["id"])
                    if not decision.allowed:
                        record = {"event": "tool_denied", "tool": call.name, "call_id": call.id, "reason": decision.reason}
                        self.attempt.chain.append(record)
                        yield Note(record)
                        conversation.append(Message(
                            role="tool",
                            content=f"The user denied permission to run \"{call.name}\". {decision.reason}. Do not retry; explain the limitation instead.",
                            tool_call_id=call.id,
                            name=call.name,
                        ))
                        continue
                elif policy == "ask":
                    reason = "approval required, but this request is non-streaming and cannot be approved"
                    record = {"event": "tool_denied", "tool": call.name, "call_id": call.id, "reason": reason}
                    self.attempt.chain.append(record)
                    yield Note(record)
                    conversation.append(Message(
                        role="tool",
                        content=f"The user denied permission to run \"{call.name}\". {reason}. Do not retry; explain the limitation instead.",
                        tool_call_id=call.id,
                        name=call.name,
                    ))
                    continue

                checkpoint_id = None
                if tool is not None and tool.risk == "write" and self.checkpoints is not None:
                    try:
                        checkpoint = self.checkpoints.take(
                            session_id=self.session_id,
                            tool=call.name,
                            call_id=call.id,
                            paths=tool.checkpoint_paths(call.arguments) if tool.checkpoint_paths else [],
                        )
                    except Exception as exc:  # noqa: BLE001 - a failed checkpoint must stop the write
                        record = {"event": "tool_denied", "tool": call.name, "call_id": call.id, "reason": f"checkpoint failed: {exc}"}
                        self.attempt.chain.append(record)
                        yield Note(record)
                        conversation.append(Message(role="tool", content=f"error: checkpoint failed: {exc}", tool_call_id=call.id, name=call.name))
                        continue
                    checkpoint_id = checkpoint["id"]
                    record = {
                        "event": "checkpoint_created",
                        "tool": call.name,
                        "call_id": call.id,
                        "checkpoint_id": checkpoint_id,
                        "files": len(checkpoint["files"]),
                    }
                    self.attempt.chain.append(record)
                    yield Note(record)

                outcome = await self.tools.execute(call.name, call.arguments)
                if checkpoint_id is not None and self.checkpoints is not None:
                    self.checkpoints.finalize(checkpoint_id)
                conversation.append(
                    Message(role="tool", content=outcome.content, tool_call_id=call.id, name=call.name)
                )
                summary = outcome.summary or (
                    tool.summary(call.arguments) if tool is not None and tool.summary else call.name
                )
                record = {
                    "event": "tool_executed",
                    "tool": call.name,
                    "call_id": call.id,
                    "ok": outcome.ok,
                    "chars": len(outcome.content),
                    "risk": tool.risk if tool is not None else "unknown",
                    "summary": summary,
                }
                if outcome.duration_ms is not None:
                    record["duration_ms"] = outcome.duration_ms
                if outcome.exit_code is not None:
                    record["exit_code"] = outcome.exit_code
                if outcome.kind is not None:
                    record["kind"] = outcome.kind
                if checkpoint_id is not None:
                    record["checkpoint_id"] = checkpoint_id
                self.attempt.chain.append(record)
                yield Note(record)

        self.state.status = "max_steps"
