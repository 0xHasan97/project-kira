# Memory browser pass — 2026-10-30

Engine: `tools/kira_lab.py --port 8917 --mock-port 8997`, mock provider `tools/mock_openai.py` on
`http://127.0.0.1:8997/v1`, a temp data dir (memory vault — nothing touched the Credential Locker; the
two provider keys, the engine token and the confirm secret were disposable and died with the process).
Bundle: `kira-chat/dist` as built by `npm run check` that day (`kira-build.json` → api 1, contract 2).

Browser: `http://127.0.0.1:8917/chat/` driven over the Chrome DevTools session, 1440×900, scale 1.
`kira.base` and `kira.token` were seeded in one evaluate and the page reloaded; the confirm secret was
typed into the confirm dialog and into the approval card and nowhere else. No screenshots this pass —
every observation below is a DOM read or an API call quoted verbatim. The clock reads UTC+6.

## What was driven

A `#/memory` route in both shells; a keyboard-entered route change; a fact kept, pinned, edited and
forgotten; a served turn that consumed the injected block; a real `write_file` approval; history
search for a user word and for a word that exists only in tool output; `capture: off` and back on;
export; the storage and overflow claims.

| # | Check | Observed | Verdict |
| --- | --- | --- | --- |
| 1 | `#/memory` renders in **Chat** and in **Agent**, and the rail entry is keyboard-reachable | Chat shell: heading `Memory`, rail `Chat · Call · Overview · Providers · Models · Sessions · Tools · Memory · refresh · disconnect`, body `nothing kept yet — say "remember that …" in chat, or type a fact above.` plus the three switches. `document.activeElement` after `.focus()` was `BUTTON[aria-label="Memory"]`, and pressing Enter on it moved the page to `#/memory`. Agent shell: same heading and switches with `.work-panel` present; `.app[data-shell]` was `agent` throughout. | matched |
| 2 | Keep a fact → confirm dialog → row appears, and survives a reload | Typing `I prefer pnpm` enabled `keep` (`keepDisabled:false`). The dialog read `keep this fact` / `It will be injected into future turns until you forget it.` / `Confirm secret` / `cancel` / `confirm write`. After the secret, the row appeared as `I prefer pnpm · 30/10/2026 · fact · user · 0× · pin · edit · forget 2f805283ed2f4534` with no error note. After `location.reload()` the same row was there, read back from the engine. | matched |
| 3 | Pin moves the fact to the top of the injected block | `pin` behind the same dialog (`summary: "pin this fact"`) repainted the row as `unpin`. After a served turn (`what do you know about me` → `mock answer, scripted by tools/mock_openai.py`, `complete · mini · 100↑ / 50↓ · 1 served`), `GET /v1/kira/memory` returned the fact with `use_count: 1` and `last_used_at: 1793333086.705323` — `mark_used` only stamps what was in the block. The block itself, read from the live store at that point with `build_block(memory, [user "what do you know about me"])`: ids `["2f805283ed2f4534", "6b34deda653343c9"]`, text `Known about the user (from your local memory; may be stale — say so if unsure):\n- [fact] I prefer pnpm\n- [fact] the project lives on drive D` — the pinned fact first, the second below it. | matched after divergence 1 |
| 4 | Edit and forget re-read from the engine, not from local state | `edit` opened an input (`aria-label="edit 6b34deda653343c9"`), `save` behind `save this edit`; the row became `the project lives on drive E`. `forget "the project lives on drive E"` behind the danger dialog (`This cannot be undone; export first if unsure.`) removed it; after a reload the table held only `I prefer pnpm` and the API said `total: 1`. | matched |
| 5 | History search finds user text and not tool output | A real `write_file` turn (`please write_file made.txt for me`, approval card `write_file · write · needs permission`, secret + `allow`) produced chain `asked permission write_file · write` → `checkpoint saved 1 file(s)` → `tool ran write_file("call_lab_1") → ok, 33 chars`, `1 tool runs`; `workspace/made.txt` on disk read `made by the lab` and `checkpoints/11f6c4a72bd7432b` existed. Search `know` → hit `user · session 2e1e282c52244c56 · 30/10/2026` with snippet `… you [know] abou…`. Search `lab` — a word present only in the tool output — returned `no stored message matches that yet.`, as did a phrase only the checkpoint id carries. | matched |
| 6 | `capture: off` removes `remember` everywhere the model sees it | Toggling the `capture` switch behind `set capture` returned `capture: "off"` and the screen printed `remember is hidden from the model while capture is off.` `GET /v1/kira/tools` went from `["echo","list_dir","now","read_file","recall","remember","run_command","search_text","write_file"]` to the same list without `remember`; `#/tools` rendered eight rows and no `remember`. Toggling back restored `capture: "explicit"` and the tool. | matched |
| 7 | Export downloads a file whose `version` is 1 and whose rows match the screen | `URL.createObjectURL` and `HTMLAnchorElement.prototype.click` were captured rather than trusted: filename `kira-memory-2026-10-30.json`, blob parsed to `{"version": 1, "memories": [{"text": "I prefer pnpm", …}]}`, identical to the one row the table showed. | matched |
| 8 | `localStorage` still holds exactly the three keys | `["kira.base","kira.shell","kira.token"]` at the end of the run, after every write and reload. | matched |
| 9 | Zero uncaught exceptions in the console | The console log for the whole session is empty — no errors, no warnings. | matched |

Extra, because the memory slice makes them worth pinning:

| # | Check | Observed | Verdict |
| --- | --- | --- | --- |
| A | The memory block is never stored as a message | `GET /v1/kira/sessions` + each transcript: `user · what do you know about me`, `assistant · mock answer, scripted by tools/mock_openai.py`, `user · please write_file made.txt for me`, `assistant · the tool round trip came back` (1 tool call). Neither `Known about the user` nor `I prefer pnpm` appears in any stored row. | matched |
| B | Both shells, 1440×900, no horizontal overflow on the new screen | Chat: `scrollWidth` 1440 against `innerWidth` 1440, screen 1152 wide, no work panel. Agent: same `scrollWidth`, screen 780 wide, work panel present. The tab strip reported `facts:true` / `history:false` in both. | matched |

## Gates, as run

Before the browser, on the tree that was driven (Task 13 Step 2):

```
$ cd kira-engine && .venv/Scripts/python.exe -m pytest -q
458 passed, 1 skipped, 1 warning in 22.17s

$ cd ../kira-chat && npm run check
Test Files  26 passed (26)
      Tests  224 passed (224)
✓ built in 419ms

$ cd .. && node kira-contracts/check-drift.mjs
kira-contracts OK — v2, 66 schemas, 6 chunk types, 16 chain events
```

Re-run after the documentation edits, then again after the review fix below: `458 passed, 1 skipped`,
`26 files / 225 tests`, drift unchanged at `v2, 66 schemas`.

## Divergences and findings

No product defect surfaced. Two things this pass could not do as the plan wrote them, both recorded
here rather than papered over:

1. **The mock provider keeps no request log.** Step 3 of the plan said to prove injection "by reading
   the recorded request body the mock logs"; `tools/mock_openai.py` suppresses its own access log and
   prints nothing per request. Injection was proved two other ways instead, both against live state:
   `use_count`/`last_used_at` moved 0 → 1 for a fact that was only ever in the built block, and
   `build_block` was run against the same SQLite file the engine was serving and printed the pinned
   fact first. If a future pass wants the wire body, the mock needs a small body log — that is a tool
   change, not an engine one.
2. **The download path is a Blob and a synthetic click**, which a headless session cannot "save". The
   pass intercepted `URL.createObjectURL`/`click` and parsed the blob instead, which is the same bytes
   the browser would have written. Nothing about the screen's export path depends on the download
   landing.

One observation, not a defect: the history tab's empty state reads `no stored message matches that
yet.` before a query is typed. It is the same sentence the search produces for a real miss, which is
slightly odd on first paint but consistent with how the other screens phrase an empty read. Left as
shipped; noted here so it is a decision and not an accident.

## Post-pass: the one defect the pass could not see

The whole-branch review that followed found a silent failure in the export path: `exportAll` chained
`.then()` without a `.catch()`, so an engine that refused the export left an unhandled rejection in the
console and nothing on screen — a backup that did not happen and did not say so. The pass could not
have caught it, because its own export succeeded (check 7). Fixed test-first, with its guard:
`MemoryScreen.test.tsx` §"says so when the export fails instead of dropping the rejection", backed by a
new `exportError` branch in `fake-engine.ts`; the red run was the unhandled `KiraApiError` itself, and
the screen now prints `cannot export memory: …` in an alert. Client tests 224 → 225.
