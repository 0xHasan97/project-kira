from __future__ import annotations

import json
from collections.abc import AsyncIterator

from ..errors import BAD_STREAM, ProviderCallError
from ..types import Completed, Delta, GenRequest, Message, StreamEvent, ToolCall, ToolCallEvent, Usage
from .base import Provider, parse_arguments, sse_data_lines


def to_wire(messages: list[Message]) -> list[dict]:
    wire: list[dict] = []
    for m in messages:
        if m.role == "tool":
            wire.append({"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content})
            continue
        content: object = m.content or ""
        if m.images:
            content = [{"type": "text", "text": m.content or ""}] + [
                {"type": "image_url", "image_url": {"url": image}} for image in m.images
            ]
        item: dict = {"role": m.role, "content": content}
        if m.tool_calls:
            item["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": _dumps(tc.arguments)},
                }
                for tc in m.tool_calls
            ]
        wire.append(item)
    return wire


def _dumps(value: dict) -> str:
    return json.dumps(value)


class OpenAICompat(Provider):
    """Works with OpenAI, OpenRouter, Groq, Together, and any local
    OpenAI-compatible server (Ollama/LM Studio/llama-server) when offline lands."""

    async def list_models(self) -> list[str]:
        resp = await self.client.get(f"{self.base_url}/models", headers=self._headers())
        if resp.status_code >= 400:
            raise await self._read_error(resp)
        # `or []`, not a `.get` default: Ollama ships `{"data": null}` until its first model is pulled.
        data = resp.json().get("data") or []
        return [str(m["id"]) for m in data if "id" in m]

    def _headers(self) -> dict:
        # A keyless stanza means no credential is wanted, and `Bearer ` with nothing after it is its
        # own kind of wrong — a strict local server can reject it. Send the header only with a key.
        auth = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        return {**auth, "Accept": "text/event-stream"}

    async def stream(self, req: GenRequest) -> AsyncIterator[StreamEvent]:
        payload: dict = {
            "model": req.model,
            "messages": to_wire(req.messages),
            "stream": True,
            "stream_options": {"include_usage": True},
            "temperature": req.temperature,
        }
        if req.tools:
            payload["tools"] = req.tools
            payload["tool_choice"] = "auto"
        if req.max_output_tokens:
            payload["max_tokens"] = req.max_output_tokens

        async with self.client.stream(
            "POST", f"{self.base_url}/chat/completions", json=payload, headers=self._headers()
        ) as resp:
            if resp.status_code >= 400:
                raise await self._read_error(resp)

            pending_tools: dict[int, dict] = {}
            usage = Usage()
            finish_reason = "stop"

            async for data in sse_data_lines(resp):
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError as exc:
                    raise ProviderCallError(self.name, f"unparseable SSE chunk: {exc}", code=BAD_STREAM) from exc

                if chunk.get("usage"):
                    u = chunk["usage"]
                    usage = Usage(
                        input_tokens=int(u.get("prompt_tokens") or 0),
                        output_tokens=int(u.get("completion_tokens") or 0),
                    )

                for choice in chunk.get("choices") or []:
                    if choice.get("finish_reason"):
                        finish_reason = str(choice["finish_reason"])
                    delta = choice.get("delta") or {}
                    text = delta.get("content")
                    if text:
                        yield Delta(text=text)
                    for frag in delta.get("tool_calls") or []:
                        idx = int(frag.get("index") or 0)
                        slot = pending_tools.setdefault(idx, {"id": None, "function": {"name": "", "arguments": ""}})
                        if frag.get("id"):
                            slot["id"] = frag["id"]
                        fn = frag.get("function") or {}
                        if fn.get("name"):
                            slot["function"]["name"] = fn["name"]
                        if fn.get("arguments"):
                            slot["function"]["arguments"] += fn["arguments"]

        for idx in sorted(pending_tools):
            entry = pending_tools[idx]
            args = parse_arguments(entry["function"]["arguments"])
            yield ToolCallEvent(
                call=ToolCall(
                    id=entry["id"] or f"call_{idx}", name=entry["function"]["name"], arguments=args
                )
            )
        yield Completed(finish_reason="tool_calls" if pending_tools else finish_reason, usage=usage)
