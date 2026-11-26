from __future__ import annotations

import json
from collections.abc import AsyncIterator

from ..errors import BAD_STREAM, ProviderCallError, STREAM_ERROR
from ..types import Completed, Delta, GenRequest, StreamEvent, ToolCall, ToolCallEvent, Usage
from .base import Provider, split_data_url, sse_data_lines

FINISH_MAP = {
    "STOP": "stop",
    "MAX_TOKENS": "length",
    "SAFETY": "content_filter",
    "RECITATION": "content_filter",
    "OTHER": "stop",
}


def to_payload(req: GenRequest) -> dict:
    system_parts = [m.content for m in req.messages if m.role == "system" and m.content]
    contents: list[dict] = []
    for m in req.messages:
        if m.role == "system":
            continue
        if m.role == "tool":
            contents.append(
                {
                    "role": "user",
                    "parts": [
                        {
                            "functionResponse": {
                                "name": m.name or "tool",
                                "response": {"result": m.content},
                            }
                        }
                    ],
                }
            )
            continue
        parts: list[dict] = []
        if m.content:
            parts.append({"text": m.content})
        for image in m.images:
            media_type, data = split_data_url(image)
            parts.append({"inlineData": {"mimeType": media_type, "data": data}})
        for tc in m.tool_calls:
            part: dict = {"functionCall": {"name": tc.name, "args": tc.arguments}}
            # The signature sits beside the functionCall, not inside it, and Google insists on it:
            # measured on `gemini-3.5-flash`, the replay without it is a 400 and with it a 200.
            if tc.signature:
                part["thoughtSignature"] = tc.signature
            parts.append(part)
        if not parts:
            parts.append({"text": ""})
        contents.append({"role": "model" if m.role == "assistant" else "user", "parts": parts})

    payload: dict = {
        "contents": contents,
        "generationConfig": {
            "temperature": req.temperature,
            **({"maxOutputTokens": req.max_output_tokens} if req.max_output_tokens else {}),
        },
    }
    if system_parts:
        payload["systemInstruction"] = {"parts": [{"text": "\n\n".join(system_parts)}]}
    if req.tools:
        payload["tools"] = [
            {
                "functionDeclarations": [
                    {
                        "name": (t.get("function") or t)["name"],
                        "description": (t.get("function") or t).get("description", ""),
                        "parameters": (t.get("function") or t).get("parameters")
                        or {"type": "object", "properties": {}},
                    }
                    for t in req.tools
                ]
            }
        ]
    return payload


class Gemini(Provider):
    def _headers(self) -> dict:
        return {"x-goog-api-key": self.api_key, "content-type": "application/json", "Accept": "text/event-stream"}

    async def list_models(self) -> list[str]:
        resp = await self.client.get(
            f"{self.base_url}/v1beta/models", params={"pageSize": 200}, headers={"x-goog-api-key": self.api_key}
        )
        if resp.status_code >= 400:
            raise await self._read_error(resp)
        return [str(m["name"]).removeprefix("models/") for m in resp.json().get("models", []) if "name" in m]

    async def stream(self, req: GenRequest) -> AsyncIterator[StreamEvent]:
        url = f"{self.base_url}/v1beta/models/{req.model}:streamGenerateContent"
        async with self.client.stream(
            "POST", url, params={"alt": "sse"}, json=to_payload(req), headers=self._headers()
        ) as resp:
            if resp.status_code >= 400:
                raise await self._read_error(resp)

            usage = Usage()
            finish_reason = "stop"
            call_seq = 0
            emitted_tool = False

            async for data in sse_data_lines(resp):
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError as exc:
                    raise ProviderCallError(self.name, f"unparseable SSE chunk: {exc}", code=BAD_STREAM) from exc

                if chunk.get("error"):
                    err = chunk["error"]
                    raise ProviderCallError(
                        self.name, str(err.get("message") or "gemini error"), code=str(err.get("status") or STREAM_ERROR)
                    )

                um = chunk.get("usageMetadata") or {}
                if um:
                    usage = Usage(
                        input_tokens=int(um.get("promptTokenCount") or usage.input_tokens),
                        output_tokens=int(um.get("candidatesTokenCount") or usage.output_tokens),
                    )

                for cand in chunk.get("candidates") or []:
                    if cand.get("finishReason"):
                        finish_reason = FINISH_MAP.get(str(cand["finishReason"]), "stop")
                    for part in (cand.get("content") or {}).get("parts") or []:
                        if part.get("text"):
                            yield Delta(text=part["text"])
                        call = part.get("functionCall")
                        if call:
                            emitted_tool = True
                            call_seq += 1
                            yield ToolCallEvent(
                                call=ToolCall(
                                    id=str(call.get("id") or f"gemini_call_{call_seq}"),
                                    name=str(call.get("name") or ""),
                                    arguments=dict(call.get("args") or {}),
                                    signature=str(part["thoughtSignature"]) if part.get("thoughtSignature") else None,
                                )
                            )

        yield Completed(finish_reason="tool_calls" if emitted_tool else finish_reason, usage=usage)
