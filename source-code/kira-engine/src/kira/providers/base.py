from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

import httpx

from ..errors import PROVIDER_4XX, PROVIDER_5XX, BAD_TOOL_CALL, ProviderCallError, RATE_LIMITED
from ..types import GenRequest, StreamEvent, ToolCall

#: Statuses that hand the turn to the next provider instead of ending it.
#:
#: The 5xx/429 family is the provider being ill. 401 and 403 are in here for a different
#: reason: they are the provider rejecting the *credentials*, which says nothing about whether
#: our request body was well-formed, so the old "every 4xx is our mapping bug" rule mis-called a
#: dead key a permanent failure. Measured with a deliberately bad key against each provider kind:
#: Groq answers `401 invalid_api_key`, Anthropic answers `401 authentication_error`, OpenRouter
#: answers `401 User not found`. A 400 or 404 keeps its old meaning — that is us sending the wrong
#: thing. Google does report a bad key as `400 API_KEY_INVALID` and an unparseable one as an empty
#: `400`, and neither is special-cased: bodies are not read for credential signals, because an
#: empty 400 and a malformed-request 400 look identical. See `docs/qa/live-providers.md`.
RETRYABLE_STATUS = {401, 403, 408, 409, 425, 429, 500, 502, 503, 504}


class Provider(ABC):
    def __init__(self, name: str, base_url: str, client: httpx.AsyncClient, api_key: str) -> None:
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.client = client
        self.api_key = api_key

    @abstractmethod
    async def list_models(self) -> list[str]: ...

    @abstractmethod
    def stream(self, req: GenRequest) -> AsyncIterator[StreamEvent]: ...

    def _fail(self, resp: httpx.Response, body: str) -> ProviderCallError:
        status = resp.status_code
        retryable = status in RETRYABLE_STATUS
        code = RATE_LIMITED if status == 429 else (PROVIDER_5XX if status >= 500 else PROVIDER_4XX)
        snippet = " ".join(body.split())[:240]
        return ProviderCallError(self.name, snippet or resp.reason_phrase, status=status, retryable=retryable, code=code)

    async def _read_error(self, resp: httpx.Response) -> ProviderCallError:
        body = (await resp.aread()).decode("utf-8", "replace")
        return self._fail(resp, body)


async def sse_data_lines(resp: httpx.Response) -> AsyncIterator[str]:
    """Yield non-empty `data:` payloads from an SSE response."""
    async for raw in resp.aiter_lines():
        line = raw.strip()
        if not line or line.startswith(":") or line.startswith("event:"):
            continue
        if not line.startswith("data:"):
            continue
        payload = line[len("data:") :].strip()
        if payload and payload != "[DONE]":
            yield payload


def parse_arguments(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProviderCallError("tool-args", f"malformed tool arguments: {exc}", code=BAD_TOOL_CALL) from exc
    return value if isinstance(value, dict) else {"value": value}


def split_data_url(value: str) -> tuple[str, str]:
    """`data:image/jpeg;base64,AAAA` -> (`image/jpeg`, `AAAA`). Raises ValueError on anything else."""
    header, _, payload = value.partition(",")
    if not header.startswith("data:") or ";base64" not in header or not payload:
        raise ValueError("image must be a base64 data URL")
    return header[len("data:"):].split(";", 1)[0], payload


def tool_call_from(index: int, entry: dict) -> ToolCall:
    fn = entry.get("function") or {}
    return ToolCall(
        id=entry.get("id") or f"call_{index}",
        name=fn.get("name") or "",
        arguments=parse_arguments(fn.get("arguments")),
    )
