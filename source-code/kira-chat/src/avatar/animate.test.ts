import { describe, expect, it } from "vitest";
import {
  BLINK_DURATION_S,
  BLINK_GAP_RANGE_S,
  BLINK_MIN_GAP_S,
  BREATH_MAX_RAD,
  BREATH_PERIOD_S,
  NECK_LIMITS,
  VISEME_BANDS,
  approach,
  blinkAt,
  blinkOnsets,
  breath,
  lookAt,
  visemeWeights,
} from "./animate.ts";
import { VISEME_KEYS } from "./pmx.ts";

/** Every float in this file is a radian, a second or a 0-1 weight; a step of 5 ms is finer than a frame. */
function sweep(from: number, to: number, step: number): Generator<number> {
  return (function* () {
    for (let t = from; t <= to; t += step) yield t;
  })();
}

const ONSETS = blinkOnsets();

describe("blinkAt", () => {
  it("paces the blinks the way a resting face does", () => {
    expect(ONSETS.length).toBeGreaterThan(20);
    expect(ONSETS[0]).toBeGreaterThanOrEqual(0);
    for (let at = 1; at < ONSETS.length; at += 1) {
      const gap = ONSETS[at] - ONSETS[at - 1];
      expect(gap, `blink ${at}`).toBeGreaterThanOrEqual(BLINK_GAP_RANGE_S[0] - 1e-9);
      expect(gap, `blink ${at}`).toBeLessThanOrEqual(BLINK_GAP_RANGE_S[1] + 1e-9);
    }
  });

  it("never fires twice inside a second, because a face that twitches is a bug", () => {
    // The gap is what makes the shape below safe to sum: no two windows can be open at once.
    expect(BLINK_MIN_GAP_S).toBeGreaterThan(BLINK_DURATION_S);
    for (let at = 1; at < ONSETS.length; at += 1) {
      expect(ONSETS[at] - ONSETS[at - 1]).toBeGreaterThanOrEqual(BLINK_MIN_GAP_S);
    }
    for (const t of sweep(0, 60, 0.005)) {
      const value = blinkAt(t, ONSETS);
      expect(value, `t=${t}`).toBeGreaterThanOrEqual(0);
      expect(value, `t=${t}`).toBeLessThanOrEqual(1 + 1e-9);
    }
  });

  it("closes the eye once and all the way, then lets go", () => {
    for (const onset of ONSETS.slice(0, 5)) {
      expect(blinkAt(onset - 0.001, ONSETS)).toBe(0);
      expect(blinkAt(onset + BLINK_DURATION_S / 2, ONSETS)).toBeCloseTo(1, 5);
      expect(blinkAt(onset + BLINK_DURATION_S, ONSETS)).toBeCloseTo(0, 5);
      expect(blinkAt(onset + BLINK_DURATION_S + 0.001, ONSETS)).toBe(0);
    }
  });

  it("is the same schedule every time it is asked, and a different one per seed", () => {
    expect(blinkOnsets(7, 30)).toEqual(blinkOnsets(7, 30));
    expect(blinkOnsets(8, 30)).not.toEqual(blinkOnsets(7, 30));
  });
});

describe("breath", () => {
  it("stays inside the range a chest has", () => {
    for (const t of sweep(0, 120, 0.01)) {
      expect(Math.abs(breath(t)), `t=${t}`).toBeLessThanOrEqual(BREATH_MAX_RAD + 1e-9);
    }
    expect(breath(0)).toBe(0);
  });

  it("comes back to the start every period, so a held pose is not read as breathing", () => {
    for (const period of [1, 7, 31]) {
      expect(breath(period * BREATH_PERIOD_S), `period ${period}`).toBeCloseTo(0, 9);
    }
    expect(breath(BREATH_PERIOD_S / 4)).toBeGreaterThan(0);
    expect(breath((3 * BREATH_PERIOD_S) / 4)).toBeLessThan(0);
  });
});

describe("lookAt", () => {
  it("keeps the neck inside what a neck does", () => {
    // The top of the pane is `y: -1` and the top of the pane is where a face looks when it tips up, so the
    // pitch is the pointer read with its sign turned over. The yaw goes with the pointer unchanged: the
    // camera stands at -Z, facing the same way the nose does, and screen-right is world -X there.
    expect(lookAt({ x: 9, y: -9 })).toEqual({ yaw: NECK_LIMITS.yaw, pitch: NECK_LIMITS.pitch });
    expect(lookAt({ x: -9, y: 9 })).toEqual({ yaw: -NECK_LIMITS.yaw, pitch: -NECK_LIMITS.pitch });
  });

  it("follows a pointer that is inside the frame instead of saturating", () => {
    expect(lookAt({ x: 0, y: 0 })).toEqual({ yaw: 0, pitch: 0 });
    expect(lookAt({ x: 0.5, y: -0.25 })).toEqual({
      yaw: NECK_LIMITS.yaw * 0.5,
      pitch: NECK_LIMITS.pitch * 0.25,
    });
    // A target below the neck limit is a head turn; above it, it is still the same head turn.
    for (const x of [0.1, 0.4, 0.7, 1]) {
      expect(lookAt({ x, y: 0 }).yaw).toBeGreaterThan(lookAt({ x: x - 0.09, y: 0 }).yaw);
    }
    for (const y of [0.1, 0.4, 0.7, 1]) {
      expect(lookAt({ x: 0, y: -y }).pitch).toBeGreaterThan(lookAt({ x: 0, y: -y + 0.09 }).pitch);
    }
  });
});

describe("visemeWeights", () => {
  it("is a closed mouth at silence, in every slot", () => {
    expect(visemeWeights(0)).toEqual({ "あ": 0, "い": 0, "う": 0, "え": 0, "お": 0 });
  });

  it("opens the one shape nearest the level, and only that one", () => {
    for (const [at, level] of VISEME_BANDS.entries()) {
      const weights = visemeWeights(level);
      const open = Object.entries(weights).filter(([, value]) => value > 0);
      expect(open, `band ${at}`).toEqual([[VISEME_KEYS[at], level]]);
    }
  });

  it("walks the five vowels as the level rises, the way a mouth does", () => {
    const seen: string[] = [];
    for (const level of sweep(0, 1, 0.001)) {
      const [name] = Object.entries(visemeWeights(level)).find(([, value]) => value > 0) ?? [];
      if (name && name !== seen[seen.length - 1]) seen.push(name);
    }
    expect(seen).toEqual([...VISEME_KEYS]);
  });

  it("never opens past the level it was given", () => {
    for (const level of sweep(0, 3, 0.01)) {
      const total = Object.values(visemeWeights(level)).reduce((sum, value) => sum + value, 0);
      expect(total, `level=${level}`).toBeLessThanOrEqual(1);
      expect(total, `level=${level}`).toBeLessThanOrEqual(Math.min(level, 1) + 1e-9);
    }
  });
});

describe("approach", () => {
  it("closes the gap without overshooting it", () => {
    let value = 0;
    for (let frame = 0; frame < 400; frame += 1) {
      const next = approach(value, 1, 1 / 60, 12);
      expect(next).toBeGreaterThanOrEqual(value);
      expect(next).toBeLessThanOrEqual(1);
      value = next;
    }
    expect(value).toBeGreaterThan(0.999);
  });

  it("holds still when there is nowhere to go, and walks backwards too", () => {
    expect(approach(0.4, 0.4, 1 / 60, 12)).toBeCloseTo(0.4, 9);
    expect(approach(1, 0, 1 / 60, 12)).toBeLessThan(1);
    expect(approach(1, 0, 0, 12)).toBe(1);
  });
});
