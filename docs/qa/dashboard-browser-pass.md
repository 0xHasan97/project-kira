# Dashboard browser pass — 2026-10-27 (UTC)

Engine: `tools/kira_lab.py` on `http://127.0.0.1:8912`, mock provider
`tools/mock_openai.py` on `http://127.0.0.1:8999`, data dir
`C:\Users\Administrator\AppData\Local\Temp\kira-lab` (memory vault, nothing in the Credential
Locker, nothing in `.kira-data`).

Browser: the app's own page at `http://127.0.0.1:8912/chat/`, connected by seeding the two
sanctioned `localStorage` keys (`kira.base`, `kira.token`) and reloading. The confirm secret was
typed into each dialog, never stored.

The clock on this machine reads UTC+6, so the screen's own timestamps (`28/10/2026, 00:4x`) are a
day ahead of this header. Both are the same minute; the month bucket (`2026-10`) agrees.

## Run order

The plan's Step 9 asks for a lab restart with one model removed, so this pass ran across several
engine processes against one kept data directory, and two more with a throwaway temp directory (the
Step 10 cleanup proof on `:8913`, and a fresh process used to re-check row 1's connect gate). Each
restart mints new secrets, because the vault is in memory: reconnecting with the token the new
process printed is part of the recipe, not a workaround. Rows 1-10 are the first process (both mocks
offering `mini` and `small`). Rows 12-16 are the second (`--models mini`). Row 11 was re-run on a
third process, the one with a corrected mock. Numbers are therefore not one continuous history: each
row quotes what its own screen showed at the moment it was checked.

| # | Check | Observed | Verdict |
| --- | --- | --- | --- |
| 1 | connect + contract v2 + five nav items | Header reads `/v1 · v2` — the engine's prefix and contract v2, no mismatch warning — with `span.dot.on` computed to `rgb(127, 209, 174)`; nav rail is `Chat · Overview · Providers · Models · Sessions` plus `refresh` and `disconnect`. Typing the printed token into the `engine_token` field and clicking Connect lands on the last route (`#/overview`), with the four mock models in the composer select. A **wrong** token does not return you to the gate: the shell stays mounted — nav rail, selects reading `no models configured`, `/v1 · v2` — and the read fails inline with `cannot read the overview: unauthorized: missing or invalid bearer token`. `disconnect` then shows the gate with that error still printed under it, and the correct token connects. | matched, with a recovery finding |
| 2 | chat turn streams, chain = attempt + served, usage non-zero | Turn shows `mock_one / trying / mini` then `mock_one / answered / mini`, footer `1 served · 0 failed · 0 skipped · 0 tool runs`, usage `100↑ / 50↓`, provider badge `MOCK_ONE`. The text arrives in word-sized chunks, so streaming is visible rather than asserted. | matched |
| 3 | Overview numbers equal Providers numbers | Overview `tokens 450 / 300 in · 150 out` against Providers `mock_one 300` + `mock_two 150`; later Overview `300 / 151 · at cap` with Providers' spend cell reading `300` for the same provider. One derived map, two screens (Task 9). | matched |
| 4 | route survives a refresh | Reload on `#/overview`, and later on `#/providers` and `#/models`: each landed on the same screen. This is what makes `#/providers` a URL a refusal can hand you. | matched |
| 5 | wrong confirm secret re-asks with the reason | After a bad secret the dialog re-opens with `test mock_one POST /v1/kira/providers/mock_one/probe — spends about 8 tokens — the engine refused that secret; type it again` and no result row appears. The typed value is not echoed back. | matched |
| 6 | Test spends nothing: spend unchanged after a probe | Result row `2 models · 0ms`; the spend cell stayed `150` before and after. The mock's own `/v1/models` publishes two ids and its completion carries the fixed 100/50, so the `0ms` is a loopback answer under the timer's resolution, not a broken stopwatch. | matched |
| 7 | cap = spend + 1 still routes (one turn of slack) | With `mock_one` at 150 spent and a cap of `151`, the turn was served by `mock_one`: `1 served · 0 failed · 0 skipped`, chain `trying`/`answered` only. The 150 it then booked put it over. | matched |
| 8 | next turn: `over budget` chip, failover to mock_two | `mock_one / over budget / used 300 of 151 tokens in 2026-10` → `mock_two / trying / mini` → `mock_two / answered / mini`, footer `1 served · 0 failed · 1 skipped`. The reason string is the chip's only explanation and its arithmetic matches Overview. | matched |
| 9 | Overview bar + sentence + working link; Providers the same number with no badge | Overview `mock_one 300 / 151 · at cap` (over-cap styling) and `mock_two 450 tokens · no cap` — the uncapped branch still prints a number, only the percentage is meaningless. Sentence: `mock_one has used all of 2026-10's cap, so no turn will route through it until the cap is raised or the month resets.` Link `raise a cap in Providers` has `href="#/providers"` and, clicked, lands there. Caveat under the bars: `Counted from stored turns, so the one in flight is not in these numbers yet — a bar can sit just under a cap the router is about to reach.` On Providers the strings `at cap` and `over cap` appear nowhere; the row reads `… was unlimited 300 7✓ 0✗`, so the cap and the spend are two cells and the human does the subtraction. See Findings. | matched, with a legibility finding |
| 10 | both capped: `budget_exhausted` + link in chat, no spend, no trouble row, nothing stored | Refused turn rendered as `KIRA / no text returned / interrupted / 0 served · 0 failed · 2 skipped · 0 tool runs` with `budget_exhausted: mode AUTO: over the monthly cap for 2026-10 (mock_one, mock_two) - raise the cap in the dashboard or wait for the reset` and the `raise a cap in Providers` link inline. Engine read before and after, identical: 4 sessions `fc22261117ef4cae(4,300) 238001d89cba4104(2,150) 856f1798ba8d42f2(4,300) 719825a7cdf54067(2,150)`, turns 6, tokens `600 in / 300 out`, `recent_issues: []`. Recent trouble stayed `no interrupted or failed turns this month.` After a reload the refused turn was gone from `#/chat` while all four engine sessions remained — the refusal lived only in React state. | matched |
| 11 | tool turn: skip note twice + tool execution, and one user turn billed 300 | With `mock_one` over cap and `mock_two` uncapped, a prompt containing `TOOL`: `over budget / used 150 of 1` → `mock_two / trying` → `mock_two / answered` → `kira / tool ran / echo("call_lab_1") → ok, 15 chars` → **`over budget` again** → `mock_two / trying` → `mock_two / answered`. Footer `2 served · 0 failed · 2 skipped · 1 tool runs`, usage `200↑ / 100↓`. `mock_two`'s spend went `0 → 300` for one user turn; the session row read 2 messages / 300 tokens. The first attempt at this row billed 150, which was the lab mock's fault, not the engine's — see Findings. | matched after fixing the lab mock |
| 12 | Models: no editable cell, `use in chat` hops | Four rows: `mini mock_one fast 4 600`, `small mock_one fast 0 0`, `mini mock_two fast 3 450`, `small mock_two fast 0 0` — zero rows are shown, not hidden. A DOM query over the table found 0 `input`/`select`/`textarea` and four buttons, all `use in chat <model>`. Sentence verbatim: `Adding or renaming a model means editing config.yaml and restarting the engine — there is no field here on purpose.` Footnote verbatim: `Turn counts come from stored assistant rows, so interrupted and failed turns are in these numbers — they spent tokens too. A model that served this month is listed by the name the provider answered with, which is why a renamed entry can appear twice.` Clicking `use in chat mini` moved to `#/chat` with the model select at `mini` (`mini · mock_one · fast`). That select has 4 options, each labelled `<id> · <provider> · <tier>` but valued with the bare id, so two options are `mini` and two are `small`. | matched |
| 13 | Models: removed model shown as `no longer configured`, no button | After restarting on the same data dir with `--models mini` and reconnecting with the new printed token: the row reads `small` with a dimmed `no longer configured` under the model name, provider `mock_two`, tier `—`, turns `1`, tokens `150`, last cell plain text `mock_two/small` and no button. The two configured rows survived with their counts; the retired row is `small · mock_two`, the provider that actually served it in Step 9. | matched |
| 14 | Sessions: how many sessions the turns made, transcript chips, delete one names id + count | 6 rows for 8 stored turns (`435784947ac5406f AUTO 2 150`, `94b220ac4c594dde AUTO 2 150`, `fc22261117ef4cae AUTO 4 300`, `238001d89cba4104 AUTO 2 150`, `856f1798ba8d42f2 AUTO 4 300`, `719825a7cdf54067 FAST 2 150`), each with a real `last used` timestamp — no row read `never` (see Findings). The transcript of `fc22261117ef4cae` replayed `third turn` (`mock_one/mini`, 150 tokens, `trying`/`answered`) and `fourth turn` (`mock_two/mini`, 150 tokens, `over budget` + reason among its chips) with the user rows printed as `complete` / `0 tokens`. `delete 719825a7cdf54067` opened `delete 719825a7cdf54067 and its 2 messages`, which names the id and the count before anything is sent. After confirming, that id was gone from the table and from the chat sidebar, and `fc22261117ef4cae` still held both turns and both chips. | matched |
| 15 | clear-all inert until the exact `DELETE ALL` | `delete every session` opens a dialog saying `Type DELETE ALL to allow this` with two fields (`confirm_phrase`, `confirm_secret`). Phrase `delete all` → `confirm write` stayed disabled. Phrase `DELETE ALL ` (trailing space) → still disabled. Exact `DELETE ALL` plus the secret → enabled. | matched |
| 16 | after clear-all, every screen empty | Sessions: `no sessions stored yet — the engine creates one per conversation, so this is empty because nothing has been asked yet, not because anything was deleted.` Overview: `nothing spent in 2026-10 yet — the month is empty, not broken.` Chat sidebar: no session buttons. Models fell back to the two configured rows at `0 / 0`, and the `small · no longer configured` row disappeared with the turn that created it. | matched, with the cap-meter consequence in Findings |

## Not exercised, and why

- The launcher's `keyring` branch. It would mint real Credential Locker entries
  (`engine/token`, `engine/confirm`) for a throwaway config, and the lab's memory vault exists so
  that a pass never has to. Both secrets were read off the lab's stderr instead.
- A real provider call. The only live paths in this product are `KIRA_LIVE=1`, `?live=true`,
  `kira-engine models` and the Test button, and none of them were pointed at anything but the mock
  on loopback.
- Concurrent windows (two tabs writing the same provider). `useWrite`'s busy flag is per screen, so
  a second tab is a real race this pass did not touch.
- A month rollover. Every number here is `2026-10`; nothing was observed crossing into `2026-11`,
  so the reset is only unit-tested behaviour.
- `mode CUSTOM` and `mode POWERFUL` from the dashboard. The lab config has no `powerful` provider,
  and the composer was left on `AUTO` for every turn above.

## Findings

- A plan-time refusal writes nothing at all — `plan()` raises at
  [kira-engine/src/kira/app.py:297](file:///D:/1.%20Ai/project-kira%20%28kimi%29/Kira/kira-engine/src/kira/app.py#L297),
  the line before `create_session` at
  [kira-engine/src/kira/app.py:298](file:///D:/1.%20Ai/project-kira%20%28kimi%29/Kira/kira-engine/src/kira/app.py#L298),
  so no screen can report that you were refused.
  Row 10 shows the whole asymmetry: the refusal is completely visible in the chat and completely
  invisible to the engine (no spend, no session, `recent_issues` empty). A month's review therefore
  cannot say "you hit the ceiling five times". A refusal counter would have to live outside the
  message table, since a message row is exactly what it refuses to write. Task 15's
  `test_a_refused_turn_stores_nothing` is the unit proof. **Follow-on for the spec, not a fix to
  make inside a pass.**
- `Router.events()` repeats skip notes on multi-step turns — row 11 read the same
  `over budget / used 150 of 1` note twice, once per plan entry, because
  [kira-engine/src/kira/router.py:142](file:///D:/1.%20Ai/project-kira%20%28kimi%29/Kira/kira-engine/src/kira/router.py#L142)
  re-yields `plan.notes` on every agent step. This is
  Task 15's note observed. Fixing it means rewriting the expected chain of every tool test, which is
  a decision for the spec's next revision.
- **The lab's mock was unfaithful, and the pass caught it by arithmetic.** `tool_call_chunks()`
  ended its stream with `finish_reason: tool_calls` and no `usage` field, so the first completion of
  a tool turn contributed 0 tokens and one user turn billed 150 — the plan says 300. The engine is
  innocent: [kira-engine/src/kira/loop.py:59](file:///D:/1.%20Ai/project-kira%20%28kimi%29/Kira/kira-engine/src/kira/loop.py#L59)
  accumulates with `+=`. Fixed in
  `kira-engine/tools/mock_openai.py` (the tool-call completion now carries `USAGE`) and row 11 was
  re-run against a fresh process: `200↑ / 100↓`, and `mock_two` 0 → 300. The product finding stands
  and is worth stating: a provider that omits `usage` on a step makes that month's spend read low,
  the cap meter with it, and nothing on any screen warns — the engine records whatever it is handed.
- The lab's own `(temp, deleted on exit)` line is true for Ctrl+C and false for a kill. Started
  without `--data-dir`, the lab printed `data C:\Users\…\Temp\kira-lab-8j4orlq_ (temp, deleted on
  exit)`, held `config.yaml kira.db kira.db-shm kira.db-wal logs` while running, and **kept all five**
  after the harness killed it — `atexit` does not run on a killed process. The unwinding path was
  then tested directly (register the same `atexit(shutil.rmtree, …)`, raise `KeyboardInterrupt`,
  let it propagate): the directory was gone. The README now says "removes it when you stop it with
  Ctrl+C" rather than promising deletion on any exit.
- Deleting history re-arms every cap. `spend_this_month` is derived from stored turns, so
  `delete every session` took `mock_one` from 600 spent to 0 while its cap override (`451`, and later
  `151`) stayed in the settings table. Providers and Overview then showed the uncapped, will-route
  state again. That is self-consistent — the meter counts what is stored — but it means the audit
  trail and the budget meter are the same rows, and wiping one silently resets the other. The health
  ledger (`7✓ 0✗`) and settings overrides both survive, so the screens disagree about what "this
  month" remembers. **Needs a sentence in the spec, and maybe in the dialog.**
- A stale token gets a shell, not the gate. With `kira.token` holding a value the engine does not
  accept, every read fails with `unauthorized: missing or invalid bearer token` and the app still draws
  the nav rail, the mode select and a model select reading `no models configured`. Nothing invites you
  back to the connect form; you have to notice the error and press `disconnect`, which does then show
  the gate with that same error under it. The recovery works — typing the fresh token connects — but it
  is a two-step manual fix for the common case of "you restarted the lab and the token changed". A
  401 on the first read should route to the gate on its own. **Spec's call.**
- Round-trip edits leave redundant overrides behind. Toggling `enabled mock_one` off and on stored an
  override whose `was` line reads `was on`; setting `priority mock_two` to 5 and back to 20 reads
  `was 20`. Both cells are then indistinguishable from an override that actually differs from
  `config.yaml`, and only `clear override` removes them. Row 9 shows what that looks like in the
  table: `on was on`.
- One sitting, many sessions. `sessionId` is React state, so an address-bar refresh — and, observed
  here, navigating to another screen and back — starts a new session. 8 turns became 6 sessions.
  That is the correct consequence of "nothing may persist the conversation id", but it makes
  `#/sessions` a list of page visits rather than of conversations. A finding about the connect flow,
  not about this screen.
- The model select names a provider it does not choose. The composer read
  `small · mock_one · fast` and the turn was served by `mock_two`, because the option's *value* is
  the bare id and the router picks by mode, cap and priority. The chain chips do name the provider
  that answered, so the pass is visible after the fact; the label is misleading before it. Either the
  label should say "provider not chosen", or the option value should carry the provider.
- Providers cannot tell you at a glance that a row is at its cap. Task 16 gave the screen a static
  enforcement sentence and left the badge on Overview, which is defensible, but in this run the
  Providers row read `… 300 …` against a cap box holding `151` with no marker at all — while the
  chat had just refused that provider. If a human has to subtract two cells to notice the state the
  engine is enforcing, the badge belongs here too. Recorded as the spec's call.
- `never` as a `last used` value is unreachable through the UI. `last_used_at` is
  `MAX(messages.created_at)`, and the only way to have a session with no message is to create one and
  never answer — which the refusal path does not do, because it raises before `create_session`. Every
  row in row 14 had a timestamp. The unit tests cover the empty session directly; a human cannot make
  one, so `never` is display code for a state the product cannot produce.
- A user row in a transcript is rendered with assistant-shaped columns: `complete` and `0 tokens`.
  Honest numbers (a user message spent nothing) under a status word that belongs to the turn.
