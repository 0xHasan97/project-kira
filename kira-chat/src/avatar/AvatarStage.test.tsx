import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { CharacterProfile } from "../contracts.ts";
import { AvatarStage, browserSeams } from "./AvatarStage.tsx";
import type { StageSeams } from "./AvatarStage.tsx";
import { loadCharacter } from "./load.ts";
import type { LoadedCharacter, MeshSource, StageHost } from "./load.ts";
import { createCanvasRenderer } from "./browser.ts";
import { FULL, rig } from "./stage-rig.ts";
import type { Rig } from "./stage-rig.ts";

const PROFILE = { display_name: "Ellen", english_name: "ellen" } as unknown as CharacterProfile;
const SOURCE = {} as MeshSource;

interface Mount {
  body: Rig;
  draws: { count: number; disposed: number };
  playback: { current: number };
  host: StageHost;
  view: ReturnType<typeof render>;
  paint(ms?: number): Promise<void>;
  /** Same character, new object — which is exactly what a re-pull of the library hands back. */
  reload(): void;
}

/**
 * Mount the pane on fakes.
 *
 * The three things a browser owns — the loader, the pixels, the GL context — all arrive through
 * `StageSeams`, so nothing here ever asks for a canvas that can draw. Timers are faked because the loop is
 * `requestAnimationFrame`, and a test that waits on real frames is a test that flakes.
 */
function mount(options: { body?: Rig; load?: StageSeams["load"]; renderer?: StageSeams["renderer"]; level?: number; moods?: boolean } = {}): Mount {
  vi.useFakeTimers();
  const body = options.body ?? rig(FULL);
  const draws = { count: 0, disposed: 0 };
  const host: StageHost = {
    imageTexture: () => {
      throw new Error("the rig already holds its own pixels");
    },
  };
  const seams: StageSeams = {
    load: options.load ?? (async () => body.loaded),
    host,
    renderer:
      options.renderer ??
      (() => ({
        draw: () => {
          draws.count += 1;
        },
        dispose: () => {
          draws.disposed += 1;
        },
      })),
  };
  const playback = { current: options.level ?? 0 };
  const stage = (profile: CharacterProfile) => (
    <AvatarStage source={SOURCE} profile={profile} playbackLevel={playback} seams={seams} moods={options.moods ?? true} />
  );
  const view = render(stage(PROFILE));
  const paint = async (ms = 16) => {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(ms);
    });
  };
  return {
    body,
    draws,
    playback,
    host,
    view,
    paint,
    reload: () => view.rerender(stage({ ...PROFILE })),
  };
}

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("the stage pane", () => {
  it("puts the body on the canvas it was given and draws it every frame", async () => {
    const pane = mount();
    expect(pane.view.container.querySelector(".avatar-stage")?.getAttribute("data-status")).toBe("loading");
    await pane.paint();
    const canvas = screen.getByLabelText("Ellen on stage") as HTMLCanvasElement;
    expect(canvas.hidden).toBe(false);
    expect(pane.view.container.querySelector(".avatar-stage")?.getAttribute("data-status")).toBe("drawing");
    expect(pane.draws.count).toBeGreaterThan(0);
    const before = pane.draws.count;
    await pane.paint(160);
    expect(pane.draws.count).toBeGreaterThan(before);
  });

  it("opens the mouth on what the call reports, and lets go when it stops", async () => {
    const pane = mount();
    await pane.paint(2000);
    const mouth = ["あ", "い", "う", "え", "お"];
    for (const name of mouth) expect(pane.body.influences[pane.body.slot(name)], name).toBe(0);

    // 0.52 display units is the `え` band; the jaw chases it, so it takes a few frames to arrive.
    pane.playback.current = 0.52;
    await pane.paint(1000);
    expect(pane.body.influences[pane.body.slot("え")]).toBeGreaterThan(0.45);
    for (const name of mouth.filter((key) => key !== "え")) {
      expect(pane.body.influences[pane.body.slot(name)], name).toBeLessThan(0.02);
    }

    pane.playback.current = 0;
    await pane.paint(3000);
    expect(pane.body.influences[pane.body.slot("え")]).toBeLessThan(0.02);
  });

  it("turns the head toward a pointer on the pane, and back when it leaves", async () => {
    const pane = mount();
    await pane.paint(100);
    const canvas = screen.getByLabelText("Ellen on stage") as HTMLCanvasElement;
    canvas.getBoundingClientRect = () => ({ left: 0, top: 0, width: 360, height: 480, right: 360, bottom: 480, x: 0, y: 0, toJSON: () => ({}) }) as DOMRect;

    fireEvent.pointerMove(canvas, { clientX: 356, clientY: 240 });
    await pane.paint(3000);
    expect(pane.body.head.rotation.y).toBeGreaterThan(0.5);

    fireEvent.pointerLeave(canvas);
    await pane.paint(3000);
    expect(pane.body.head.rotation.y).toBeLessThan(0.05);
  });

  it("wears the mood the user picks, and none when they pick none", async () => {
    const pane = mount();
    await pane.paint(100);
    expect(pane.body.influences[pane.body.slot("笑い")]).toBe(0);

    fireEvent.click(screen.getByRole("button", { name: "happy" }));
    await pane.paint(3000);
    expect(pane.body.influences[pane.body.slot("笑い")]).toBeGreaterThan(0.95);
    expect(pane.body.influences[pane.body.slot("怒り")]).toBe(0);

    fireEvent.click(screen.getByRole("button", { name: "stern" }));
    await pane.paint(3000);
    expect(pane.body.influences[pane.body.slot("笑い")]).toBeLessThan(0.05);
    expect(pane.body.influences[pane.body.slot("怒り")]).toBeGreaterThan(0.95);
    expect((screen.getByRole("button", { name: "stern" }) as HTMLButtonElement).ariaPressed).toBe("true");

    fireEvent.click(screen.getByRole("button", { name: "neutral" }));
    await pane.paint(3000);
    expect(pane.body.influences[pane.body.slot("怒り")]).toBeLessThan(0.05);
  });

  it("offers the moods only once there is a face to wear them", async () => {
    // A disabled button is not an explanation: while the mesh is still arriving there is nothing for a
    // mood to change, so the choice waits with the canvas rather than sitting there promising something.
    let release!: (loaded: LoadedCharacter) => void;
    const pane = mount({ load: () => new Promise<LoadedCharacter>((resolve) => { release = resolve; }) });
    await pane.paint(0);
    expect(screen.queryByRole("button", { name: "surprised" })).toBeNull();

    release(pane.body.loaded);
    await pane.paint(100);
    fireEvent.click(screen.getByRole("button", { name: "surprised" }));
    await pane.paint(3000);
    expect(pane.body.influences[pane.body.slot("びっくり")]).toBeGreaterThan(0.95);
    // The stage is a portrait, a mood row and a findings list — and the pane that holds it is 85dvh of a
    // 900px screen. The 2026-11-02 pass measured the lecture below that height, which is why the take-off
    // button had gone missing; the why-now lives in the library column, next to the buttons it explains.
    expect(pane.view.container.textContent).not.toMatch(/mood is your pick/);
  });

  it("leaves the mood row out of a window that has no room for it", async () => {
    // The desktop card is 320 pixels of face and two controls. Measured on the live card: the row
    // arrived, crowded the name, and left buttons that move her face with nothing on screen to show
    // them — so the pane is asked not to draw them, rather than told to hide them in CSS.
    const pane = mount({ moods: false });
    await pane.paint(100);
    expect(pane.draws.count).toBeGreaterThan(0);
    expect(screen.queryByRole("group", { name: "mood" })).toBeNull();
  });

  it("keeps the mood across a re-pull of the same character", async () => {
    // The library re-reads on a timer, and every read hands back a new profile object. That re-runs the
    // load — and a pick the user already made should not be the first thing to vanish when it does.
    const pane = mount();
    await pane.paint(100);
    fireEvent.click(screen.getByRole("button", { name: "happy" }));
    await pane.paint(3000);
    expect(pane.body.influences[pane.body.slot("笑い")]).toBeGreaterThan(0.95);

    // A real re-pull brings a body that starts at rest; the fake hands back the same one, so put it there.
    pane.body.influences[pane.body.slot("笑い")] = 0;

    pane.reload();
    await pane.paint(3000);
    expect(pane.body.influences[pane.body.slot("笑い")]).toBeGreaterThan(0.95);
    expect((screen.getByRole("button", { name: "happy" }) as HTMLButtonElement).ariaPressed).toBe("true");
  });

  it("says this window cannot draw, and gives the body back", async () => {
    const pane = mount({ renderer: () => null });
    await pane.paint();
    expect(pane.view.getByText(/cannot draw 3D/)).toBeTruthy();
    expect(pane.view.container.querySelector(".avatar-stage")?.getAttribute("data-status")).toBe("no-3d");
    expect(pane.body.disposed.count).toBe(1);
    expect(pane.draws.count).toBe(0);
  });

  it("makes a body that will not load into a line of text", async () => {
    const pane = mount({
      load: () => Promise.reject(new Error("the mesh route said no: character_not_found")),
    });
    await pane.paint();
    expect(pane.view.getByRole("alert").textContent).toContain("cannot put Ellen on stage");
    expect(pane.view.getByRole("alert").textContent).toContain("character_not_found");
    expect(pane.view.container.querySelector(".avatar-stage")?.getAttribute("data-status")).toBe("failed");
  });

  it("stops the loop and hands everything back when the pane goes away", async () => {
    const pane = mount();
    await pane.paint(200);
    const drawn = pane.draws.count;
    expect(drawn).toBeGreaterThan(0);

    pane.view.unmount();
    await pane.paint(1000);
    expect(pane.draws.count).toBe(drawn);
    expect(pane.draws.disposed).toBe(1);
    expect(pane.body.disposed.count).toBe(1);
  });

  it("throws away a body that arrives after the pane already left", async () => {
    let release!: (loaded: LoadedCharacter) => void;
    const pane = mount({ load: () => new Promise<LoadedCharacter>((resolve) => { release = resolve; }) });
    await pane.paint(0);
    pane.view.unmount();
    release(pane.body.loaded);
    await pane.paint(1000);
    expect(pane.body.disposed.count).toBe(1);
    expect(pane.draws.count).toBe(0);
  });

  it("reports what the load could not do, next to the face that shows it", async () => {
    const body = rig(FULL);
    body.loaded.findings.push("hair.bmp — the material names it and the archive never carried it, so the face is drawn in magenta");
    const pane = mount({ body });
    await pane.paint();
    expect(pane.view.getByText(/hair\.bmp/)).toBeTruthy();
  });

  it("borrows the browser's answers rather than building them itself", () => {
    // The default seams are the page's real ones, and the pane never reaches for a GL context by hand —
    // that is what lets every test above run with no canvas at all.
    expect(browserSeams.load).toBe(loadCharacter);
    expect(browserSeams.renderer).toBe(createCanvasRenderer);
    const text = readFileSync(resolve(process.cwd(), "src/avatar/AvatarStage.tsx"), "utf8");
    expect(text).not.toContain("new WebGLRenderer");
  });
});
