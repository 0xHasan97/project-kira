import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

// Not `./styles.css?raw`: vitest answers style imports with an empty string (css: false, the default),
// and this guard is worthless against "". The file on disk is the same one the build consumes.
// Whitespace is flattened so a selector that Prettier wraps across lines still matches the one-line
// form these assertions read; declarations are unaffected.
const css = readFileSync(
  resolve(process.cwd(), "src/styles.css"),
  "utf8",
).replace(/\s+/g, " ");

/** The twelve properties every screen already reads. A shell that inherits one of them ships half a skin. */
export const BASE_TOKENS = [
  "--ink",
  "--panel",
  "--panel-2",
  "--line",
  "--text",
  "--muted",
  "--accent",
  "--warn",
  "--bad",
  "--mono",
  "--sans",
  "--display",
] as const;

function block(selector: string): string {
  const start = css.indexOf(`${selector} {`);
  expect(start, `no ${selector} block in styles.css`).toBeGreaterThan(-1);
  return css.slice(start, css.indexOf("}", start));
}

/** Every rule inside a `@media` query, found by brace counting: a phone block is many rules, not one. */
function media(query: string): string {
  const start = css.indexOf(`@media ${query} {`);
  expect(start, `no @media ${query} block in styles.css`).toBeGreaterThan(-1);
  let depth = 0;
  for (let index = css.indexOf("{", start); index < css.length; index += 1) {
    if (css[index] === "{") depth += 1;
    if (css[index] === "}") {
      depth -= 1;
      if (depth === 0) return css.slice(start, index + 1);
    }
  }
  throw new Error(`@media ${query} never closes`);
}

function inside(source: string, selector: string): string {
  const start = source.indexOf(`${selector} {`);
  expect(start, `no ${selector} block`).toBeGreaterThan(-1);
  return source.slice(start, source.indexOf("}", start));
}

describe("shell tokens", () => {
  it.each(BASE_TOKENS)("chat re-declares %s", (token) => {
    expect(block('.app[data-shell="chat"]')).toContain(`${token}:`);
  });

  it.each(BASE_TOKENS)("agent re-declares %s", (token) => {
    expect(block('.app[data-shell="agent"]')).toContain(`${token}:`);
  });

  it("never lets the chat shell fall back to the pre-skin palette", () => {
    expect(block('.app[data-shell="chat"]')).not.toContain("--ink: #0f1113");
    expect(block('.app[data-shell="agent"]')).not.toContain("--ink: #0f1113");
  });

  it("declares the seven MYRAA themes, and only for the chat shell", () => {
    for (const theme of [
      "violet",
      "crimson",
      "emerald",
      "celestial",
      "gold",
      "rose",
      "charcoal",
    ]) {
      expect(block(`.app[data-shell="chat"][data-theme="${theme}"]`)).toContain(
        "--accent:",
      );
      expect(css).not.toContain(`[data-shell="agent"][data-theme="${theme}"]`);
    }
  });

  // The small mono labels (nav, badges) sit on these surfaces in accent ink, so AA is the floor.
  it.each([
    "violet",
    "crimson",
    "emerald",
    "celestial",
    "gold",
    "rose",
    "charcoal",
  ])("keeps %s's accent readable on both chat surfaces", (theme) => {
    const accent = colorOf(
      block(`.app[data-shell="chat"][data-theme="${theme}"]`),
      "--accent",
    );
    expect(
      contrast(accent, colorOf(block('.app[data-shell="chat"]'), "--panel")),
    ).toBeGreaterThanOrEqual(4.5);
    expect(
      contrast(accent, colorOf(block('.app[data-shell="chat"]'), "--panel-2")),
    ).toBeGreaterThanOrEqual(4.5);
    // The pressed switch and the selected segment print --on-accent on the accent itself.
    expect(
      contrast(accent, colorOf(block('.app[data-shell="chat"]'), "--ink")),
    ).toBeGreaterThanOrEqual(4.5);
  });

  it("sizes the chat band to its content instead of stretching it", () => {
    const chatBlocks = [...css.matchAll(/\.app\[data-shell="chat"\] \{/g)].map(
      (match) => {
        const start = match.index ?? 0;
        return css.slice(start, css.indexOf("}", start));
      },
    );
    // An `auto` row stretches under align-content: normal, which is how the switch drifted to y=88.
    expect(
      chatBlocks.some((source) =>
        source.includes("grid-template-rows: auto minmax(0, 1fr)"),
      ),
    ).toBe(true);
  });
  // A chain chip is as wide as its detail; in the 300px panel that widened the grid track and every
  // paragraph scrolled sideways with it instead of wrapping.
  it("fits the work panel's chain chips inside its column", () => {
    expect(block(".work-body")).toContain(
      "grid-template-columns: minmax(0, 1fr)",
    );
    expect(block('.app[data-shell="agent"] .work-panel .chain li')).toContain(
      "flex-wrap: wrap",
    );
    expect(
      block('.app[data-shell="agent"] .work-panel .chain-detail'),
    ).toContain("white-space: normal");
    expect(block(".work-json")).toContain("overflow-wrap: anywhere");
    expect(block(".work-json")).not.toContain("break-all");
  });
  // At 56px the 141px pill centred itself to x=-31 (Chat cut off) and the collapse toggle fell outside.
  it("stacks the shell switch when the rail narrows to 56px", () => {
    expect(
      block('.app[data-shell="agent"][data-sidebar="collapsed"] .shell-switch'),
    ).toContain("flex-direction: column");
    expect(
      block(
        '.app[data-shell="agent"][data-sidebar="collapsed"] .rail-brand .shell-switch button',
      ),
    ).toContain("white-space: nowrap");
    expect(
      block(
        '.app[data-shell="agent"][data-sidebar="collapsed"] .sidebar-toggle',
      ),
    ).toContain("margin-left: 0");
  });
  it("keeps the composer on screen at desktop widths, not only on a phone", () => {
    // The thread was already `overflow: auto` and `min-height: 0`, but nothing capped it: `.app` grew
    // with its content, so a long sitting scrolled the document. `useFollow` then set a `scrollTop` on
    // an element that cannot scroll, and the auto-grown composer pushed send below the fold.
    const app = block(".app");
    expect(app).toContain("height: 100vh");
    expect(app).toContain("height: 100dvh");
    expect(app).toContain("overflow: hidden");
    expect(block(".pane")).toContain("min-height: 0");
    // The dashboard screens are the other child of that column; they are long by nature.
    expect(block(".screen")).toContain("overflow-y: auto");
    expect(block(".rail")).toContain("overflow-y: auto");
  });

  // The rail's light ink was inherited by the pressed switch, washing its label out on its own pill.
  it("lets the pressed switch keep its own ink inside the agent rail", () => {
    expect(
      block(
        '.app[data-shell="agent"] .rail .shell-switch button[aria-pressed="true"]',
      ),
    ).toContain("color: var(--on-accent)");
  });
});

// The phone block is the only place the app agrees to be 390px wide. Each rule here replaces a
// desktop assumption that a thumb, a notch or a soft keyboard breaks.
describe("the agent turn trace", () => {
  it("is a foldable card, not a floating pill list", () => {
    const trace = block(".turn-trace");
    expect(trace).toContain("border: 1px solid var(--line)");
    expect(trace).toContain("border-radius: var(--radius-sheet)");
    expect(block(".trace-head")).toContain("list-style: none");
    expect(css).toContain(".turn-trace[open] .trace-chevron");
  });

  it("keeps the step's own words, and clips a long command instead of the meta", () => {
    expect(block(".trace-object")).toContain("text-overflow: ellipsis");
    const meta = block(".trace-meta");
    expect(meta).toContain("flex: none");
    expect(meta).toContain("margin-left: auto");
    expect(meta).toContain("tabular-nums");
  });

  it("animates the activity marks, and stops when the reader asked it to", () => {
    expect(css).toContain("@keyframes trace-bars");
    expect(css).toContain("@keyframes trace-dots");
    // The app-wide switch already covers every animation, this one included.
    expect(media("(prefers-reduced-motion: reduce)")).toContain(
      "animation: none !important",
    );
  });
});

describe("the phone layout", () => {
  const phone = media("(max-width: 48rem)");

  it("sizes the app to the visible viewport, not to 100vh behind the browser chrome", () => {
    expect(phone).toContain("height: 100vh");
    expect(phone).toContain("height: 100dvh");
  });

  it("keeps the bottom bar's buttons above the home indicator and inside a thumb", () => {
    expect(phone).toContain("padding-bottom: env(safe-area-inset-bottom)");
    expect(phone).toMatch(/min-height: 44px/);
    expect(phone).toMatch(/min-width: 44px/);
  });

  it("lets the status bar paint the app colour when installed", () => {
    expect(phone).toContain(
      "padding-top: calc(0.7rem + env(safe-area-inset-top))",
    );
  });

  it("sets 16px type where iOS would otherwise zoom the page on focus", () => {
    expect(phone).toMatch(/font-size: 16px/);
  });

  it("moves navigation to the bottom and keeps the full rail behind one button", () => {
    expect(phone).toContain(".phone-bar {");
    expect(phone).toContain(".app > .rail {");
    expect(phone).toContain("display: none");
    expect(phone).toContain('.app > .rail[data-open="on"]');
  });

  it("scrolls the screen, not the document, so the bar never leaves the viewport", () => {
    expect(phone).toContain("overflow: hidden");
    expect(phone).toContain("overflow-y: auto");
  });

  // The chat rail's rows are inline-block on a desktop bar, where the icon sits beside the text for
  // free. In a column sheet the icon and the label collided, so the sheet re-lays each row itself.
  it("gives every row in the sheet one icon then one label, and the whole width", () => {
    const row = inside(phone, '.app > .rail[data-open="on"] button');
    expect(row).toContain("display: flex");
    expect(row).toContain("gap:");
    expect(row).toContain("width: 100%");
  });

  it("dims the page under the sheet, so a tap outside is a visible dismissal", () => {
    expect(block(".rail-scrim")).toContain("display: none");
    const scrim = inside(phone, ".rail-scrim");
    expect(scrim).toContain("position: fixed");
    expect(scrim).toContain("inset: 0");
  });

  // The model label is the longest string in the header ("mini · mock_one, mock_two · fast"). At 46vw
  // it lost its tail; a phone gives it a row of its own instead of a cap that only ever clips.
  it("gives the model picker its own line rather than a width cap", () => {
    const picker = inside(phone, '.bar select[name="model"]');
    expect(picker).toContain("flex: 1 1 100%");
    expect(phone, "the 46vw cap is what clipped the label").not.toContain(
      "max-width: 46vw",
    );
    expect(inside(phone, ".bar .spacer")).toContain("display: none");
  });

  // The agent header is 48px on a desktop, where its controls fit one line. On a phone the model
  // picker wraps, and a fixed height let the second row paint over the screen title below it.
  it("lets the agent header grow to the rows it actually has", () => {
    const bar = inside(phone, '.app[data-shell="agent"] .bar');
    expect(bar).toContain("height: auto");
    expect(bar).toContain("min-height: 48px");
  });

  // 15rem of side plus a thread is a desktop split; at 390px the thread got 150px.
  it("stacks the agent body, and caps the strip and the work panel at a third of the screen", () => {
    const body = inside(phone, '.app[data-shell="agent"] .body');
    expect(body).toContain("grid-template-columns: 1fr");
    expect(body).toContain("grid-template-rows: auto minmax(0, 1fr)");
    expect(inside(phone, '.app[data-shell="agent"] .work-panel')).toContain(
      "max-height: 34dvh",
    );
    expect(inside(phone, ".work-body")).toContain("min-height: 0");
  });
});

describe("the focused chat layout", () => {
  it("keeps the conversation single-column and drops the workspace rail", () => {
    const shell = block('.app[data-chat-focus="on"]');
    expect(shell).toContain("grid-template-columns: minmax(0, 1fr)");
    expect(css).toContain(
      '.app[data-chat-focus="on"] > .rail { display: none; }',
    );
  });

  // The transcript scrolls under a sticky composer. A translucent card let the chain chips show
  // through the textarea on a short phone, so the focused chat composer is fully opaque.
  it("floats the composer over the transcript as an opaque card", () => {
    expect(block('.app[data-chat-focus="on"] .composer')).toContain(
      "background: var(--panel)",
    );
  });

  it("keeps the surface switch in the phone chat header", () => {
    expect(css).toContain(".chat-bar .shell-switch { flex: 0 0 auto; }");
    expect(media("(max-width: 22rem)")).toContain(
      ".chat-brand { display: none; }",
    );
  });
});

describe("the avatar stage", () => {
  it("lifts the reading cap for the stage in both shells and nowhere else", () => {
    expect(block(".screen")).toContain("max-width: 72rem");
    expect(block(".pane > .screen.avatar-screen")).toContain("max-width: none");
    expect(block('.app[data-shell="agent"] .screen.avatar-screen')).toContain(
      "max-width: none",
    );
  });

  it("gives the library the flexible column and the stage the fixed one", () => {
    expect(block(".avatar-body")).toContain(
      "grid-template-columns: minmax(0, 1fr) minmax(14rem, 22rem)",
    );
    const pane = block(".stage-pane");
    expect(pane).toContain("position: sticky");
    expect(pane).toContain("background: var(--panel-2)");
    // The one property `.screen` is valued for, and the one a body cannot stand in.
    expect(pane).not.toContain("max-width: 72rem");
  });

  it("lets the card be as tall as the drawing inside it, not as tall as a ratio", () => {
    // Measured in the 2026-11-02 browser pass: with `aspect-ratio` on the pane the card was 469px and the
    // drawing alone 424, so the column flex squeezed `.avatar-stage` to 166 and the 424px canvas spilled
    // out over the "take everyone off" button. The ratio is the drawing's; the card takes the length.
    expect(block(".stage-pane")).not.toContain("aspect-ratio");
    expect(block(".avatar-stage")).toContain("flex: 0 0 auto");
    expect(block(".avatar-stage")).not.toContain("min-height: 0");
    // 70dvh was a cap for a card that was only a portrait. The card is now portrait + moods + findings,
    // and at 900px the drawing pushed the pane's own controls past its fold — the take-off button was
    // painted half out of the box. 85dvh still leaves the bar and the screen's padding above it.
    expect(block(".stage-pane")).toContain("max-height: 85dvh");
  });

  it("stacks the stage over the table on a phone and stops it sticking", () => {
    const phone = media("(max-width: 48rem)");
    expect(inside(phone, ".avatar-body")).toContain(
      "grid-template-columns: 1fr",
    );
    const pane = inside(phone, ".stage-pane");
    expect(pane).toContain("position: static");
    // Same defect, worse here: a square, 42dvh-tall card at 390px showed 354px of a 477px portrait and
    // kept the mood buttons and the take-off control below a fold the screen itself could not reach.
    // The card is in the page's flow now, so scrolling the screen reveals all of it.
    expect(pane).not.toContain("aspect-ratio");
    expect(pane).not.toContain("max-height");
    // A 13px path field makes iOS zoom the page on focus, and the zoom outlives the field.
    expect(phone).toContain(".import-row input,");
    // The named widths would put the buttons in a 98px box at 390px, so the phone opts out of them.
    expect(inside(phone, ".avatar-library > table.grid")).toContain(
      "table-layout: auto",
    );
    // Measured at 390×844 in the 2026-11-04 pass: the table's min-content is 394px, `.screen` answers that
    // with its own horizontal scroll, and scrolling to reach `remove` slid the stage — the body you were
    // looking at — off the left edge. The table scrolls now, and the drawing stays put.
    const library = inside(phone, ".avatar-library");
    expect(library).toContain("min-width: 0");
    expect(library).toContain("overflow-x: auto");
  });

  it("sizes the library table by column, not by how much its worst name can break", () => {
    // Measured in the 2026-11-02 browser pass with three donor archives imported: `table-layout: auto`
    // starved the actions column until `remove 星临者女仆装皮肤` folded to one glyph per line, and the
    // table then slid under the sticky stage pane.
    expect(block(".avatar-library > table.grid")).toContain(
      "table-layout: fixed",
    );
    expect(block(".avatar-library > table.grid th:nth-child(5)")).toContain(
      "width: 25%",
    );
    expect(block(".avatar-library > table.grid td:first-child")).toContain(
      "overflow-wrap: anywhere",
    );
    expect(block(".avatar-library .row-actions button")).toContain(
      "flex: 1 1 100%",
    );
  });

  it("keeps a badge on one line, because a two-line pill is an oval around a stack", () => {
    // Same pass: the stage column is narrow enough to wrap `on stage` across two lines inside a
    // 999px radius, which reads as a defect on the one cell that says whether a body is live.
    expect(block(".badge")).toContain("border-radius: 999px");
    expect(block(".badge")).toContain("white-space: nowrap");
  });

  it("holds the canvas to the camera's own ratio and the moods to a thumb", () => {
    // The stage camera is framed 3:4 and the drawing buffer is 360×480. CSS that stretched the element to
    // its box would tilt the face, so the element keeps the ratio and the buffer keeps its size.
    expect(block(".avatar-stage canvas")).toContain("aspect-ratio: 3 / 4");
    expect(block(".avatar-stage canvas")).toContain("width: 100%");
    expect(block(".avatar-stage canvas")).toContain("height: auto");
    expect(block(".stage-moods button")).toContain("min-height: 2.1rem");
    expect(block('.stage-moods button[aria-pressed="true"]')).toContain(
      "border-color: var(--accent)",
    );
    // A donor archive with eleven missing textures would otherwise push the mood buttons — and on a
    // phone the whole pane below them — off the screen.
    const notes = block(".stage-notes");
    expect(notes).toContain("max-height: 7rem");
    expect(notes).toContain("overflow-y: auto");
  });
});

// The call screen's css was briefly a separate file that nothing imported, so the screen shipped
// unstyled while every test stayed green. `main.tsx` reads `styles.css` and nothing else.
describe("call screen", () => {
  it("styles the self-view and keeps it mirrored", () => {
    expect(block(".call-self")).toContain("transform: scaleX(-1)");
    expect(block(".call-self")).toContain("aspect-ratio: 4 / 3");
  });

  it("gives the stage a fixed column and the transcript the flexible one", () => {
    expect(block(".call-body")).toContain(
      "grid-template-columns: minmax(18rem, 380px) minmax(0, 1fr)",
    );
  });

  it("stops blinking the live caret when motion is off", () => {
    expect(block('.app[data-motion="off"] .call-live::after')).toContain(
      "animation: none",
    );
  });

  it("paints the call only from shell tokens", () => {
    // The `.call-*` block is the tail of the file; every earlier `@media` string is identical.
    const start = css.indexOf("/* real-time call");
    expect(
      start,
      "the call styles moved out of styles.css, where main.tsx imports them",
    ).toBeGreaterThan(-1);
    const call = css.slice(start);
    expect(
      call.match(/#[0-9a-f]{3,6}\b/gi),
      "a literal colour will not follow the theme",
    ).toBeNull();
    for (const token of [
      "--accent",
      "--panel",
      "--panel-2",
      "--line",
      "--muted",
      "--bad",
    ]) {
      expect(call, `.call-* never reads ${token}`).toContain(`var(${token})`);
    }
  });
});

function colorOf(source: string, token: string): [number, number, number] {
  const value =
    source.match(new RegExp(`${token}:\\s*([^;]+);`))?.[1].trim() ?? "";
  const hex = value.match(/^#([0-9a-f]{6})$/i);
  if (hex) {
    const n = Number.parseInt(hex[1], 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  }
  const rgb = value.match(/^rgb\(\s*(\d+)[ ,]+(\d+)[ ,]+(\d+)\s*\)$/);
  if (rgb) return [Number(rgb[1]), Number(rgb[2]), Number(rgb[3])];
  throw new Error(`cannot read ${token} from "${value}"`);
}

function contrast(
  a: [number, number, number],
  b: [number, number, number],
): number {
  const luminance = ([r, g, bl]: [number, number, number]) => {
    const channel = (v: number) => {
      const s = v / 255;
      return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
    };
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(bl);
  };
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

describe("the companion card", () => {
  it("paints nothing behind the card, which is the only way a transparent window is transparent", () => {
    // pywebview's `transparent` shows the desktop through whatever the page leaves unpainted. `body`
    // paints --ink and `.app[data-shell]` paints a themed gradient over it, so both are switched off
    // for this window alone, by the attribute the screen sets before it renders.
    const page = inside(css, 'html[data-window="companion"] body');
    expect(page).toContain("background: transparent");
    const shell = inside(css, ".companion-window");
    expect(shell).toContain("background: transparent");
    expect(shell).toContain("overflow: hidden");
    expect(shell).toContain("height: 100dvh");
  });

  it("is a card you can see the desk through, not a second app window", () => {
    const card = inside(css, ".companion");
    expect(card).toContain("color-mix");
    expect(card).toContain("flex-direction: column");
    expect(card).toContain("border-radius");
    // An opaque --panel would be a rectangle of chrome; the card is the same colour with a hole in it.
    expect(card).not.toMatch(/background: var\(--panel\);/);
  });

  it("lets the body take the card's height and keeps the controls on screen with it", () => {
    // The app's stage keeps a 3:4 portrait; in a 320x420 window that pushes the click-through switch
    // and `hide` below the fold, and a control you cannot reach is not a control.
    expect(inside(css, ".companion .avatar-stage")).toContain("min-height: 0");
    const canvas = inside(css, ".companion .avatar-stage canvas");
    expect(canvas).toContain("max-height: 100%");
    expect(canvas).toContain("background: transparent");
    expect(inside(css, ".companion-bar")).toContain(
      "justify-content: space-between",
    );
  });
});
