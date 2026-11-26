from __future__ import annotations

import time
from dataclasses import dataclass

from .errors import ProviderCallError
from .store import Store

MAX_COOLDOWN_S = 300.0
BASE_COOLDOWN_S = 5.0


@dataclass
class ProviderState:
    failures: int = 0
    successes: int = 0
    cooled_until: float = 0.0
    last_reason: str = ""


@dataclass
class HealthLedger:
    """Cooldown/penalty bookkeeping so failover is visible instead of silent."""

    store: Store | None = None
    clock=time.monotonic

    def __post_init__(self) -> None:
        self._states: dict[str, ProviderState] = {}
        if self.store is not None:
            for row in self.store.load_health():
                self._states[row["provider"]] = ProviderState(
                    failures=row["failures"],
                    successes=row["successes"],
                    cooled_until=row["cooled_until"],
                    last_reason=row["last_reason"],
                )

    def _persist(self, name: str, st: ProviderState) -> None:
        if self.store is not None:
            self.store.upsert_health(
                name,
                failures=st.failures,
                successes=st.successes,
                cooled_until=st.cooled_until,
                last_reason=st.last_reason,
            )

    def state(self, name: str) -> ProviderState:
        return self._states.setdefault(name, ProviderState())

    def available(
        self, names: list[str]
    ) -> tuple[list[str], list[dict]]:
        now = self.clock()
        eligible: list[str] = []
        skipped: list[dict] = []
        for name in names:
            st = self.state(name)
            if st.cooled_until > now:
                skipped.append(
                    {
                        "provider": name,
                        "event": "skipped_cooling",
                        "retry_in_s": round(st.cooled_until - now, 1),
                        "reason": st.last_reason,
                    }
                )
                continue
            eligible.append(name)
        return eligible, skipped

    def record_failure(self, err: ProviderCallError) -> dict:
        st = self.state(err.provider)
        st.failures += 1
        st.last_reason = f"{err.code} status={err.status} {err.message}"[:400]
        backoff = 0.0
        if err.retryable:
            backoff = min(MAX_COOLDOWN_S, BASE_COOLDOWN_S * 2 ** (st.failures - 1))
            st.cooled_until = self.clock() + backoff
        self._persist(err.provider, st)
        return {
            "provider": err.provider,
            "event": "failed",
            "retryable": err.retryable,
            "cooldown_s": round(backoff, 1),
            "reason": st.last_reason,
        }

    def record_success(self, name: str) -> None:
        st = self.state(name)
        st.failures = 0
        st.successes += 1
        st.cooled_until = 0.0
        st.last_reason = ""
        self._persist(name, st)

    def clear_cooldown(self, name: str) -> None:
        """Drop the cooling timer now. Counters stay: they are the history the panel shows."""
        st = self.state(name)
        st.cooled_until = 0.0
        self._persist(name, st)

    def view(self, name: str) -> dict:
        """One provider's ledger row in the published shape, so the dashboard can show a
        provider that has never failed instead of leaving it out."""
        now = self.clock()
        st = self.state(name)
        return {
            "failures": st.failures,
            "successes": st.successes,
            "cooling_s": round(max(0.0, st.cooled_until - now), 1),
            "last_reason": st.last_reason,
        }

    def snapshot(self) -> dict[str, dict]:
        now = self.clock()
        return {
            name: {
                "failures": st.failures,
                "successes": st.successes,
                "cooling_s": round(max(0.0, st.cooled_until - now), 1),
                "last_reason": st.last_reason,
            }
            for name, st in self._states.items()
        }
