/**
 * The stage: one loaded body, the idle motion from `animate.ts`, and a renderer it never sees.
 *
 * `createStage` takes the drawing away as an injected host for the same reason `load.ts` takes texture
 * decoding as one. A `WebGLRenderer` needs a canvas and a GL context, and neither exists in jsdom, so
 * without the seam the only way to learn whether Kira blinks is to look at her. With it, the suite
 * drives `frame()` with numbers and reads back `morphTargetInfluences` and bone rotations, and the page
 * side is one function that calls `render`.
 *
 * What is smoothed, and what is not, is a decision rather than a default. The blink and the breath are
 * written straight through: `animate.ts` already hands back a curve that starts and ends at rest, and
 * filtering it would only make the eye slower to shut. The head, the mouth and the mood come from
 * outside — a pointer, an `AnalyserNode`, a button — so they are noisy and they get `approach`.
 */

import { AmbientLight, DirectionalLight, PerspectiveCamera, Scene, Vector3 } from "three";
import type { BufferGeometry, Bone } from "three";
import { MOOD_KEYS, VISEME_KEYS } from "./pmx.ts";
import { DEFAULT_BLINKS, approach, blinkAt, breath, lookAt, visemeWeights } from "./animate.ts";
import type { LoadedCharacter } from "./load.ts";

/** What only the page can do: turn this scene and camera into pixels on a canvas. */
export interface StageRenderer {
  draw(scene: Scene, camera: PerspectiveCamera): void;
  dispose(): void;
}

export interface StageFrame {
  /** seconds since the stage started */
  t: number;
  /** playback loudness, 0-1, from the call's analyser — 0 whenever nothing is playing */
  level: number;
  /** the pointer over the pane, -1..1 on each axis, or null when it is elsewhere */
  pointer: { x: number; y: number } | null;
}

export type Mood = (typeof MOOD_KEYS)[number];

export interface StageOptions {
  /** blink onsets, so a caller can hold the schedule still in a test */
  blinks?: readonly number[];
  /** how fast the head chases the pointer, and the mouth the meter, per second */
  headRate?: number;
  mouthRate?: number;
  moodRate?: number;
}

export interface Stage {
  readonly scene: Scene;
  readonly camera: PerspectiveCamera;
  /** what this body cannot do, in the order the stage found out */
  readonly findings: string[];
  frame(frame: StageFrame): void;
  setMood(mood: Mood | null): void;
  dispose(): void;
}

/** The bone the chest turns on, and the bone the face turns on. PMX names both, in this spelling. */
const UPPER_BODY = "上半身";
const HEAD = "頭";

/** The lid morph. `まばたき２` and `まばたき３` are half-closed variants, and the plain one is the blink. */
const BLINK_MORPH = "まばたき";

/** Per second. A head that takes ~0.5 s to arrive is a head that looks thought about. */
const HEAD_RATE = 6;
/** The meter speaks every 20 ms; the mouth should be open by the next few frames and gone soon after. */
const MOUTH_RATE = 18;
/** A mood is a choice someone made, so it settles rather than snaps. */
const MOOD_RATE = 5;

/** Degrees. A portrait lens — wide enough that the face stays flat, tight enough that the shoes leave. */
const STAGE_FOV = 18;
/**
 * The share of a body's own height a portrait shows.
 *
 * Measured across the ten donor bodies rather than picked: each is 18.4-22.9 units tall and each head bone
 * sits 11-15 % below the top of the hair, so one fraction frames all of them, and a body twice the size of
 * another is framed the same portrait because it is asked for the same share of itself.
 */
const FRAME_SHARE = 0.36;
/** Where the head is when the file gives no bone to read: the middle of that 11-15 % band, below the top. */
const HEAD_BELOW_TOP = 0.13;
/** A mesh with no vertices to measure still has to be framed, so it gets the corpus's own median height. */
const UNKNOWN_BODY = 20;

function boneByName(bones: Bone[], name: string): Bone | undefined {
  return bones.find((bone) => bone.name === name);
}

/** The body's own height, straight off the bind-pose vertices — the only numbers every model certainly has. */
function bodySpan(geometry: BufferGeometry): { low: number; high: number } {
  const position = geometry.getAttribute("position") as { array: ArrayLike<number>; count: number; itemSize: number } | undefined;
  if (position === undefined || position.count === 0) return { low: 0, high: UNKNOWN_BODY };
  let low = Number.POSITIVE_INFINITY;
  let high = Number.NEGATIVE_INFINITY;
  for (let at = 0; at < position.count; at += 1) {
    const y = position.array[at * position.itemSize + 1];
    if (y < low) low = y;
    if (y > high) high = y;
  }
  return Number.isFinite(low) ? { low, high } : { low: 0, high: UNKNOWN_BODY };
}

/** How far back a `STAGE_FOV` lens has to sit to show `height` units of the subject. */
function distanceFor(height: number): number {
  return height / (2 * Math.tan(((STAGE_FOV / 2) * Math.PI) / 180));
}

/**
 * Put one loaded character on a stage.
 *
 * Nothing here fetches, decodes or draws. The character arrives from `loadCharacter`, the drawing
 * arrives as a host, and what leaves is a face that breathes, blinks, follows the pointer, and moves
 * its mouth at whatever level the call hands it.
 */
export function createStage(loaded: LoadedCharacter, renderer: StageRenderer, options: StageOptions = {}): Stage {
  const scene = new Scene();
  scene.add(loaded.object);

  const upperBody = boneByName(loaded.bones, UPPER_BODY);
  const head = boneByName(loaded.bones, HEAD);
  const lid = loaded.morphs.get(BLINK_MORPH);
  const visemes = VISEME_KEYS.map((key) => [key, loaded.morphs.get(key)] as const);
  const moods = MOOD_KEYS.map((key) => [key, loaded.morphs.get(key)] as const);

  // A portrait card, because that is the shape the pane is — and the height of a portrait is a property of
  // the body being drawn, not of the app. The first version of this line aimed at y=13.4 because "a body
  // stands about 15 units" is what the format note says; every body in the corpus stands 18-23, so the pane
  // showed everyone from the collarbone down and cut their head off.
  const { low, high } = bodySpan(loaded.geometry);
  const tall = Math.max(high - low, 1);
  const headY = head === undefined ? high - tall * HEAD_BELOW_TOP : head.getWorldPosition(new Vector3()).y;
  const frame = tall * FRAME_SHARE;
  const aim = headY - tall * 0.03;
  const camera = new PerspectiveCamera(STAGE_FOV, 3 / 4, 0.1, 100);
  // On the -Z side, because that is where every face in the corpus actually is: the vertices the `あ` and
  // `まばたき` morphs move sit at z ≈ -0.4 to -1.1 in all ten bodies, while the head bone sits near z=0.
  // The winding agrees with the stored normals 99.9 % of the time as the file has it, so nothing is mirrored
  // on the way in and the camera has to go to the face rather than the face turned to the camera.
  camera.position.set(0, aim + frame * 0.06, -distanceFor(frame));
  camera.lookAt(0, aim, 0);

  // `MeshToonMaterial` answers to lights, so a scene without them is a silhouette. A directional light
  // is rays, not a lamp: only its direction matters, and this one comes from the camera's own side and
  // above — the face lit, not backlit — with a fill that keeps the underside of the chin from going flat black.
  const key = new DirectionalLight(0xffffff, 1);
  key.position.set(0.35, 0.6, -1);
  scene.add(key, new AmbientLight(0xffffff, 0.55));

  const blinks = options.blinks ?? DEFAULT_BLINKS;
  const headRate = options.headRate ?? HEAD_RATE;
  const mouthRate = options.mouthRate ?? MOUTH_RATE;
  const moodRate = options.moodRate ?? MOOD_RATE;

  const findings: string[] = [];
  if (upperBody === undefined) findings.push(`no '${UPPER_BODY}' bone, so this body has no chest to breathe with`);
  if (head === undefined) findings.push(`no '${HEAD}' bone, so this body has no head to turn toward the pointer`);
  if (lid === undefined) findings.push(`no '${BLINK_MORPH}' morph, so the eye stays open`);
  const sightless = visemes.filter(([, slot]) => slot === undefined).map(([key]) => key);
  if (sightless.length > 0) {
    findings.push(`${sightless.join(", ")} — no morph by that exact name, so nothing moves for those sounds`);
  }
  const moodless = moods.filter(([, slot]) => slot === undefined).map(([key]) => key);
  if (moodless.length > 0 && moodless.length === moods.length) {
    findings.push(`no ${moodless.join(" / ")} morphs, so the face holds one expression`);
  }

  const influences = loaded.mesh.morphTargetInfluences ?? [];
  let mood: Mood | null = null;
  let lastT: number | null = null;
  let disposed = false;

  /** Settle one influence toward a target, with `dt` of the last frame — the noisy inputs only. */
  const chase = (slot: number | undefined, target: number, dt: number, rate: number) => {
    if (slot === undefined || influences[slot] === undefined) return;
    influences[slot] = approach(influences[slot], target, dt, rate);
  };

  return {
    scene,
    camera,
    findings,

    frame(next) {
      if (disposed) return;
      const dt = lastT === null ? 1 / 60 : Math.max(next.t - lastT, 0);
      lastT = next.t;

      if (upperBody !== undefined) upperBody.rotation.x = breath(next.t);
      if (lid !== undefined && influences[lid] !== undefined) influences[lid] = blinkAt(next.t, blinks);

      if (head !== undefined) {
        const target = lookAt(next.pointer ?? { x: 0, y: 0 });
        head.rotation.y = approach(head.rotation.y, target.yaw, dt, headRate);
        head.rotation.x = approach(head.rotation.x, target.pitch, dt, headRate);
      }

      const mouth = visemeWeights(next.level);
      for (const [key, slot] of visemes) chase(slot, mouth[key] ?? 0, dt, mouthRate);
      for (const [key, slot] of moods) chase(slot, mood === key ? 1 : 0, dt, moodRate);

      renderer.draw(scene, camera);
    },

    setMood(next) {
      mood = next;
    },

    dispose() {
      if (disposed) return;
      disposed = true;
      scene.remove(loaded.object);
      loaded.dispose();
      renderer.dispose();
    },
  };
}
