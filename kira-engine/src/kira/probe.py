from __future__ import annotations

import time
from dataclasses import dataclass, field

import httpx

from .errors import KiraError, ProviderCallError
from .providers.registry import ProviderRegistry
from .types import Completed, Delta, GenRequest, Message

#: One word, so a probe cannot turn into an essay that gets billed.
PROBE_PROMPT = "Reply with exactly one word: ok"
#: Measured live on Gemini 3.5 Flash, twice. First pass: 8, 32 and 64 output tokens all closed the
#: stream with zero characters and `finish_reason=length`, and 128 answered `ok`. Second pass, same
#: prompt: 64 answered a word and 128 came back empty. A reasoning model spends an unpredictable
#: amount of the budget on hidden thinking, so no number here is a guarantee — it is a hedge, and
#: 256 is where the hedge stopped needing an asterisk. A probe under that floor tests the budget,
#: not the provider; the `finish_reason=length` in the error string is what tells the two apart.
PROBE_MAX_OUTPUT_TOKENS = 256
SAMPLE_LIMIT = 8

PROBE_ERRORS = (KiraError, ProviderCallError, httpx.HTTPError)


@dataclass
class ProbeResult:
    """What we learned about one provider. A failure is a value, never an exception."""

    provider: str
    ok: bool
    model_count: int = 0
    sample: list[str] = field(default_factory=list)
    latency_ms: int | None = None
    error: str | None = None

    def to_wire(self) -> dict:
        return {
            "provider": self.provider,
            "ok": self.ok,
            "model_count": self.model_count,
            "sample": list(self.sample),
            "latency_ms": self.latency_ms,
            "error": self.error,
        }


def _missing_key(registry: ProviderRegistry, name: str) -> str | None:
    cfg = registry.config_for(name)
    if cfg.key_ref and registry.key_for(name) is None:
        return f"no key in the {registry.vault.location} (ref '{cfg.key_ref}')"
    return None


async def probe_models(registry: ProviderRegistry, name: str) -> ProbeResult:
    """`list_models` only. This is what the CLI and `?live=true` run: free, read-only metadata."""
    result = ProbeResult(provider=name, ok=False)
    try:
        missing = _missing_key(registry, name)
        if missing:
            result.error = missing
            return result
        listed = await registry.build(name).list_models()
    except PROBE_ERRORS as exc:
        result.error = str(exc)[:300]
        return result
    result.ok = True
    result.model_count = len(listed)
    result.sample = listed[:SAMPLE_LIMIT]
    return result


async def probe_provider(registry: ProviderRegistry, name: str) -> ProbeResult:
    """The dashboard's Test button: metadata plus one tiny completion.

    A human clicked this, so it may spend up to `PROBE_MAX_OUTPUT_TOKENS` of them. Nothing here writes
    to the `messages` table - a diagnostic is not a conversation, so it must not appear in the month's
    spend.
    """
    result = await probe_models(registry, name)
    if not result.ok:
        return result
    request = GenRequest(
        model=registry.config_for(name).models[0],
        messages=[Message(role="user", content=PROBE_PROMPT)],
        max_output_tokens=PROBE_MAX_OUTPUT_TOKENS,
    )
    started = time.monotonic()
    text: list[str] = []
    finish_reason: str | None = None
    try:
        async for event in registry.build(name).stream(request):
            if isinstance(event, Delta):
                text.append(event.text)
            elif isinstance(event, Completed):
                finish_reason = event.finish_reason
    except PROBE_ERRORS as exc:
        result.ok = False
        result.error = f"completion failed: {str(exc)[:280]}"
        result.latency_ms = int((time.monotonic() - started) * 1000)
        return result
    result.latency_ms = int((time.monotonic() - started) * 1000)
    if not "".join(text).strip():
        # The stream opened, ran and closed without a character. That is a provider that did not
        # answer, not one that did; `ok` would put a green tick on silence.
        result.ok = False
        result.error = f"completion returned no text (finish_reason={finish_reason})"
    return result
