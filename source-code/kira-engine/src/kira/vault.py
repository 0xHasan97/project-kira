from __future__ import annotations

import os
import secrets

from .errors import SecretStoreUnavailable

SERVICE = "kira"
ENGINE_TOKEN_REF = "engine/token"
ENGINE_CONFIRM_REF = "engine/confirm"


class Vault:
    """Provider keys, the engine token and the write-confirm secret live in the OS credential store.

    backend="memory" is for tests and first-run scaffolding only.
    """

    def __init__(self, backend: str | None = None) -> None:
        self.backend = (backend or os.environ.get("KIRA_VAULT") or "keyring").lower()
        self._memory: dict[str, str] = {}
        self._ring = None
        if self.backend == "keyring":
            try:
                import keyring

                self._ring = keyring
            except Exception as exc:  # noqa: BLE001 - surface as a config-time failure
                raise SecretStoreUnavailable(
                    f"Windows Credential Locker unavailable ({exc}); set KIRA_VAULT=memory for tests"
                ) from exc

    @property
    def location(self) -> str:
        return "Windows Credential Locker" if self.backend == "keyring" else "in-process memory store (not persisted)"

    def get(self, name: str) -> str | None:
        if self.backend == "memory":
            return self._memory.get(name)
        assert self._ring is not None
        try:
            return self._ring.get_password(SERVICE, name)
        except Exception as exc:  # noqa: BLE001 - never a silent None
            raise SecretStoreUnavailable(f"cannot read secret '{name}': {exc}") from exc

    def set(self, name: str, value: str) -> None:
        if self.backend == "memory":
            self._memory[name] = value
            return
        assert self._ring is not None
        try:
            self._ring.set_password(SERVICE, name, value)
        except Exception as exc:  # noqa: BLE001
            raise SecretStoreUnavailable(f"cannot write secret '{name}': {exc}") from exc

    def delete(self, name: str) -> None:
        if self.backend == "memory":
            self._memory.pop(name, None)
            return
        assert self._ring is not None
        try:
            self._ring.delete_password(SERVICE, name)
        except Exception as exc:  # noqa: BLE001
            raise SecretStoreUnavailable(f"cannot delete secret '{name}': {exc}") from exc

    def has(self, name: str) -> bool:
        return self.get(name) is not None

    def _get_or_create(self, ref: str) -> tuple[str, bool]:
        """Returns (secret, created_now). The caller prints it only when created."""
        existing = self.get(ref)
        if existing:
            return existing, False
        secret = secrets.token_urlsafe(32)
        self.set(ref, secret)
        return secret, True

    def get_or_create_engine_token(self) -> tuple[str, bool]:
        return self._get_or_create(ENGINE_TOKEN_REF)

    def get_or_create_confirm(self) -> tuple[str, bool]:
        return self._get_or_create(ENGINE_CONFIRM_REF)
