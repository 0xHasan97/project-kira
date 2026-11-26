# Live provider pass — 2026-10-29

Everything before this file was tested against a scripted provider. This is the first pass that put
the user's own credential on the wire and asked a real model a real question.

Command: `KIRA_DATA_DIR="<repo>/.kira-data" KIRA_LIVE=1 .venv/Scripts/python -m pytest -q tests/test_live_providers.py`
— it writes `docs/qa/live-providers.json` with the call counts you see below. The Gemini key was put in
the Windows Credential Locker with `keys set provider/gemini --from-stdin`, was never echoed to a
terminal, a log, a chain record or this file, and the only length anyone recorded is the openrouter
one: **1 character**, which is how the placeholder turned out to be a placeholder. The rows marked
*fake key* below were sent with hand-typed invalid credentials straight to each provider's own endpoint
— no real key was involved and no credits were spent, because the point of those rows is the status
code a dead credential gets.

The config under test is the real one at `.kira-data/config.yaml`: `gemini` (fast, keyed), `openrouter`
(powerful, placeholder), `groq` and `anthropic` (no key at all). `AUTO` therefore plans
`[('gemini', 'gemini-3.5-flash'), ('openrouter', 'anthropic/claude-sonnet-4.5')]` and the turn the user
actually gets is chain `skipped_missing_key · skipped_missing_key · attempt · served` — the two unkeyed
providers never cost a call.

## What the wire said

| Call | Outcome |
|---|---|
| `gemini` `list_models` | **60 models**, free, no chat request sent |
| `gemini-3.5-flash`, 256-token budget, "Reply with exactly one word." | **answered**: 11 characters, `finish_reason=stop`, 7 input / 3 output tokens, 4431 ms |
| `gemini-2.5-flash` | **HTTP 404** `provider_4xx`, retryable=False: `This model models/gemini-2.5-flash is no longer available to new users. Please update your code to use models/gemini-3.8-flash for the latest features and improvements. We recommend you to use the Inter…` (the engine keeps 240 characters of the body) |
| `gemini-3.8-flash` | no byte within 60 s → `ReadTimeout` |
| `gemini-flash-latest` | no byte within 60 s → `ReadTimeout` |
| `openrouter` with the 1-character key | **HTTP 400 with an empty body** on `GET /models` and on `POST /chat/completions` — the machine-readable form is `openrouter: Bad Request` |
| `openrouter` with a well-formed but fake `sk-or-v1-…` key | `GET /models` → **200** (that endpoint is public); chat → **HTTP 401** `User not found.` |
| `groq` with a fake `gsk_…` key | **HTTP 401** both endpoints: `{"error":{"message":"Invalid API Key","type":"invalid_request_error","code":"invalid_api_key"}}` |
| `anthropic` with a fake `sk-ant-…` key | **HTTP 401**: `{"type":"error","error":{"type":"authentication_error","message":"invalid x-api-key"}}` |
| `gemini` with a fake `AIza…` key | **HTTP 400**: `API key not valid. Please pass a valid API key.`, status `INVALID_ARGUMENT`, reason `API_KEY_INVALID` |

The interesting one is the thinking-model budget, measured twice on the same prompt. First pass:
8, 32 and 64 output tokens all closed the stream with **zero characters** and `finish_reason=length`;
128 and 256 returned the word. Second pass, hours later: 64 returned `Understood` (10 characters,
2 output tokens, still `finish_reason=length`) and **128 came back empty with 0 output tokens**. A
reasoning model's hidden spend is not a constant, so any probe budget is a hedge rather than a proof.

## Four defects, all fixed test-first

**1 — Silence was served as an answer.** A stream that opened, ran and closed without one character
and without a tool call reached the router as a success: the chain said `served` and the user stared at
an empty bubble. Guard tests: `test_an_answer_of_nothing_fails_over_instead_of_being_served`,
`test_a_tool_call_turn_is_not_an_empty_answer` (a tool call is an answer; zero text is not),
`test_every_provider_answering_nothing_is_exhaustion`. Production: a new `empty_answer` chain event and
failover in `router.py`; nothing had reached the client, so the next provider gets the turn.

**2 — The dashboard probe put a green tick on the same silence.** `probe_provider` broke out of the
stream on the first event and called anything that did not throw a pass. It now reads to the end and
fails with `completion returned no text (finish_reason=…)`. Guard:
`test_a_completion_that_says_nothing_does_not_pass`.

**3 — The probe budget sat under the floor.** 8 tokens could never clear a thinking model's hidden
output, so a working provider read as broken. `PROBE_MAX_OUTPUT_TOKENS` is now 256, with the two
measurements written into the constant's comment and a tripwire on the constant itself
(`test_the_probe_budget_clears_a_thinking_models_hidden_output`) — because the second pass proved
even 128 can come back empty, the number is a documented hedge, not a guarantee.

**4 — A rejected key ended the turn instead of moving it.** `RETRYABLE_STATUS` treated every 4xx but 429
as "our mapping bug, do not fail over". 401 and 403 are the provider rejecting the *credentials*; they
say nothing about whether the body was well-formed. Guards:
`test_openai_status_codes_classify_failover_eligibility` (429/503 → fail over, 401/403 → fail over,
400/404 → abort) and `test_a_dead_key_fails_over_instead_of_stranding_the_turn` in the real router.
A 401 now also cools that provider in the ledger, so the next turn does not pay for the same dead key
again. The fake-key rows above are what justify it: three of the four provider kinds answer a bad key
with 401, so the carve-out is measured, not inferred.

What did **not** become a code change: the key on this machine's OpenRouter entry is one character, and
that gets a **400** with an empty body — the status the abort rule exists for. Loosening 400 on an
empty-body heuristic would bury a genuine request-mapping bug behind another provider's answer, and
Google's `400 API_KEY_INVALID` shows a provider *can* name the credential in a 400 — but if one provider
says `API_KEY_INVALID` and another says nothing at all, the rule becomes "read provider bodies and
guess", which is exactly the coupling the status table exists to avoid. So the honest reading lives in
the QA harness (`_verdict`: a 4xx on the bodiless `GET /models` is a credential, and it is named in the
report rather than hidden) and in the user's own key, not in the router. The residual risk is stated in
that function's docstring: a wrong `/models` URL for a provider kind would also land in `key_rejected`,
which is why the report prints provider, status and message. If a future provider's dead key does strand
a turn, this is the paragraph to come back to.

`gemini-2.5-flash` was retired by Google, not by Kira, and it was still named in both the shipped
sample config and `.kira-data/config.yaml`. Both now list `gemini-3.5-flash-lite`: re-measured on
2026-11-26, `gemini-3.5-flash` returned `provider_5xx` 503 high-demand on three app turns in a row,
while the lite model answered text, a signed tool call with replay, and a 1x1 red PNG in one pass.
The retired model is not offered by the sample; the provider's live `/models` listing still reports
what Google reports, including non-chat models.

## Still missing on this machine

- `provider/openrouter` in the Locker is a 1-character placeholder. Replace it with a real key
  (`run-kira.bat` → Providers, or `keys set provider/openrouter --from-stdin`) or delete the entry so
  the router reports `skipped_missing_key` instead of spending a call on it. Nothing here deleted it.
- `groq` and `anthropic` have no key. BYOK: the engine does not fetch, scrape, share or bundle one, and
  no free-key catalogue is on the roadmap.
- `gemini-3.8-flash` and `gemini-flash-latest` were unreachable inside 60 s. The engine's own
  `request_timeout_s` is 120, so a turn on either would wait, not fail fast. Not treated as a defect
  and not treated as working.

## What this pass cannot prove

One provider answered, so failover was exercised against a script, never against a second live
provider; a mid-stream abort and real spend over a month are still unproved here. The unit suite is
unchanged in what it fakes.

Vision was tried and the wire refused. Two image turns — a hand-built 96×96 and then a 48×48 solid red
PNG, `data:image/png;base64,…`, "What colour is this image? Answer with one word." to
`gemini-3.5-flash` — each waited ~53 s and came back **HTTP 503** `provider_5xx`, retryable=True:
`This model is currently experiencing high demand. Spikes in demand are usually temporary. Please try
again later.` Text turns on the same key answered in 4 s, so this reads as Google's image capacity, not
Kira's encoding. Note too that the config on this machine declares **no** vision provider at all
(`vision:` is absent from every entry, so it defaults to false): an image frame there is filtered out as
`skipped_config` before any money is spent, which is the behaviour you want while the upstream is 503.
The shipped sample config does declare `vision: true` for gemini and anthropic, so a fresh install will
send the frame and take the 503 and the failover — which is why the retryable classification above
matters. Nothing was changed on either side.

The two local voices (whisper, Piper) are still not installed, so a call today runs on the remote BYOK
stages or on typed input.

## Gate counts after the fixes

356 engine tests (+1 skipped: this file, off unless `KIRA_LIVE=1`) · 203 chat tests across 24 files ·
drift gate `v2, 56 schemas, 6 chunk types, 16 chain events`.
