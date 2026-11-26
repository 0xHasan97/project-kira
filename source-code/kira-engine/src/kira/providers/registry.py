from __future__ import annotations

import httpx

from ..config import Config, ProviderConfig
from ..errors import ConfigError
from ..vault import Vault
from .anthropic import Anthropic
from .base import Provider
from .gemini import Gemini
from .openai_compat import OpenAICompat

KIND_TO_CLASS: dict[str, type[Provider]] = {
    "openai_compat": OpenAICompat,
    "anthropic": Anthropic,
    "gemini": Gemini,
}


class ProviderRegistry:
    """Builds providers on demand; a missing key is reported, never guessed."""

    def __init__(self, config: Config, vault: Vault, client: httpx.AsyncClient) -> None:
        self.config = config
        self.vault = vault
        self.client = client

    @property
    def names(self) -> list[str]:
        return [p.name for p in sorted(self.config.providers, key=lambda c: (c.priority, c.name))]

    def config_for(self, name: str) -> ProviderConfig:
        try:
            return self.config.by_name[name]
        except KeyError as exc:
            raise ConfigError(f"unknown provider '{name}'") from exc

    def providers_offering(self, model: str) -> list[str]:
        return [p.name for p in self.config.providers if model in p.models and p.name in self.names]

    def key_for(self, name: str) -> str | None:
        ref = self.config_for(name).key_ref
        if not ref:
            return None
        return self.vault.get(ref)

    def build(self, name: str) -> Provider:
        cfg = self.config_for(name)
        cls = KIND_TO_CLASS[cfg.kind]
        api_key = self.key_for(name)
        if not api_key and cfg.key_ref:
            raise ConfigError(
                f"provider '{name}' has no key in the {self.vault.location} (ref='{cfg.key_ref}'); "
                f"set it with: kira-engine keys set {cfg.key_ref}"
            )
        # A stanza that declares no `key_ref` is a provider that needs no credential — the local
        # OpenAI-compatible server the contract advertises (Ollama, LM Studio, llama-server). `plan()`
        # already lets those through; refusing them here made unit 5's offline model unreachable.
        return cls(name=cfg.name, base_url=cfg.base_url, client=self.client, api_key=api_key or "")
