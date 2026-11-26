from __future__ import annotations

import json
from collections.abc import AsyncIterator

from ..errors import BAD_STREAM, ProviderCallError, STREAM_ERROR
from ..types import Completed, Delta, GenRequest, Message, StreamEvent, ToolCall, ToolCallEvent, Usage
from .base import Provider, parse_arguments, split_data_url, sse_data_lines

ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MAX_TOKENS = 4096

STOP_REASON_MAP = {
    "end_turn": "stop",
    "stop_sequence": "stop",
    "max_tokens": "length",
    "tool_use": "tool_calls",
}


def split_system(messages: list[Message]) -> tuple[str, list[Message]]:
    system = "\n\n".join(m.content for m in messages if m.role == "system" and m.content)
    return system, [m for m in messages if m.role != "system"]


def to_wire(messages: list[Message]) -> list[dict]:
    """Anthropic has no 'tool' role: tool results ride inside a user turn."""
    wire: list[dict] = []
    for m in messages:
        if m.role == "tool":
            wire.append(
                {
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": m.tool_call_id, "content": m.content}
                    ],
                }
            )
            continue
        blocks: list[dict] = []
        if m.content:
            blocks.append({"type": "text", "text": m.content})
        for image in m.images:
            media_type, data = split_data_url(image)
            blocks.append({"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}})
        for tc in m.tool_calls:
            blocks.append({"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.arguments})
        if not blocks:
            blocks.append({"type": "text", "text": ""})
        wire.append({"role": "assistant" if m.role == "assistant" else "user", "content": blocks})
    return _merge_consecutive(wire)


def _merge_consecutive(wire: list[dict]) -> list[dict]:
    """Adjacent same-role turns must merge — Anthropic requires strict alternation."""
    merged: list[dict] = []
    for item in wire:
        if merged and merged[-1]["role"] == item["role"]:
            merged[-1]["content"].extend(item["content"])
        else:
            merged.append({"role": item["role"], "content": list(item["content"])})
    return merged


def to_tools(tools: list[dict]) -> list[dict]:
    out = []
    for t in tools:
        fn = t.get("function", t)
        out.append(
            {
                "name": fn["name"],
                "description": fn.get("description", ""),
                "input_schema": fn.get("parameters") or {"type": "object", "properties": {}},
            }
        )
    return out


class Anthropic(Provider):
    async def list_models(self) -> list[str]:
        resp = await self.client.get(
            f"{self.base_url}/v1/models",
            params={"limit": 100},
            headers={"x-api-key": self.api_key, "anthropic-version": ANTHROPIC_VERSION},
        )
        if resp.status_code >= 400:
            raise await self._read_error(resp)
        return [str(m["id"]) for m in resp.json().get("data", []) if "id" in m]

    def _headers(self) -> dict:
        return {
            "x-api-key": self.api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
            "Accept": "text/event-stream",
        }

    async def stream(self, req: GenRequest) -> AsyncIterator[StreamEvent]:
        system, rest = split_system(req.messages)
        payload: dict = {
            "model": req.model,
            "messages": to_wire(rest),
            "stream": True,
            "max_tokens": req.max_output_tokens or DEFAULT_MAX_TOKENS,
            "temperature": req.temperature,
        }
        if system:
            payload["system"] = system
        if req.tools:
            payload["tools"] = to_tools(req.tools)

        async with self.client.stream(
            "POST", f"{self.base_url}/v1/messages", json=payload, headers=self._headers()
        ) as resp:
            if resp.status_code >= 400:
                raise await self._read_error(resp)

            usage = Usage()
            stop_reason = "end_turn"
            open_tools: dict[int, dict] = {}

            async for data in sse_data_lines(resp):
                try:
                    event = json.loads(data)
                except json.JSONDecodeError as exc:
                    raise ProviderCallError(self.name, f"unparseable SSE chunk: {exc}", code=BAD_STREAM) from exc

                kind = event.get("type")
                if kind == "error":
                    err = event.get("error") or {}
                    raise ProviderCallError(
                        self.name, str(err.get("message") or "stream error"), code=str(err.get("type") or STREAM_ERROR)
                    )
                if kind == "message_start":
                    u = (event.get("message") or {}).get("usage") or {}
                    usage.input_tokens = int(u.get("input_tokens") or 0)
                elif kind == "content_block_start":
                    block = event.get("content_block") or {}
                    if block.get("type") == "tool_use":
                        open_tools[int(event.get("index") or 0)] = {
                            "id": block.get("id"),
                            "name": block.get("name") or "",
                            "json": "",
                        }
                elif kind == "content_block_delta":
                    delta = event.get("delta") or {}
                    dtype = delta.get("type")
                    if dtype == "text_delta" and delta.get("text"):
                        yield Delta(text=delta["text"])
                    elif dtype == "input_json_delta":
                        idx = int(event.get("index") or 0)
                        if idx in open_tools:
                            open_tools[idx]["json"] += delta.get("partial_json") or ""
                elif kind == "content_block_stop":
                    idx = int(event.get("index") or 0)
                    slot = open_tools.pop(idx, None)
                    if slot:
                        yield ToolCallEvent(
                            call=ToolCall(
                                id=slot["id"] or f"toolu_{idx}",
                                name=slot["name"],
                                arguments=parse_arguments(slot["json"] or "{}"),
                            )
                        )
                elif kind == "message_delta":
                    d = event.get("delta") or {}
                    if d.get("stop_reason"):
                        stop_reason = str(d["stop_reason"])
                    u = event.get("usage") or {}
                    usage.output_tokens = int(u.get("output_tokens") or 0)

        yield Completed(finish_reason=STOP_REASON_MAP.get(stop_reason, "stop"), usage=usage)
