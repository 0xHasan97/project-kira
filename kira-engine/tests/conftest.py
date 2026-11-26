from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from kira.app import Engine, create_app
from kira.config import Config, ProviderConfig
from kira.store import Store
from kira.vault import Vault


def provider_configs() -> list[ProviderConfig]:
    return [
        ProviderConfig(
            name="fast_one",
            kind="openai_compat",
            base_url="https://fast1.invalid/v1",
            models=["mini"],
            tier="fast",
            key_ref="provider/fast_one",
            priority=10,
        ),
        ProviderConfig(
            name="fast_two",
            kind="openai_compat",
            base_url="https://fast2.invalid/v1",
            models=["mini"],
            tier="fast",
            key_ref="provider/fast_two",
            priority=20,
        ),
        ProviderConfig(
            name="big",
            kind="openai_compat",
            base_url="https://big.invalid/v1",
            models=["max"],
            tier="powerful",
            key_ref="provider/big",
            priority=30,
        ),
        ProviderConfig(
            name="ant",
            kind="anthropic",
            base_url="https://ant.invalid",
            models=["claude-mock"],
            tier="powerful",
            key_ref="provider/ant",
            priority=40,
        ),
        ProviderConfig(
            name="gem",
            kind="gemini",
            base_url="https://gem.invalid",
            models=["gemini-mock"],
            tier="fast",
            key_ref="provider/gem",
            priority=50,
        ),
    ]


class Scripted:
    """Fake provider wire: pops queued responses per base_url host."""

    def __init__(self) -> None:
        self.queues: dict[str, list[httpx.Response]] = {}
        self.calls: list[str] = []
        self.bodies: list[tuple[str, dict]] = []

    @staticmethod
    def _key(host: str) -> str:
        return host.split(".invalid")[0]

    def queue(self, base_url: str, response: httpx.Response) -> None:
        self.queues.setdefault(self._key(base_url.split("//")[-1].split("/")[0]), []).append(response)

    def handler(self, request: httpx.Request) -> httpx.Response:
        host = self._key(request.url.host or "")
        self.calls.append(f"{host}{request.url}")
        body = request.content.decode("utf-8", "replace") if request.content else ""
        payload: dict = {}
        if body:
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                payload = {"raw": body}
        if payload:
            self.bodies.append((host, payload))
        queue = self.queues.get(host)
        if not queue:
            return httpx.Response(500, json={"error": {"message": f"no scripted response for {host}"}})
        return queue.pop(0)

    def body_for(self, host: str) -> dict:
        wanted = self._key(host)
        for name, payload in self.bodies:
            if name == wanted:
                return payload
        raise AssertionError(f"no request recorded for {wanted}; saw {self.calls}")

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)


def sse_body(chunks: list[dict], *, terminate: bool = True) -> bytes:
    lines = [f"data: {json.dumps(chunk)}\n\n" for chunk in chunks]
    if terminate:
        lines.append("data: [DONE]\n\n")
    return "".join(lines).encode()


def openai_text_chunks(text: str, *, usage: bool = True) -> list[dict]:
    chunks = [{"choices": [{"index": 0, "delta": {"content": part}}]} for part in list(text)]
    chunks.append({"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]})
    if usage:
        chunks.append({"choices": [], "usage": {"prompt_tokens": 11, "completion_tokens": len(text)}})
    return chunks


def openai_tool_chunks(name: str, arguments: str, *, call_id: str = "call_1") -> list[dict]:
    return [
        {"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0, "id": call_id, "type": "function", "function": {"name": name, "arguments": ""}}]}}]},
        {"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0, "function": {"arguments": arguments[:3]}}]}}]},
        {"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0, "function": {"arguments": arguments[3:]}}]}}]},
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
    ]


def ok(chunks: list[dict]) -> httpx.Response:
    return httpx.Response(200, content=sse_body(chunks), headers={"content-type": "text/event-stream"})


def ok_json(payload: dict) -> httpx.Response:
    return httpx.Response(200, json=payload)


TEST_TOKEN = "test-engine-token"
TEST_CONFIRM = "test-confirm-secret"


class Harness:
    def __init__(self, tmp_path: Path, providers: list[ProviderConfig] | None = None) -> None:
        self.script = Scripted()
        self.vault = Vault("memory")
        for provider in providers or provider_configs():
            self.vault.set(provider.key_ref, f"key-{provider.name}")
        self.vault.set("engine/token", TEST_TOKEN)
        self.vault.set("engine/confirm", TEST_CONFIRM)
        self.config = Config(
            data_dir=tmp_path / ".kira-data",
            providers=providers if providers is not None else provider_configs(),
        )
        self.config.data_dir.mkdir(parents=True, exist_ok=True)
        self.client = httpx.AsyncClient(transport=self.script.transport)
        self.engine = Engine(self.config, vault=self.vault, http_client=self.client)
        self.app = create_app(self.config, engine=self.engine)
        self.api = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app), base_url="http://kira.test"
        )

    @property
    def auth(self) -> dict:
        return {"Authorization": f"Bearer {TEST_TOKEN}"}

    @property
    def signed(self) -> dict:
        """What a dashboard write actually looks like on the wire: bearer token plus confirm header."""
        return {"Authorization": f"Bearer {TEST_TOKEN}", "X-Kira-Confirm": TEST_CONFIRM}

    @property
    def store(self) -> Store:
        return self.engine.store


@pytest.fixture
def harness(tmp_path):
    return Harness(tmp_path)
