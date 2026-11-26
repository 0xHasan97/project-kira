from __future__ import annotations

import pytest

from kira.errors import ConfigError
from kira.policy import RISK_DEFAULTS, effective_policy, validate_policy
from kira.store import Store
from kira.tools import ToolDef


def tool(name="t", risk="read"):
    return ToolDef(name=name, description="d", parameters={}, handler=lambda _a: "", risk=risk)


def test_risk_defaults():
    assert RISK_DEFAULTS == {"read": "allow", "write": "ask", "exec": "ask", "network": "ask"}
    assert effective_policy(tool(risk="read"), {}) == "allow"
    assert effective_policy(tool(risk="write"), {}) == "ask"


def test_override_wins_and_unknown_risk_fails_closed():
    assert effective_policy(tool(risk="write"), {"t": "allow"}) == "allow"
    assert effective_policy(tool(name="t", risk="mystery"), {}) == "ask"


def test_validate_policy():
    for value in ("allow", "ask", "deny"):
        assert validate_policy(value) == value
    with pytest.raises(ConfigError, match="allow, ask, deny"):
        validate_policy("maybe")


def test_store_round_trip_and_reset(tmp_path):
    store = Store(tmp_path / "k.db")
    assert store.tool_policies() == {}
    store.set_tool_policy("write_file", "deny")
    assert store.tool_policies() == {"write_file": "deny"}
    store.set_tool_policy("write_file", None)
    assert store.tool_policies() == {}
    with pytest.raises(ConfigError):
        store.set_tool_policy("write_file", "sometimes")
    store.close()
