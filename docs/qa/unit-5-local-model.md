# Unit 5 — a model on this machine: verification record — 2026-10-30

This is the click-install-and-answer pass for the offline tier. It is not a new subsystem: the
2026-10-29 sandbox pass had already proved a keyless `openai_compat` stanza is built, routed and
served end to end (`docs/qa/full-app-live-pass.md`), so the work here was to put a real server
behind that stanza and measure what a turn costs in wall-clock time.

The machine is the one the roadmap named: Ryzen 5 5600G, 24 GB RAM, **RX 5500 4 GB, AMD — no
CUDA**, so CPU inference is the only option and the model class is 3–4 B at Q4.

## What was installed

| Step | Command | Result |
| --- | --- | --- |
| server | `winget install Ollama.Ollama` | Ollama 0.40.13, server on `127.0.0.1:11434` |
| model A | `ollama pull qwen3:4b` | 2.5 GB, reasoning model (emits a hidden thinking block) |
| model B | `ollama pull qwen3:4b-instruct-2507-q4_K_M` | non-thinking instruct build of the same size class |

The engine never starts or installs this server and has no code path to do so; the config stanza
below is the whole integration.

## The stanza

`.kira-data/config.yaml`, appended after every remote:

```yaml
  - name: ollama
    kind: openai_compat
    base_url: http://127.0.0.1:11434/v1
    tier: fast
    priority: 140
    models:
      # Non-thinking first: the plain qwen3:4b is a reasoning model and spends
      # hundreds of tokens thinking before it says a word.
      - qwen3:4b-instruct-2507-q4_K_M
      - qwen3:4b
```

`priority: 140` sits after every shipped remote (50–120), so `AUTO` only reaches this machine when
nothing remote can serve — including offline. Naming a model routes to it directly, which is what
the picker does.

## Probe, before any turn

`kira-engine models` reported `ollama ok`, `model_count 1`, sample `["qwen3:4b"]` on the first run,
before the instruct model was pulled.

The same run exposed a real defect: **fresh Ollama answers `GET /v1/models` with
`{"object":"list","data":null}`** until its first model is pulled, and `openai_compat.py` did
`resp.json().get("data", [])`, which hands back that `None` and crashes the probe. Fixed test-first
(`test_a_server_with_no_models_yet_lists_nothing_instead_of_crashing`, commit `82fed01`); the fix is
`resp.json().get("data") or []`. A brand-new install must report an empty catalogue, not a
`TypeError`.

## A live turn — reasoning model, no token cap

The first live UI-shaped turn (`stream: false`, no `max_tokens` — what the chat screen sends) ran on
`qwen3:4b`:

| | |
| --- | --- |
| HTTP | `200` |
| wall clock | 23.18 s |
| usage | 1 186 in / 333 out |
| chain | `attempt · served · tool_executed(echo) · attempt · served` |
| text | `ok` |

It also chose and ran the `echo` tool, so the local path exercises the harness exactly like a remote.

## The 32-token trap

A 32-token probe on `qwen3:4b` returned **zero visible text**: the reasoning model spent the entire
budget thinking, the engine emitted `empty_answer`, then `providers_exhausted` with a `503`. That is
the engine doing the right thing — silence is not an answer (see unit 4's live-provider findings) —
but it is the wrong model for a small budget. At 512 tokens the same model still consumed all 512
thinking and surfaced `1,2` of a requested `1..20`.

The fix is model choice, not engine code: the non-thinking instruct build
(`qwen3:4b-instruct-2507-q4_K_M`) answers the same request in full — 758 in / 51 out, `1..20`
complete — and it is listed first in the stanza so the picker defaults to it.

## Streaming, over a real socket

A fake-transport test (`httpx.ASGITransport`) showed time-to-first-token equal to total time and
looked like a burst. It was the transport, not the engine: ASGI buffers a response iterator. Measured
against the engine's own socket and against Ollama directly, both stream incrementally:

| Path | first delta | total | chunks |
| --- | --- | --- | --- |
| engine SSE (`127.0.0.1:8901/v1`) | 1.51 s | 2.43 s | 50 |
| Ollama direct (`127.0.0.1:11434/v1`) | 1.06 s | 1.91 s | — |

So the local tier is a real streaming provider, ~0.4 s of engine overhead per turn.

## The browser pass

Driven with Chrome DevTools MCP against a lab engine started by `tools/kira_lab.py --local`, which
generates a config with the Ollama stanza and reports the server's catalogue at startup.

| Surface | What was seen |
| --- | --- |
| provider rail | `ollama · no key needed` |
| model picker | `qwen3:4b · ollama · fast` |
| a real UI turn | answered `local ok` by provider `OLLAMA`, 1 tool run |
| dashboard | `2 served · 0 failed · 1 tool runs`, 2 011 tokens, health `2✓ / 0✗` |
| Providers screen | row `priority 140`, key buttons disabled, labelled keyless |
| live probe button | `1 models · 2110 ms` |

## What this record does not claim

- **Not a benchmark.** One machine, one prompt shape, one model pair. The 23 s reasoning-model turn
  and the ~2 s instruct turn are for the same short request; they are not a throughput figure.
- **Not GPU-accelerated.** The RX 5500 exposes no CUDA and Ollama is running CPU-only here. Nothing
  in this pass says what a machine with a supported GPU would do.
- **Not a quality claim.** `qwen3:4b`-class models are a floor, not a substitute for a remote
  frontier model — that is exactly why `priority: 140` puts them last.
- **Not installed voice stages.** Unit 6's whisper/Piper absence is unchanged by this pass.
