import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import type { Scene } from "three";
import { describe, expect, it } from "vitest";
import { NECK_LIMITS, BLINK_DURATION_S, blinkOnsets, breath } from "./animate.ts";
import { createStage } from "./stage.ts";
import type { Rig } from "./stage-rig.ts";
import { FULL, rig } from "./stage-rig.ts";

/** One frame of everything the stage reads: the clock, the meter, and where the pointer is. */
function frame(t: number, level = 0, pointer: { x: number; y: number } | null = null) {
  return { t, level, pointer };
}

/** Run the clock forward in 60 Hz steps so the smoothing settles the way it does on a real frame loop. */
function runTo(stage: ReturnType<typeof createStage>, from: number, to: number, level = 0) {
  for (let t = from; t <= to + 1e-9; t += 1 / 60) stage.frame(frame(t, level));
}

function stageFor(body: Rig, draw?: (scene: Scene) => void) {
  const calls: { scene: Scene }[] = [];
  const stage = createStage(body.loaded, {
    draw: (scene) => {
      calls.push({ scene });
      draw?.(scene);
    },
    dispose: () => {},
  });
  return { stage, calls };
}

describe("the stage's idle motion", () => {
  it("closes the eye the model publishes, on the schedule and nowhere else", () => {
    const body = rig(FULL);
    const { stage } = stageFor(body);
    const onsets = blinkOnsets();
    const lid = body.slot("まばたき");

    runTo(stage, 0, onsets[0] + BLINK_DURATION_S / 2);
    expect(body.influences[lid]).toBeGreaterThan(0.95);

    runTo(stage, onsets[0] + BLINK_DURATION_S + 0.2, onsets[1] - 0.2);
    expect(body.influences[lid]).toBe(0);
  });

  it("breathes with the upper body and leaves the head alone", () => {
    const body = rig(FULL);
    const { stage } = stageFor(body);
    stage.frame(frame(1.0));
    expect(body.upperBody.rotation.x).toBeCloseTo(breath(1.0), 6);
    expect(body.head.rotation.x).toBe(0);
  });

  it("turns the head toward the pointer and stops where a neck stops", () => {
    const body = rig(FULL);
    const { stage } = stageFor(body);
    runTo(stage, 0, 3, 0);
    for (let t = 3; t <= 6; t += 1 / 60) stage.frame(frame(t, 0, { x: 9, y: -9 }));
    expect(body.head.rotation.y).toBeGreaterThan(NECK_LIMITS.yaw - 0.01);
    expect(body.head.rotation.y).toBeLessThanOrEqual(NECK_LIMITS.yaw + 1e-6);
    // A pointer at the top of the pane tips the nose up, which is a positive turn about +X for a face
    // looking down -Z.
    expect(body.head.rotation.x).toBeGreaterThanOrEqual(NECK_LIMITS.pitch - 0.05);
    expect(body.head.rotation.x).toBeLessThanOrEqual(NECK_LIMITS.pitch + 1e-6);
  });

  it("says which part is missing instead of pretending to move it", () => {
    const body = rig(["あ"], ["頭"]);
    const { stage } = stageFor(body);
    stage.frame(frame(0.5));
    expect(stage.findings.join("\n")).toContain("まばたき");
    expect(stage.findings.join("\n")).toContain("上半身");
    expect(body.influences[body.slot("あ")]).toBe(0);
  });

  it("names a body with no bones at all", () => {
    const body = rig(FULL, []);
    const { stage } = stageFor(body);
    stage.frame(frame(0.5));
    expect(stage.findings.join("\n")).toContain("頭");
  });

  it("lights the body, because a toon material in the dark is a silhouette", () => {
    const body = rig(FULL);
    const { stage } = stageFor(body);
    const lights = stage.scene.children.filter((child) => (child as { isLight?: boolean }).isLight);
    expect(lights).toHaveLength(2);
    // A directional key that comes from the camera's side and above, so the face is lit and not backlit.
    // The camera is on -Z (see the next test), so the light has to be on -Z too — a lamp behind the head
    // lights the back of the skull and leaves the face a mask.
    const key = lights.find((light) => (light as { isDirectionalLight?: boolean }).isDirectionalLight);
    expect(key?.position.z).toBeLessThan(0);
    expect(key?.position.y).toBeGreaterThan(0);
  });

  it("stands where the face is, and frames the head rather than the collarbone", () => {
    const body = rig(FULL);
    const { stage } = stageFor(body);
    // Every body in the corpus has its mouth and eyelid vertices at negative z — measured across all ten,
    // -0.4 to -1.1 — while the head bone sits near z=0. A camera at +Z therefore films the back of the head,
    // which is exactly what the first browser pass caught.
    expect(stage.camera.position.z).toBeLessThan(0);
    // And the aim comes from this body, not from a number written down for a shorter one: the head is at
    // 16.29 and the pane is a portrait, so the centre lands near the chin, well above the chest.
    expect(stage.camera.position.y).toBeGreaterThan(14);
    expect(stage.camera.position.y).toBeLessThan(18);
    // Close enough that a 19-unit body does not fill the frame with its own sternum: the visible height at
    // the aim is a third of the body, so the head and the shoulders are in and the shoes are out.
    const visible = 2 * Math.abs(stage.camera.position.z) * Math.tan(((stage.camera.fov / 2) * Math.PI) / 180);
    expect(visible).toBeGreaterThan(5);
    expect(visible).toBeLessThan(9);
  });

  it("frames a body with no head bone by the vertices it does have", () => {
    const body = rig(FULL, ["上半身"]);
    const { stage } = stageFor(body);
    // 19.23 - 0.17 = 19.4 tall, and the corpus's heads sit 11-15 % below the top of the hair.
    expect(stage.camera.position.z).toBeLessThan(0);
    expect(stage.camera.position.y).toBeGreaterThan(15);
    expect(stage.camera.position.y).toBeLessThan(18);
  });
});

describe("the stage's mouth", () => {
  it("stays shut at silence", () => {
    const body = rig(FULL);
    const { stage } = stageFor(body);
    runTo(stage, 0, 2, 0);
    for (const name of ["あ", "い", "う", "え", "お"]) expect(body.influences[body.slot(name)]).toBe(0);
  });

  it("opens the shape the level is nearest, and only that one", () => {
    const body = rig(FULL);
    const { stage } = stageFor(body);
    runTo(stage, 0, 2, 0.52);
    const open = FULL.slice(1, 6).filter((name) => body.influences[body.slot(name)] > 0.05);
    expect(open).toEqual(["え"]);
    expect(body.influences[body.slot("え")]).toBeGreaterThan(0.45);
  });

  it("lets go when the audio does", () => {
    const body = rig(FULL);
    const { stage } = stageFor(body);
    runTo(stage, 0, 2, 0.72);
    expect(body.influences[body.slot("お")]).toBeGreaterThan(0.5);
    runTo(stage, 2.02, 5, 0);
    for (const name of ["あ", "い", "う", "え", "お"]) {
      expect(body.influences[body.slot(name)], name).toBeLessThan(0.02);
    }
  });

  it("holds one mood at a time, and none when the user picks none", () => {
    const body = rig(FULL);
    const { stage } = stageFor(body);
    runTo(stage, 0, 2, 0);
    stage.setMood("笑い");
    runTo(stage, 2.02, 5, 0);
    expect(body.influences[body.slot("笑い")]).toBeGreaterThan(0.95);
    expect(body.influences[body.slot("怒り")]).toBe(0);
    stage.setMood("怒り");
    runTo(stage, 5.02, 8, 0);
    expect(body.influences[body.slot("笑い")]).toBeLessThan(0.05);
    expect(body.influences[body.slot("怒り")]).toBeGreaterThan(0.95);
    stage.setMood(null);
    runTo(stage, 8.02, 11, 0);
    expect(body.influences[body.slot("怒り")]).toBeLessThan(0.05);
  });

  it("drives the mouth even when the model has no visemes", () => {
    const body = rig(["まばたき"]);
    const { stage } = stageFor(body);
    runTo(stage, 0, 2, 0.9);
    expect(stage.findings.join("\n")).toContain("あ");
    expect(body.influences).toEqual([0]);
  });
});

describe("the seam", () => {
  it("draws through the host it was handed, once per frame", () => {
    const body = rig(FULL);
    const { stage, calls } = stageFor(body);
    stage.frame(frame(0.2));
    stage.frame(frame(0.4));
    expect(calls).toHaveLength(2);
    expect(calls[0].scene.children).toContain(body.loaded.object);
  });

  it("stops drawing after dispose and gives the rig back", () => {
    const body = rig(FULL);
    const { stage, calls } = stageFor(body);
    stage.dispose();
    stage.frame(frame(0.2));
    expect(calls).toHaveLength(0);
    expect(body.disposed.count).toBe(1);
  });

  it("constructs no renderer, because that is the whole point of the seam", () => {
    // The claim in the header comment, pinned: this module may import three, but never the thing that
    // needs a GL context. A jsdom suite that opened one would fail here rather than on a machine with no GPU.
    // The name is allowed in prose — only an import or a construction means the module reached for it.
    const source = readFileSync(resolve(process.cwd(), "src/avatar/stage.ts"), "utf8");
    expect(source).not.toMatch(/import\s*\{[^}]*\bWebGLRenderer\b/s);
    expect(source).not.toContain("new WebGLRenderer");
    expect(source).not.toContain("createElement");
  });
});
