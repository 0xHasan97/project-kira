# Tool-harness browser pass — 2026-10-28 (UTC)

Engine: `tools/kira_lab.py --port 8916 --mock-port 8996`, mock provider
`tools/mock_openai.py` on `http://127.0.0.1:8996/v1`, data dir a temp one reseeded before the run
(memory vault — nothing in the Credential Locker). The workspace held `note.txt`
(`hello from the lab\n`) and a one-test `test_sample.py`; `plugins/` held a valid `demo_lookup`
declaration and `broken.json` with an invalid name. `mock_openai.py` routes a prompt word to a
scripted tool call — `write_file`, `demo_lookup`, `unittest`, `failing` — so each check below asks for
a different tool without a real model in the loop.

Browser: `http://127.0.0.1:8916/chat/`, headless over raw CDP — the cached Playwright Chromium
(`%LOCALAPPDATA%\ms-playwright\chromium-1248\chrome-win64\chrome.exe`),
`Emulation.setDeviceMetricsOverride` at **1440×900**, device scale 1, Node 24's global `fetch` and
`WebSocket`, no npm packages. `kira.base` and `kira.token` were seeded in one evaluate and the page
reloaded; the confirm secret entered the approval card and the confirm dialog and nowhere else.

One script, start to finish. Screenshots 01–16 and `report.json` in the pass directory. The clock on
this machine reads UTC+6; no timestamp below is quoted except what the UI printed.

## What was driven

Denied write in the chat shell; the same write allowed in the agent shell; the Changes and
Checkpoints tabs; a tamper, a refused restore, the same restore after the bytes matched; the Tools
route's policy select to `deny` and back to the config default; a turn under that policy; the plugin
list and a plugin call; a passing `unittest discover`; a command that exits 3; all six routes in both
shells at 1440×900.

| # | Check | Observed | Verdict |
| --- | --- | --- | --- |
| 1 | An `ask` tool holds the stream open and the card offers both decisions | Sending `please write_file made.txt for me` produced, while `.msg.streaming` was still true, `approval for write_file` / `write_file · write · needs permission`, the preview `{"path": "made.txt", "content": "made by the lab\n"}`, and two buttons — `allow` and `deny` — both dead until the secret is typed. | matched |
| 2 | Deny writes nothing and the turn still finishes | After typing the secret and pressing `deny`, the article settled as `the tool round trip came back` with chain `trying` → `answered` → `asked permission write_file · write` → `tool denied write_file · the user denied this call` → `trying` → `answered`; footer `0 tool runs`; `made.txt` absent on disk. | matched |
| 3 | Allow writes, and the write is checkpointed before it happens | Same prompt in the agent shell, `allow`: chain `asked permission` → `checkpoint saved 1 file(s)` → `tool ran write_file("call_lab_1") → ok, 33 chars` → `answered`; footer `1 tool runs`; `made.txt` on disk reads `made by the lab\n`; `checkpoints/e499b4d4ab854ab9` exists. Changes tab: `made.txt · checkpoint e499b4d4ab854ab9`. Checkpoints tab: `e499b4d4ab854ab9 · write_file · complete · 1 file(s)`. | matched after finding 2 |
| 4 | Restore refuses a changed file with 409 and succeeds once the bytes match, verified on disk | Overwrote `made.txt` with `tampered by the pass\n`, then `restore e499b4d4ab854ab9` behind the confirm dialog: error `checkpoint_conflict: 1 file(s) changed since the checkpoint`, file still tampered. Wrote the checkpointed bytes back and pressed the same button: notice `restored 1 file(s)`, `made.txt` now absent (the checkpoint recorded that it did not exist before the write), and a safety checkpoint `a931ab2ac9914ff0` (`restore · complete`) joined the list. | matched |
| 5 | Policy changes over HTTP from the Tools route | `#/tools` lists eight tools with risk, source, default and policy — `demo_lookup · network · plugin:demo.json · ask`, `run_command · exec · builtin · ask`, `write_file · write · builtin · ask`, the rest `allow`. Selecting `deny` for `write_file` behind the confirm dialog repainted the row with `overridden`; the next `write_file` prompt finished with `tool denied write_file · tool is denied by policy`, **no approval card appeared**, and `made.txt` stayed absent. Choosing `config default` cleared the override back to `ask` with `overridden` gone. | matched |
| 6 | The plugin registry loads one file and skips the other | Tools route, plugins: `demo_lookup — loaded`; `bad name! — skipped: name must match ^[a-z][a-z0-9_]{2,39}$`. A `demo_lookup id 42` prompt raised `approval for demo_lookup` / `network · needs permission`; after `allow` the chain read `tool ran demo_lookup("call_lab_1") → ok, 30 chars` — the mock's `{"id": "42", "name": "widget"}` is 30 characters, so the payload crossed the wire. | matched |
| 7 | Terminal, Tests and Problems read real subprocess results | `run unittest discover` → `python -m unittest discover · exit 0 · 128 ms` in Terminal, the same line with `exit 0` in Tests (classified by argv, not by the model). `do the failing one` → `run_command("call_lab_1") → error, 83 chars`, Problems `run_command: exit 3`. The Agents tab carried `chainSummary` `2 served · 0 failed · 0 skipped · 1 tool runs`, the chips, the registry list and the plugin statuses. | matched |
| 8 | Both shells, all six routes, no horizontal overflow at 1440×900 | Twelve route×shell combinations: `documentElement.scrollWidth` 1440 against a 1440 window every time (`over: 0`). Agent keeps the 300px work panel at x=1140 on every route; chat has none. All eight work-tab bodies measured 299/299. `localStorage` at the end held exactly `kira.base`, `kira.shell`, `kira.token`; 12 messages in one session. | matched |

## Findings

Three were real defects, fixed inside the pass; the guards are listed with each.

- **Deny deadlocked the turn.** The card sent `deny` with an empty confirm secret — its own comment
  said "denying needs no secret" — but the engine's decision endpoint is a mutating call and answered
  `no confirm secret`. The card stayed up, the SSE stream stayed open, and the pass timed out waiting
  for the turn. Both buttons now send the typed secret and both are disabled until one is typed
  ([ApprovalCard.tsx:59](file:///D:/1.%20Ai/project-kira%20%28kimi%29/Kira/kira-chat/src/components/ApprovalCard.tsx#L59));
  `ApprovalCard.test.tsx` asserts `deny` is dead without a secret and carries it when pressed.
- **A checkpoint had no session.** `AgentRun` passed `session_id=None` to both
  `checkpoints.take` and `approvals.open`, so `GET /v1/kira/checkpoints?session_id=…` — exactly what
  the Checkpoints tab asks for — could never return a row. The tab read "no checkpoints in this
  session" one click after Changes showed the same checkpoint's id. `AgentRun` now carries
  `session_id`, `build_run` passes the turn's session, and both calls use it
  ([loop.py:168](file:///D:/1.%20Ai/project-kira%20%28kimi%29/Kira/kira-engine/src/kira/loop.py#L168));
  `test_approvals_api.py::test_the_checkpoint_belongs_to_the_turns_session` drives a streamed turn and
  reads the row back by the `done` chunk's session.
- **A deny had no reason.** `decide_approval(id, "deny")` stored `reason=""`, and the loop quotes the
  reason back to the model and into the chain chip — `tool denied write_file ·` with nothing after the
  dot, and a tool message reading `… permission to run "write_file". . Do not retry`. The store now
  fills `the user denied this call` when a denial states none
  ([store.py:317](file:///D:/1.%20Ai/project-kira%20%28kimi%29/Kira/kira-engine/src/kira/store.py#L317));
  `test_approvals_store.py::test_a_deny_without_a_reason_still_has_one`.

Two are notes, not defects:

- **The pass found the deny bug before it found anything else.** The first run of the script never
  produced a completed turn; that is the whole reason the script exists. The engine-side tests had
  been green because they post the decision themselves with `harness.signed`, which carries the
  confirm secret — the client was the only liar.
- **Restore has no force button in the UI.** The pass proved 409 by changing the file and proved
  success by matching the bytes; `force: true` exists on the client method and the endpoint but no
  screen offers it. That is deliberate — an overwrite that ignores "this file moved" is the one
  restore a human should do through the API with the diffs in front of them — but it means a moved
  file needs the terminal.

## Not exercised, and why

- A real provider. Every turn above went to `tools/mock_openai.py`; a real model choosing these tools
  is what `KIRA_LIVE=1` is for, and the mock exists so the harness itself can be checked without it.
- The approval timeout. `approval_timeout_s` is 120 s in the lab; waiting it out would have cost two
  minutes per attempt and the store test already covers the expiry path.
- A non-streaming request with an `ask` tool. The spec's rule (deny with "cannot be approved") is
  covered by the engine suite, not by a screen — the dashboard has no non-streaming chat call.
- Plugin `secret_ref`. The engine substitutes it from the vault before the request; the demo plugin
  needs no key, and the vault path is unit-tested in `test_plugins.py`.
- Widths below 1440px. The two breakpoints were not driven; the work panel's own 299/299 scrollWidth
  is the in-panel guard.
