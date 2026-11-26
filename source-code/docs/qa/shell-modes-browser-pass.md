# Shell-modes browser pass — 2026-10-28 (UTC)

Engine: `tools/kira_lab.py --port 8916 --mock-port 8996`, mock provider
`tools/mock_openai.py` on `http://127.0.0.1:8996/v1`, data dir a temp one the lab removes on
Ctrl+C (memory vault — nothing in the Credential Locker, nothing in `.kira-data`). The pass script was
run several times against that one process, so the session list accumulated one session per run
(`6 stored sessions` by the last one); every check below quotes what its own run showed.

Browser: the page at `http://127.0.0.1:8916/chat/`, driven headless over raw CDP — the cached
Playwright Chromium (`%LOCALAPPDATA%\ms-playwright\chromium-1248\chrome-win64\chrome.exe`),
`Emulation.setDeviceMetricsOverride` at **1440×900**, device scale 1, Node 24's global `fetch` and
`WebSocket`, no npm packages. The app's own in-app browser was not used because its page is
531×553 and has no resize tool, which hides the desktop layout this pass is about. The two
sanctioned `localStorage` keys (`kira.base`, `kira.token`) were seeded in one evaluate and the page
reloaded, so no token was ever typed into a field or echoed into a URL.

The clock on this machine reads UTC+6; no date is quoted below except the `2026-10` month bucket.

## What was driven

One script, start to finish: default chat load; theme tiles in the options panel; a plain turn; the
Look tab's four caption sizes and the glass toggle; the Status tab; a `TOOL` turn under 600ms network
latency with the switch pressed 150ms into the stream; the agent shell and all eight work tabs; the
sidebar collapse; `#/providers` in agent and then a flip to chat on that route; a reload. Screenshots
01–08 in the pass directory, `report.json` beside them.

| # | Check | Observed | Verdict |
| --- | --- | --- | --- |
| 1 | Both positions render, the switch keeps the top-left corner, `data-shell` flips | Chat: `.app` at `1440px` one column, rows `51.97px 848.03px`, rail band `0,0 1440×52`, switch `x16 y10 141×32`, `data-shell="chat"`, `data-theme="charcoal"`, `data-glass="on"`, `data-motion="on"`, `data-caption="m"`, `data-density="compact"`. Agent: grid `240px 900px 300px`, rail `0,0 240×900`, switch `x10 y19 138×43`, `data-theme` still `violet`, work panel present. Pressing Chat↔Agent flips the attribute and the whole surface with it; the work panel exists only in agent. | matched |
| 2 | Seven themes: accent computed per theme, ≥4.5:1 against the chat surfaces | Measured `--accent`/`--panel`(`#07080d`)/`--panel-2`(`#0b0c12`)/`--ink`(`#020205`): violet `#a855f7` 5.06/4.93/5.24 · crimson `#f43f5e` 5.45/5.32/5.64 · emerald `#10b981` 7.89/7.70/8.17 · celestial `#0ea5e9` 7.22/7.05/7.48 · gold `#f59e0b` 9.32/9.09/9.65 · rose `#f43f5e` 5.45/5.32/5.64 · charcoal `#6669f5` 4.67/4.56/4.84. Six distinct accents, not seven: crimson and rose share the donor's `rgb(244 63 94)` triple — recorded in [the spec §2](file:///D:/1.%20Ai/project-kira%20%28kimi%29/Kira/docs/specs/2026-10-28-kira-shell-modes-design.md) as a donor collision kept on purpose; their ambient washes differ (`rgb(69 10 10)` vs `rgb(76 5 25)`). | matched, with the recorded collision |
| 3 | Glass off/on changes `backdrop-filter` on `.msg.assistant` | `blur(40px)` → toggle → `blur(0px)` with `data-glass="off"` → toggle → `blur(40px)`. The answer keeps its `rgba(255,255,255,0.03)` fill when the blur goes, so the sheet stays a sheet. | matched |
| 4 | Caption S/M/L/XL compute to 20/24/30/36px | `.msg.assistant .content`: `s` 20px · `m` 24px · `l` 30px · `xl` 36px, `data-caption` following each press. At `m` the computed family is `"Space Grotesk", Inter, sans-serif` at weight 300. | matched |
| 5 | Switch mid-answer: the stream survives the flip and the work panel fills | With 600ms latency, `TOOL round trip please`, sampled 150ms after send: `data-shell="chat"`, button label `thinking`, `.msg.streaming` present, text `waiting for the first token`. Clicked Agent, sampled 120ms later: `data-shell="agent"`, same `.msg.streaming` article, same text — the turn kept streaming across the repaint. After it completed: 2 answers, last text `the tool round trip came back`, `5 steps` in the summary, send back to `send`. The Agents tab then read `2 served · 0 failed · 0 skipped · 1 tool runs` with the five chips (`trying`/`answered`/`kira tool ran echo("call_lab_1") → ok, 15 chars`/`trying`/`answered`) and `TOOLS SEEN THIS TURN echo`. | matched |
| 6 | Work panel: five empty tabs name sub-project 2, three tabs show real data | Changes `no file changes yet — arrives with the tool harness (sub-project 2)`; Terminal, Tests, Problems, Checkpoints the same shape. Agents/Context/Developer: `SESSION 6e11ad79 MODEL mini MODE AUTO USAGE 200↑ / 100↓ STATUS complete` and `NAMESPACE /v1 CONTRACT v2 PROVIDER_CHAIN [ … ]` with the three events as JSON. All eight bodies measured `scrollWidth = clientWidth = 299`. | matched |
| 7 | Sidebar collapse: 240px → 56px, remembered | Agent `grid-template-columns` `240px 900px 300px`, toggle → `56px 1084px 300px` with `data-sidebar="collapsed"`; after reload the same grid and attribute. The collapsed rail's own `scrollWidth` equals its `clientWidth` (55), and the switch fits inside it as a 36×93 column. | matched |
| 8 | No text is painted in its own surface colour | Every sampled label composites to a different colour from the surface under it. Chat (`#07080d` ground): rail label 10px **4.93**, rail-active label 4.93, mode select 15px 16.47, `/v1 · v2` 12.9px 7.80, side heading 10px 8.08, answer 24px 16.09, answer meta 12.48px 7.44, composer hint 12.8px 8.08. Agent (`#161616` ground): rail label 13px 13.70, rail-active 13.70, pressed switch 10px 13.72, `/v1 · v2` 11.18px 4.89, work tab 11px 13.70, answer 13px 12.71. | matched |
| 9 | `/v1 · v2` in both shells and on a non-chat route | `/v1 · v2` in the chat bar and the agent bar; still there on `#/providers` in agent, and after flipping to chat on that route the providers screen stayed put with the work panel gone (`workPanel:false`, `providersScreen:true`). | matched |
| 10 | Options panel carries the look, and the pressed control reads | Theme tiles repaint `--accent` live; the Look tab's caption segmented control and the glass toggle act as row 3 and 4 say; the Status tab read `SESSION … 6e11ad79 6 stored sessions PROVIDERS … mock_one 16✓ 0✗ KEY OK mock_two 0✓ 0✗ KEY OK`. The selected segment is now ink (`rgb(2,2,5)`) on the accent, not white on it. | matched after row 3 of Findings |
| 11 | A chat turn shows the chain and the usage the lab scripts | `mock answer, scripted by tools/mock_openai.py`, badge `mock_one`, footer `complete mini 100↑ / 50↓ 1 served · 0 failed · 0 skipped · 0 tool runs`, chips `mock_one trying mini` → `mock_one answered mini`, glass `blur(40px)`, answer ink `rgb(233,236,239)` on `rgba(255,255,255,0.03)`, switch dot `rgb(168,85,247)` (violet). In chat the chain has no `summary` (it is not collapsed); in agent the same chain is inside `<details>` reading `2 STEPS` / `5 STEPS`. | matched |
| 12 | A reload keeps the preferences and drops the transcript | After reload: `data-shell="chat"`, `data-sidebar="collapsed"`, `data-theme="violet"`, grid `1440px`, `messages: 0`, no work panel — the six keys persist, the conversation does not, because the engine owns it and the view is one continuous session. | matched, with the note in Findings |

## Findings

Five of these were fixed inside the pass, one commit each, with a jsdom guard where the rule is
testable there.

- **The chat band stretched its first track.** `.app[data-shell="chat"]` had one explicit column and
  no rows, so the layout's `auto` row stretched under `align-content: normal`: the rail band was
  208px tall and the switch sat at `y=88`, not in the corner the donor's screenshot shows. Fixed in
  [styles.css:643](file:///D:/1.%20Ai/project-kira%20%28kimi%29/Kira/kira-chat/src/styles.css#L643) with
  `grid-template-rows: auto minmax(0, 1fr)` (declared at line 647); the band is now 52px and the switch `y=10`.
  `styles.test.ts` matches every `.app[data-shell="chat"]` block for that pair.
- **Charcoal's accent was 4.48:1 on `--panel`.** `rgb(99 102 241)` from the donor's charcoal triple
  sat under AA for a 10px label by 0.02. Moved three steps of one channel to
  `rgb(102 105 245)` — 4.67 on `--panel`, 4.56 on `--panel-2` — and the theme guard in
  `styles.test.ts` now runs all seven rather than the one it was written for.
- **White on the chat accents was the worst text in the app.** Measured per theme:
  `#f59e0b` 2.15, `#10b981` 2.54, `#0ea5e9` 2.77, `#f43f5e` 3.67, `#a855f7` 3.96, `#6669f5` 4.28.
  It painted the pressed switch label and the options panel's selected segment. `--on-accent` is now
  `var(--ink)`: 4.84–9.65 across the six accents. The same test's third assertion is the one that
  would have caught it (`accent` vs `--ink` ≥ 4.5). The agent shell already read dark ink on its
  light accent (13.72), so the two shells now agree.
- **The work panel scrolled sideways.** A chain chip is as wide as its `.chain-detail` (up to 22rem,
  `nowrap`); in a 300px panel that widened the grid's `auto` track, and every paragraph stretched to
  the widened track instead of wrapping — `1 tool run` in the Agents tab was cut mid-word. Fixed with
  `grid-template-columns: minmax(0, 1fr)` on `.work-body` and panel-scoped wrapping on the chips:
  all eight tabs now measure 299/299.
- **`break-all` on the Developer tab.** `word-break: break-all` fractured `mock_one` into `mock_on` +
  `e` and split `"call_lab_1"` across lines even though every token fits the panel. Now
  `overflow-wrap: anywhere`, so it breaks only when a token cannot fit.
- **The collapsed rail lost three controls.** At 56px the 141px switch centred itself to **x=-31** —
  `Chat` was cut off at the left edge — and the collapse toggle sat at **x=69**, outside the rail,
  while the rail's own `scrollWidth` was 86 against a 55px client box. The footer's `refresh` and
  `disconnect` were plain text and spilled past the border too. Fixed by stacking the switch buttons
  (36px column, 93px tall), giving the footer lucide icons behind `.rail-label`, and — since
  `.rail-label` is `display:none` when collapsed — putting `aria-label` on every rail button so the
  names survive. The rail now measures 55/55 and the toggle returns to x=10. `App.test.tsx` asserts
  the seven names, and `styles.test.ts` the stacking rules.
- **Two donor facts recorded, not fixed.** Crimson and rose share an accent (row 2). The agent
  shell's `--on-accent` is `#09090b` on `#d7d7cc` (13.72) — no inverse problem there.
- **The transcript is view-only.** Row 12: reloading keeps six keys and drops every `.msg`. The
  engine has the session; the screen does not re-read it. This is the same "one sitting, many
  sessions" behaviour the dashboard pass recorded, seen from the other side.
- **The session list grows per run.** Because the lab's dir was kept for this sitting and each page
  load starts a new session, the sidebar read six sessions by the last run. Nothing in this pass is
  about history, but a repeated pass will look like heavy use to `#/sessions`.

## Not exercised, and why

- A real provider call. Everything above went to `tools/mock_openai.py` on loopback; the live paths
  still need `KIRA_LIVE=1` and a user's own key.
- `prefers-reduced-motion`. The motion toggle sets `data-motion`, and the CSS respects the media
  query, but this Chromium ran with its default (no preference emulated).
- Widths below 1440px. The two media breakpoints (`70rem`, `60rem`) were not driven; the in-app
  browser's 531px viewport is the closest thing that was looked at, and it was the reason the
  desktop pass exists.
- Keyboard-only traversal. The focus ring is in the stylesheet and `styles.test.ts`; the pass
  clicked.
- The confirm dialogs and every write path. The dashboard pass covers them against the same engine;
  nothing here writes.
- The avatar/voice slices. They are not in this sub-project; the options panel is the donor's
  pattern only.
