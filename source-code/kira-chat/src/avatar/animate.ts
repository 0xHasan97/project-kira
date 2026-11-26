/**
 * The motion a body needs when nobody is asking anything of it.
 *
 * Everything here is a pure function of seconds and levels, for one reason: the renderer that turns
 * these numbers into a face is a `WebGLRenderer` behind a canvas, and a test suite that cannot open a
 * GL context still has to know whether Kira blinks twice a second or never returns to a closed eye.
 * So the shapes live here, `stage.ts` applies them, and the jsdom suite reads the numbers.
 *
 * The units are deliberate. Angles are radians on the bone's own local axes, times are seconds since
 * the stage started, and every weight is 0-1 where 1 is the morph's full published offset — the same
 * scale `mesh.morphTargetInfluences` takes.
 */

import { VISEME_KEYS } from "./pmx.ts";

/** How long one blink holds the eye shut, at its widest. Longer reads as a wink. */
export const BLINK_DURATION_S = 0.18;

/** A resting face blinks every 2.5-6 s. The range is the literature's, not a taste call. */
export const BLINK_GAP_RANGE_S = [2.5, 6] as const;

/**
 * The floor under any two blinks.
 *
 * It is above `BLINK_DURATION_S` on purpose: that single inequality is what lets `blinkAt` add up
 * whatever windows are open without ever seeing two, which is the difference between a blink and a
 * flutter.
 */
export const BLINK_MIN_GAP_S = 1;

/** Seconds for one full breath — in, out, and back to where the chest started. */
export const BREATH_PERIOD_S = 4;

/** Radians of pitch the upper body takes at the top of a breath. This is a chest, not a seesaw. */
export const BREATH_MAX_RAD = 0.035;

/** What a neck does. Past these the bone snaps sideways and the face stops looking interested. */
export const NECK_LIMITS = { yaw: 0.61, pitch: 0.35 };

/**
 * The playback level at which each vowel is the closest shape.
 *
 * There is no pitch here — the meter measures loudness, so loudness chooses the opening and the band
 * chooses which of the five openings that is. Ascending order is what makes a rising level walk
 * あ→い→う→え→お instead of jittering between them.
 */
export const VISEME_BANDS = [0.05, 0.18, 0.34, 0.52, 0.72] as const;

export type VisemeWeight = Partial<Record<(typeof VISEME_KEYS)[number], number>>;

const clamp = (value: number, low: number, high: number) => Math.min(Math.max(value, low), high);

/**
 * Blink onsets, deterministic per seed.
 *
 * A seeded walk rather than `Math.random()` because the stage re-derives its schedule after a reload
 * and a face that blinks on a different beat every time the screen opens is untestable and uncanny.
 */
export function blinkOnsets(seed = 7, horizonS = 3600): number[] {
  // Numerical Recipes' LCG: no dependency, no state, and the period is far longer than a sitting.
  let state = (seed >>> 0) || 1;
  const next = () => {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
    return state / 0x100000000;
  };
  const [shortest, longest] = BLINK_GAP_RANGE_S;
  const onsets: number[] = [];
  for (let at = shortest + next() * (longest - shortest); at < horizonS; at += shortest + next() * (longest - shortest)) {
    onsets.push(at);
  }
  return onsets;
}

/** The schedule the stage blinks on unless it is handed another one. */
export const DEFAULT_BLINKS = blinkOnsets();

/**
 * How shut the eye is at time `t`: 0 open, 1 closed, and back to 0 by `BLINK_DURATION_S`.
 *
 * A half-sine, because it starts and ends at zero velocity — the shape a lid has. The scan stops at
 * the first onset in the future, which is what keeps an hour of schedule cheap per frame.
 */
export function blinkAt(t: number, onsets: readonly number[] = DEFAULT_BLINKS): number {
  let low = 0;
  let high = onsets.length;
  while (low < high) {
    const middle = (low + high) >> 1;
    if (onsets[middle] > t) high = middle;
    else low = middle + 1;
  }
  const onset = onsets[low - 1];
  if (onset === undefined || t - onset >= BLINK_DURATION_S) return 0;
  return Math.sin(((t - onset) / BLINK_DURATION_S) * Math.PI);
}

/** The upper body's pitch at time `t`, in radians, centred on 0 so a held pose is not breathing. */
export function breath(t: number): number {
  return BREATH_MAX_RAD * Math.sin((2 * Math.PI * t) / BREATH_PERIOD_S);
}

export interface LookTarget {
  /** -1 at the left edge of the pane, 1 at the right */
  x: number;
  /** -1 at the top, 1 at the bottom */
  y: number;
}

/** Where the head points, with the pointer's reach clamped to what a neck does. */
export function lookAt(target: LookTarget, limits = NECK_LIMITS): { yaw: number; pitch: number } {
  // The yaw goes with the pointer because the camera stands where the face points (-Z): screen-right is
  // world -X there, and a positive turn about +Y takes a nose at -Z toward -X. The pitch is negated for the
  // same reason read the other way — a pointer at the top of the pane is `-1`, and the top of the pane is
  // where a face looks when it tips its nose up.
  return {
    yaw: clamp(target.x, -1, 1) * limits.yaw,
    // `0 - target.y` rather than `-target.y`: a pointer dead centre is `0`, and a unary minus would hand
    // back `-0`, which is a different number to every comparison that cares about identity.
    pitch: clamp(0 - target.y, -1, 1) * limits.pitch,
  };
}

/**
 * The five mouth shapes for one loudness reading.
 *
 * Exactly one slot opens, by as much as the level itself: a whisper moves the jaw a whisper's
 * distance, and silence returns every slot to 0 so the morphs let go instead of holding a shape.
 */
export function visemeWeights(level: number): Required<VisemeWeight> {
  const open = clamp(level, 0, 1);
  const weights = { "あ": 0, "い": 0, "う": 0, "え": 0, "お": 0 } as Required<VisemeWeight>;
  if (open <= 0) return weights;
  let nearest = 0;
  for (let band = 1; band < VISEME_BANDS.length; band += 1) {
    if (Math.abs(VISEME_BANDS[band] - open) < Math.abs(VISEME_BANDS[nearest] - open)) nearest = band;
  }
  weights[VISEME_KEYS[nearest]] = open;
  return weights;
}

/**
 * Move `current` toward `target` at a rate, not a step.
 *
 * The exponential form is frame-rate independent, which matters because the same numbers have to look
 * the same on a 60 Hz laptop and a 120 Hz phone; `dt` of 0 holds, so a paused stage stays put.
 */
export function approach(current: number, target: number, dt: number, perSecond: number): number {
  return target + (current - target) * Math.exp(-perSecond * dt);
}
