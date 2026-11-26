"""Opt-in live provider checks. Off unless KIRA_LIVE=1.

The unit suite fakes every provider, so on its own it can be green while no real
API was ever called. This file is the antidote: when you run it, it makes genuine
requests with your own keys and writes the call counts to
docs/qa/live-providers.json, so "tested" always means "answered over the wire".
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("KIRA_LIVE") != "1",
    reason="live provider calls spend real credits; set KIRA_LIVE=1 to run",
)

LIVE_PROMPT = "Reply with exactly one word."
PROBE_TIMEOUT_S = 90.0


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _write_report(payload: dict) -> Path:
    path = _repo_root() / "docs" / "qa" / "live-providers.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _note_error(row: dict, exc: BaseException, prefix: str) -> None:
    from kira.errors import ProviderCallError

    row["error"] = f"{prefix}: {type(exc).__name__}: {exc}"[:300]
    row["error_status"] = getattr(exc, "status", None) if isinstance(exc, ProviderCallError) else None


async def _probe(provider_cfg, vault, client):
    from kira.config import load_config
    from kira.probe import PROBE_MAX_OUTPUT_TOKENS
    from kira.providers.registry import ProviderRegistry
    from kira.types import Completed, Delta, GenRequest, Message

    registry = ProviderRegistry(load_config(None), vault, client)
    provider = registry.build(provider_cfg.name)

    row = {
        "provider": provider_cfg.name,
        "kind": provider_cfg.kind,
        "tier": provider_cfg.tier,
        "model": None,
        "calls": 0,
        "list_models_ok": False,
        "chat_ok": False,
        "model_count": None,
        "finish_reason": None,
        "text_chars": 0,
        "usage": {"input_tokens": 0, "output_tokens": 0},
        "latency_ms": None,
        "error": None,
        "error_status": None,
    }

    try:
        models = await provider.list_models()
        row["calls"] += 1
        row["list_models_ok"] = True
        row["model_count"] = len(models)
        row["model"] = provider_cfg.models[0] if provider_cfg.models else (models[0] if models else None)
    except Exception as exc:  # noqa: BLE001 - a live probe reports, it does not classify
        _note_error(row, exc, "list_models")
        return row

    if not row["model"]:
        row["error"] = "nothing to probe: config lists no model and the provider offered none"
        return row

    request = GenRequest(
        model=row["model"],
        messages=[Message(role="user", content=LIVE_PROMPT)],
        # The same floor the dashboard probe uses: a reasoning model spends the first hundred
        # output tokens on hidden thinking, so a smaller budget proves nothing about the provider.
        max_output_tokens=PROBE_MAX_OUTPUT_TOKENS,
    )
    text: list[str] = []
    completed: Completed | None = None
    started = time.perf_counter()
    try:
        async for event in provider.stream(request):
            if isinstance(event, Delta):
                text.append(event.text)
            elif isinstance(event, Completed):
                completed = event
        row["calls"] += 1
        row["text_chars"] = sum(len(part) for part in text)
        # "A turn came back" is not "the provider answered". The live Gemini probe completed with
        # zero characters and `finish_reason=length` at 8 tokens — a green tick on silence.
        row["chat_ok"] = completed is not None and row["text_chars"] > 0
        row["finish_reason"] = completed.finish_reason if completed else None
        if completed:
            row["usage"] = {"input_tokens": completed.usage.input_tokens, "output_tokens": completed.usage.output_tokens}
        if completed is not None and not row["text_chars"]:
            row["error"] = f"completed with no text (finish_reason={row['finish_reason']})"
    except Exception as exc:  # noqa: BLE001
        _note_error(row, exc, "stream")
    finally:
        row["latency_ms"] = round((time.perf_counter() - started) * 1000)
    return row


def _verdict(row: dict) -> str:
    """`answered` / `key_rejected` / `failed`, judged from what the wire actually said.

    A BYOK harness cannot bill Kira for a credential the user pasted in. The evidence that a
    rejection is the key and not the code: `GET /models` is a free metadata read with no request
    body, so a 4xx on it has nothing of ours to have mis-mapped. Measured live: a one-character
    placeholder key got `400` with an empty body from OpenRouter on both `/models` and
    `/chat/completions`.

    Residual risk, accepted on purpose: a wrong `/models` URL for a provider kind would also land
    here, so the report names the provider, the status and the message, and the dashboard probe
    path shows the same thing to the user rather than the gate quietly deciding it is fine.
    """
    if row["chat_ok"]:
        return "answered"
    if row["error_status"] is not None and 400 <= row["error_status"] < 500 and not row["list_models_ok"]:
        return "key_rejected"
    return "failed"


async def test_live_providers_answer_and_are_recorded():
    from kira.config import load_config
    from kira.vault import Vault

    cfg = load_config(None)
    vault = Vault(os.environ.get("KIRA_LIVE_BACKEND"))

    keyed = [p for p in cfg.providers if not p.key_ref or vault.get(p.key_ref)]
    assert keyed, (
        f"KIRA_LIVE=1 but no provider in {cfg.config_path} has a key in the vault; "
        "run: kira-engine keys set provider/<name> --from-stdin"
    )

    async with httpx.AsyncClient(timeout=PROBE_TIMEOUT_S) as client:
        rows = [await _probe(p, vault, client) for p in keyed]

    for row in rows:
        row["verdict"] = _verdict(row)
    rejected = [r for r in rows if r["verdict"] == "key_rejected"]

    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "engine": "kira-engine",
        "live_calls_total": sum(r["calls"] for r in rows),
        "providers_tested": len(rows),
        "providers_answered": [r["provider"] for r in rows if r["verdict"] == "answered"],
        "providers_key_rejected": [
            f"{r['provider']}: HTTP {r['error_status']} — {r['error']}" for r in rejected
        ],
        "providers_skipped_no_key": [p.name for p in cfg.providers if p not in keyed],
        "results": rows,
    }
    path = _write_report(report)

    failures = [r for r in rows if r["verdict"] == "failed"]
    assert report["live_calls_total"] > 0, f"no live call was made; see {path}"
    assert report["providers_answered"], "no provider answered with a character of text: " + "; ".join(
        f"{r['provider']}: {r['error'] or 'no Completed event'}" for r in rows
    )
    assert not failures, "live provider(s) did not answer: " + "; ".join(
        f"{r['provider']}: {r['error'] or 'no Completed event'}" for r in failures
    )
