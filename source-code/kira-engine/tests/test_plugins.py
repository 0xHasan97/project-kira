from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from kira.plugins import load_plugins
from kira.tools import ToolRegistry
from kira.vault import Vault


def spec(**overrides):
    base = {
        "name": "demo_lookup",
        "description": "Look up a demo record.",
        "risk": "network",
        "parameters": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
        "request": {
            "method": "GET",
            "url": "https://api.invalid/demo/{id}",
            "query": {"units": "metric"},
            "headers": {"accept": "application/json"},
        },
        "secret_ref": "plugin/demo",
        "secret_header": "authorization",
        "secret_prefix": "Bearer ",
    }
    base.update(overrides)
    return base


def load(tmp_path, files, transport=None):
    directory = tmp_path / "plugins"
    directory.mkdir(exist_ok=True)
    for name, payload in files.items():
        (directory / name).write_text(json.dumps(payload), encoding="utf-8")
    vault = Vault("memory")
    vault.set("plugin/demo", "plugin-secret")
    client = httpx.AsyncClient(
        transport=transport or httpx.MockTransport(lambda r: httpx.Response(200, json={"ok": True}))
    )
    tools, statuses = load_plugins(directory, client, vault)
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)
    return registry, statuses


def execute(registry, name, **arguments):
    return asyncio.run(registry.execute(name, arguments))


def test_valid_plugin_loads(tmp_path):
    registry, statuses = load(tmp_path, {"demo.json": spec()})
    assert [s.status for s in statuses] == ["loaded"]
    tool = registry.get("demo_lookup")
    assert tool is not None and tool.risk == "network" and tool.default_policy == "ask"


def test_plugin_call_substitutes_and_sends_the_locker_secret(tmp_path):
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"name": "widget"})

    registry, _ = load(tmp_path, {"demo.json": spec()}, httpx.MockTransport(handler))
    outcome = execute(registry, "demo_lookup", id="a b")
    assert outcome.ok
    assert seen["url"].endswith("/demo/a%20b?units=metric")
    assert seen["auth"] == "Bearer plugin-secret"
    assert json.loads(outcome.content) == {"name": "widget"}
    assert "plugin-secret" not in outcome.summary


@pytest.mark.parametrize(
    "broken, reason",
    [
        (spec(name="Bad Name"), "name"),
        (spec(risk="root"), "risk"),
        (spec(request={"method": "DELETE", "url": "https://x.invalid/"}), "method"),
        (spec(request={"method": "GET", "url": "ftp://x.invalid/"}), "http"),
        (spec(request={"method": "GET", "url": "https://x.invalid/{missing}"}), "placeholder"),
        (spec(request={"method": "GET", "url": "https://x.invalid/", "query": {"a": "{nope}"}}), "placeholder"),
        (spec(secret_header="x"), "secret_header"),
    ],
)
def test_bad_plugins_are_skipped_with_a_reason(tmp_path, broken, reason):
    registry, statuses = load(tmp_path, {"bad.json": broken})
    assert statuses[0].status == "skipped"
    assert reason in statuses[0].reason
    assert registry.names == []


def test_name_collision_skips_the_second_file(tmp_path):
    registry, statuses = load(tmp_path, {"a.json": spec(), "b.json": spec()})
    assert sorted(s.status for s in statuses) == ["loaded", "skipped"]
    assert len(registry.names) == 1


def test_missing_secret_fails_without_calling(tmp_path):
    def handler(request):
        raise AssertionError("must not call the endpoint without the secret")

    directory = tmp_path / "plugins"
    directory.mkdir()
    (directory / "demo.json").write_text(json.dumps(spec()), encoding="utf-8")
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    tools, _ = load_plugins(directory, client, Vault("memory"))
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)
    outcome = execute(registry, "demo_lookup", id="1")
    assert not outcome.ok
    assert "not in the Credential Locker" in outcome.content


def test_unknown_parameter_and_missing_required_are_errors(tmp_path):
    registry, _ = load(tmp_path, {"demo.json": spec()})
    assert "unknown parameter" in execute(registry, "demo_lookup", id="1", extra="x").content
    assert "missing parameter" in execute(registry, "demo_lookup").content


def test_non_2xx_and_oversize_are_errors(tmp_path):
    registry, _ = load(
        tmp_path, {"demo.json": spec()}, httpx.MockTransport(lambda r: httpx.Response(404, text="nope"))
    )
    outcome = execute(registry, "demo_lookup", id="1")
    assert not outcome.ok and "HTTP 404" in outcome.content

    registry, _ = load(
        tmp_path,
        {"big.json": spec(name="big_lookup")},
        httpx.MockTransport(lambda r: httpx.Response(200, content=b"x" * 40000)),
    )
    outcome = execute(registry, "big_lookup", id="1")
    assert outcome.ok and "truncated" in outcome.content
