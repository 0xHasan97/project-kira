from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from .store import Store


@dataclass
class Decision:
    allowed: bool
    reason: str


class ApprovalBroker:
    """One process-wide map of pending approvals. A restart expires the rows instead of lying."""

    def __init__(self, store: Store, timeout_s: float = 120.0) -> None:
        self.store = store
        self.timeout_s = timeout_s
        self._waiters: dict[str, asyncio.Future[Decision]] = {}

    def expire_all(self) -> int:
        return self.store.expire_pending_approvals()

    def open(self, *, session_id: str | None, tool: str, arguments: dict, risk: str) -> dict:
        row = self.store.add_approval(session_id, tool, arguments, risk, expires_at=time.time() + self.timeout_s)
        self._waiters[row["id"]] = asyncio.get_running_loop().create_future()
        return row

    async def wait(self, approval_id: str) -> Decision:
        future = self._waiters.get(approval_id)
        if future is None:
            return Decision(False, "no live approval for this turn")
        try:
            return await asyncio.wait_for(future, timeout=self.timeout_s)
        except asyncio.TimeoutError:
            self.store.decide_approval(approval_id, "deny", reason="approval timed out")
            return Decision(False, "approval timed out")
        finally:
            self._waiters.pop(approval_id, None)

    def decide(self, approval_id: str, decision: str) -> dict | None:
        row = self.store.decide_approval(approval_id, decision)
        future = self._waiters.get(approval_id)
        if future is not None and not future.done() and row is not None:
            future.set_result(Decision(row["status"] == "allowed", row["reason"]))
        return row

    def cancel(self, approval_id: str) -> None:
        self.store.decide_approval(approval_id, "deny", reason="the turn ended before a decision")
        future = self._waiters.get(approval_id)
        if future is not None and not future.done():
            future.set_result(Decision(False, "the turn ended before a decision"))
