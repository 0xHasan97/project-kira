# Kira sub-project 10 — shell modes: a Chat surface and an Agent surface

Date: 2026-10-28
Status: approved for planning; changes **client CSS + layout only** — no engine code, no contract change.
Depends on: sub-project 1 (spine), sub-project 9 (control dashboard, merged).
Sibling slices, each needing its own spec: tool harness (2), desktop shell (3), voice (6), 3D
avatar. Project-level ordering and completion arithmetic: `docs/ROADMAP.md`.

## 1. What this is

`kira-chat` grows a two-position switch in its top-left corner — the place the brand mark
occupies today at `kira-chat/src/App.tsx:126`. One position is **Chat**, wearing the visual
language of the donor MYRAA. The other is **Agent**, wearing the layout geometry of ALTREX with
PocketStrike's glass tokens. Switching repaints the whole surface **and re-arranges it**: the
five existing screens are reachable from both shells, but Chat presents them as MYRAA-style
header chips and Agent presents them as ALTREX's sidebar plus a right-hand work panel.

This is the first of five slices the request "two switchable modes, all features, exactly as
possible" breaks down into. It is deliberately the visible one: it delivers the switch and both
skins without needing a desktop window, a microphone, or a tool harness.

### Explicitly not in this spec

| Not here | Why | Lands in |
|---|---|---|
| 3D avatar, MMD/PMX characters | A browser tab served at `/chat/` cannot do alpha hit-test click-through or a tray menu | sub-project 3, then the avatar slice |
| Voice, wake word, barge-in | Needs a persistent native listener | sub-project 6 |
| Tools beyond `echo`/`now`, file writes, terminal, checkpoints | `kira-engine/src/kira/tools.py:26` ships a registry with two demo tools and its own docstring defers OS control | sub-project 2 |
| Plugins, self-modifying actions | See §8 | sub-project 2 |
| Phone/LAN reach | Ground rule: loopback only, enforced in config validation | its own spec, §8 |
| ZORION and NEXTRON-X100 looks | Not knowable from disk — see §2 | nowhere; decided 2026-10-28 |
| MYRAA's Memory Core, Character Studio, screen-share PIP, api hub | Features of a companion app, not of a skin | each judged on its own later |

## 2. Donor evidence, and the two donors that cannot be matched

Every value in §4 and §5 was read from a donor file, not recalled. The load-bearing reads:

| Claim | Source | Verified |
|---|---|---|
| MYRAA root surface `#020205`, glass formula, 7 theme names | `MYRAA/src/App.tsx:638`, `:522`, `:305` | yes |
| MYRAA per-theme ambient gradient + text glow | `MYRAA/src/App.tsx:591-621` | yes |
| MYRAA is not a chat app (no message list anywhere) | whole-tree read; no transcript/session model | yes |
| ALTREX `:root` tokens (13px base, `#161616`, `--accent #d7d7cc`, radii 6/8/12, `--content-width: 780px`) | `ALTREX/apps/desktop/src/renderer/src/styles.css:3-34` | yes |
| ALTREX work panel = 8 tabs, exactly this order | `ALTREX/.../v4/WorkPanel.tsx:16-25` | yes |
| PocketStrike OLED black + glass tokens (blur 20, white 0.07 fill / 0.15 border, radii 10/14/20) | `PocketStrike/lib/app/theme/app_palette.dart:11-34`, `glass_tokens.dart:44-47` | yes |

**ZORION** is a PyInstaller onedir build (`_internal` has `python312.dll`, PySide6, shiboken6,
`base_library.zip`; no `app.asar`, no WebView2 loader, no bundled CSS). Its `_internal/ui/qml/`
directory **exists but is empty** — no hex colour is readable anywhere on disk. What *is* knowable
is its feature surface from `config.default.yaml` (`overlay.widgets: status, mic, task, hologram,
system, clock, emergency, conversation, quick`; `permissions.autonomy_level`; `privacy`), which §6
borrows as option names only.
*Correction added after the roadmap pass, same day:* `ZORION.exe` carries 7 `pyi-` markers, so its
CArchive is appended to the exe and **carving it is a stdlib Python job that never executes
donor code**. Whether the QML is in there is **unknown until carved** — the empty `_internal/ui/`
is a bad sign, since data files normally land in `_internal`. This spec still does not ship a
ZORION look; the spike that would settle it is a unit in `docs/ROADMAP.md`.

**NEXTRON-X100** is `NEXTRON-X100-V2-Setup.exe` (121,275,552 bytes) plus a `.sha256`. Nothing
else. Probed statically: `MZ` header, no `NullsoftInst` and no `Inno Setup Setup Data` marker in
its last 1 MB, no `app.asar` in its first 5 MB — **format unidentified**, and `7z` is not installed
on this machine to try a generic extraction. Its framework, screens and palette stay unknowable
without installing it, which ground rule 3 forbids. Decision taken 2026-10-28: **skip both looks.**
Neither appears as a named theme; nothing in this spec claims to reproduce them. Screenshots from
the user, or consent to install an extractor, are the only routes to changing that.

One fidelity note recorded rather than fixed: MYRAA's own map gives **crimson and rose the same
glow triple** `rgba(244,63,94,0.5)` (`App.tsx:613`, `:617`) — only their ambient gradients
differ. Porting "exactly as possible" reproduces that collision. It is a donor bug, not ours, and
`[data-theme]` values are named after MYRAA's so a later fix is a one-line change.

## 3. The shell model

New module **`kira-chat/src/shell.ts`**, shaped exactly like `hash-route.ts` (which is already
unit-tested), exporting:

```ts
export const SHELLS = ["chat", "agent"] as const;
export type Shell = (typeof SHELLS)[number];
const DEFAULT_SHELL: Shell = "chat";
export function currentShell(): Shell;      // reads localStorage["kira.shell"]
export function onShell(fn: (s: Shell) => void): () => void;  // "kira-shell" event + storage event
export function navigateShell(s: Shell): void;                // writes, then notifies
```

Choices and their reasons:

- **`shell`, not `mode`.** `App.tsx:35` already uses `useState<Mode>` for the router's
  `AUTO/FAST/POWERFUL/CUSTOM`, and `Mode` is exported from `kira-contracts/contract.ts:8`. Two
  unrelated concepts cannot share a name in one file.
- **Preference, not URL.** A route is a place you can link to; a shell is how you like to look at
  that place. Putting it in the hash (`#/agent/sessions`) would double every entry in `ROUTES`,
  rewrite the every-route assertion at `App.test.tsx:161`, and buy nothing a user can perceive
  beyond a back-button that changes colours.
- **`localStorage` is already sanctioned for exactly this class of value.** Ground rule 4 permits
  `kira.base`/`kira.token` there because a reload staying one click was a chosen behaviour.
  `kira.shell`, `kira.theme`, `kira.look` and `kira.sidebar` are the same class — presentation
  preferences, no secret in any of them. The grep-scoped storage checks added in sub-project 9 name
  the files that must stay clean (`confirm.tsx`, `api.ts`, screens); this adds four keys — one of
  them (`kira.look`) a single JSON object rather than one key per knob, so the options panel can
  grow a control without growing the storage surface — and the spec says so out loud rather than
  leaving the count to drift.
- **Unknown or absent value ⇒ `chat`.** Same fallback rule `parse()` in `hash-route.ts:6` uses.
  The storage `change` event is listened to so a second tab follows, which is a preference, not a
  session.

`App.tsx` gains `const [shell, setShell] = useState<Shell>(() => currentShell())`, subscribes in
the existing `useEffect` pattern, and renders `<div className="app" data-shell={shell}
data-theme={theme}>`. The switch is **its own component**, `src/shell-switch.tsx`, because Chat
shell has no `.rail` to live inside (§4) — both arrangements mount the same element first, in their
own top-left slot:

```tsx
export function ShellSwitch({ shell, connected }: { shell: Shell; connected: boolean }) {
  return (
    <div className="shell-switch" role="group" aria-label="surface">
      <span className={`dot ${connected ? "on" : "off"}`} />
      {SHELLS.map((s) => (
        <button type="button" key={s} aria-pressed={s === shell} onClick={() => navigateShell(s)}>
          {s === "chat" ? "Chat" : "Agent"}
        </button>
      ))}
    </div>
  );
}
```

`aria-pressed` on both buttons rather than `aria-current`, because this is a state toggle, not
navigation — the route keeps `aria-current="page"` where it has it today.

## 4. Chat shell — MYRAA's language

Mechanism: **one token re-scope**, not a parallel component tree. Every component already reads
the twelve custom properties declared at `styles.css:2-13` (nine colours plus `--mono`, `--sans`,
`--display`; `:root` opens at `:1` and closes at `:14`), so re-declaring them under
`[data-shell="chat"]` repaints all five screens with no per-file colour edit. The alternatives —
forking components per shell, or adopting Tailwind so donor class strings could be copied
verbatim — both break the hand-written-CSS decision recorded in the sub-project 9 spec, and the
second would add a build dependency to change colours.

New tokens both shells may use: `--glass-fill`, `--glass-border`, `--glass-blur`, `--glow`,
`--radius-sheet`, `--label-size`, and `--ok` — the twelve base tokens at `styles.css:2-13` have no
success colour at all, and ALTREX's `--success #91b99c` and MYRAA's emerald (`App.tsx:614`,
`rgb(16,185,129)`) are the two shells' values for it.

| Token | Chat shell value | Donor source |
|---|---|---|
| `--ink` | `#020205` | `MYRAA App.tsx:638` root |
| `--panel` | `#07080d` | card surface `#07080d/95` |
| `--panel-2` | `#0b0c12` | dialog surface |
| `--line` | `rgb(255 255 255 / 0.10)` | `border-white/10` |
| `--glass-fill` | `rgb(255 255 255 / 0.03)` | `bg-white/[0.03]` |
| `--glass-blur` | `40px` | `backdrop-blur-2xl` (`MYRAA App.tsx:830`, `:991`; `2xl` is 40px — `:869` and `:894` use `xl` = 24px) |
| `--accent` | theme-driven, default `rgb(99 102 241)` | `App.tsx:620`, default at `:305` |
| `--glow` | `0 0 12px <theme rgb> / 0.5` | `App.tsx:612-620` |
| radii | `8 / 12 / 999` | donor frequency: `lg` 37, `xl` 41, `full` 36 |

Type scale, ported as rules not adjectives: labels are `var(--mono)` at `10px`, `uppercase`,
`letter-spacing: 0.08em` (MYRAA uses `text-[9–11px] font-mono uppercase tracking-widest`);
captions are `var(--display)` at `1.5rem` `font-weight: 300` (`text-2xl font-light`); body stays
`15px` so the dashboard does not become unreadable — MYRAA's own micro-type is chrome, not prose.
`--display` maps to Space Grotesk, `--sans` to Inter, `--mono` to JetBrains Mono (§7).

**Seven runtime themes.** `[data-theme="violet" | "crimson" | "emerald" | "celestial" | "gold" |
"rose" | "charcoal"]` re-declares `--accent` and `--glow` only, using MYRAA's glow rgb triples
(`App.tsx:612-620`) and its ambient gradients as a two-stop `--panel` wash. Picker lives in the
Chat shell's header, persists as `kira.theme`, defaults to `charcoal` because that is MYRAA's own
default (`App.tsx:305`). Agent shell ignores `data-theme`: ALTREX has one accent, and inventing a
second theme set for it would be a claim about a donor we did not copy.

**Arrangement.** Chat shell replaces the vertical `.rail` with MYRAA's header-chip band: the five
routes render as `mono` uppercase chips across the top, and the pane below becomes a single
centred column at `--content-width` with the transcript reading like subtitles — streamed text
appends per chunk into a `font-display` caption block, which is what `App.tsx:500` does. The
existing `@media (max-width: 60rem)` rule that already turns `.rail` into a horizontal bar
(`styles.css:143-154`) is the shape Chat shell uses at every width, so the narrow case is the
normal case, not a fallback.

The selects cannot move into that band: `.rail` and `header.bar` are separate parents in
`App.tsx:125` and `:162`, and the plan could have added a portal but will not. Chat shell instead
shows **two stacked strips** — the chip band (`.rail`: switch, brand, five route chips) directly
over the control band (`.bar`: routing mode, model, theme button, settings, contract text). Same
DOM, placed by CSS, no portals, and the switch stays the first item in the first strip.

**The options panel.** MYRAA's overlay panel (`src/components/SettingsPanel.tsx:36-46` section list
with lucide icons, `:70-76` mono `10px` uppercase group heading over a `rounded-xl
border-white/10 bg-white/[0.03]` list, `:97-99` a `role="switch"` toggle, `:104` the toggle row,
`:112` a `role="radio"` segmented control, `:187` the mono status pill) is the shape of the Chat
shell's Settings affordance: a header with a status pill, an icon tab row, grouped rows, tile
grids, a segmented control and footer actions. What ports is the **pattern**, carrying Kira's real
options (theme, look, routing mode, engine status) — never a dead tile. The action chips in the
user's 2026-10-28 screenshots (Wave/Dance/Kiss, food tiles, timers) are **not** in the 1.5.2 source
drop and act on a 3D character Kira does not have yet; they belong to the avatar slice, not here.

**The switch does not move.** It is the leftmost item in the top-left corner in both arrangements:
inside the vertical `.rail` in Agent shell, and at the head of the chip band in Chat shell. Same
`role="group"` element, same two `aria-pressed` buttons, so it stays where the request asked for it
through one switch — which is also what makes the switch testable as one component rather than two.

## 5. Agent shell — ALTREX's geometry, PocketStrike's glass

| Token | Agent shell value | Donor source |
|---|---|---|
| `--ink` | `#09090B` | `app_palette.dart:12` `darkBaseAlt` |
| `--panel` | `#161616` | `styles.css:8` `--bg-app` |
| `--panel-2` | `#1b1b1b` | `styles.css:9` `--bg-sidebar` |
| `--line` | `#2b2b2b`, strong `#3b3b3b` | `styles.css:13-14` |
| `--text` / `--muted` | `#eeeeec` / `#858581` | `styles.css:15-17` |
| `--accent` | `#d7d7cc` | `styles.css:18` |
| `--ok` / `--warn` / `--bad` | `#91b99c` / `#c8b382` / `#d89993` | `styles.css:19-21` |
| `--glass-fill` / `--glass-border` / `--glass-blur` | `rgb(255 255 255/0.07)` / `0.15` / `20px` | `glass_tokens.dart:44-46` |
| base font size | `13px` | `styles.css:7` |
| `--content-width` | `780px` | `styles.css:31` |

**Radius conflict, resolved not averaged.** ALTREX uses `6/8/12` (`styles.css:22-24`),
PocketStrike uses `10/14/20` (`glass_tokens.dart:32-34`). Both are real donor values and the
shells cannot hold both. Resolution: **controls take ALTREX's `6/8`, glass sheets take
PocketStrike's `14/20`** — buttons, inputs and selects keep the tight coding-workspace feel, and
the work panel and dialogs get the frosted-sheet radius. Recorded here because "blend the two
styles" would have produced a third thing matching neither.

**Layout.** `.app` becomes `grid-template-columns: 240px 1fr auto`: a sidebar collapsing to a
56px rail with a 48px top bar (ALTREX's own numbers, at its `styles.css:56-57` — `.app-shell`
`grid-template: 48px minmax(0,1fr) / 240px minmax(0,1fr)` and
`.sidebar-is-collapsed { grid-template-columns: 56px … }`), the five routes as a vertical list,
the conversation column capped at `780px`, and a right-hand work panel. Sidebar collapse is a
button in the sidebar header, state in `kira.sidebar`, because 240px of chrome is the first thing
you give back on a small window.

**Work panel: ALTREX's 8 tabs, in its order** (`WorkPanel.tsx:16-25`), each labelled with what
fills it:

| Tab | Backed by today | Until |
|---|---|---|
| Changes | nothing — empty state names sub-project 2 | harness produces file diffs |
| Terminal | nothing — same | harness runs commands argv-only |
| Tests | nothing — same | harness runs a project's tests |
| Problems | nothing — same | harness reports diagnostics |
| Agents | **yes**: the nine `CHAIN_EVENTS` as a step timeline + `ToolRegistry.names` (`echo`, `now`) | grows with harness |
| Checkpoints | nothing — same | harness snapshots before writes |
| Context | **yes**: session id, model, mode, token usage from existing endpoints | — |
| Developer | **yes**: `provider_chain` provenance, `API_PREFIX`, `CONTRACT_VERSION` | — |

An honest empty state is `no file changes yet — arrives with the tool harness (sub-project 2)`,
rendered in the same muted mono style as the rest, and a test asserts each of the five unfilled
tabs contains the string `sub-project 2`. This is the direct cost of choosing full ALTREX tabs
over data-backed tabs only: five tabs that do nothing, each saying so.

**Agent shell's transcript** re-renders the same turn data as PocketStrike's `agent_timeline.dart`
— collapsible step chips on the terminal surface (`#09090B`), labelled with Kira's nine
`CHAIN_EVENTS` (`kira-contracts/contract.ts:10-19`: `attempt`, `served`, `failed`,
`skipped_cooling`, `skipped_missing_key`, `skipped_config`, `skipped_budget`,
`aborted_mid_stream`, `tool_executed`). Chat shell keeps today's inline list. One dataset, two
renderings, both reading `ChatScreen`'s existing turn state.

## 6. Options surface

Both shells expose a Settings affordance in their own chrome, and the options are named after what
the two source-bearing agent donors actually store, not invented:

- **Chat:** theme (7), glass on/off, caption size, reduced motion.
- **Agent:** sidebar collapsed, work panel tab, density (13px/15px base), font scale.
- **Both:** engine URL, token, routing mode, model — already exist at `App.tsx:163-177`.

ZORION's `config.default.yaml` supplies the *idea* of an `emergency` and a `quick` overlay widget;
neither is built here, and its look is not claimed anywhere (§2). PocketStrike's
`ConfirmationPolicy {alwaysAsk, destructiveOnly, autonomous}` and `ToolRisk {safe, external,
destructive}` are the right shape for the harness and are **specified into sub-project 2**, not
half-implemented as a UI control with no policy behind it.

## 7. Fonts

MYRAA's identity is Space Grotesk (display) + Inter (body) + JetBrains Mono (labels), and ALTREX,
laya and PocketStrike independently use Inter + a mono — four donors agreeing, so this is the real
look, not a guess. Decision: **self-host all three via the `@fontsource` packages**
(`@fontsource/space-grotesk`, `@fontsource/inter`, `@fontsource/jetbrains-mono`, all OFL) added to
`kira-chat` devDependencies and imported in `main.tsx`, so Vite emits the woff2 into `dist/assets`
and the engine serves them from loopback.

That shape was chosen over the two alternatives on purpose: no runtime request to a font CDN
(`font-src 'self'` in ALTREX's CSP exists for the same reason, and a loopback-local app phoning
home on every open breaks the local-first premise), and no binary woff2 files committed into the
repo, which keeps rule 2's "no vendored files" clean — the fonts come from `package.json`, are
reproducible, and carry their OFL text through the package. A `### Fonts` row goes in
`PROVENANCE.md` naming the three faces and their licence, because third-party *assets* need the
same archaeology as third-party *code*.

## 8. Ground-rule collisions, and what replaced them

An earlier round asked what to do about four Ultron capabilities that collide with the rules set
on 2026-10-27, and the answer was "port them, off by default". Two of those cannot be gated, and
were re-decided as compliant substitutes:

- **`0.0.0.0` bind.** Ultron's `dashboard/server.py` binds all interfaces and adds a Windows
  firewall allow rule. Kira's rule 5 is loopback-only *and enforced in config validation* — a
  switch that defeats it does not gate the guarantee, it deletes it. Substitute, as its own
  sub-project: loopback engine + a pairing token handed to whatever already crosses the boundary.
  Nothing in this spec binds or opens a port.
- **Plaintext keys.** Ultron writes `config/api_keys.json` in the clear. Off-by-default does not
  help — a file that exists gets backed up. Substitute: keys only in the Credential Locker, which
  Kira already does; the Agent shell's settings can show and rotate them, never export them.
- **`self_evolution.py`** (LLM writes Python into `actions/`, hot-loads it, guarded by a four-regex
  blocklist) is out. MYRAA's `DeclarativeApiAdapter` — a JSON GET/POST spec carrying no executable
  code — and Ultron's own `TOOL = {name, description, parameters, handler, behavior}` registry,
  discovery limited to modules present at startup, give a real plugin system with an honest guard.
  Specified into sub-project 2.
- **Surveillance actions** (webcam face tracking with Telegram broadcast, always-on camera,
  BLE/LAN probing, background meeting recording) are out of the roadmap as a set. They are the
  donor's product, not Kira's, and none of them came up in this spec's feature list.

## 9. Invariants and failure handling

What switching must not change, stated as testable claims:

1. The token gate (`App.tsx:101-120`) runs before either shell mounts. A stale token shows the
   connect gate identically in both.
2. `X-Kira-Confirm` is never stored — the sub-project 9 rule survives this one, and
   `kira.shell`/`kira.theme`/`kira.look`/`kira.sidebar` joining `kira.base`/`kira.token` in
   `localStorage` adds preferences only. A grep-scoped test asserts the confirm secret appears in no
   storage call.
3. The engine-contract banner (`App.tsx:157-161`) renders in both arrangements — a Chat shell that
   hides it would let a stale bundle look healthy, which is the exact failure the QA pass caught.
4. `KiraClient`, the SSE turn reader and `App.tsx:43-68` `refresh()` are untouched. No contract
   version bump; `kira-contracts/check-drift.mjs` output stays `v2, 39 schemas, 5 chunk types, 9
   chain events`.
5. Both shells render the same data for the same route. Switching mid-turn does not re-fetch or
   lose the streamed text — the turn lives in state above the shell branch.

Failure cases: unknown/absent `kira.shell` ⇒ `chat`; unknown `kira.theme` ⇒ `charcoal`; a theme
whose `--accent` fails 4.5:1 against `--panel` is caught by the browser pass measuring computed
styles (jsdom computes neither `backdrop-filter` nor contrast, so this cannot be a unit test —
same lesson as sub-project 9's `span.dot.on` check); a work panel tab whose data endpoint errors
renders the screen's existing error style, not an empty panel; two tabs disagreeing on shell
converges on the last write via the `storage` event.

## 10. Testing

- **`src/shell.test.ts`** — mirrors `hash-route.test.ts`: default, parse of unknown, notify on
  change, same-shell click still fires, `storage` event follow.
- **`App.test.tsx`** — the every-route assertion at `:161` runs for both shells; new cases for the
  chip band vs sidebar arrangement, `aria-pressed` on the switch, the gate and the contract banner
  in both, and mid-turn switch keeping streamed text.
- **`src/screens/AgentPanel.test.tsx`** — three filled tabs show real data against a stubbed
  client; five unfilled tabs each contain `sub-project 2`.
- **`styles.test.ts`** (jsdom, string-level) — asserts `[data-shell="chat"]` and
  `[data-shell="agent"]` each re-declare all twelve base tokens, so a shell cannot silently inherit
  `:root` for one variable and ship a half-painted screen. This is the cheap guard for the whole
  mechanism.
- **Existing gates stay green and are the acceptance bar**: `npm run check` (tsc → vitest → build;
  baseline 87 tests / 11 files), `node kira-contracts/check-drift.mjs`, `cd kira-engine &&
  .venv/Scripts/python -m pytest -q` (baseline 191 passed, 1 skipped) — engine tests pass
  unchanged, because the engine does not change.
- **Browser pass**, re-running `kira-engine/tools/kira_lab.py` + `tools/mock_openai.py` exactly as
  sub-project 9's Task 20 did, extended to: switch both ways with a live turn in flight, all seven
  themes readably, the work panel's three real tabs against a `TOOL` turn, computed contrast per
  theme, and `#020205`-on-`#020205` invisible-surface checks. Findings go to
  `docs/qa/shell-modes-browser-pass.md`, not into this spec's prose.
- **README + `test_docs_match_engine.py`**: no new engine surface, so the doc test gains a
  `### Shell modes` expectation only if it starts asserting client copy; the README gains the
  section regardless, since "two modes, switch top-left" is the first thing a user asks about.

## 11. Rollback

One attribute on one element. Removing `data-shell`/`data-theme` from `div.app` at
`App.tsx:124`, deleting the two `[data-shell=…]` selector blocks, and dropping `<ShellSwitch/>`
back to the existing `.rail-brand` markup returns every screen to the sub-project 9 appearance
with no component deleted, no prop changed, no endpoint touched. `shell.ts`, `shell-switch.tsx` and
the four localStorage keys become dead code and go in the same revert.

## 12. After this spec

Order agreed 2026-10-28 for the rest of the original ask: **tool harness (2)** — so the work panel
fills and the plugin/permission shapes in §8 get built; **desktop shell (3)**; **voice (6)**;
**3D avatar**. The avatar slice re-opens one rejection already on record in `PROVENANCE.md`
("MYRAA 3D/MMD character engine — rejected: orthogonal to the agent, skins are
non-redistributable"), and it has a hole no amount of reading closes: MYRAA's own default
character is missing from its source (`evelyn.ts` is imported by `registry.ts:10` but absent, and
`assets/characters/**` is excluded by `electron-builder.public.yml:26`), so that slice builds the
stage and the user supplies a model.
