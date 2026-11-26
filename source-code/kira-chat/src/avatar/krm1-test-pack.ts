/**
 * Hand-packed KRM1 bytes, for the tests that need a blob to lie in a specific place.
 *
 * The happy path is proved against bytes the engine really wrote (`krm1-fixture.ts`); a refusal cannot be,
 * because a fixture that misstates its own counts is a different fixture. So the tests build the smallest
 * mesh whose arithmetic a refusal can be about, and mutate one field.
 */

import { KRM1_FORMAT, KRM1_MAGIC } from "./krm1.ts";

/** One vertex, one face, one material — the shape `minimal` below writes. */
export class Pack {
  private readonly bytes: number[] = [];

  magic(value: string): this {
    for (const char of value) this.bytes.push(char.charCodeAt(0));
    return this;
  }

  u32(value: number): this {
    return this.view(4, (view) => view.setUint32(0, value, true));
  }

  i32(value: number): this {
    return this.view(4, (view) => view.setInt32(0, value, true));
  }

  f32(value: number): this {
    return this.view(4, (view) => view.setFloat32(0, value, true));
  }

  u8(value: number): this {
    this.bytes.push(value);
    return this;
  }

  text(value: string): this {
    const encoded = new TextEncoder().encode(value);
    this.u32(encoded.length);
    this.bytes.push(...encoded);
    return this;
  }

  private view(length: number, write: (view: DataView) => void): this {
    const buffer = new ArrayBuffer(length);
    write(new DataView(buffer));
    this.bytes.push(...new Uint8Array(buffer));
    return this;
  }

  get buffer(): ArrayBuffer {
    return new Uint8Array(this.bytes).buffer as ArrayBuffer;
  }
}

export interface MinimalOptions {
  vertexCount?: number;
  faceIndexCount?: number;
  materialFirst?: number;
  materialCount?: number;
  /** the single bone's parent field, when the table is the default one-bone one */
  boneParent?: number;
  /** a whole bone table: one parent index per bone, replacing the default single bone */
  boneParents?: number[];
  /** `[declared, relative, escapes]` per texture, written where the writer writes them — before materials */
  texturePaths?: Array<[string, string, boolean]>;
  /** the single material's texture slots, for the layers a test wants to see the loader dress */
  material?: { texture?: number; sphere?: number; sphereMode?: number; sharedToon?: boolean; toon?: number; flags?: number };
  morphVertex?: number;
}

/** The smallest mesh a decoder can be asked about, with one mutation per call. */
export const minimal = (over: MinimalOptions = {}): ArrayBuffer => {
  const vertices = over.vertexCount ?? 1;
  const faces = over.faceIndexCount ?? 1;
  const parents = over.boneParents;
  const textures = over.texturePaths ?? [];
  const vertexBytes = vertices * (12 + 12 + 8 + 32);
  const pack = new Pack()
    .magic(KRM1_MAGIC)
    .u32(KRM1_FORMAT)
    .u32(vertices)
    .u32(faces)
    .u32(parents === undefined ? 1 : parents.length)
    .u32(1)
    .u32(textures.length)
    .u32(over.morphVertex === undefined ? 0 : 1);
  for (let at = 0; at < vertexBytes / 4; at += 1) pack.f32(0);
  // The writer keeps the face indices as one flat u32 block, whatever width the PMX file used.
  for (let at = 0; at < faces; at += 1) pack.u32(0);
  for (const [declared, relative, escapes] of textures) {
    pack.text(declared).text(relative).u8(escapes ? 1 : 0);
  }
  pack
    .text("m0")
    .f32(0).f32(0).f32(0).f32(1) // diffuse
    .f32(0).f32(0).f32(0) // ambient
    .f32(0).f32(0).f32(0) // specular
    .f32(0) // shine
    .f32(0).f32(0).f32(0).f32(0) // edge colour
    .f32(0) // edge size
    .u8(over.material?.flags ?? 0) // flags, packed with the indexes rather than inside the colour block
    .i32(over.material?.texture ?? -1) // texture
    .i32(over.material?.sphere ?? -1) // sphere
    .u8(over.material?.sphereMode ?? 0).u8(over.material?.sharedToon ? 1 : 0) // sphere mode, shared toon
    .i32(over.material?.toon ?? -1) // toon
    .u32(over.materialFirst ?? 0)
    .u32(over.materialCount ?? 1);
  const table = parents === undefined ? [over.boneParent ?? -1] : parents;
  table.forEach((parent, at) => {
    pack.text(`b${at}`).text(`b${at}_en`).i32(parent).f32(at).f32(0).f32(0).u32(0);
  });
  if (over.morphVertex !== undefined) {
    pack.u32(0).text("口").u32(1).u32(over.morphVertex).f32(0).f32(0).f32(0);
  }
  // Format 2 always carries the two physics counts, even when both are zero.
  pack.u32(0).u32(0);
  return pack.buffer;
};
