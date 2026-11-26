from __future__ import annotations

from collections.abc import Mapping

from .errors import ConfigError
from .tools import ToolDef

POLICIES = ("allow", "ask", "deny")
RISK_DEFAULTS = {"read": "allow", "write": "ask", "exec": "ask", "network": "ask"}


def validate_policy(value: str) -> str:
    if value not in POLICIES:
        raise ConfigError(f"policy must be one of {', '.join(POLICIES)}")
    return value


def effective_policy(tool: ToolDef, overrides: Mapping[str, str]) -> str:
    if tool.name in overrides:
        return overrides[tool.name]
    return tool.default_policy or RISK_DEFAULTS.get(tool.risk, "ask")
