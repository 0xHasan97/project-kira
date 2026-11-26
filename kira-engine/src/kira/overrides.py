"""One merged view of the providers, shared by the router, the API and the dashboard.

`config.yaml` is the hand-authored baseline and is never written by Kira. The `settings`
table holds the four fields the dashboard tunes. The merge runs per request instead of
being cached, so a toggle takes effect on the next turn rather than at the next restart,
and a row that cannot be trusted is reported instead of quietly applied.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .config import TIERS, Config, ProviderConfig
from .errors import ConfigError
from .store import SETTINGS_KEYS, Store

TUNABLE_FIELDS = ("enabled", "priority", "tier", "monthly_cap")

#: Matches the `priority` bounds on SettingsRequest in the published contract; keep the two in step.
MAX_PRIORITY = 1000

#: setting key -> the phrase used when a write gets it wrong. Each one describes exactly what the
#: matching read-side validator accepts, plus the bound the tolerant reader leaves alone.
_WRITER_HINTS = {
    "enabled": "true or false",
    "priority": f"an integer from 0 to {MAX_PRIORITY}",
    "tier": f"one of {list(TIERS)}",
    "monthly_cap": "an integer >= 0, where 0 means unlimited",
}


def _boolean(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _integer(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _tier(value: Any) -> str | None:
    return value if isinstance(value, str) and value in TIERS else None


def _cap(value: Any) -> int | None:
    """A stored cap is a non-negative int; 0 is the dashboard's spelling of unlimited."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value >= 0 else None


#: setting key -> validator. `None` from a validator means the row is unusable.
_VALIDATORS: dict[str, Callable[[Any], Any]] = {
    "enabled": _boolean,
    "priority": _integer,
    "tier": _tier,
    "monthly_cap": _cap,
}


class _Junk:
    """Marker for a stored row that cannot be used - distinct from `None`, which is a value."""

    def __repr__(self) -> str:
        return "<junk>"


JUNK = _Junk()


@dataclass
class FieldState:
    base: Any
    override: Any
    effective: Any

    def to_wire(self) -> dict[str, Any]:
        return {"base": self.base, "override": self.override, "effective": self.effective}


@dataclass
class EffectiveProvider:
    name: str
    kind: str
    base_url: str
    models: list[str]
    key_ref: str
    priority: int
    tier: str
    enabled: bool
    monthly_cap: int | None
    base: ProviderConfig
    states: dict[str, FieldState] = field(default_factory=dict)
    context_window: int | None = None


@dataclass
class MergedView:
    providers: list[EffectiveProvider]
    by_name: dict[str, EffectiveProvider]
    orphan_settings: list[str]


def _baseline(key: str, base: ProviderConfig) -> Any:
    if key == "enabled":
        # config.yaml has no `enabled` key: a stanza you wrote is a provider you meant.
        return True
    if key == "monthly_cap":
        return base.monthly_token_cap
    return getattr(base, key)


def _effective(key: str, baseline: Any, override: Any) -> Any:
    if override is None:
        return baseline
    if key == "monthly_cap":
        return None if override == 0 else override
    return override


def _override_or_junk(key: str, raw_json: str) -> Any:
    """The validated override value, or `JUNK` when the row cannot be trusted."""
    try:
        value = json.loads(raw_json)
    except json.JSONDecodeError:
        return JUNK
    validated = _VALIDATORS[key](value)
    return JUNK if validated is None else validated


def build_view(config: Config, store: Store | None = None) -> MergedView:
    rows = store.settings_map() if store is not None else {}
    orphans: list[str] = []
    providers: list[EffectiveProvider] = []

    for base in config.providers:
        stored = rows.get(base.name, {})
        states: dict[str, FieldState] = {}
        values: dict[str, Any] = {}
        for key in TUNABLE_FIELDS:
            override: Any = None
            if key in stored:
                parsed = _override_or_junk(key, stored[key])
                if isinstance(parsed, _Junk):
                    orphans.append(f"{base.name}.{key}")
                else:
                    override = parsed
            baseline = _baseline(key, base)
            states[key] = FieldState(base=baseline, override=override, effective=_effective(key, baseline, override))
            values[key] = states[key].effective
        orphans.extend(f"{base.name}.{key}" for key in sorted(set(stored) - SETTINGS_KEYS))
        providers.append(
            EffectiveProvider(
                name=base.name,
                kind=base.kind,
                base_url=base.base_url,
                models=list(base.models),
                key_ref=base.key_ref,
                priority=values["priority"],
                tier=values["tier"],
                enabled=values["enabled"],
                monthly_cap=values["monthly_cap"],
                base=base,
                states=states,
                context_window=base.context_window,
            )
        )

    for name in sorted(rows):
        if name in config.by_name:
            continue
        orphans.extend(f"{name}.{key}" for key in sorted(rows[name]))

    return MergedView(
        providers=providers,
        by_name={p.name: p for p in providers},
        orphan_settings=sorted(set(orphans)),
    )


def enabled_providers(view: MergedView) -> list[EffectiveProvider]:
    """What routing sees: stand-down providers are absent here, and therefore everywhere."""
    return sorted((p for p in view.providers if p.enabled), key=lambda p: (p.priority, p.name))


def matches_baseline(key: str, base: ProviderConfig, value: Any) -> bool:
    """True when storing `value` would not change what config.yaml already says.

    Compared by effect, not spelling: `monthly_cap: 0` and a stanza with no cap are both unlimited,
    so a round trip through the dashboard's `0` must not leave a row behind. The writer uses this to
    drop the override instead of storing it, which is what keeps `was …` lines and `clear override`
    meaning something.
    """
    baseline = _baseline(key, base)
    return _effective(key, baseline, value) == baseline


def validate_setting(key: str, value: Any) -> Any:
    """The strict twin of the tolerant read path. Returns the value to store; None means clear.

    `build_view` reports a row it cannot use as an orphan, because a hand-edited database must not
    be able to crash the router. This function refuses the same shapes outright, so the dashboard
    never writes one. It borrows `_VALIDATORS` for what a field *is* and adds only the range the
    reader deliberately leaves loose: priority outside 0..1000 still sorts, so reading it tolerates
    it, but asking for it is a typo and a typo deserves an error.
    """
    if key not in TUNABLE_FIELDS:
        raise ConfigError(f"'{key}' is not a tunable setting; settings holds {list(TUNABLE_FIELDS)}")
    if value is None:
        return None
    if key == "tier" and isinstance(value, str):
        # The router compares lowercase; a human typing "Powerful" meant the tier that exists.
        value = value.strip().lower()
    if _VALIDATORS[key](value) is None:
        raise ConfigError(f"{key} needs {_WRITER_HINTS[key]}")
    if key == "priority" and not 0 <= value <= MAX_PRIORITY:
        raise ConfigError(f"priority needs {_WRITER_HINTS[key]}")
    return value
