# Agent shell + composer — live pass, 2026-10-31

The pass that took the agent surface from "the chat screen with a work panel bolted on" to something
that reads like an agent. PandaCode's agent mode was the studied product; what shipped is its
*mechanisms* — a verb grammar for a turn, a transcript that folds, a composer that answers to Enter,
a status strip that counts — reimplemented in Kira's own tokens and DOM. No donor code was copied and
no donor installer was run (ground rules, `PROVENANCE.md`).

## What shipped

| Piece | File | What it does |
| --- | --- | --- |
| Turn grammar | `kira-chat/src/trace.ts` | chain events → rows of `{verb, object, meta, status}`. `tool_executed` is `Ran`/`Read`/`Wrote` by tool name, an ask is `Asked to run`, a denial is `Couldn't call`, a budget skip is `Skipped`. Statuses: `done · failed · denied · waiting · note` |
| Foldable transcript | `kira-chat/src/components/TurnTrace.tsx` | a `<details>` card per turn — head says what the turn *did* (`Answered by mock_two after 1 provider was skipped · 1 failed · 2 steps`), body is the rows, each with a glyph |
| Activity | same | bars while a step is running, dots while the turn is open; both stop under `data-motion="off"` and `prefers-reduced-motion` |
| Composer semantics | `kira-chat/src/composer.ts` | `wantsSend` (Enter sends, Shift+Enter is a newline, Ctrl/Cmd+Enter still works, an IME composition never sends), `autosize` (grow to the text, cap at 180 px, then scroll), `elapsed` (`4s` / `1m 05s` / `1h 04m`) |
| Status strip | `kira-chat/src/screens/ChatScreen.tsx` | one line under the box: `Enter sends · 2 models · AUTO` at rest, `Working for 12s · 2 steps` while a turn is open, read out by `aria-live="polite"` only when it is changing |
| One tile | same | `send` and `stop` are the same slot — the tile that exists is the next action. `stop` wears the interrupt colour |

## What the browser said

Chromium against the built bundle served by the lab engine at `http://127.0.0.1:8901/chat/`
(`tools/kira_lab.py --port 8901 --mock-port 8999`, temp data dir, memory vault, mock providers only —
nothing here reached a paid provider).

| Check | Reading |
| --- | --- |
| Enter sends, from real key events | typed `demo_lookup the order` + Enter → the turn ran, the box emptied, the tile became `stop` |
| The footer counts the open turn | `Enter sends · 2 models · AUTO` → `Working for 0s · 0 steps` → back to `Enter sends …` |
| The transcript folds and keeps its words | heads `Answered by mock_two after 1 provider was skipped · 1 failed · 2 steps` and `Read 1 file · 1 step`; rows below |
| Every status glyph reaches the DOM | `note :: Asked to run run_command · exec` / `failed :: Couldn't run python -c import sys; sys.exit(3) · 25 chars` / `done :: Read echo round trip · 15 chars` / `denied :: Couldn't call demo_lookup · tool is denied by policy` |
| The prompt grows with its text | 1 line → `height: 65px`; 2 lines → `70px`; 4 lines → `128px`; 6 lines → `180px` with `overflow-y: auto` while `scrollHeight` was 187 px |
| A key write needs no second secret | Providers → paste → `key ok` in the row, no dialog (contract half in this same commit: the two key routes publish no `X-Kira-Confirm`) |

## Three defects the pass found, each fixed test-first

1. **A settled ask kept counting as pending.** `tool_approval_requested` renders `waiting` while the
   turn is open, and the turn stayed open in the DOM after it settled — so a decision made two minutes
   ago still wore a clock. Fixed in `TurnTrace.tsx`: a `waiting` row is demoted to `note` when the turn
   is not live. Test: *stops counting an ask as pending once the turn settles*.
2. **An offline shell said nothing.** With the worker serving the shell and no engine behind it, the
   screen showed `no models configured` and a red dot — the wording of a broken app, not of an
   unreachable one. `App.tsx` now distinguishes a refusal (`KiraApiError`, the engine answered) from
   no answer at all, and prints `no answer from the engine at http://127.0.0.1:8901 (Failed to fetch)`
   on the shell, not only on the gate — which matters because a stored token means there is no gate to
   print it on. Test: *says the engine did not answer when the shell is mounted without an engine*.
3. **The desktop scrolled the document, so the thread never scrolled.** `.thread` already had
   `overflow: auto` and `min-height: 0`, but `.app` was `min-height: 100vh`, so nothing ever capped it:
   a long sitting grew the page, `useFollow` set `scrollTop` on an element that could not scroll, and
   the newest answer — plus, once the composer could grow, the send row — sat below the fold. Fixed by
   giving the shell the containment the phone layout already had: `.app { height: 100dvh; overflow:
   hidden }`, `min-height: 0` on `.pane`, and their own scroll on `.screen` and `.rail`. After:
   `documentElement.scrollHeight` 900 = viewport, thread `scrollHeight > clientHeight`, send row on
   screen with the composer at its 180 px cap, and the Tools screen scrolls inside itself
   (855 px of viewport, 912 px of content). Test: *keeps the composer on screen at desktop widths, not
   only on a phone* (`styles.test.ts`).

## One flake, and what it was

`ProvidersScreen writes > cap 0 means unlimited …` failed 2 of 4 full-suite runs and 0 of 5 runs of its
own file. The write always arrived; testing-library's 1 s default `waitFor` budget is what ran out while
37 jsdom environments competed for the machine. Fixed at the root rather than at the call site:
`configure({ asyncUtilTimeout: 5000 })` in `src/test-setup.ts`. The suite then ran green four times in
a row.

## Gates

`npx tsc --noEmit` clean · vitest **327 passed / 37 files** (stable over four consecutive full runs) ·
engine **536 passed, 1 skipped** · `node kira-contracts/check-drift.mjs` → `kira-contracts OK — v2,
77 schemas, 6 chunk types, 16 chain events`.

## Not in it

- No virtualised transcript: a 500-message sitting still renders every row.
- The transcript grammar is client-side only. The engine's chain events are unchanged, and the
  contract stayed at v2.
- No per-row click-through to the raw chain record; the existing `ChainTrace` in the work panel is
  still where the JSON lives.
- The composer's cap is a constant (180 px), not a share of the viewport.
