from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import httpx

from .limits import MAX_PLUGIN_BYTES, MAX_PLUGIN_RESPONSE
from .tools import ToolDef, ToolOutcome
from .vault import Vault

NAME = re.compile(r"^[a-z][a-z0-9_]{2,39}$")
HEADER = re.compile(r"^[a-z][a-z0-9-]{2,63}$")
PLACEHOLDER = re.compile(r"\{([^{}]+)\}")
RISKS = ("read", "write", "exec", "network")
POLICIES = ("allow", "ask", "deny")


@dataclass
class PluginStatus:
    file: str
    name: str
    status: str
    reason: str = ""

    def to_wire(self) -> dict:
        return {"file": self.file, "name": self.name, "status": self.status, "reason": self.reason}


def _templates(value, path: str, params: set[str]) -> None:
    if isinstance(value, str):
        for name in PLACEHOLDER.findall(value):
            if name not in params:
                raise ValueError(f"{path} names an undeclared placeholder {{{name}}}")
    elif isinstance(value, dict):
        for key, item in value.items():
            _templates(item, f"{path}.{key}", params)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _templates(item, f"{path}[{index}]", params)


def _fill(template: str, values: dict) -> str:
    return PLACEHOLDER.sub(lambda match: quote(str(values[match.group(1)]), safe=""), template)


def _parse(path: Path) -> dict:
    if path.stat().st_size > MAX_PLUGIN_BYTES:
        raise ValueError(f"file is larger than {MAX_PLUGIN_BYTES} bytes")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("plugin file must be a JSON object")
    name = str(raw.get("name", ""))
    if not NAME.match(name):
        raise ValueError("name must match ^[a-z][a-z0-9_]{2,39}$")
    if not str(raw.get("description", "")).strip():
        raise ValueError("description must not be empty")
    risk = str(raw.get("risk", "network"))
    if risk not in RISKS:
        raise ValueError(f"risk must be one of {', '.join(RISKS)}")
    policy = raw.get("policy", "ask")
    if policy not in POLICIES:
        raise ValueError(f"policy must be one of {', '.join(POLICIES)}")
    parameters = raw.get("parameters")
    if not isinstance(parameters, dict) or parameters.get("type") != "object":
        raise ValueError("parameters must be an object schema")
    properties = parameters.get("properties", {})
    if not isinstance(properties, dict):
        raise ValueError("parameters.properties must be an object")
    for key, schema in properties.items():
        if not isinstance(schema, dict) or schema.get("type") not in ("string", "integer", "number", "boolean"):
            raise ValueError(f"parameter {key} must be a scalar schema")
    request = raw.get("request")
    if not isinstance(request, dict):
        raise ValueError("request must be an object")
    if str(request.get("method", "GET")).upper() not in ("GET", "POST"):
        raise ValueError("method must be GET or POST")
    url = str(request.get("url", ""))
    if not url.startswith(("http://", "https://")):
        raise ValueError("url must be http(s)")
    timeout_s = request.get("timeout_s", 10)
    if isinstance(timeout_s, bool) or not isinstance(timeout_s, int) or not (1 <= timeout_s <= 30):
        raise ValueError("timeout_s must be 1-30")
    headers = request.get("headers", {})
    secret_header = raw.get("secret_header", "authorization")
    if not isinstance(headers, dict):
        raise ValueError("request.headers must be an object")
    if not isinstance(secret_header, str) or not HEADER.match(secret_header):
        raise ValueError("secret_header must be a lowercase header name at least three characters long")
    params = set(properties)
    _templates(url, "request.url", params)
    _templates(request.get("query", {}), "request.query", params)
    _templates(headers, "request.headers", params)
    _templates(request.get("body", {}), "request.body", params)
    return raw


def _handler(spec: dict, client: httpx.AsyncClient, vault: Vault):
    name = spec["name"]
    request = spec["request"]
    method = str(request.get("method", "GET")).upper()
    url_template = str(request["url"])
    query = request.get("query", {}) or {}
    headers = request.get("headers", {}) or {}
    body = request.get("body", {}) or {}
    timeout_s = int(request.get("timeout_s", 10))
    properties = spec["parameters"].get("properties", {})
    required = spec["parameters"].get("required", [])
    secret_ref = spec.get("secret_ref")
    secret_header = spec.get("secret_header", "authorization")
    secret_prefix = spec.get("secret_prefix", "Bearer ")

    async def call(arguments: dict) -> ToolOutcome:
        unknown = set(arguments) - set(properties)
        if unknown:
            return ToolOutcome(False, f"error: unknown parameter(s): {', '.join(sorted(unknown))}")
        missing = [key for key in required if key not in arguments]
        if missing:
            return ToolOutcome(False, f"error: missing parameter(s): {', '.join(missing)}")
        values = {key: arguments[key] for key in arguments if key in properties}
        try:
            url = _fill(url_template, values)
            params = {key: _fill(str(value), values) for key, value in query.items()}
            header_values = {key: _fill(str(value), values) for key, value in headers.items()}
            payload = {key: _fill(value, values) if isinstance(value, str) else value for key, value in body.items()}
        except KeyError as exc:
            return ToolOutcome(False, f"error: plugin parameter {exc} was not supplied")
        if secret_ref:
            secret = vault.get(str(secret_ref))
            if secret is None:
                return ToolOutcome(False, f"error: secret '{secret_ref}' is not in the Credential Locker")
            header_values[secret_header] = f"{secret_prefix}{secret}"
        try:
            response = await client.request(
                method,
                url,
                params=params,
                headers=header_values,
                json=payload if method == "POST" else None,
                timeout=timeout_s,
            )
        except httpx.HTTPError as exc:
            return ToolOutcome(False, f"error: {name} request failed: {type(exc).__name__}")
        text = response.text
        if response.status_code >= 400:
            return ToolOutcome(False, f"error: HTTP {response.status_code} from {name}: {text[:300]}")
        if len(text.encode("utf-8")) > MAX_PLUGIN_RESPONSE:
            text = text.encode("utf-8")[:MAX_PLUGIN_RESPONSE].decode("utf-8", "replace") + "\n[truncated]"
        return ToolOutcome(True, text, summary=f"{name}({', '.join(sorted(values))})")

    return call


def load_plugins(directory: Path, client: httpx.AsyncClient, vault: Vault) -> tuple[list[ToolDef], list[PluginStatus]]:
    tools: list[ToolDef] = []
    statuses: list[PluginStatus] = []
    taken: set[str] = set()
    directory = Path(directory)
    if not directory.is_dir():
        return tools, statuses
    for path in sorted(directory.glob("*.json")):
        try:
            spec = _parse(path)
            name = spec["name"]
            if name in taken:
                raise ValueError(f"duplicate plugin name '{name}'")
            taken.add(name)
            tools.append(
                ToolDef(
                    name=name,
                    description=str(spec.get("description", "")),
                    parameters=spec["parameters"],
                    handler=_handler(spec, client, vault),
                    risk=str(spec.get("risk", "network")),
                    default_policy=str(spec.get("policy", "ask")),
                    source=f"plugin:{path.name}",
                    summary=lambda args, _name=name: f"{_name}({', '.join(sorted(args))})",
                )
            )
            statuses.append(PluginStatus(path.name, name, "loaded"))
        except Exception as exc:  # noqa: BLE001 - a bad file must not stop the engine
            statuses.append(PluginStatus(path.name, _safe_name(path), "skipped", str(exc)))
    return tools, statuses


def _safe_name(path: Path) -> str:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return str(raw.get("name", path.stem)) if isinstance(raw, dict) else path.stem
    except Exception:
        return path.stem
