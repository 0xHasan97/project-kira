# Sub-project 10 — shell modes implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A two-position Chat/Agent switch in `kira-chat`'s top-left corner that repaints and re-arranges all
five screens — MYRAA's language for Chat, ALTREX geometry + PocketStrike glass for Agent — with no engine change.

**Architecture:** One token re-scope, not a parallel component tree. `div.app` carries `data-shell` (plus
`data-theme`, and the look attributes); two selector blocks re-declare every base custom property; layout
differences are grid rules on the same DOM. The switch, the options panel and the work panel are the only new
elements, and each is a real component with its own test.

**Tech Stack:** React 19 + TypeScript 7 + Vite 8, Vitest 5 + jsdom, hand-written CSS custom properties,
`@fontsource` (OFL) for the three faces, `lucide-react` (ISC) for icons.

**Spec:** `docs/specs/2026-10-28-kira-shell-modes-design.md` — read §3-§11 before Task 5.

## Global Constraints

- **BYOK only.** No free-tier catalogue, no key scraping, no aggregation. Nothing in this plan talks to a provider.
- **Reimplement, never copy.** No donor source text, no vendored donor files. Every colour in this plan is a value read from a donor file, cited inline; the CSS is written here.
- **Never execute donor code or installers.** Reading MYRAA/ALTREX/PocketStrike with `sed`/`grep`/`unzip -p` is allowed; running anything from them is not.
- **Secrets never leave the Credential Locker.** Provider keys, `engine/token`, `engine/confirm` are never written to disk, logs, responses or URLs. `X-Kira-Confirm` never enters `localStorage`.
- **`localStorage` keys are a closed list:** `kira.base`, `kira.token` (existing, sanctioned by sub-project 9),
  plus `kira.shell`, `kira.theme`, `kira.look`, `kira.sidebar` (added here, presentation only). Any other key is a bug.
- **Loopback only.** Do not add a `0.0.0.0` bind or a port-opening path. The engine does not change in this plan.
- **No contract change.** `CONTRACT_VERSION` stays 2, `API_PREFIX` stays `/v1`; `check-drift.mjs` must still print
  `v2, 39 schemas, 5 chunk types, 9 chain events`.
- **Commits:** never run `git config`. Commit as `git -c user.name="Kira" -c user.email="kira@localhost" commit …`.
  One commit per task, on `feat/shell-modes`.
- **Gates after every task:** `cd kira-chat && npx tsc --noEmit && npx vitest run` (build once at Task 17).
- Baselines to preserve: engine `191 passed, 1 skipped`; chat `87 tests / 11 files` before Task 2.

---

## File map

| File | Responsibility |
|---|---|
| `kira-chat/src/shell.ts` (new) | which surface is active: read, subscribe, write |
| `kira-chat/src/theme.ts` (new) | the seven MYRAA theme names: read, subscribe, write |
| `kira-chat/src/look.ts` (new) | cosmetic preferences (glass, motion, caption size, scale, density) as one JSON value |
| `kira-chat/src/shell-switch.tsx` (new) | the top-left toggle, shared by both arrangements |
| `kira-chat/src/options-panel.tsx` (new) | MYRAA's panel pattern carrying Kira's real options |
| `kira-chat/src/useChat.ts` (new) | the chat state machine lifted above the shell branch |
| `kira-chat/src/screens/AgentPanel.tsx` (new) | ALTREX's 8-tab work panel |
| `kira-chat/src/screens/ChatScreen.tsx` | becomes presentational; consumes `useChat`'s state |
| `kira-chat/src/App.tsx` | shell/theme/look state, `data-*` attributes, both arrangements |
| `kira-chat/src/styles.css` | two `[data-shell]` token blocks, seven theme blocks, look blocks, geometry |
| `kira-chat/src/components/ChainTrace.tsx` | gains the PocketStrike step-chip rendering |
| `kira-chat/src/{shell,theme,look}.test.ts` (new) | module tests mirroring `hash-route.test.ts` |
| `kira-chat/src/styles.test.ts` (new) | string-level guard: both shells declare every token |
| `kira-chat/src/App.test.tsx` | every-route × both shells, switch, gate, banner, mid-turn switch |
| `kira-chat/src/screens/AgentPanel.test.tsx` (new) | 8 tabs, 5 honest empty states, 3 real ones |
| `kira-chat/src/fake-engine.ts` | a held-open SSE stream so mid-turn switching is testable |
| `Kira/PROVENANCE.md`, `Kira/README.md` | fonts/icons rows, the shell-modes section |

---

### Task 1: Amend the spec with what planning found

Planning read more than the spec did. Six corrections, all recorded before any code:

**Files:**
- Modify: `docs/specs/2026-10-28-kira-shell-modes-design.md`

**Interfaces:**
- Consumes: nothing. Produces: the numbers every later task implements.

- [ ] **Step 1: Fix the token count.** §4 says "the ten custom properties at `styles.css:1-14`". There are
  **twelve** (nine colours + `--mono`/`--sans`/`--display`), declared at `styles.css:2-13`. Replace both
  occurrences and make §10's `styles.test.ts` bullet say "all twelve base tokens".

- [ ] **Step 2: Fix the blur value.** §4 says `--glass-blur: 16px` from `backdrop-blur-2xl`. Tailwind's
  `blur-2xl` is **40px**; `blur-xl` is 24px (`MYRAA src/App.tsx:830`, `:991` use `2xl`; `:869`, `:894` use `xl`).
  Change the Chat value to `40px` and cite those lines.

- [ ] **Step 3: Name both Chat bands.** §4 says the selects "move into that band". They cannot: the rail and the
  header are different parents. Replace that sentence with: the Chat shell shows **two stacked strips** — the
  chip band (`.rail`: switch, brand, five route chips) and the control band (`.bar`: routing mode, model, theme
  button, settings, contract text). Same DOM, placed by CSS, no portals.

- [ ] **Step 4: Name the fourth key.** §3, §9.2 and §11 list three new keys. The options surface in §6 needs a
  fourth: `kira.look`, one JSON value `{glass, motion, caption, scale, density}`. Update all three places.

- [ ] **Step 5: Record the panel.** Add to §4, after the arrangement paragraph:

  > **The options panel.** MYRAA's overlay panel (`src/components/SettingsPanel.tsx:36-46` section list with
  > lucide icons, `:70-76` mono `10px` uppercase group heading over a `rounded-xl border-white/10
  > bg-white/[0.03]` list, `:97-99` a `role="switch"` toggle, `:104` the toggle row, `:112` a `role="radio"`
  > segmented control, `:187` the mono status pill) is the shape of the Chat shell's Settings affordance. What
  > ports is the **pattern** — header with status pill, icon tab row, grouped rows, tile grids, segmented
  > control, footer actions — carrying Kira's real options. The action chips in the user's 2026-10-28
  > screenshots (Wave/Dance/Kiss/food tiles) are **not** in the 1.5.2 source drop and act on a 3D character Kira
  > does not have yet; they belong to the avatar slice, not here.

- [ ] **Step 6: Commit**

```bash
git add docs/specs/2026-10-28-kira-shell-modes-design.md
git -c user.name="Kira" -c user.email="kira@localhost" commit -m "docs(spec): measure the shell-modes spec against its own donors — twelve tokens, 40px blur, two bands, four keys, the panel pattern"
```

---

### Task 2: `shell.ts` — which surface is active

**Files:**
- Create: `kira-chat/src/shell.ts`
- Test: `kira-chat/src/shell.test.ts`

**Interfaces:**
- Produces: `SHELLS`, `Shell`, `currentShell()`, `onShell(fn)`, `navigateShell(s)`. Consumed by `App.tsx`,
  `shell-switch.tsx`, `options-panel.tsx`, `AgentPanel`.

- [ ] **Step 1: Write the failing test**

```ts
// kira-chat/src/shell.test.ts
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { currentShell, navigateShell, onShell, SHELLS, type Shell } from "./shell.ts";

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  localStorage.clear();
});

describe("shell", () => {
  it("defaults to chat when nothing is stored", () => {
    expect(currentShell()).toBe("chat");
  });

  it("falls back to chat on an unknown value", () => {
    localStorage.setItem("kira.shell", "terminal");
    expect(currentShell()).toBe("chat");
  });

  it("reads both documented shells", () => {
    for (const shell of SHELLS) {
      localStorage.setItem("kira.shell", shell);
      expect(currentShell()).toBe(shell);
    }
  });

  it("notifies subscribers on navigate and stops after unsubscribe", () => {
    const seen: Shell[] = [];
    const off = onShell((shell) => seen.push(shell));
    navigateShell("agent");
    expect(seen).toEqual(["agent"]);
    off();
    navigateShell("chat");
    expect(seen).toEqual(["agent"]);
  });

  it("navigateShell fires even when the shell already matches", () => {
    navigateShell("chat");
    const seen: Shell[] = [];
    onShell((shell) => seen.push(shell));
    navigateShell("chat");
    expect(seen).toEqual(["chat"]);
  });

  it("follows a write from another tab", () => {
    const seen: Shell[] = [];
    onShell((shell) => seen.push(shell));
    localStorage.setItem("kira.shell", "agent");
    window.dispatchEvent(new StorageEvent("storage", { key: "kira.shell", newValue: "agent" }));
    expect(seen).toEqual(["agent"]);
  });

  it("ignores a storage event for some other key", () => {
    const seen: Shell[] = [];
    onShell((shell) => seen.push(shell));
    window.dispatchEvent(new StorageEvent("storage", { key: "kira.theme", newValue: "violet" }));
    expect(seen).toEqual([]);
  });
});
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd kira-chat && npx vitest run src/shell.test.ts`
Expected: FAIL — `Failed to resolve import "./shell.ts"`.

- [ ] **Step 3: Write the module**

```ts
// kira-chat/src/shell.ts
export const SHELLS = ["chat", "agent"] as const;
export type Shell = (typeof SHELLS)[number];

const SHELL_KEY = "kira.shell";
const SHELL_EVENT = "kira-shell";
const DEFAULT_SHELL: Shell = "chat";

function parse(value: string | null): Shell {
  return value !== null && (SHELLS as readonly string[]).includes(value) ? (value as Shell) : DEFAULT_SHELL;
}

/** Which surface the user prefers. A preference, not a route: two tabs may disagree. */
export function currentShell(): Shell {
  return parse(localStorage.getItem(SHELL_KEY));
}

type Listener = (shell: Shell) => void;
const listeners = new Set<Listener>();

function notify(): void {
  const shell = currentShell();
  for (const fn of listeners) fn(shell);
}

function onStorage(event: StorageEvent): void {
  if (event.key === SHELL_KEY) notify();
}

export function onShell(fn: Listener): () => void {
  listeners.add(fn);
  if (listeners.size === 1) {
    window.addEventListener(SHELL_EVENT, notify);
    window.addEventListener("storage", onStorage);
  }
  return () => {
    listeners.delete(fn);
    if (listeners.size === 0) {
      window.removeEventListener(SHELL_EVENT, notify);
      window.removeEventListener("storage", onStorage);
    }
  };
}

export function navigateShell(shell: Shell): void {
  localStorage.setItem(SHELL_KEY, shell);
  // Dispatched even when nothing changed: a click on the active position still means "paint this".
  window.dispatchEvent(new Event(SHELL_EVENT));
}
```

- [ ] **Step 4: Run the test**

Run: `cd kira-chat && npx vitest run src/shell.test.ts`
Expected: PASS, 7 tests.

- [ ] **Step 5: Commit**

```bash
git add kira-chat/src/shell.ts kira-chat/src/shell.test.ts
git -c user.name="Kira" -c user.email="kira@localhost" commit -m "feat(chat): a shell preference module, shaped like the hash route so the two read the same way"
```

---

### Task 3: The switch, and the attribute that everything hangs on

**Files:**
- Create: `kira-chat/src/shell-switch.tsx`
- Modify: `kira-chat/src/App.tsx:124-129` (the `.app` div and `.rail-brand`)
- Test: `kira-chat/src/App.test.tsx` (new `describe` block)

**Interfaces:**
- Consumes: `SHELLS`, `Shell`, `navigateShell` (Task 2).
- Produces: `<ShellSwitch shell connected />`; `div.app[data-shell]` — the hook every later CSS block uses.

- [ ] **Step 1: Write the failing test**

```ts
// append to kira-chat/src/App.test.tsx, inside the existing `describe("App", ...)`
describe("surface switch", () => {
  it("starts on the stored shell and flips the app attribute when clicked", async () => {
    localStorage.setItem("kira.shell", "chat");
    const engine = fakeEngine({ models: MODELS, health: HEALTH });
    connectedTo(engine);
    const view = render(<App />);

    const group = await screen.findByRole("group", { name: "surface" });
    const [chat, agent] = within(group).getAllByRole("button");
    expect(chat.getAttribute("aria-pressed")).toBe("true");
    expect(agent.getAttribute("aria-pressed")).toBe("false");
    expect(view.container.querySelector(".app")?.getAttribute("data-shell")).toBe("chat");

    fireEvent.click(agent!);
    expect(localStorage.getItem("kira.shell")).toBe("agent");
    expect(view.container.querySelector(".app")?.getAttribute("data-shell")).toBe("agent");
    expect(agent!.getAttribute("aria-pressed")).toBe("true");
    expect(chat!.getAttribute("aria-pressed")).toBe("false");
  });

  it("keeps the connection dot inside the switch", async () => {
    const engine = fakeEngine({ models: MODELS, health: HEALTH });
    connectedTo(engine);
    render(<App />);
    const group = await screen.findByRole("group", { name: "surface" });
    expect(group.querySelector("span.dot.on")).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd kira-chat && npx vitest run src/App.test.tsx`
Expected: FAIL — `Unable to find an accessible element with the role "group" and name "surface"`.

- [ ] **Step 3: Write the component**

```tsx
// kira-chat/src/shell-switch.tsx
import { navigateShell, SHELLS, type Shell } from "./shell.ts";

/** Two positions, one component: both arrangements mount this in their own top-left slot. */
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

- [ ] **Step 4: Wire it into `App.tsx`**

Add the imports and state (the `useEffect` sits beside the existing `onRoute` one):

```tsx
import { currentShell, onShell, type Shell } from "./shell.ts";
import { ShellSwitch } from "./shell-switch.tsx";

// inside App(), after `const [route, setRoute] = ...`
const [shell, setShell] = useState<Shell>(() => currentShell());
useEffect(() => onShell(setShell), []);
```

Replace the `.app` open tag and the `.rail-brand` block:

```tsx
<div className="app" data-shell={shell}>
  <nav className="rail" aria-label="Kira sections">
    <div className="rail-brand">
      <ShellSwitch shell={shell} connected={connected} />
      <strong>Kira</strong>
    </div>
```

(The old `span.dot` in `.rail-brand` is gone — `ShellSwitch` renders it, so there is one dot, not two.)

- [ ] **Step 5: Run the whole chat suite**

Run: `cd kira-chat && npx tsc --noEmit && npx vitest run`
Expected: PASS — 89 tests / 11 files (87 + the 2 new ones). The every-route test still finds `Kira` because
`<strong>Kira</strong>` stayed.

- [ ] **Step 6: Commit**

```bash
git add kira-chat/src/shell-switch.tsx kira-chat/src/App.tsx kira-chat/src/App.test.tsx
git -c user.name="Kira" -c user.email="kira@localhost" commit -m "feat(chat): the top-left surface switch, with data-shell as the only thing the skins hang on"
```

---

### Task 4: Fonts and icons as dependencies

**Files:**
- Modify: `kira-chat/package.json`, `kira-chat/package-lock.json`, `kira-chat/src/main.tsx`
- Modify: `Kira/PROVENANCE.md`

**Interfaces:**
- Produces: `--display` may name Space Grotesk, `--sans` Inter, `--mono` JetBrains Mono (Tasks 5-9 set them);
  `lucide-react` icon exports (Tasks 9-15 import them).

- [ ] **Step 1: Prove the registry is reachable, and that every icon name exists**

```bash
cd kira-chat && npm view @fontsource/space-grotesk version && npm view lucide-react version
```
Expected: two version numbers. If the registry is unreachable, **stop and report** — do not substitute a CDN
(the local-first premise in spec §7) and do not leave a half-added dependency.

- [ ] **Step 2: Install**

```bash
cd kira-chat && npm install --save @fontsource/space-grotesk @fontsource/inter @fontsource/jetbrains-mono lucide-react
```

- [ ] **Step 3: Verify the icon names this plan uses exist in the installed version**

```bash
cd kira-chat && node -e "const l=require('lucide-react');const want=['Palette','Route','Sparkles','Activity','X','Settings','RefreshCw','Power','PanelLeftClose','PanelLeftOpen','FileDiff','Terminal','FlaskConical','CircleAlert','Bot','History','Layers','Code','MessageSquare','Gauge','Server','Cpu'];const missing=want.filter(n=>!(n in l));console.log(missing.length?('MISSING '+missing.join(',')):'all present')"
```
Expected: `all present`. If not, substitute the closest present name in the task that uses it, and say so in
the commit message.

- [ ] **Step 4: Import the faces in `main.tsx`**

```tsx
// kira-chat/src/main.tsx — before "./styles.css"
import "@fontsource/space-grotesk/300.css";
import "@fontsource/space-grotesk/500.css";
import "@fontsource/inter/400.css";
import "@fontsource/inter/500.css";
import "@fontsource/jetbrains-mono/400.css";
```

- [ ] **Step 5: Prove Vite emits them locally**

```bash
cd kira-chat && npx vite build 2>&1 | tail -5 && ls dist/assets | grep -ci woff2
```
Expected: build succeeds; the `grep -c` prints a count ≥ 5. No `https://fonts.` string anywhere:

```bash
grep -rn "fonts.googleapis\|fonts.gstatic" src/ dist/assets/*.css ; echo "exit=$?"
```
Expected: no output, `exit=1`.

- [ ] **Step 6: Record the archaeology in `PROVENANCE.md`**

Add below the existing table:

```markdown
| Third-party asset | Design influence from | Licence | Vendored file? |
|---|---|---|---|
| Typefaces `@fontsource/space-grotesk`, `@fontsource/inter`, `@fontsource/jetbrains-mono` | MYRAA, ALTREX, laya and PocketStrike independently use Space Grotesk / Inter / a mono for chrome | SIL OFL 1.1 | no — npm dependencies, imported in `main.tsx`, emitted into `dist/assets` by Vite |
| Icons `lucide-react` | ALTREX and MYRAA both import lucide | ISC | no — npm dependency, tree-shaken at build |
```

- [ ] **Step 7: Commit**

```bash
git add kira-chat/package.json kira-chat/package-lock.json kira-chat/src/main.tsx PROVENANCE.md
git -c user.name="Kira" -c user.email="kira@localhost" commit -m "feat(chat): self-hosted OFL faces and lucide icons, so the skins can name a typeface without phoning a CDN"
```

---

### Task 5: The token guard, and the Chat shell's repaint

**Files:**
- Create: `kira-chat/src/styles.test.ts`
- Modify: `kira-chat/src/styles.css` (append; nothing above line 14 changes)
- Modify: `kira-chat/src/App.tsx` (move `ConfirmProvider` inside `.app`)

**Interfaces:**
- Consumes: `data-shell` (Task 3). Produces: `[data-shell="chat"]` tokens; the same twelve names re-declared in Task 9's Agent block.

- [ ] **Step 1: Write the failing guard**

```ts
// kira-chat/src/styles.test.ts
import { describe, expect, it } from "vitest";
import css from "./styles.css?raw";

/** The twelve properties every screen already reads. A shell that inherits one of them ships half a skin. */
export const BASE_TOKENS = [
  "--ink", "--panel", "--panel-2", "--line", "--text", "--muted", "--accent", "--warn", "--bad",
  "--mono", "--sans", "--display",
] as const;

function block(selector: string): string {
  const start = css.indexOf(`${selector} {`);
  expect(start, `no ${selector} block in styles.css`).toBeGreaterThan(-1);
  return css.slice(start, css.indexOf("}", start));
}

describe("shell tokens", () => {
  it.each(BASE_TOKENS)("chat re-declares %s", (token) => {
    expect(block('.app[data-shell="chat"]')).toContain(`${token}:`);
  });

  it.each(BASE_TOKENS)("agent re-declares %s", (token) => {
    expect(block('.app[data-shell="agent"]')).toContain(`${token}:`);
  });

  it("declares the seven MYRAA themes, and only for the chat shell", () => {
    for (const theme of ["violet", "crimson", "emerald", "celestial", "gold", "rose", "charcoal"]) {
      expect(block(`.app[data-shell="chat"][data-theme="${theme}"]`)).toContain("--accent:");
      expect(css).not.toContain(`[data-shell="agent"][data-theme="${theme}"]`);
    }
  });

  it("never lets a shell fall back to the pre-skin palette", () => {
    // Both blocks declare --ink; if a shell omitted it, the rule above would still pass on a substring
    // elsewhere in the file, so check the value itself differs from :root's.
    expect(block('.app[data-shell="chat"]')).not.toContain("--ink: #0f1113");
    expect(block('.app[data-shell="agent"]')).not.toContain("--ink: #0f1113");
  });
});
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd kira-chat && npx vitest run src/styles.test.ts`
Expected: FAIL — `no .app[data-shell="chat"] block in styles.css`.

- [ ] **Step 3: Append the Chat token block to `styles.css`**

```css
/* ── Shell modes (spec 2026-10-28 §4) ────────────────────────────────────────────────────────────
   One token re-scope per shell. Every screen reads these twelve properties, so a block here repaints
   the whole surface; the geometry rules below only decide where the same DOM sits. Values are donor
   reads, cited — see PROVENANCE.md for why that is not copying. */
.app[data-shell="chat"] {
  --ink: #020205; /* MYRAA App.tsx:638 bg-[#020205] */
  --panel: #07080d; /* MyraaCharacter.tsx:91 / Onboarding.tsx:142 bg-[#07080d]/90-95 */
  --panel-2: #0b0c12; /* TaskHud.tsx:132 bg-[#0b0c12]/95 */
  --line: rgb(255 255 255 / 0.1); /* border-white/10 */
  --text: #ffffff; /* App.tsx:638 text-white */
  --muted: #94a3b8; /* App.tsx:839 text-slate-400 */
  --accent: rgb(99 102 241); /* App.tsx:620 charcoal triple */
  --warn: #fbbf24; /* App.tsx:1030 text-amber-400 */
  --bad: #fb7185; /* App.tsx:871 text-rose-400 */
  --ok: rgb(16 185 129); /* App.tsx:614 emerald triple */
  --mono: "JetBrains Mono", ui-monospace, Consolas, monospace;
  --sans: "Inter", "Segoe UI Variable Text", system-ui, sans-serif;
  --display: "Space Grotesk", "Inter", sans-serif;
  --glow: 0 0 12px rgb(99 102 241 / 0.5); /* App.tsx:620 drop-shadow */
  --glass-fill: rgb(255 255 255 / 0.03); /* bg-white/[0.03], SettingsPanel.tsx:76 */
  --glass-border: rgb(255 255 255 / 0.1); /* border-white/10 */
  --glass-blur: 40px; /* backdrop-blur-2xl, App.tsx:830 */
  --radius-control: 8px; /* rounded-lg */
  --radius-sheet: 16px; /* rounded-2xl, MyraaCharacter.tsx:91 */
  --radius-dialog: 24px; /* rounded-3xl, Onboarding.tsx:142 */
  --label-size: 10px; /* text-[10px] font-mono uppercase tracking-widest, SettingsPanel.tsx:72 */
  --content-width: 46rem;
  --caption-size: 1.5rem; /* text-2xl font-light */
  font-size: calc(15px * var(--text-scale, 1));
}
```

- [ ] **Step 4: Append the Chat arrangement rules**

```css
/* Chat arrangement: two stacked bands, a ledger strip, and one centred column of subtitles. */
.app[data-shell="chat"] {
  grid-template-columns: 1fr;
}
.app[data-shell="chat"] .rail {
  flex-direction: row;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.4rem;
  padding: 0.6rem 1rem;
  border-right: 0;
  border-bottom: 1px solid var(--line);
  background: color-mix(in srgb, var(--panel) 85%, transparent);
}
.app[data-shell="chat"] .rail-brand {
  margin: 0 0.6rem 0 0;
}
.app[data-shell="chat"] .rail button {
  padding: 0.25rem 0.75rem;
  border-radius: 999px;
  font-family: var(--mono);
  font-size: var(--label-size);
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.app[data-shell="chat"] .rail button.rail-active {
  color: var(--accent);
  box-shadow: var(--glow);
}
.app[data-shell="chat"] .bar {
  background: var(--panel);
  border-bottom: 1px solid var(--line);
}
.app[data-shell="chat"] .body {
  grid-template-columns: 1fr;
  grid-template-rows: auto 1fr;
}
.app[data-shell="chat"] .side {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.4rem 1rem;
  padding: 0.5rem 1rem;
  border-right: 0;
  border-bottom: 1px solid var(--line);
  background: transparent;
  overflow: visible;
}
.app[data-shell="chat"] .side h2 {
  margin: 0;
  font-size: var(--label-size);
}
.app[data-shell="chat"] .side ul {
  display: flex;
  flex-wrap: wrap;
  gap: 0.3rem;
}
.app[data-shell="chat"] .side li > button {
  width: auto;
}
.app[data-shell="chat"] .thread > * {
  width: 100%;
  max-width: var(--content-width);
  margin-inline: auto;
}
.app[data-shell="chat"] .msg {
  border-left: 0;
  padding: 0.2rem 0;
}
.app[data-shell="chat"] .msg.assistant {
  background: var(--glass-fill);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-sheet);
  padding: 0.9rem 1.1rem;
  backdrop-filter: blur(var(--glass-blur));
}
.app[data-shell="chat"] .msg.assistant .content {
  font-family: var(--display);
  font-size: var(--caption-size);
  font-weight: 300;
  line-height: 1.35;
}
.app[data-shell="chat"] .who {
  font-family: var(--mono);
  font-size: var(--label-size);
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.app[data-shell="chat"] .chain li {
  border-radius: 999px;
}
.app[data-shell="chat"] .composer {
  max-width: var(--content-width);
  margin-inline: auto;
  width: 100%;
}
.app[data-shell="chat"] .dot.on {
  box-shadow: var(--glow);
}
```

- [ ] **Step 5: Move `ConfirmProvider` inside `.app`, so the dialog inherits the shell's tokens**

```tsx
// App.tsx: the provider wraps the grid, not the other way round.
return (
  <div className="app" data-shell={shell}>
    <ConfirmProvider>
      <nav className="rail" aria-label="Kira sections">
        …
      </nav>
      <div className="pane">…</div>
    </ConfirmProvider>
  </div>
);
```

`.confirm-backdrop` is `position: fixed`, so a fixed child of a grid container creates no extra track.

- [ ] **Step 6: Run the guard and the suite**

Run: `cd kira-chat && npx vitest run src/styles.test.ts src/App.test.tsx`
Expected: `styles.test.ts` passes except the four Agent assertions (expected to fail until Task 9). Temporarily
scope the run to the chat cases with `-t chat`, which must be green:

```bash
npx vitest run src/styles.test.ts -t "chat re-declares"
```
Expected: 12 passed.

- [ ] **Step 7: Commit**

```bash
git add kira-chat/src/styles.test.ts kira-chat/src/styles.css kira-chat/src/App.tsx
git -c user.name="Kira" -c user.email="kira@localhost" commit -m "feat(chat): the Chat shell repaints from one token block, and a guard stops a shell inheriting half a palette"
```

---

### Task 6: `theme.ts` and the seven MYRAA themes

**Files:**
- Create: `kira-chat/src/theme.ts`, `kira-chat/src/theme.test.ts`
- Modify: `kira-chat/src/styles.css`, `kira-chat/src/App.tsx`

**Interfaces:**
- Produces: `THEMES` (donor order), `Theme`, `currentTheme()`, `onTheme(fn)`, `navigateTheme(t)`;
  `div.app[data-theme]`.

- [ ] **Step 1: Write the failing test**

```ts
// kira-chat/src/theme.test.ts
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { currentTheme, navigateTheme, onTheme, THEMES, type Theme } from "./theme.ts";

beforeEach(() => localStorage.clear());
afterEach(() => localStorage.clear());

describe("theme", () => {
  it("defaults to MYRAA's own default, charcoal", () => {
    expect(currentTheme()).toBe("charcoal"); // MYRAA App.tsx:305
  });

  it("keeps MYRAA's order, so the picker reads like the donor's", () => {
    expect([...THEMES]).toEqual(["violet", "crimson", "emerald", "celestial", "gold", "rose", "charcoal"]);
  });

  it("falls back on an unknown theme", () => {
    localStorage.setItem("kira.theme", "neon");
    expect(currentTheme()).toBe("charcoal");
  });

  it("notifies on change, even for the active theme, and stops after unsubscribe", () => {
    const seen: Theme[] = [];
    const off = onTheme((t) => seen.push(t));
    navigateTheme("violet");
    expect(seen).toEqual(["violet"]);
    off();
    navigateTheme("gold");
    expect(seen).toEqual(["violet"]);
  });
});
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd kira-chat && npx vitest run src/theme.test.ts` → FAIL: cannot resolve `./theme.ts`.

- [ ] **Step 3: Write the module**

```ts
// kira-chat/src/theme.ts
export const THEMES = ["violet", "crimson", "emerald", "celestial", "gold", "rose", "charcoal"] as const; // donor order, App.tsx:522
export type Theme = (typeof THEMES)[number];

const THEME_KEY = "kira.theme";
const THEME_EVENT = "kira-theme";
const DEFAULT_THEME: Theme = "charcoal"; // App.tsx:305

function parse(value: string | null): Theme {
  return value !== null && (THEMES as readonly string[]).includes(value) ? (value as Theme) : DEFAULT_THEME;
}

export function currentTheme(): Theme {
  return parse(localStorage.getItem(THEME_KEY));
}

type Listener = (theme: Theme) => void;
const listeners = new Set<Listener>();

function notify(): void {
  const theme = currentTheme();
  for (const fn of listeners) fn(theme);
}

function onStorage(event: StorageEvent): void {
  if (event.key === THEME_KEY) notify();
}

export function onTheme(fn: Listener): () => void {
  listeners.add(fn);
  if (listeners.size === 1) {
    window.addEventListener(THEME_EVENT, notify);
    window.addEventListener("storage", onStorage);
  }
  return () => {
    listeners.delete(fn);
    if (listeners.size === 0) {
      window.removeEventListener(THEME_EVENT, notify);
      window.removeEventListener("storage", onStorage);
    }
  };
}

export function navigateTheme(theme: Theme): void {
  localStorage.setItem(THEME_KEY, theme);
  window.dispatchEvent(new Event(THEME_EVENT));
}
```

- [ ] **Step 4: Append the seven theme blocks**

```css
/* MYRAA's glow triples, App.tsx:612-620. crimson and rose really do share one triple (App.tsx:613 vs :617);
   that collision is the donor's and is reproduced on purpose so a later fix is one line. */
.app[data-shell="chat"][data-theme="violet"] {
  --accent: rgb(168 85 247);
  --glow: 0 0 12px rgb(168 85 247 / 0.5);
}
.app[data-shell="chat"][data-theme="crimson"] {
  --accent: rgb(244 63 94);
  --glow: 0 0 12px rgb(244 63 94 / 0.5);
}
.app[data-shell="chat"][data-theme="emerald"] {
  --accent: rgb(16 185 129);
  --glow: 0 0 12px rgb(16 185 129 / 0.5);
}
.app[data-shell="chat"][data-theme="celestial"] {
  --accent: rgb(14 165 233);
  --glow: 0 0 12px rgb(14 165 233 / 0.5);
}
.app[data-shell="chat"][data-theme="gold"] {
  --accent: rgb(245 158 11);
  --glow: 0 0 12px rgb(245 158 11 / 0.5);
}
.app[data-shell="chat"][data-theme="rose"] {
  --accent: rgb(244 63 94);
  --glow: 0 0 12px rgb(244 63 94 / 0.5);
}
.app[data-shell="chat"][data-theme="charcoal"] {
  --accent: rgb(99 102 241);
  --glow: 0 0 12px rgb(99 102 241 / 0.5);
}
/* The ambient wash: MYRAA's per-theme gradient, two stops under the panel surface. */
.app[data-shell="chat"][data-theme="violet"] { background: linear-gradient(160deg, rgb(59 7 100 / 0.4), transparent 55%), var(--ink); }
.app[data-shell="chat"][data-theme="crimson"] { background: linear-gradient(160deg, rgb(69 10 10 / 0.4), transparent 55%), var(--ink); }
.app[data-shell="chat"][data-theme="emerald"] { background: linear-gradient(160deg, rgb(2 44 34 / 0.4), transparent 55%), var(--ink); }
.app[data-shell="chat"][data-theme="celestial"] { background: linear-gradient(160deg, rgb(8 47 73 / 0.45), transparent 55%), var(--ink); }
.app[data-shell="chat"][data-theme="gold"] { background: linear-gradient(160deg, rgb(69 26 3 / 0.3), transparent 55%), var(--ink); }
.app[data-shell="chat"][data-theme="rose"] { background: linear-gradient(160deg, rgb(76 5 25 / 0.4), transparent 55%), var(--ink); }
.app[data-shell="chat"][data-theme="charcoal"] { background: linear-gradient(160deg, rgb(15 23 42 / 0.5), transparent 55%), var(--ink); }
```

- [ ] **Step 5: Wire `data-theme` into `App.tsx`**

```tsx
import { currentTheme, onTheme, type Theme } from "./theme.ts";
const [theme, setTheme] = useState<Theme>(() => currentTheme());
useEffect(() => onTheme(setTheme), []);
// <div className="app" data-shell={shell} data-theme={theme}>
```

- [ ] **Step 6: Run**

Run: `cd kira-chat && npx vitest run src/theme.test.ts src/styles.test.ts -t "theme"`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add kira-chat/src/theme.ts kira-chat/src/theme.test.ts kira-chat/src/styles.css kira-chat/src/App.tsx
git -c user.name="Kira" -c user.email="kira@localhost" commit -m "feat(chat): seven MYRAA themes as one attribute, including the crimson/rose collision the donor ships"
```

---

### Task 7: `look.ts` — the cosmetic preferences

**Files:**
- Create: `kira-chat/src/look.ts`, `kira-chat/src/look.test.ts`
- Modify: `kira-chat/src/styles.css`, `kira-chat/src/App.tsx`

**Interfaces:**
- Produces: `Look`, `DEFAULT_LOOK`, `currentLook()`, `onLook(fn)`, `setLook(patch)`. One key: `kira.look`.
  Attributes `data-glass`, `data-motion`, `data-caption`, `data-scale`, `data-density`.

- [ ] **Step 1: Write the failing test**

```ts
// kira-chat/src/look.test.ts
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { currentLook, DEFAULT_LOOK, onLook, setLook } from "./look.ts";

beforeEach(() => localStorage.clear());
afterEach(() => localStorage.clear());

describe("look", () => {
  it("starts at the donor defaults", () => {
    expect(currentLook()).toEqual(DEFAULT_LOOK);
  });

  it("survives corrupt json without throwing", () => {
    localStorage.setItem("kira.look", "{oops");
    expect(currentLook()).toEqual(DEFAULT_LOOK);
  });

  it("fills missing fields from the defaults", () => {
    localStorage.setItem("kira.look", JSON.stringify({ glass: false }));
    expect(currentLook()).toEqual({ ...DEFAULT_LOOK, glass: false });
  });

  it("refuses an unknown enum value field by field", () => {
    localStorage.setItem("kira.look", JSON.stringify({ caption: "huge", scale: "xxl", density: "airy", motion: "maybe" }));
    expect(currentLook()).toEqual(DEFAULT_LOOK);
  });

  it("merges a patch, persists it, and notifies", () => {
    const seen: string[] = [];
    onLook((look) => seen.push(look.caption));
    setLook({ caption: "xl" });
    expect(currentLook().caption).toBe("xl");
    expect(seen).toEqual(["xl"]);
    expect(localStorage.getItem("kira.look")).toContain('"caption":"xl"');
  });
});
```

- [ ] **Step 2: Run it and watch it fail.** `npx vitest run src/look.test.ts` → cannot resolve.

- [ ] **Step 3: Write the module**

```ts
// kira-chat/src/look.ts
export type Caption = "s" | "m" | "l" | "xl";
export type Scale = "s" | "m" | "l";
export type Density = "compact" | "cozy";

export interface Look {
  glass: boolean;
  motion: boolean;
  caption: Caption;
  scale: Scale;
  density: Density;
}

export const DEFAULT_LOOK: Look = { glass: true, motion: true, caption: "m", scale: "m", density: "compact" };

const LOOK_KEY = "kira.look";
const LOOK_EVENT = "kira-look";

function oneOf<T extends string>(value: unknown, allowed: readonly T[], fallback: T): T {
  return typeof value === "string" && (allowed as readonly string[]).includes(value) ? (value as T) : fallback;
}

function bool(value: unknown, fallback: boolean): boolean {
  return typeof value === "boolean" ? value : fallback;
}

/** One JSON value, merged over the defaults, so a partial or corrupt payload still yields a complete Look. */
export function currentLook(): Look {
  const raw = localStorage.getItem(LOOK_KEY);
  if (!raw) return DEFAULT_LOOK;
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return DEFAULT_LOOK;
  }
  if (typeof parsed !== "object" || parsed === null) return DEFAULT_LOOK;
  const value = parsed as Record<string, unknown>;
  return {
    glass: bool(value.glass, DEFAULT_LOOK.glass),
    motion: bool(value.motion, DEFAULT_LOOK.motion),
    caption: oneOf(value.caption, ["s", "m", "l", "xl"] as const, DEFAULT_LOOK.caption),
    scale: oneOf(value.scale, ["s", "m", "l"] as const, DEFAULT_LOOK.scale),
    density: oneOf(value.density, ["compact", "cozy"] as const, DEFAULT_LOOK.density),
  };
}

type Listener = (look: Look) => void;
const listeners = new Set<Listener>();

function notify(): void {
  const look = currentLook();
  for (const fn of listeners) fn(look);
}

function onStorage(event: StorageEvent): void {
  if (event.key === LOOK_KEY) notify();
}

export function onLook(fn: Listener): () => void {
  listeners.add(fn);
  if (listeners.size === 1) {
    window.addEventListener(LOOK_EVENT, notify);
    window.addEventListener("storage", onStorage);
  }
  return () => {
    listeners.delete(fn);
    if (listeners.size === 0) {
      window.removeEventListener(LOOK_EVENT, notify);
      window.removeEventListener("storage", onStorage);
    }
  };
}

export function setLook(patch: Partial<Look>): void {
  localStorage.setItem(LOOK_KEY, JSON.stringify({ ...currentLook(), ...patch }));
  window.dispatchEvent(new Event(LOOK_EVENT));
}
```

- [ ] **Step 4: Append the look rules**

```css
/* Look preferences. Each attribute flips one token; nothing here is a second code path. */
.app[data-glass="off"] {
  --glass-fill: transparent;
  --glass-border: var(--line);
  --glass-blur: 0px;
}
.app[data-motion="off"] *,
.app[data-motion="off"] *::before,
.app[data-motion="off"] *::after {
  transition: none !important;
  animation: none !important;
}
@media (prefers-reduced-motion: reduce) {
  .app * {
    transition: none !important;
    animation: none !important;
  }
}
.app[data-caption="s"] { --caption-size: 1.25rem; }
.app[data-caption="m"] { --caption-size: 1.5rem; }
.app[data-caption="l"] { --caption-size: 1.875rem; }
.app[data-caption="xl"] { --caption-size: 2.25rem; }
.app { --text-scale: 1; } /* the scale attribute sets the multiplier only */
.app[data-scale="s"] { --text-scale: 0.95; }
.app[data-scale="l"] { --text-scale: 1.1; }
.app[data-shell="agent"][data-density="cozy"] { font-size: calc(15px * var(--text-scale, 1)); }
```

Ordering matters: `--text-scale` must be declared before the shell blocks read it, so put this block **above**
the `[data-shell]` blocks. That is the one insert in this task that is not an append.

- [ ] **Step 5: Wire the attributes in `App.tsx`**

```tsx
import { currentLook, onLook, type Look } from "./look.ts";
const [look, setLookState] = useState<Look>(() => currentLook());
useEffect(() => onLook(setLookState), []);
// <div
//   className="app"
//   data-shell={shell}
//   data-theme={theme}
//   data-glass={look.glass ? "on" : "off"}
//   data-motion={look.motion ? "on" : "off"}
//   data-caption={look.caption}
//   data-scale={look.scale}
//   data-density={look.density}
// >
```
The `--text-scale` variables come from the attribute rules; no inline style is needed.

- [ ] **Step 6: Run.** `npx vitest run src/look.test.ts` → 5 passed.

- [ ] **Step 7: Commit**

```bash
git add kira-chat/src/look.ts kira-chat/src/look.test.ts kira-chat/src/styles.css kira-chat/src/App.tsx
git -c user.name="Kira" -c user.email="kira@localhost" commit -m "feat(chat): cosmetic preferences as one merged json value, so a corrupt key cannot half-apply"
```

---

### Task 8: The options panel — MYRAA's pattern, Kira's options

**Files:**
- Create: `kira-chat/src/options-panel.tsx`, `kira-chat/src/options-panel.test.tsx`
- Modify: `kira-chat/src/App.tsx`, `kira-chat/src/styles.css`

**Interfaces:**
- Consumes: `Shell`, `Theme`/`navigateTheme`, `Look`/`setLook`, `ChatState` is **not** consumed here (panel takes
  only what it shows: `health`, `sessions.length`, `sessionId`, `model`, `mode`).
- Produces: `<OptionsPanel open onClose shell theme look mode setMode models model setModel health sessionId sessions onRefresh onDisconnect />`

- [ ] **Step 1: Write the failing test**

```tsx
// kira-chat/src/options-panel.test.tsx
import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { OptionsPanel } from "./options-panel.tsx";
import { DEFAULT_LOOK } from "./look.ts";

function mount(overrides: Partial<Parameters<typeof OptionsPanel>[0]> = {}) {
  const props: Parameters<typeof OptionsPanel>[0] = {
    open: true,
    onClose: vi.fn(),
    shell: "chat",
    theme: "charcoal",
    look: DEFAULT_LOOK,
    mode: "AUTO",
    setMode: vi.fn(),
    models: [{ id: "mini", provider: "mock", tier: "fast" } as never],
    model: "mini",
    setModel: vi.fn(),
    health: null,
    sessionId: null,
    sessionCount: 0,
    onRefresh: vi.fn(),
    onDisconnect: vi.fn(),
    ...overrides,
  };
  return { props, view: render(<OptionsPanel {...props} />) };
}

beforeEach(() => localStorage.clear());

describe("options panel", () => {
  it("opens on Theme with the donor's seven themes, in donor order", () => {
    mount();
    const tabs = screen.getAllByRole("tab").map((t) => t.textContent);
    expect(tabs).toEqual(["Theme", "Mode", "Look", "Status"]);
    const tiles = within(screen.getByRole("group", { name: "theme" })).getAllByRole("radio");
    expect(tiles.map((t) => t.textContent)).toEqual([
      "violet", "crimson", "emerald", "celestial", "gold", "rose", "charcoal",
    ]);
    expect(screen.getByRole("radio", { name: "charcoal" }).getAttribute("aria-checked")).toBe("true");
  });

  it("writes the chosen theme to kira.theme", () => {
    mount();
    fireEvent.click(screen.getByRole("radio", { name: "celestial" }));
    expect(localStorage.getItem("kira.theme")).toBe("celestial");
  });

  it("shows routing mode and models as tiles, and writes the look switches", () => {
    const { props } = mount();
    fireEvent.click(screen.getByRole("tab", { name: /mode/i }));
    fireEvent.click(screen.getByRole("radio", { name: "POWERFUL" }));
    expect(props.setMode).toHaveBeenCalledWith("POWERFUL");
    fireEvent.click(screen.getByRole("button", { name: "use model mini mock fast" }));
    expect(props.setModel).toHaveBeenCalledWith("mini");

    fireEvent.click(screen.getByRole("tab", { name: /look/i }));
    fireEvent.click(screen.getByRole("switch", { name: "glass" }));
    expect(JSON.parse(localStorage.getItem("kira.look")!).glass).toBe(false);
    fireEvent.click(screen.getByRole("radio", { name: "XL" }));
    expect(JSON.parse(localStorage.getItem("kira.look")!).caption).toBe("xl");
  });

  it("shows the session and the provider ledger on Status", () => {
    mount({
      sessionId: "sess-abcdef12",
      sessionCount: 3,
      health: {
        providers: { groq: { failures: 0, successes: 4, cooling_s: 0, last_reason: "" } },
        configured: [{ name: "groq", kind: "openai_compat", tier: "fast", priority: 50, models: ["mini"], key_present: true }],
      } as never,
    });
    fireEvent.click(screen.getByRole("tab", { name: /status/i }));
    expect(screen.getByText(/sess-abcd/)).toBeTruthy();
    expect(screen.getByText("groq")).toBeTruthy();
    expect(screen.getByText("key ok")).toBeTruthy();
    expect(screen.getByText("4✓ 0✗")).toBeTruthy();
  });

  it("cancels with Escape and closes with the ✕", () => {
    const { props } = mount();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(props.onClose).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "close settings" }));
    expect(props.onClose).toHaveBeenCalledTimes(2);
  });

  it("renders nothing when closed", () => {
    const { view } = mount({ open: false });
    expect(view.container.textContent).toBe("");
  });
});
```

- [ ] **Step 2: Run it and watch it fail.** `npx vitest run src/options-panel.test.tsx` → cannot resolve.

- [ ] **Step 3: Write the component**

```tsx
// kira-chat/src/options-panel.tsx
import { useEffect, useRef, useState } from "react";
import { Activity, Palette, Route, Sparkles, X } from "lucide-react";
import type { HealthResponse, Mode, ModelInfo } from "./contracts.ts";
import { setLook, type Caption, type Look } from "./look.ts";
import type { Shell } from "./shell.ts";
import { navigateTheme, THEMES, type Theme } from "./theme.ts";
import { MODES } from "./contracts.ts";

const TABS = [
  { id: "theme", label: "Theme", icon: Palette },
  { id: "mode", label: "Mode", icon: Route },
  { id: "look", label: "Look", icon: Sparkles },
  { id: "status", label: "Status", icon: Activity },
] as const;
type Tab = (typeof TABS)[number]["id"];

const CAPTIONS: Caption[] = ["s", "m", "l", "xl"];
const CAPTION_LABELS: Record<Caption, string> = { s: "S", m: "M", l: "L", xl: "XL" };

export interface OptionsPanelProps {
  open: boolean;
  onClose(): void;
  shell: Shell;
  theme: Theme;
  look: Look;
  mode: Mode;
  setMode(mode: Mode): void;
  models: ModelInfo[];
  model: string;
  setModel(model: string): void;
  health: HealthResponse | null;
  sessionId: string | null;
  sessionCount: number;
  onRefresh(): void;
  onDisconnect(): void;
}

/**
 * MYRAA's overlay panel, carrying the options Kira actually has. The pattern is the donor's
 * (SettingsPanel.tsx: section list with icons, mono group headings over a divided glass list,
 * role="switch" toggles, a role="radio" segmented control, a mono status pill); the contents are ours.
 */
export function OptionsPanel(props: OptionsPanelProps) {
  const { open, onClose } = props;
  const [tab, setTab] = useState<Tab>("theme");
  const panelRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    panelRef.current?.focus();
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const cooling = props.health
    ? Object.values(props.health.providers).filter((state) => state.cooling_s > 0).length
    : 0;

  return (
    <div className="options-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="options-panel" role="dialog" aria-modal="true" aria-label="settings" tabIndex={-1} ref={panelRef}>
        <header className="options-head">
          <span className="options-badge">K</span>
          <div>
            <h2>Kira</h2>
            <p className="status-pill">
              <span className={`dot ${props.sessionId || props.sessionCount > 0 ? "on" : "off"}`} />
              {cooling > 0 ? `${cooling} provider${cooling === 1 ? "" : "s"} cooling` : "Local engine"}
            </p>
          </div>
          <span className="spacer" />
          <button type="button" className="icon-button" aria-label="close settings" onClick={onClose}>
            <X size={16} />
          </button>
        </header>

        <div className="options-tabs" role="tablist" aria-label="settings sections">
          {TABS.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              type="button"
              role="tab"
              id={`options-tab-${id}`}
              aria-selected={tab === id}
              aria-controls={`options-tabpanel-${id}`}
              className={tab === id ? "active" : ""}
              onClick={() => setTab(id)}
            >
              <Icon size={14} />
              {label}
            </button>
          ))}
        </div>

        <div className="options-body" role="tabpanel" id={`options-tabpanel-${tab}`} aria-labelledby={`options-tab-${tab}`}>
          {tab === "theme" && <ThemeTab theme={props.theme} />}
          {tab === "mode" && <ModeTab {...props} />}
          {tab === "look" && <LookTab look={props.look} shell={props.shell} />}
          {tab === "status" && <StatusTab {...props} />}
        </div>

        <footer className="options-foot">
          <button type="button" onClick={props.onRefresh}>
            refresh
          </button>
          <button type="button" className="danger" onClick={props.onDisconnect}>
            disconnect
          </button>
        </footer>
      </div>
    </div>
  );
}

function Group({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section className="options-group">
      <h3>{title}</h3>
      {hint && <p className="options-hint">{hint}</p>}
      {children}
    </section>
  );
}

function ThemeTab({ theme }: { theme: Theme }) {
  return (
    <Group title="Theme" hint="MYRAA's seven, including its own default.">
      <div className="tiles" role="group" aria-label="theme">
        {THEMES.map((name) => (
          <button
            key={name}
            type="button"
            role="radio"
            aria-checked={name === theme}
            className={`tile tile-${name}`}
            onClick={() => navigateTheme(name)}
          >
            {name}
          </button>
        ))}
      </div>
    </Group>
  );
}

function ModeTab({ mode, setMode, models, model, setModel }: OptionsPanelProps) {
  return (
    <>
      <Group title="Routing mode" hint="A tier filter over your own providers. Never a hidden catalogue.">
        <div className="segmented" role="group" aria-label="routing mode">
          {MODES.map((m) => (
            <button key={m} type="button" role="radio" aria-checked={m === mode} onClick={() => setMode(m)}>
              {m}
            </button>
          ))}
        </div>
      </Group>
      <Group title="Model" hint={`${models.length} configured`}>
        <div className="tiles" role="group" aria-label="model">
          {models.map((m) => (
            <button
              key={`${m.provider}-${m.id}`}
              type="button"
              role="radio"
              aria-checked={m.id === model}
              aria-label={`use model ${m.id} ${m.provider} ${m.tier}`}
              className="tile"
              onClick={() => setModel(m.id)}
            >
              <strong>{m.id}</strong>
              <span>
                {m.provider} · {m.tier}
              </span>
            </button>
          ))}
          {models.length === 0 && <p className="empty">no models configured</p>}
        </div>
      </Group>
    </>
  );
}

function LookTab({ look, shell }: { look: Look; shell: Shell }) {
  return (
    <>
      <Group title="Caption size" hint="How large the streamed answer reads.">
        <div className="segmented" role="group" aria-label="caption size">
          {CAPTIONS.map((size) => (
            <button
              key={size}
              type="button"
              role="radio"
              aria-checked={look.caption === size}
              onClick={() => setLook({ caption: size })}
            >
              {CAPTION_LABELS[size]}
            </button>
          ))}
        </div>
      </Group>
      <Group title="Surface">
        <div className="rows">
          <ToggleRow
            label="glass"
            description="Frosted sheets behind answers, dialogs and panels."
            checked={look.glass}
            onChange={(glass) => setLook({ glass })}
          />
          <ToggleRow
            label="animations"
            description="Motion and transitions. Off follows your system's reduced-motion setting."
            checked={look.motion}
            onChange={(motion) => setLook({ motion })}
          />
          {shell === "agent" && (
            <ToggleRow
              label="cozy density"
              description="15px base instead of the workspace's 13px."
              checked={look.density === "cozy"}
              onChange={(cozy) => setLook({ density: cozy ? "cozy" : "compact" })}
            />
          )}
        </div>
      </Group>
    </>
  );
}

function ToggleRow({
  label,
  description,
  checked,
  onChange,
}: {
  label: string;
  description: string;
  checked: boolean;
  onChange(checked: boolean): void;
}) {
  return (
    <div className="row">
      <div>
        <div className="row-label">{label}</div>
        <div className="row-hint">{description}</div>
      </div>
      <button type="button" role="switch" aria-checked={checked} aria-label={label} onClick={() => onChange(!checked)}>
        <span />
      </button>
    </div>
  );
}

function StatusTab({ health, sessionId, sessionCount }: OptionsPanelProps) {
  return (
    <>
      <Group title="Session" hint="The engine owns history; this is the session it is appending to.">
        <div className="rows">
          <div className="row">
            <div>
              <div className="row-label">{sessionId ? sessionId.slice(0, 8) : "no session yet"}</div>
              <div className="row-hint">{sessionCount} stored session{sessionCount === 1 ? "" : "s"}</div>
            </div>
          </div>
        </div>
      </Group>
      <Group title="Providers" hint="Key presence and the router's ledger.">
        <div className="rows">
          {!health && <p className="empty">not read yet</p>}
          {health?.configured.map((provider) => {
            const state = health.providers[provider.name];
            return (
              <div className="row" key={provider.name}>
                <div>
                  <div className="row-label mono">{provider.name}</div>
                  <div className="row-hint">
                    {state ? `${state.successes}✓ ${state.failures}✗${state.cooling_s ? ` · ${state.cooling_s}s` : ""}` : "idle"}
                  </div>
                </div>
                <span className={`pill ${provider.key_present ? "pill-ok" : "pill-warn"}`}>
                  {provider.key_present ? "key ok" : "no key"}
                </span>
              </div>
            );
          })}
        </div>
      </Group>
    </>
  );
}
```

- [ ] **Step 4: Style the panel (append to `styles.css`)**

```css
/* MYRAA's overlay panel: backdrop, glass sheet, badge header, icon tab row, grouped rows, footer pair. */
.options-backdrop {
  position: fixed;
  inset: 0;
  z-index: 30;
  display: flex;
  align-items: flex-start;
  justify-content: flex-start;
  padding: clamp(0.5rem, 3vw, 2.5rem);
  background: rgb(0 0 0 / 0.35);
  overflow: auto;
}
.options-panel {
  width: min(26rem, 100%);
  max-height: calc(100vh - 2rem);
  display: flex;
  flex-direction: column;
  border: 1px solid var(--glass-border, var(--line));
  border-radius: var(--radius-dialog, 12px);
  background: color-mix(in srgb, var(--panel) 92%, transparent);
  backdrop-filter: blur(var(--glass-blur, 0px));
  box-shadow: 0 24px 64px rgb(0 0 0 / 0.45);
  overflow: hidden;
}
.options-head {
  display: flex;
  align-items: center;
  gap: 0.7rem;
  padding: 0.9rem 1rem;
}
.options-head h2 {
  margin: 0;
  font-family: var(--display);
  font-size: 1.1rem;
  letter-spacing: 0.02em;
}
.options-badge {
  width: 2.2rem;
  height: 2.2rem;
  display: grid;
  place-items: center;
  border-radius: calc(var(--radius-control, 6px) + 4px);
  background: linear-gradient(140deg, var(--accent), color-mix(in srgb, var(--accent) 40%, var(--ink)));
  color: var(--ink);
  font-family: var(--display);
  font-size: 1.1rem;
  font-weight: 600;
}
.status-pill {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  margin: 0.15rem 0 0;
  font-family: var(--mono);
  font-size: 9px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--muted);
}
.options-tabs {
  display: flex;
  gap: 0.25rem;
  padding: 0 0.75rem 0.75rem;
  border-bottom: 1px solid var(--line);
}
.options-tabs button {
  flex: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.35rem;
  padding: 0.4rem 0.5rem;
  border-radius: var(--radius-control, 6px);
  background: transparent;
  border: 1px solid transparent;
  font-size: 0.75rem;
  color: var(--muted);
}
.options-tabs button.active {
  color: var(--text);
  background: color-mix(in srgb, var(--accent) 22%, transparent);
  border-color: color-mix(in srgb, var(--accent) 35%, transparent);
}
.options-body {
  padding: 0.9rem 1rem 1rem;
  overflow: auto;
  display: grid;
  gap: 1rem;
}
.options-group h3 {
  margin: 0 0 0.15rem;
  font-family: var(--mono);
  font-size: var(--label-size, 10px);
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--muted);
}
.options-hint {
  margin: 0 0 0.5rem;
  font-size: 11px;
  color: color-mix(in srgb, var(--muted) 80%, transparent);
}
.tiles {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(6.5rem, 1fr));
  gap: 0.4rem;
}
.tile {
  display: grid;
  gap: 0.1rem;
  justify-items: start;
  padding: 0.5rem 0.6rem;
  border-radius: var(--radius-sheet, 10px);
  border: 1px solid var(--line);
  background: var(--panel-2);
  font-size: 0.78rem;
  text-align: left;
}
.tile span {
  font-family: var(--mono);
  font-size: 10px;
  color: var(--muted);
}
.tile[aria-checked="true"] {
  border-color: var(--accent);
  box-shadow: inset 0 0 0 1px var(--accent);
}
.tile-violet { background: linear-gradient(140deg, rgb(168 85 247 / 0.35), var(--panel-2)); }
.tile-crimson { background: linear-gradient(140deg, rgb(244 63 94 / 0.35), var(--panel-2)); }
.tile-emerald { background: linear-gradient(140deg, rgb(16 185 129 / 0.35), var(--panel-2)); }
.tile-celestial { background: linear-gradient(140deg, rgb(14 165 233 / 0.35), var(--panel-2)); }
.tile-gold { background: linear-gradient(140deg, rgb(245 158 11 / 0.35), var(--panel-2)); }
.tile-rose { background: linear-gradient(140deg, rgb(251 113 133 / 0.35), var(--panel-2)); }
.tile-charcoal { background: linear-gradient(140deg, rgb(99 102 241 / 0.35), var(--panel-2)); }
.segmented {
  display: flex;
  gap: 0.25rem;
  padding: 0.2rem;
  border: 1px solid var(--line);
  border-radius: var(--radius-control, 6px);
  background: var(--panel-2);
}
.segmented button {
  flex: 1;
  padding: 0.3rem 0.4rem;
  border: 0;
  border-radius: calc(var(--radius-control, 6px) - 2px);
  background: transparent;
  font-family: var(--mono);
  font-size: 11px;
  color: var(--muted);
}
.segmented button[aria-checked="true"] {
  background: var(--accent);
  color: var(--ink);
}
.rows {
  display: grid;
  border: 1px solid var(--line);
  border-radius: var(--radius-sheet, 10px);
  background: var(--glass-fill, transparent);
  overflow: hidden;
}
.row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding: 0.6rem 0.75rem;
}
.row + .row {
  border-top: 1px solid color-mix(in srgb, var(--line) 60%, transparent);
}
.row-label {
  font-size: 0.8rem;
  color: var(--text);
}
.row-hint {
  margin-top: 0.1rem;
  font-size: 11px;
  line-height: 1.35;
  color: var(--muted);
}
.row [role="switch"] {
  flex: none;
  width: 2.4rem;
  height: 1.25rem;
  padding: 0.1rem;
  border-radius: 999px;
  border: 1px solid var(--line);
  background: color-mix(in srgb, var(--line) 60%, transparent);
  display: flex;
  align-items: center;
}
.row [role="switch"][aria-checked="true"] {
  background: var(--accent);
  border-color: var(--accent);
}
.row [role="switch"] span {
  width: 0.9rem;
  height: 0.9rem;
  border-radius: 50%;
  background: var(--text);
  transition: transform 160ms ease;
}
.row [role="switch"][aria-checked="true"] span {
  transform: translateX(1.1rem);
}
.pill {
  flex: none;
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 0.05rem 0.5rem;
  font-family: var(--mono);
  font-size: 9px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.pill-ok { color: var(--ok, var(--accent)); border-color: color-mix(in srgb, var(--ok, var(--accent)) 45%, transparent); }
.pill-warn { color: var(--warn); border-color: color-mix(in srgb, var(--warn) 45%, transparent); }
.options-foot {
  display: flex;
  gap: 0.5rem;
  padding: 0.7rem 1rem 0.9rem;
  border-top: 1px solid var(--line);
}
.options-foot button {
  flex: 1;
}
```

- [ ] **Step 5: Mount it from `App.tsx`**

```tsx
const [panelOpen, setPanelOpen] = useState(false);
// in the existing `.bar`, before the spacer:
<button type="button" aria-expanded={panelOpen} onClick={() => setPanelOpen((open) => !open)}>
  settings
</button>
// after the screen branch, still inside `.pane`? No — inside `.app`, after </div> of .pane:
<OptionsPanel
  open={panelOpen}
  onClose={() => setPanelOpen(false)}
  shell={shell}
  theme={theme}
  look={look}
  mode={mode}
  setMode={setMode}
  models={models}
  model={model}
  setModel={setModel}
  health={null}
  sessionId={null}
  sessionCount={0}
  onRefresh={voidRefresh}
  onDisconnect={() => {
    localStorage.removeItem(TOKEN_KEY);
    setToken("");
    setConnected(false);
    setPanelOpen(false);
  }}
/>
```
`health`/`sessionId`/`sessionCount` become real in Task 11, when `useChat` returns them to `App`. Until then the
panel's Status tab says `not read yet`, which is true.

- [ ] **Step 6: Run.** `npx tsc --noEmit && npx vitest run src/options-panel.test.tsx`
Expected: 6 passed.

- [ ] **Step 7: Commit**

```bash
git add kira-chat/src/options-panel.tsx kira-chat/src/options-panel.test.tsx kira-chat/src/App.tsx kira-chat/src/styles.css
git -c user.name="Kira" -c user.email="kira@localhost" commit -m "feat(chat): MYRAA's panel pattern carrying real options — themes, modes, look switches, ledger"
```

---

### Task 9: The Agent shell's tokens and geometry

**Files:**
- Modify: `kira-chat/src/styles.css`

**Interfaces:**
- Consumes: `styles.test.ts` from Task 5. Produces: `[data-shell="agent"]`; every later agent task styles inside it.

- [ ] **Step 1: Run the failing half of the guard**

Run: `cd kira-chat && npx vitest run src/styles.test.ts`
Expected: FAIL — `no .app[data-shell="agent"] block in styles.css` (12 cases).

- [ ] **Step 2: Append the Agent token block**

```css
/* Agent shell — ALTREX's geometry, PocketStrike's glass. Controls take ALTREX's 6/8; glass sheets take
   PocketStrike's 14/20. Averaging them would match neither donor (spec §5). */
.app[data-shell="agent"] {
  --ink: #09090b; /* PocketStrike app_palette.dart:12 darkBaseAlt */
  --panel: #161616; /* ALTREX styles.css:8 --bg-app */
  --panel-2: #1b1b1b; /* :9 --bg-sidebar */
  --line: #2b2b2b; /* :13 */
  --line-strong: #3b3b3b; /* :14 */
  --text: #eeeeec; /* :15 */
  --muted: #858581; /* :17 */
  --accent: #d7d7cc; /* :18 */
  --warn: #c8b382; /* :20 */
  --bad: #d89993; /* :21 */
  --ok: #91b99c; /* :19 */
  --mono: "JetBrains Mono", Consolas, monospace; /* :48 */
  --sans: "Inter", "Segoe UI", system-ui, sans-serif; /* :5 */
  --display: "Inter", "Segoe UI", system-ui, sans-serif; /* ALTREX has one family — :5 */
  --glow: 0 0 10px rgb(215 215 204 / 0.25);
  --glass-fill: rgb(255 255 255 / 0.07); /* PocketStrike glass_tokens.dart:44 */
  --glass-border: rgb(255 255 255 / 0.15); /* :45 */
  --glass-blur: 20px; /* :46 blurSigma */
  --radius-control: 6px; /* ALTREX :22 --radius-sm */
  --radius-sheet: 14px; /* PocketStrike :48 radiusMd */
  --radius-dialog: 20px; /* :49 radiusLg */
  --label-size: 11px; /* ALTREX :50 small/.metadata */
  --content-width: 780px; /* :31 --content-width */
  --caption-size: 1rem;
  font-size: calc(13px * var(--text-scale, 1)); /* :7 */
}
```

- [ ] **Step 3: Append the Agent geometry**

```css
/* ALTREX's shell: a 240px sidebar (56px collapsed), a 48px top bar, a 780px conversation column,
   and the work panel as the third column. styles.css:56-57 for the donor numbers. */
.app[data-shell="agent"] {
  grid-template-columns: 240px minmax(0, 1fr) auto;
  gap: 0;
}
.app[data-shell="agent"] .rail {
  background: var(--panel-2);
  border-right: 1px solid var(--line);
  padding: 0.5rem 0.6rem 0.9rem;
}
.app[data-shell="agent"] .rail-brand {
  min-height: 64px; /* ALTREX styles.css:59 */
  font-family: var(--sans);
  font-size: 13px;
  font-weight: 620;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  margin-bottom: 0.2rem;
}
.app[data-shell="agent"] .rail button {
  min-height: 36px; /* :62 */
  display: flex;
  align-items: center;
  gap: 0.6rem;
  padding: 0 0.7rem;
  border-radius: var(--radius-control);
  color: var(--text);
}
.app[data-shell="agent"] .rail button:not(.rail-active) {
  color: var(--text);
  opacity: 0.78;
}
.app[data-shell="agent"] .rail button:hover:not(:disabled) {
  background: #2c2c2c; /* :11 --bg-surface-hover */
  border-color: transparent;
}
.app[data-shell="agent"] .rail button.rail-active {
  background: #222; /* :10 --bg-surface */
  border-color: var(--line);
  color: var(--text);
}
.app[data-shell="agent"] .bar {
  height: 48px;
  padding: 0 0.9rem;
  background: var(--panel);
  border-bottom: 1px solid var(--line);
}
.app[data-shell="agent"] .body {
  grid-template-columns: 15rem minmax(0, 1fr);
}
.app[data-shell="agent"] .side {
  background: var(--panel);
  border-right: 1px solid var(--line);
}
.app[data-shell="agent"] .thread {
  padding: 1.1rem 1.4rem 0;
}
.app[data-shell="agent"] .thread > * {
  max-width: var(--content-width); /* ALTREX conversation-column, styles.css:154 */
  width: 100%;
}
.app[data-shell="agent"] .msg {
  border-left-width: 2px;
  border-radius: 0 var(--radius-control) var(--radius-control) 0;
}
.app[data-shell="agent"] .msg.assistant {
  background: var(--glass-fill);
  border: 1px solid var(--glass-border);
  border-left: 2px solid var(--accent);
  border-radius: 0 var(--radius-sheet) var(--radius-sheet) 0;
  backdrop-filter: blur(var(--glass-blur));
}
.app[data-shell="agent"] .composer textarea {
  background: #272727; /* ALTREX :12 --bg-input */
  border-color: var(--line-strong);
  border-radius: var(--radius-control);
}
.app[data-shell="agent"] .chain li {
  border-radius: 999px;
  background: var(--panel-2);
}
.app[data-shell="agent"] .screen {
  max-width: var(--content-width);
}
```

- [ ] **Step 4: Run the guard**

Run: `cd kira-chat && npx vitest run src/styles.test.ts`
Expected: all cases pass (12 chat + 12 agent + theme cases).

- [ ] **Step 5: Commit**

```bash
git add kira-chat/src/styles.css
git -c user.name="Kira" -c user.email="kira@localhost" commit -m "feat(chat): the Agent shell's tokens and geometry, with the radius conflict resolved rather than averaged"
```

---

### Task 10: Sidebar collapse

**Files:**
- Modify: `kira-chat/src/App.tsx`, `kira-chat/src/styles.css`, `kira-chat/src/App.test.tsx`

**Interfaces:**
- Consumes: `data-shell`. Produces: `data-sidebar="collapsed|expanded"`, key `kira.sidebar`, button
  `aria-label="collapse sidebar" | "expand sidebar"`.

- [ ] **Step 1: Write the failing test**

```ts
it("collapses the agent sidebar to a rail and remembers the choice", async () => {
  localStorage.setItem("kira.shell", "agent");
  const engine = fakeEngine({ models: MODELS, health: HEALTH });
  connectedTo(engine);
  const view = render(<App />);
  await screen.findByRole("group", { name: "surface" });

  expect(view.container.querySelector(".app")?.getAttribute("data-sidebar")).toBe("expanded");
  fireEvent.click(screen.getByRole("button", { name: "collapse sidebar" }));
  expect(view.container.querySelector(".app")?.getAttribute("data-sidebar")).toBe("collapsed");
  expect(localStorage.getItem("kira.sidebar")).toBe("collapsed");
  expect(screen.getByRole("button", { name: "expand sidebar" })).toBeTruthy();
});

it("has no collapse control in the chat shell", async () => {
  localStorage.setItem("kira.shell", "chat");
  const engine = fakeEngine({ models: MODELS, health: HEALTH });
  connectedTo(engine);
  render(<App />);
  await screen.findByRole("group", { name: "surface" });
  expect(screen.queryByRole("button", { name: /sidebar/ })).toBeNull();
});
```

- [ ] **Step 2: Run and watch it fail** — `getAttribute` returns `null`, so FAIL.

- [ ] **Step 3: Implement in `App.tsx`**

```tsx
const SIDEBAR_KEY = "kira.sidebar";

const [collapsed, setCollapsed] = useState(() => localStorage.getItem(SIDEBAR_KEY) === "collapsed");

function toggleSidebar() {
  setCollapsed((prev) => {
    localStorage.setItem(SIDEBAR_KEY, prev ? "expanded" : "collapsed");
    return !prev;
  });
}

// on the .app div:
// data-sidebar={collapsed ? "collapsed" : "expanded"}

// inside .rail-brand, after <strong>Kira</strong>:
{shell === "agent" && (
  <button
    type="button"
    className="sidebar-toggle"
    aria-pressed={collapsed}
    aria-label={collapsed ? "expand sidebar" : "collapse sidebar"}
    onClick={toggleSidebar}
  >
    {collapsed ? <PanelLeftOpen size={15} /> : <PanelLeftClose size={15} />}
  </button>
)}
```

Wrap each nav label so the collapsed rail can hide it:

```tsx
<button …>
  <NavIcon route={item} />
  <span className="rail-label">{NAV_LABELS[item]}</span>
</button>
```

- [ ] **Step 4: Append the collapse rules**

```css
.app[data-shell="agent"][data-sidebar="collapsed"] {
  grid-template-columns: 56px minmax(0, 1fr) auto; /* ALTREX styles.css:57 */
}
.app[data-shell="agent"][data-sidebar="collapsed"] .rail-brand {
  justify-content: center;
  padding: 0;
}
.app[data-shell="agent"][data-sidebar="collapsed"] .rail-brand strong { display: none; }
.app[data-shell="agent"][data-sidebar="collapsed"] .rail-label { display: none; }
.app[data-shell="agent"][data-sidebar="collapsed"] .rail button {
  justify-content: center;
  padding: 0;
}
.sidebar-toggle {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0.25rem;
  background: transparent;
  border-color: transparent;
}
```

- [ ] **Step 5: Implement `NavIcon` (temporary, text-only until Task 16)**

```tsx
function NavIcon({ route }: { route: Route }) {
  return <span className="nav-icon" aria-hidden="true">{NAV_GLYPHS[route]}</span>;
}
const NAV_GLYPHS: Record<Route, string> = { chat: "•", overview: "◇", providers: "▤", models: "▦", sessions: "≡" };
```
Task 16 replaces the glyphs with lucide icons; the markup and tests stay.

- [ ] **Step 6: Run** — `npx vitest run src/App.test.tsx` → the two new cases pass; the every-route test still
finds `Kira` (the strong is only hidden by CSS, still in the DOM).

- [ ] **Step 7: Commit**

```bash
git add kira-chat/src/App.tsx kira-chat/src/styles.css kira-chat/src/App.test.tsx
git -c user.name="Kira" -c user.email="kira@localhost" commit -m "feat(chat): the agent sidebar collapses to ALTREX's 56px rail, and the choice survives a reload"
```

---

### Task 11: Lift the chat state above the shell branch

**Files:**
- Create: `kira-chat/src/useChat.ts`, `kira-chat/src/useChat.test.tsx`
- Modify: `kira-chat/src/screens/ChatScreen.tsx`, `kira-chat/src/App.tsx`, `kira-chat/src/fake-engine.ts`,
  `kira-chat/src/App.test.tsx`

**Interfaces:**
- Produces: `useChat({client, model, mode, connected, watching}) → ChatState` with
  `{entries, sessionId, sessions, health, prompt, setPrompt, busy, live, ledgerError, send, stop, openSession, pullLedger}`;
  `Entry` moves here. `ChatScreen` takes `{chat, shell, models, mode}`.

- [ ] **Step 1: Give the fake engine a stream that stays open**

```ts
// fake-engine.ts: add to FakeOptions
holdOpen?: boolean;

// inside fakeEngine(), after `const calls: Recorded[] = [];`
let release: (() => void) | null = null;

// replace `function sse(chunks)` usage for the held case with a local stream:
function sse(chunks: unknown[], hold: boolean): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(`data: ${JSON.stringify(chunk)}\n\n`));
      if (hold) release = () => controller.close();
      else controller.close();
    },
  });
  return new Response(body, { status: 200, headers: { "content-type": "text/event-stream" } });
}
// in the /chat/completions branch: return sse(options.chunks ?? [], options.holdOpen ?? false);
// in the returned object: return { fetch: fetchImpl as unknown as typeof fetch, calls, releaseStream: () => release?.() };
```

- [ ] **Step 2: Write the failing test**

```tsx
// kira-chat/src/useChat.test.tsx
import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { chain, delta, done, fakeEngine } from "./fake-engine.ts";
import { useChat } from "./useChat.ts";

const MODELS = [] as never[];

describe("useChat", () => {
  it("keeps the streamed text in one place while a turn is in flight", async () => {
    const engine = fakeEngine({
      holdOpen: true,
      chunks: [delta("half an"), delta("swer"), done()],
    });
    vi.stubGlobal("fetch", engine.fetch);
    const client = new (await import("./api.ts")).KiraClient({ baseUrl: "http://127.0.0.1:8901", token: "t" });

    const { result } = renderHook(() =>
      useChat({ client, model: "mini", mode: "AUTO", connected: true, watching: false }),
    );

    act(() => result.current.setPrompt("go"));
    act(() => void result.current.send());

    await waitFor(() => expect(result.current.live?.text).toBe("half answer"));
    expect(result.current.busy).toBe(true);

    act(() => engine.releaseStream());
    await waitFor(() => expect(result.current.busy).toBe(false));
    expect(result.current.entries.at(-1)?.content).toBe("half answer");
  });

  it("records a refusal as an interrupted turn with its chain", async () => {
    const engine = fakeEngine({ chatStatus: 429, chatJsonError: {
      code: "budget_exhausted", message: "over the cap", status: 429, retryable: false,
      provider_chain: [{ provider: "groq", event: "skipped_budget", reason: "used all of it" }],
    } });
    vi.stubGlobal("fetch", engine.fetch);
    const client = new (await import("./api.ts")).KiraClient({ baseUrl: "http://127.0.0.1:8901", token: "t" });
    const { result } = renderHook(() =>
      useChat({ client, model: "mini", mode: "AUTO", connected: true, watching: false }),
    );
    act(() => result.current.setPrompt("go"));
    act(() => void result.current.send());
    await waitFor(() => expect(result.current.busy).toBe(false));
    const turn = result.current.entries.at(-1)?.turn;
    expect(turn?.status).toBe("interrupted");
    expect(turn?.errorCode).toBe("budget_exhausted");
    expect(turn?.chain[0]?.event).toBe("skipped_budget");
  });
});
```

- [ ] **Step 3: Run it and watch it fail** — cannot resolve `./useChat.ts`.

- [ ] **Step 4: Write `useChat.ts`** (the body is `ChatScreen`'s current state and handlers, moved verbatim;
  the only rename is `route === "chat"` → `watching`)

```ts
import { useCallback, useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import type { KiraClient } from "./api.ts";
import type { ChatChunk, HealthResponse, Mode, SessionRow } from "./contracts.ts";
import { KiraApiError } from "./contracts.ts";
import { applyChunk, emptyTurn } from "./turn.ts";
import type { Turn } from "./turn.ts";

export interface Entry {
  id: number;
  role: "user" | "assistant";
  content: string;
  turn?: Turn;
}

export interface UseChatOptions {
  client: KiraClient;
  model: string;
  mode: Mode;
  connected: boolean;
  /** True when a surface that shows the ledger is mounted (the chat screen, or the agent shell). */
  watching: boolean;
}

export interface ChatState {
  entries: Entry[];
  sessionId: string | null;
  sessions: SessionRow[];
  health: HealthResponse | null;
  prompt: string;
  setPrompt(prompt: string): void;
  busy: boolean;
  live: Turn | null;
  ledgerError: string | null;
  send(event?: FormEvent): void;
  stop(): void;
  openSession(id: string): Promise<void>;
  pullLedger(): void;
}

export function useChat({ client, model, mode, connected, watching }: UseChatOptions): ChatState {
  // …the state block from ChatScreen.tsx (entries, sessionId, sessions, health, prompt, busy, live,
  // ledgerError, abortRef, nextId) unchanged…
  // …pullLedger as today…
  useEffect(() => {
    if (watching) pullLedger();
  }, [watching, pullLedger]);
  // …send/stop/openSession as today…
  return { entries, sessionId, sessions, health, prompt, setPrompt, busy, live, ledgerError, send, stop, openSession, pullLedger };
}
```

Copy the five handlers literally from `ChatScreen.tsx` today; do not reword them. `messageOf` moves into
`useChat.ts` and `ChatScreen` keeps its own copy only if it still needs one (it will not).

- [ ] **Step 5: Make `ChatScreen` presentational**

```tsx
export interface ChatScreenProps {
  chat: ChatState;
  shell: Shell;
  models: ModelInfo[];
  mode: Mode;
}

export function ChatScreen({ chat, shell, models, mode }: ChatScreenProps) {
  const { entries, live, busy, prompt, setPrompt, send, stop, openSession, sessions, health, ledgerError, sessionId } = chat;
  // …the existing JSX, with `route !== "chat"` early-return removed (App decides what mounts)…
}
```
Remove the `route` prop and the `pullLedger` effect (they are in the hook now). Keep every string.

- [ ] **Step 6: Update `App.tsx`**

```tsx
const chat = useChat({ client, model, mode, connected, watching: route === "chat" || shell === "agent" });
// …
{route === "chat" ? <ChatScreen chat={chat} shell={shell} models={models} mode={mode} /> : …}
// pass the real values into OptionsPanel now:
// health={chat.health} sessionId={chat.sessionId} sessionCount={chat.sessions.length}
```

- [ ] **Step 7: Add the mid-turn switch test to `App.test.tsx`**

```ts
it("keeps the streamed text when the shell changes mid-turn", async () => {
  const engine = fakeEngine({ models: MODELS, health: HEALTH, holdOpen: true, chunks: [delta("still"), delta(" here"), done()] });
  connectedTo(engine);
  const view = render(<App />);
  await waitFor(() => expect(modelSelect().value).toBe("llama-3.3-70b-versatile"));
  fireEvent.change(screen.getByLabelText("message"), { target: { value: "go" } });
  fireEvent.click(screen.getByRole("button", { name: "send" }));
  expect(await screen.findByText("still here")).toBeTruthy();

  fireEvent.click(within(screen.getByRole("group", { name: "surface" })).getByRole("button", { name: "Agent" }));
  expect(view.container.querySelector(".app")?.getAttribute("data-shell")).toBe("agent");
  expect(screen.getByText("still here")).toBeTruthy();

  engine.releaseStream();
  await waitFor(() => expect(screen.getByRole("button", { name: "send" })).toBeTruthy());
});
```

- [ ] **Step 8: Run everything**

Run: `cd kira-chat && npx tsc --noEmit && npx vitest run`
Expected: all green — the 5 streaming/replay cases in `App.test.tsx` prove the extraction preserved behaviour.

- [ ] **Step 9: Commit**

```bash
git add kira-chat/src/useChat.ts kira-chat/src/useChat.test.tsx kira-chat/src/screens/ChatScreen.tsx kira-chat/src/App.tsx kira-chat/src/App.test.tsx kira-chat/src/fake-engine.ts
git -c user.name="Kira" -c user.email="kira@localhost" commit -m "refactor(chat): lift the turn above the shell branch, so switching surfaces mid-answer loses nothing"
```

---

### Task 12: The work panel — ALTREX's eight tabs, honestly filled

**Files:**
- Create: `kira-chat/src/screens/AgentPanel.tsx`, `kira-chat/src/screens/AgentPanel.test.tsx`
- Modify: `kira-chat/src/App.tsx`, `kira-chat/src/styles.css`

**Interfaces:**
- Consumes: `ChatState` (Task 11), `ChainTrace` (Task 14 for the chips; plain list until then).
- Produces: `<AgentPanel chat model mode />`; `PANEL_TABS` in ALTREX's order.

- [ ] **Step 1: Write the failing test**

```tsx
// kira-chat/src/screens/AgentPanel.test.tsx
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AgentPanel, PANEL_TABS } from "./AgentPanel.tsx";
import { emptyTurn } from "../turn.ts";
import type { ChatState } from "../useChat.ts";

function chatWith(overrides: Partial<ChatState> = {}): ChatState {
  return {
    entries: [], sessionId: null, sessions: [], health: null, prompt: "", setPrompt: () => {},
    busy: false, live: null, ledgerError: null, send: () => {}, stop: () => {},
    openSession: async () => {}, pullLedger: () => {}, ...overrides,
  };
}

function mount(chat: ChatState = chatWith()) {
  return render(<AgentPanel chat={chat} model="mini" mode="AUTO" />);
}

describe("AgentPanel", () => {
  it("shows ALTREX's eight tabs in the donor's order", () => {
    mount();
    expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).toEqual([...PANEL_TABS]);
    expect([...PANEL_TABS]).toEqual([
      "Changes", "Terminal", "Tests", "Problems", "Agents", "Checkpoints", "Context", "Developer",
    ]);
  });

  it.each(["Changes", "Terminal", "Tests", "Problems", "Checkpoints"])(
    "the %s tab says what fills it and when",
    (tab) => {
      mount();
      fireEvent.click(screen.getByRole("tab", { name: tab }));
      const panel = screen.getByRole("tabpanel");
      expect(panel.textContent).toContain("sub-project 2");
    },
  );

  it("the Agents tab shows the turn's chain as a step timeline", () => {
    const turn = { ...emptyTurn(), status: "complete" as const, chain: [
      { provider: "groq", event: "attempt" as const, model: "mini" },
      { provider: "groq", event: "served" as const, model: "mini" },
      { provider: "kira", event: "tool_executed" as const, tool: "echo", ok: true, chars: 3 },
    ] };
    mount(chatWith({ entries: [{ id: 1, role: "assistant", content: "hi", turn }] }));
    fireEvent.click(screen.getByRole("tab", { name: "Agents" }));
    const panel = screen.getByRole("tabpanel");
    expect(within(panel).getByText("trying")).toBeTruthy();
    expect(within(panel).getByText("answered")).toBeTruthy();
    expect(within(panel).getByText("tool ran")).toBeTruthy();
    expect(panel.textContent).toContain("echo");
  });

  it("the Context tab reads the session, model, mode and usage", () => {
    const turn = { ...emptyTurn(), status: "complete" as const, usage: { prompt_tokens: 12, completion_tokens: 7 } };
    mount(chatWith({ sessionId: "sess-abcdef12", entries: [{ id: 1, role: "assistant", content: "hi", turn }] }));
    fireEvent.click(screen.getByRole("tab", { name: "Context" }));
    const panel = screen.getByRole("tabpanel");
    expect(panel.textContent).toContain("sess-abcd");
    expect(panel.textContent).toContain("mini");
    expect(panel.textContent).toContain("AUTO");
    expect(panel.textContent).toContain("12↑ / 7↓");
  });

  it("the Developer tab names the provenance contract", () => {
    mount();
    fireEvent.click(screen.getByRole("tab", { name: "Developer" }));
    const panel = screen.getByRole("tabpanel");
    expect(panel.textContent).toContain(API_PREFIX);
    expect(panel.textContent).toContain(`v${CONTRACT_VERSION}`);
    expect(panel.textContent).toContain("provider_chain");
  });

  it("says when there is no turn yet, instead of an empty timeline", () => {
    mount();
    fireEvent.click(screen.getByRole("tab", { name: "Agents" }));
    expect(screen.getByRole("tabpanel").textContent).toContain("no turn yet");
  });
});
```
(`import { API_PREFIX, CONTRACT_VERSION } from "../contracts.ts";` at the top.)

- [ ] **Step 2: Run and watch it fail** — cannot resolve `./AgentPanel.tsx`.

- [ ] **Step 3: Write the component**

```tsx
// kira-chat/src/screens/AgentPanel.tsx
import { useState } from "react";
import { FileDiff, Terminal, FlaskConical, CircleAlert, Bot, History, Layers, Code } from "lucide-react";
import { ChainTrace } from "../components/ChainTrace.tsx";
import { API_PREFIX, CONTRACT_VERSION } from "../contracts.ts";
import type { Mode } from "../contracts.ts";
import { chainSummary } from "../turn.ts";
import type { Turn } from "../turn.ts";
import type { ChatState } from "../useChat.ts";

export const PANEL_TABS = [
  "Changes",
  "Terminal",
  "Tests",
  "Problems",
  "Agents",
  "Checkpoints",
  "Context",
  "Developer",
] as const; // ALTREX WorkPanel.tsx:16-25, same order
export type PanelTab = (typeof PANEL_TABS)[number];

const ICONS: Record<PanelTab, typeof Code> = {
  Changes: FileDiff,
  Terminal,
  Tests: FlaskConical,
  Problems: CircleAlert,
  Agents: Bot,
  Checkpoints: History,
  Context: Layers,
  Developer: Code,
};

const EMPTY: Partial<Record<PanelTab, string>> = {
  Changes: "no file changes yet — arrives with the tool harness (sub-project 2)",
  Terminal: "no commands yet — the harness runs them argv-only (sub-project 2)",
  Tests: "no test runs yet — the harness runs a project's tests (sub-project 2)",
  Problems: "no diagnostics yet — the harness reports them (sub-project 2)",
  Checkpoints: "no snapshots yet — the harness takes one before a write (sub-project 2)",
};

function lastTurn(chat: ChatState): Turn | null {
  if (chat.live) return chat.live;
  for (let i = chat.entries.length - 1; i >= 0; i -= 1) {
    const turn = chat.entries[i]?.turn;
    if (turn) return turn;
  }
  return null;
}

export function AgentPanel({ chat, model, mode }: { chat: ChatState; model: string; mode: Mode }) {
  const [tab, setTab] = useState<PanelTab>("Changes");
  const turn = lastTurn(chat);
  const tools = turn ? turn.chain.filter((r) => r.event === "tool_executed").map((r) => r.tool ?? "tool") : [];

  return (
    <aside className="work-panel" aria-label="work panel">
      <div className="work-tabs" role="tablist" aria-label="work panel tabs">
        {PANEL_TABS.map((name) => {
          const Icon = ICONS[name];
          return (
            <button
              key={name}
              type="button"
              role="tab"
              aria-selected={tab === name}
              className={tab === name ? "active" : ""}
              onClick={() => setTab(name)}
            >
              <Icon size={13} />
              {name}
            </button>
          );
        })}
      </div>
      <div className="work-body" role="tabpanel" aria-label={tab}>
        {EMPTY[tab] ? <p className="empty">{EMPTY[tab]}</p> : null}
        {tab === "Agents" && (
          <>
            {!turn && <p className="empty">no turn yet — ask something and the chain will appear here</p>}
            {turn && (
              <>
                <p className="work-meta">{chainSummary(turn)}</p>
                <ChainTrace chain={turn.chain} />
                <h4>tools seen this turn</h4>
                {tools.length === 0 ? (
                  <p className="empty">none — the registry itself is listed once sub-project 2 adds an endpoint for it</p>
                ) : (
                  <ul className="work-list">{tools.map((tool, i) => <li key={`${tool}-${i}`} className="mono">{tool}</li>)}</ul>
                )}
              </>
            )}
          </>
        )}
        {tab === "Context" && (
          <dl className="work-facts">
            <dt>session</dt><dd className="mono">{chat.sessionId ? chat.sessionId.slice(0, 8) : "none yet"}</dd>
            <dt>model</dt><dd className="mono">{model || "—"}</dd>
            <dt>mode</dt><dd className="mono">{mode}</dd>
            <dt>usage</dt><dd className="mono">{turn?.usage ? `${turn.usage.prompt_tokens}↑ / ${turn.usage.completion_tokens}↓` : "—"}</dd>
            <dt>status</dt><dd className="mono">{turn?.status ?? "—"}</dd>
          </dl>
        )}
        {tab === "Developer" && (
          <dl className="work-facts">
            <dt>namespace</dt><dd className="mono">{API_PREFIX}</dd>
            <dt>contract</dt><dd className="mono">v{CONTRACT_VERSION}</dd>
            <dt>provider_chain</dt>
            <dd className="mono work-json">{JSON.stringify(turn?.chain ?? [], null, 2)}</dd>
          </dl>
        )}
      </div>
    </aside>
  );
}
```

- [ ] **Step 4: Append the panel styles**

```css
.app[data-shell="agent"] .work-panel {
  width: 300px;
  min-width: 0;
  display: flex;
  flex-direction: column;
  border-left: 1px solid var(--line);
  background: var(--panel);
  border-radius: var(--radius-sheet) 0 0 var(--radius-sheet);
}
.work-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 0.15rem;
  padding: 0.5rem;
  border-bottom: 1px solid var(--line);
}
.work-tabs button {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.25rem 0.45rem;
  border: 1px solid transparent;
  border-radius: var(--radius-control);
  background: transparent;
  font-size: 11px;
  color: var(--muted);
}
.work-tabs button.active {
  color: var(--text);
  background: #222;
  border-color: var(--line-strong);
}
.work-body {
  padding: 0.75rem;
  overflow: auto;
  display: grid;
  gap: 0.6rem;
  align-content: start;
}
.work-body h4 {
  margin: 0;
  font-family: var(--mono);
  font-size: 10px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--muted);
}
.work-meta {
  margin: 0;
  font-family: var(--mono);
  font-size: 11px;
  color: var(--muted);
}
.work-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 0.2rem;
}
.work-facts {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 0.35rem 0.75rem;
  margin: 0;
  font-size: 12px;
}
.work-facts dt {
  font-family: var(--mono);
  font-size: 10px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--muted);
}
.work-facts dd {
  margin: 0;
}
.work-json {
  white-space: pre-wrap;
  word-break: break-all;
  font-size: 11px;
  color: var(--muted);
}
@media (max-width: 70rem) {
  .app[data-shell="agent"] .work-panel { width: 240px; }
}
@media (max-width: 60rem) {
  .app[data-shell="agent"] { grid-template-columns: 1fr; }
  .app[data-shell="agent"] .work-panel {
    width: auto;
    border-left: 0;
    border-top: 1px solid var(--line);
    border-radius: 0;
  }
}
```

- [ ] **Step 5: Mount it**

```tsx
// App.tsx, after </div> of .pane, inside the .app grid:
{shell === "agent" && <AgentPanel chat={chat} model={model} mode={mode} />}
```

- [ ] **Step 6: Run** — `npx vitest run src/screens/AgentPanel.test.tsx` → 11 passed (1 + 5 + 1 + 1 + 1 + 1 + 1).

- [ ] **Step 7: Commit**

```bash
git add kira-chat/src/screens/AgentPanel.tsx kira-chat/src/screens/AgentPanel.test.tsx kira-chat/src/App.tsx kira-chat/src/styles.css
git -c user.name="Kira" -c user.email="kira@localhost" commit -m "feat(chat): ALTREX's eight work-panel tabs, five of them saying plainly what is not built yet"
```

---

### Task 13: Step chips for the agent transcript

**Files:**
- Modify: `kira-chat/src/components/ChainTrace.tsx`, `kira-chat/src/screens/ChatScreen.tsx`,
  `kira-chat/src/styles.css`, `kira-chat/src/App.test.tsx`

**Interfaces:**
- Produces: `<ChainTrace chain collapsible />` — a `<details>` wrapper with an `N steps` summary.

- [ ] **Step 1: Write the failing test** (in `App.test.tsx`)

```ts
it("collapses the chain into step chips in the agent shell", async () => {
  localStorage.setItem("kira.shell", "agent");
  const records: ChainRecord[] = [
    { provider: "groq", event: "attempt", model: "llama-3.3-70b-versatile" },
    { provider: "groq", event: "served", model: "llama-3.3-70b-versatile" },
  ];
  const engine = fakeEngine({ models: MODELS, health: HEALTH, chunks: [chain(records[0]!), delta("ok"), done({ provider_chain: records })] });
  connectedTo(engine);
  render(<App />);
  fireEvent.change(await screen.findByLabelText("message"), { target: { value: "go" } });
  fireEvent.click(screen.getByRole("button", { name: "send" }));
  expect(await screen.findByText("ok")).toBeTruthy();
  expect(screen.getByText("2 steps")).toBeTruthy();
  expect(screen.getByLabelText("provider chain")).toBeTruthy();
});
```

- [ ] **Step 2: Run it and watch it fail** — no `2 steps`.

- [ ] **Step 3: Implement**

```tsx
// ChainTrace.tsx
export function ChainTrace({ chain, collapsible = false }: { chain: ChainRecord[]; collapsible?: boolean }) {
  if (chain.length === 0) return null;
  const steps = (
    <ol className="chain" aria-label="provider chain">
      {/* …unchanged… */}
    </ol>
  );
  if (!collapsible) return steps;
  return (
    <details className="chain-steps" open>
      <summary>{chain.length} step{chain.length === 1 ? "" : "s"}</summary>
      {steps}
    </details>
  );
}
```

`ChatScreen` passes `collapsible={shell === "agent"}` in both places it renders `<ChainTrace>`.

- [ ] **Step 4: Style**

```css
.chain-steps {
  border: 1px solid var(--line);
  border-radius: var(--radius-sheet);
  background: #09090b; /* PocketStrike terminal surface, app_palette.dart:34 */
  padding: 0.35rem 0.5rem;
}
.chain-steps > summary {
  cursor: pointer;
  font-family: var(--mono);
  font-size: 10px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--muted);
}
.chain-steps[open] > summary {
  margin-bottom: 0.35rem;
}
```

- [ ] **Step 5: Run** — the new case passes; the existing `provider chain` assertions on the chat shell still
  find a bare `<ol>`.

- [ ] **Step 6: Commit**

```bash
git add kira-chat/src/components/ChainTrace.tsx kira-chat/src/screens/ChatScreen.tsx kira-chat/src/styles.css kira-chat/src/App.test.tsx
git -c user.name="Kira" -c user.email="kira@localhost" commit -m "feat(chat): the agent transcript folds the chain into PocketStrike-style step chips"
```

---

### Task 14: Every-route proof in both shells, and the invariants

**Files:**
- Modify: `kira-chat/src/App.test.tsx`

**Interfaces:**
- Consumes: everything above. Produces: the acceptance bar for §9.

- [ ] **Step 1: Replace the every-route test with a both-shells version**

```ts
it("renders every route for real in both shells and a placeholder for none", async () => {
  for (const shell of ["chat", "agent"] as const) {
    localStorage.setItem("kira.shell", shell);
    const engine = fakeEngine({
      models: MODELS,
      health: HEALTH,
      sessions: [{ id: "sess-1", mode: "AUTO", created_at: 1, message_count: 2, tokens: 10, last_used_at: 2 }],
    });
    connectedTo(engine);
    for (const route of ["chat", "overview", "providers", "models", "sessions"] as const) {
      window.location.hash = `#/${route}`;
      const view = render(<App />);
      expect(await screen.findByText("Kira")).toBeTruthy();
      expect(view.container.querySelector(".app")?.getAttribute("data-shell")).toBe(shell);
      expect(screen.queryByText(/arrives in M12/)).toBeNull();
      // The banner is the one thing a stale bundle can still show, so both shells must carry it.
      expect(screen.getByText(`${API_PREFIX} · v${CONTRACT_VERSION}`)).toBeTruthy();
      view.unmount();
    }
  }
});

it("runs the token gate before either shell mounts", async () => {
  localStorage.setItem("kira.shell", "agent");
  const engine = fakeEngine();
  vi.stubGlobal("fetch", engine.fetch);
  render(<App />);
  expect(screen.getByRole("heading", { name: "Connect to Kira" })).toBeTruthy();
  expect(screen.queryByRole("group", { name: "surface" })).toBeNull();
  expect(engine.calls).toEqual([]);
});

it("writes no secret to storage when the shell and look change", () => {
  localStorage.clear();
  navigateShell("agent");
  navigateTheme("violet");
  setLook({ glass: false });
  const keys = Object.keys(localStorage).sort();
  expect(keys).toEqual(["kira.look", "kira.shell", "kira.theme"]);
  const dump = keys.map((k) => localStorage.getItem(k)).join("|");
  expect(dump).not.toMatch(/confirm|token|secret|key/i);
});
```

- [ ] **Step 2: Run the suite**

Run: `cd kira-chat && npx tsc --noEmit && npx vitest run`
Expected: green. Record the count in the commit message.

- [ ] **Step 3: Commit**

```bash
git add kira-chat/src/App.test.tsx
git -c user.name="Kira" -c user.email="kira@localhost" commit -m "test(chat): every route in both shells, the gate ahead of both, and no secret in the three new keys"
```

---

### Task 15: Icons and keyboard reach

**Files:**
- Modify: `kira-chat/src/App.tsx` (`NavIcon`), `kira-chat/src/styles.css`

**Interfaces:**
- Consumes: `lucide-react` (Task 4). Produces: nav glyphs replaced by icons; focus-visible ring on both shells.

- [ ] **Step 1: Replace the placeholder glyphs**

```tsx
import { Activity, Cpu, History, MessageSquare, Server } from "lucide-react";

const NAV_ICONS = {
  chat: MessageSquare,
  overview: Activity,
  providers: Server,
  models: Cpu,
  sessions: History,
} as const;

function NavIcon({ route }: { route: Route }) {
  const Icon = NAV_ICONS[route];
  return <Icon size={15} aria-hidden="true" />;
}
```
Delete `NAV_GLYPHS` and the `nav-icon` span wrapper (the icon replaces the glyph; `.rail-label` stays).

- [ ] **Step 2: Style focus and the icon slot**

```css
.nav-icon,
.rail button svg {
  flex: none;
}
.rail button {
  gap: 0.55rem;
}
.app button:focus-visible,
.app select:focus-visible,
.app textarea:focus-visible,
.app summary:focus-visible {
  outline: 1px solid var(--accent);
  outline-offset: 2px;
}
```

- [ ] **Step 3: Run** — `npx vitest run` green (no test asserts glyphs; the nav is reached by name).

- [ ] **Step 4: Commit**

```bash
git add kira-chat/src/App.tsx kira-chat/src/styles.css
git -c user.name="Kira" -c user.email="kira@localhost" commit -m "feat(chat): lucide icons in the nav and a focus ring that follows the shell accent"
```

---

### Task 16: Documentation and the storage claim

**Files:**
- Modify: `Kira/README.md`, `Kira/PROVENANCE.md`

**Interfaces:**
- Consumes: the finished client. Produces: the section a user looks for first.

- [ ] **Step 1: Add the README section** (after "The dashboard", before "Checks")

```markdown
## Two modes: Chat and Agent

The switch in the top-left corner changes how the same five screens look and sit. It is a preference,
not a route: `#/providers` is the same place in both, and `kira.shell` remembers which you prefer.
`kira.theme` (seven), `kira.look` (glass, motion, caption size, scale, density) and `kira.sidebar`
(the agent sidebar's collapse) are the other three preferences. None of them is a secret, and the
storage claim above still holds: `grep -rn "localStorage" kira-chat/src/` now also returns `shell.ts`,
`theme.ts` and `look.ts`, and every key is one of those six.

- **Chat** wears MYRAA's language: `#020205`, frosted panels, mono uppercase labels, a Space Grotesk
  caption for the answer, seven accent themes, and an options panel shaped like MYRAA's overlay.
- **Agent** wears ALTREX's geometry with PocketStrike's glass: a 240px sidebar collapsing to 56px, a
  48px top bar, a 780px conversation column, and an eight-tab work panel. Five of those tabs are empty
  on purpose and say so — they fill with the tool harness (sub-project 2).

Switching mid-answer keeps the streamed text: the turn lives above the shell branch. The engine is not
told about the mode; nothing about routing changes.
```

- [ ] **Step 2: Update the storage sentence in "Two secrets"** to name the six keys instead of two, keeping
  the claim (no confirm secret, no key).

- [ ] **Step 3: Extend the PROVENANCE table**

```markdown
| `shell.ts`, `theme.ts`, `look.ts`, `shell-switch.tsx`, `options-panel.tsx`, both `[data-shell]` blocks | MYRAA visual language (`App.tsx:305`, `:522`, `:612-638`, `SettingsPanel.tsx:36-112`); ALTREX geometry and tokens (`styles.css:3-34`, `:56-59`, `WorkPanel.tsx:16-25`); PocketStrike glass and radii (`glass_tokens.dart:32-49`, `app_palette.dart:11-34`) | none / none / none | no — values read, CSS written here |
```

- [ ] **Step 4: Commit**

```bash
git add README.md PROVENANCE.md
git -c user.name="Kira" -c user.email="kira@localhost" commit -m "docs: the two modes, the six keys they add, and where every value came from"
```

---

### Task 17: All gates, one build

**Files:** none (verification only).

- [ ] **Step 1: Chat**

```bash
cd kira-chat && npm run check
```
Expected: tsc clean, all tests pass, `vite build` succeeds, `stamp-version.mjs` writes `dist/kira-build.json`.

- [ ] **Step 2: Contract**

```bash
cd .. && node kira-contracts/check-drift.mjs
```
Expected: `kira-contracts OK — v2, 39 schemas, 5 chunk types, 9 chain events`.

- [ ] **Step 3: Engine (must be untouched)**

```bash
cd kira-engine && .venv/Scripts/python.exe -m pytest -q
```
Expected: `191 passed, 1 skipped`.

- [ ] **Step 4: Grep claims**

```bash
cd .. && grep -rn "localStorage" kira-chat/src/ | grep -v "test" | sed 's/:.*//' | sort -u
grep -rniE 'localStorage\.(set|get)Item\("?(confirm|key)' kira-chat/src/ ; echo "exit=$?"
grep -rn "0\.0\.0\.0" kira-engine/src kira-chat/src ; echo "exit=$?"
```
Expected: files `App.tsx`, `look.ts`, `shell.ts`, `theme.ts` (+ `fake-engine.ts` if it seeds none);
second and third greps print nothing (`exit=1`).

- [ ] **Step 5: Commit the build stamp only if it changed**

```bash
git status --short
```
`dist/` is not tracked; nothing to commit. If `git status` shows anything else, stop and explain it.

---

### Task 18: The browser pass

**Files:**
- Create: `docs/qa/shell-modes-browser-pass.md`

- [ ] **Step 1: Build and start the lab**

```bash
cd kira-chat && npm run build
cd ../kira-engine && .venv/Scripts/python.exe tools/kira_lab.py --data-dir "$TEMP/kira-lab-shell"
```
Record the printed token and confirm secret from stderr.

- [ ] **Step 2: Drive the page** with the Playwright MCP (`browser_navigate` with `ignoreCache`,
  then seed `kira.base`/`kira.token` and reload — the sub-project 9 recipe; rebuilding without it serves a
  cached bundle).

Checks, each recorded with what the screen actually showed:

1. Both positions render, the switch stays top-left in each, and `data-shell` flips.
2. All seven themes: `--accent` computed on `.app` differs per theme and every theme's accent has ≥ 4.5:1
   against `--panel` (measure with `getComputedStyle` + a contrast function in `browser_evaluate`).
3. Glass on/off changes `backdrop-filter` on `.msg.assistant`.
4. Caption S/M/L/XL: computed `font-size` on `.msg.assistant .content` is 20/24/30/36px.
5. Switch mid-answer with a `TOOL` prompt: text keeps growing after the click; the Agents tab fills.
6. Work panel: five empty tabs each name sub-project 2; Agents/Context/Developer show real data.
7. Agent sidebar collapse: computed `grid-template-columns` first track is 240px, then 56px.
8. `#020205`-on-`#020205` check: no text is the same colour as the surface behind it.
9. Contract banner visible in both shells.

- [ ] **Step 3: Write `docs/qa/shell-modes-browser-pass.md`** in the shape of `dashboard-browser-pass.md`
  (header with engine/browser/locale, then a numbered table `# | Check | Observed | Verdict`).

- [ ] **Step 4: Fix what the pass finds, in follow-up commits** (`fix(chat): …`), each with its own test
  where the finding is testable in jsdom.

- [ ] **Step 5: Commit**

```bash
git add docs/qa/shell-modes-browser-pass.md
git -c user.name="Kira" -c user.email="kira@localhost" commit -m "test(qa): browser pass over both shells, seven themes and the work panel against a scripted provider"
```

---

## Self-review

**Spec coverage.** §3 shell module → Task 2. §3 `data-*` + switch → Tasks 3, 6, 7. §4 Chat tokens/type/themes/
arrangement → Tasks 5, 6, 8. §4 panel → Task 8. §5 Agent tokens/geometry/work panel/step chips → Tasks 9, 12,
13. §6 options → Tasks 7, 8 (engine URL/token/routing/model already exist at `App.tsx:163-177`; the panel adds
theme, glass, motion, caption, scale, density, sidebar — every §6 item except the work-panel tab, which is the
panel's own state, and PocketStrike's `ConfirmationPolicy`, which §6 explicitly defers to sub-project 2).
§7 fonts → Task 4. §9 invariants → Tasks 3 (gate order test), 11 (mid-turn), 14 (banner, both shells, storage).
§10 tests → Tasks 5, 14. §11 rollback → every token block is additive; removing `data-*` and the two files
restores the old look. §10's README note → Task 16.

**Placeholders.** None: every step carries the code or the command. `useChat.ts` Step 4 says "copy the handlers
literally" rather than re-printing 90 lines that already exist at `ChatScreen.tsx:57-130`; the executor has that
file open.

**Type consistency.** `Shell`, `Theme`, `Look`, `ChatState`, `PanelTab` are declared once and imported
everywhere they appear. `OptionsPanel` takes `sessionCount` (a number), not `sessions` — the panel never needs
the rows. `AgentPanel` takes `mode: Mode` and `model: string`, not the whole `App` state.
