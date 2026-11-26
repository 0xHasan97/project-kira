from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

ToolSchema = dict[str, Any]


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]
    #: An opaque value some providers attach to a function call and require back verbatim when the
    #: call is replayed. Google's thinking models sign every `functionCall` part (`thoughtSignature`)
    #: and answer a replay without it with `400 Function call is missing a thought_signature`; nothing
    #: in our own tool contract, UI or history reads it, so it stays off the wire and lives only for
    #: the length of the turn that made it. See `tests/test_providers.py`.
    signature: str | None = None


@dataclass
class Message:
    role: str  # system | user | assistant | tool
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None
    name: str | None = None
    #: Data URLs for a vision model. Never persisted; the call attaches them to one turn.
    images: list[str] = field(default_factory=list)


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    estimated: bool = False


@dataclass
class GenRequest:
    model: str
    messages: list[Message]
    tools: list[ToolSchema] = field(default_factory=list)
    temperature: float = 1.0
    max_output_tokens: int | None = None


@dataclass
class Delta:
    text: str


@dataclass
class ToolCallEvent:
    call: ToolCall


@dataclass
class ApprovalRequest:
    id: str
    tool: str
    risk: str
    arguments: dict[str, Any]


@dataclass
class Completed:
    finish_reason: str
    usage: Usage = field(default_factory=Usage)


StreamEvent = Delta | ToolCallEvent | Completed
