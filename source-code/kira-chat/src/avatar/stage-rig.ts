/**
 * A body a test can hold.
 *
 * `stage.test.ts` and `AvatarStage.test.tsx` both need a `LoadedCharacter` that is real enough for three
 * to animate — actual `Bone`s, a `Mesh` with `morphTargetInfluences`, a `Group` the stage can mount and
 * take away — without a `KRM1` payload behind it. This is that rig, and the only reason it is a module
 * rather than a test helper is that two suites drive it.
 */
import { Bone, BufferGeometry, Float32BufferAttribute, Group, Mesh } from "three";
import type { LoadedCharacter } from "./load.ts";

/** A body that can do everything: blink, five vowels, four moods. */
export const FULL = ["まばたき", "あ", "い", "う", "え", "お", "笑い", "怒り", "悲しむ", "びっくり"];

/**
 * Ellen's own measurements, from the archive the browser pass imported.
 *
 * The rig is a body the stage has to frame, so it carries the numbers a real body has: the chest bone at
 * 11.07, the head at 16.29, vertices from -0.17 to 19.23. Those are what `kira-engine` reads out of
 * `9y5Huh14gN.zip`, and a rig invented at a rounder height would let a wrong camera pass its tests.
 */
const CHEST_Y = 11.07;
const HEAD_Y = 16.29;
const CHEST_Z = -0.22;
const HEAD_Z = 0.25;
const FOOT_Y = -0.17;
const HAIR_Y = 19.23;

export interface Rig {
  upperBody: Bone;
  head: Bone;
  influences: number[];
  slot(name: string): number;
  loaded: LoadedCharacter;
  /** how many times the pane gave the body back */
  disposed: { count: number };
}

export function rig(names: string[], boneNames = ["上半身", "頭"]): Rig {
  // three's `Bone` constructor takes no name — `new Bone("頭")` would be a bone called "Bone", and the
  // stage looks its parts up by the name the PMX gives them.
  const upperBody = new Bone();
  upperBody.name = "上半身";
  upperBody.position.set(0, CHEST_Y, CHEST_Z);
  const head = new Bone();
  head.name = "頭";
  // A bone holds its own translation relative to whatever it is hung from, which is how `load.ts` fills it
  // in from the file's absolute positions — so the rig subtracts the same way.
  head.position.set(0, HEAD_Y - CHEST_Y, HEAD_Z - CHEST_Z);
  upperBody.add(head);
  const group = new Group();
  group.add(upperBody);
  const influences = new Array(names.length).fill(0);
  const morphs = new Map(names.map((name, at) => [name, at]));
  const mesh = new Mesh(new BufferGeometry());
  mesh.geometry.setAttribute("position", new Float32BufferAttribute([0, FOOT_Y, 0, 0, HAIR_Y, 0], 3));
  mesh.morphTargetInfluences = influences;
  const disposed = { count: 0 };
  const loaded = {
    object: group,
    mesh,
    geometry: mesh.geometry,
    materials: [],
    skeleton: null,
    bones: boneNames.map((name) => (name === "上半身" ? upperBody : head)),
    textures: new Map(),
    morphs,
    morphTableIndexes: new Map(),
    findings: [],
    dispose: () => {
      disposed.count += 1;
    },
  } as unknown as LoadedCharacter;
  return {
    upperBody,
    head,
    influences,
    slot: (name: string) => names.indexOf(name),
    loaded,
    disposed,
  };
}
