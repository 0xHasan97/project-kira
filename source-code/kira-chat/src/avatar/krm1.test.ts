import { describe, expect, it } from "vitest";
import { KRM1_FIXTURE_BASE64 } from "./krm1-fixture.ts";
import { KRM1_FORMAT, KRM1_MAGIC, Krm1Error, decodeKrm1 } from "./krm1.ts";
import { Pack, minimal } from "./krm1-test-pack.ts";

/**
 * The happy path is proved against bytes the engine itself wrote. `kira-engine/tests/test_krm1_fixture.py`
 * checks that the base64 in `krm1-fixture.ts` is `pack_mesh()` of the fixture parameters named there, so
 * these two halves only mean something because they read the same bytes: a decoder written against a blob
 * its own author invented proves nothing about the writer.
 */
const fromBase64 = (value: string): ArrayBuffer => {
  const raw = atob(value);
  const bytes = new Uint8Array(raw.length);
  for (let at = 0; at < raw.length; at += 1) bytes[at] = raw.charCodeAt(at);
  return bytes.buffer;
};

const mesh = () => decodeKrm1(fromBase64(KRM1_FIXTURE_BASE64));

const triple = (block: Float32Array, at: number): number[] => [
  // `+ 0` folds a stored `-0` onto `0`: PMX writes the y of the origin as negative zero, and a stage that
  // put it there would draw the same vertex.
  (block[at * 3] as number) + 0,
  (block[at * 3 + 1] as number) + 0,
  (block[at * 3 + 2] as number) + 0,
];

describe("decodeKrm1 — the blocks the engine wrote", () => {
  it("reads the header the writer packed", () => {
    const answer = mesh();
    expect(answer.format).toBe(KRM1_FORMAT);
    expect(answer.vertexCount).toBe(4);
    expect(answer.faceIndexCount).toBe(6);
    expect(answer.boneCount).toBe(3);
    expect(answer.materialCount).toBe(2);
    expect(answer.textureCount).toBe(6);
    expect(answer.morphCount).toBe(1);
  });

  it("keeps each vertex's own position, normal and uv", () => {
    const answer = mesh();
    expect(triple(answer.positions, 0)).toEqual([0, 0, 0]);
    expect(triple(answer.positions, 1)).toEqual([1, -1, 2]);
    expect(triple(answer.positions, 2)).toEqual([2, -2, 4]);
    expect(triple(answer.positions, 3)).toEqual([3, -3, 6]);
    // Real PMX normals are not unit — the corpus carries 0.9888 and 1.025 — so the writer keeps them and so
    // does this reader. Nothing here renormalises, because a stage that rescales is a stage that disagrees
    // with the report about the same bytes.
    expect(triple(answer.normals, 0)).toEqual([0, 1, 0]);
    expect(triple(answer.normals, 1)).toEqual([0.5, 0.25, -0.125]);
    expect(triple(answer.normals, 2)).toEqual([1, 0.5, -0.25]);
    expect(triple(answer.normals, 3)).toEqual([1.5, 0.75, -0.375]);
    expect(Array.from(answer.uvs.slice(0, 4))).toEqual([0, 1, 0.0625, 0.96875]);
    expect(Array.from(answer.uvs.slice(4, 8))).toEqual([0.125, 0.9375, 0.1875, 0.90625]);
  });

  it("expands a two-weight row to the four slots a skinned renderer asks for", () => {
    // The fixture is written with `weight_kind=2` (BDEF4): four bone indices and four weights, straight
    // through. The engine does the one-and-two-bone expansion; this only ever passes four on.
    const answer = mesh();
    expect(Array.from(answer.skinIndices.slice(0, 4))).toEqual([0, 1, 2, 0]);
    expect(Array.from(answer.skinWeights.slice(0, 4))).toEqual([1, 0, 0, 0]);
    expect(Array.from(answer.skinIndices.slice(4, 8))).toEqual([1, 2, 0, 1]);
    expect(Array.from(answer.skinWeights.slice(4, 8))).toEqual([0.5, 0.25, 0.125, 0.125]);
    expect(Array.from(answer.skinIndices.slice(12, 16))).toEqual([0, 1, 2, 0]);
    expect(Array.from(answer.skinWeights.slice(12, 16))).toEqual([0.5, 0.25, 0.125, 0.125]);
  });

  it("keeps the face order the file stored", () => {
    expect(Array.from(mesh().faces)).toEqual([0, 3, 2, 1, 0, 3]);
  });

  it("carries the declared path beside the one the file route serves", () => {
    const answer = mesh();
    // The six names are the six ways a corpus reference can read: a subfolder with a CJK filename, the
    // format only Kira decodes, a file the archive never carried, a reference that climbs out of the
    // folder (the engine's own `escapes` answer), one that is absolute on the machine that wrote it, and
    // a format no browser opens. The relative string is what the file route takes; `escapes` is the
    // engine's answer, not ours, and the stage has to be able to read it.
    expect(answer.textures).toEqual([
      { declared: "tex\\颜.png", relative: "tex/颜.png", escapes: false },
      { declared: "hair.tga", relative: "hair.tga", escapes: false },
      { declared: "hair.bmp", relative: "hair.bmp", escapes: false },
      { declared: "..\\outside.png", relative: "../outside.png", escapes: true },
      { declared: "C:\\Users\\me\\face.png", relative: "C:/Users/me/face.png", escapes: false },
      { declared: "body.dds", relative: "body.dds", escapes: false },
    ]);
  });

  it("tiles the face indices across the materials, in their own order", () => {
    const [first, second] = mesh().materials;
    expect(first.name).toBe("m0");
    expect([first.first, first.count]).toEqual([0, 3]);
    expect(first.diffuse).toEqual([0, 1, 0, 1]);
    expect(first.ambient).toEqual([0, 0, 1]);
    expect(first.specular).toEqual([0, 1, 0]);
    expect(first.shine).toBe(0);
    expect(first.flags).toBe(0);
    expect(first.edgeColour).toEqual([1, 0, 0, 0]);
    expect(first.edgeSize).toBe(0);
    expect([first.texture, first.sphere, first.sphereMode, first.sharedToon, first.toon]).toEqual([0, -1, 0, false, -1]);

    expect(second.name).toBe("m1");
    expect([second.first, second.count]).toEqual([3, 3]);
    expect(second.diffuse).toEqual([0.125, 0.875, 0.0625, 1]);
    expect(second.ambient).toEqual([0.03125, 0.0625, 0.984375]);
    expect(second.specular).toEqual([0.0625, 0.96875, 0.015625]);
    expect(second.shine).toBe(0.125);
    expect(second.flags).toBe(1);
    expect(second.edgeColour).toEqual([0.875, 0.03125, 0.0625, 0.125]);
    expect(second.edgeSize).toBe(0.0078125);
    // A memo-only material — the framing the corpus writes for a prop that never gets a picture. `texture`
    // is -1 and the stage colours it from `diffuse` alone; the reader that counts it says so too.
    expect([second.texture, second.sphere, second.toon]).toEqual([-1, -1, -1]);
  });

  it("hands over absolute positions and the parent that makes them relative", () => {
    const answer = mesh();
    expect(answer.bones.map((bone) => bone.name)).toEqual(["bone0", "bone1", "bone2"]);
    expect(answer.bones.map((bone) => bone.nameEn)).toEqual(["bone0_en", "bone1_en", "bone2_en"]);
    expect(answer.bones.map((bone) => bone.parent)).toEqual([-1, 0, 1]);
    expect(answer.bones[0]!.position.map((value) => value + 0)).toEqual([0, 0, 0]);
    expect(answer.bones[1]!.position).toEqual([1, -1, 0.5]);
    expect(answer.bones[2]!.position).toEqual([2, -2, 1]);
    expect(answer.bones.map((bone) => bone.flags)).toEqual([0, 0, 0]);
  });

  it("keeps a parent that sits later in the table, because the corpus writes them", () => {
    // `astra-4ca04839` — 398 bones, 8 of them naming a parent further down the table than themselves.
    // PMX's bone section is a flat list of parent *indexes*, not a pre-order walk, and MMD loads the whole
    // table before it hangs anything, so a forward reference is a file that is fine. The decoder's job is
    // to hand the renderer the same edges the file drew, and to refuse only what cannot be drawn.
    const answer = decodeKrm1(minimal({ boneParents: [1, -1] }));
    expect(answer.bones.map((bone) => bone.parent)).toEqual([1, -1]);
    expect(answer.bones.map((bone) => bone.name)).toEqual(["b0", "b1"]);
  });

  it("keeps the PMX table index beside the morph's own name", () => {
    // Only `口` is a vertex morph here; `まばたき` is kind 0 (group) and never reaches the mesh, which is
    // why `morphCount` is 1 while the profile reports two names.
    expect(mesh().morphs).toEqual([
      {
        morphIndex: 0,
        name: "口",
        elements: [
          { vertex: 0, offset: [0, 0, 0] },
          { vertex: 1, offset: [0.0625, -0.03125, 0.125] },
        ],
      },
    ]);
  });

  it("reads a mesh whose optional blocks are empty", () => {
    // A bare prop — geometry and one material, no pictures, no skeleton, no morphs. The stage can still
    // draw it, so an empty block is a shape, not a fault.
    const pack = new Pack()
      .magic(KRM1_MAGIC)
      .u32(KRM1_FORMAT)
      .u32(1)
      .u32(1)
      .u32(0)
      .u32(0)
      .u32(0)
      .u32(0);
    for (let at = 0; at < 16; at += 1) pack.f32(0);
    pack.u32(0);
    // The format-2 physics block: no rigid bodies, no constraints.
    pack.u32(0).u32(0);
    const answer = decodeKrm1(pack.buffer);
    expect(answer.textures).toEqual([]);
    expect(answer.materials).toEqual([]);
    expect(answer.bones).toEqual([]);
    expect(answer.morphs).toEqual([]);
    expect(Array.from(answer.faces)).toEqual([0]);
  });
});

describe("decodeKrm1 — what it refuses", () => {
  it("names the bytes it opened with when they are not the magic", () => {
    // Long enough to be a header, so the refusal is about the magic and not about the length.
    const pack = new Pack().magic("PMX ");
    for (let at = 0; at < 7; at += 1) pack.u32(0);
    const notAMesh = pack.buffer;
    expect(() => decodeKrm1(notAMesh)).toThrowError(Krm1Error);
    expect(() => decodeKrm1(notAMesh)).toThrowError(/not a KRM1 mesh/);
    expect(() => decodeKrm1(notAMesh)).toThrowError(/"PMX "/);
  });

  it("refuses a format number it cannot read past rather than guessing at one", () => {
    const future = new Pack().magic(KRM1_MAGIC).u32(KRM1_FORMAT + 1).u32(0).u32(0).u32(0).u32(0).u32(0).u32(0).buffer;
    expect(() => decodeKrm1(future)).toThrowError(new RegExp(`format ${KRM1_FORMAT + 1}`));
  });

  it("refuses a header that runs out mid-block", () => {
    const truncated = minimal().slice(0, 40);
    expect(() => decodeKrm1(truncated)).toThrowError(/ends inside/);
  });

  it("refuses a count too large for the bytes that follow it, and does not allocate for it", () => {
    const lying = new Pack().magic(KRM1_MAGIC).u32(KRM1_FORMAT).u32(2_000_000_000).u32(0).u32(0).u32(0).u32(0).u32(0).buffer;
    expect(() => decodeKrm1(lying)).toThrowError(/ends inside the vertex blocks/);
  });

  it("refuses bytes left over after the last block it can name", () => {
    const clean = new Uint8Array(minimal());
    const padded = new Uint8Array(clean.length + 1);
    padded.set(clean);
    expect(() => decodeKrm1(padded.buffer)).toThrowError(/trailing byte/);
  });

  it("refuses material ranges that do not tile the face indices", () => {
    expect(() => decodeKrm1(minimal({ materialFirst: 5 }))).toThrowError(/not one mesh/);
    expect(() => decodeKrm1(minimal({ materialCount: 4 }))).toThrowError(/own 4 of the 1 face indices/);
  });

  it("refuses a bone whose parent names a bone the table does not have", () => {
    expect(() => decodeKrm1(minimal({ boneParent: 1 }))).toThrowError(/bone 0 names 1 as its parent/);
    expect(() => decodeKrm1(minimal({ boneParent: -2 }))).toThrowError(/bone 0 names -2 as its parent/);
  });

  it("refuses a chain that closes on itself, because a skeleton with no root hangs nothing", () => {
    // One bone that is its own parent, and two that are each other's — a forward reference the file is
    // allowed to make, and a loop it is not. Both would walk forever once the renderer descended.
    expect(() => decodeKrm1(minimal({ boneParents: [0] }))).toThrowError(/closes a loop/);
    expect(() => decodeKrm1(minimal({ boneParents: [1, 0] }))).toThrowError(/closes a loop/);
    expect(() => decodeKrm1(minimal({ boneParents: [-1, 2, 1] }))).toThrowError(/closes a loop/);
  });

  it("refuses a morph that moves a vertex the mesh does not have", () => {
    expect(() => decodeKrm1(minimal({ morphVertex: 9 }))).toThrowError(/moves vertex 9 of a mesh that has only 1/);
  });

  it("refuses an empty buffer without reading past its end", () => {
    expect(() => decodeKrm1(new ArrayBuffer(0))).toThrowError(/ends inside the header/);
  });
});
