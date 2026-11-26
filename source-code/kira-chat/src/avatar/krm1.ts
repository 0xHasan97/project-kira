/**
 * KRM1 — the one mesh format the stage reads, and the reason a browser never touches a PMX.
 *
 * `kira-engine/src/kira/mesh.py` writes this: the same walk that produced the character's report, so the
 * mesh and the capability card cannot disagree about what a model holds. What crosses the wire is flat,
 * in one order, with every quirk (inline counts, memo-only materials, the two bone-morph strides, GBK
 * names, the boundary search) already resolved on the side that paid for resolving them.
 *
 * Nothing here guesses. The magic and the format number are checked before a block is read, each block's
 * byte count is checked before it is allocated, and the last byte has to be the end. A blob that fails
 * any of that is a `Krm1Error`, not a half-drawn character: a stride mistake in a mesh does not throw, it
 * renders a face sideways and calls it a model.
 */

export const KRM1_MAGIC = "KRM1";

/** Bumped only by a change a decoder cannot read past, so an old client refuses instead of mis-drawing. */
export const KRM1_FORMAT = 2;

/**
 * Sizes the writer fixes per record. Each count comes from `mesh.py`'s own layout, not from a guess at
 * what a mesh ought to need: a count from a stale or hostile blob must not be able to make this allocate.
 */
const BYTES_PER_VERTEX = 12 + 12 + 8 + 32; // position + normal + uv + (4 u32 + 4 f32)
const BYTES_PER_FACE_INDEX = 4;
/** Two length-prefixed strings can be no shorter than their lengths, and one flag byte follows them. */
const MIN_BYTES_PER_TEXTURE = 4 + 4 + 1;
/** A name, the 16-float colour block, then `u8 i32 i32 u8 u8 i32 u32 u32`. */
const MIN_BYTES_PER_MATERIAL = 4 + 64 + 23;
/** Two names, then `i32` parent, `3 f32` position, `u32` flags. */
const MIN_BYTES_PER_BONE = 8 + 4 + 12 + 4;
/** The PMX-table index, the name, and the element count. */
const MIN_BYTES_PER_MORPH = 4 + 4 + 4;
const BYTES_PER_RIGID_BODY = 4 + 1 + 2 + 1 + 1 + 14 * 4;
const BYTES_PER_CONSTRAINT = 4 + 4 + 1 + 24 * 4;

/** Refusal is the whole job: the screen shows this instead of building a scene out of it. */
export class Krm1Error extends Error {
  constructor(message: string) {
    super(message);
    this.name = "Krm1Error";
  }
}

export interface Krm1Texture {
  /** as the model declared it, kept so a finding can quote the file rather than our rewrite of it */
  declared: string;
  /** posix, relative to the character's folder — what `KiraClient.characterFileUrl` takes */
  relative: string;
  /** the reference leaves the folder, so the file route would refuse it and nothing is fetched */
  escapes: boolean;
}

export interface Krm1Material {
  name: string;
  /** r, g, b, a — `color` and `transparent` both come off these */
  diffuse: [number, number, number, number];
  ambient: [number, number, number];
  specular: [number, number, number];
  shine: number;
  /** PMX's own bit field, undecoded; only the double-sided bit is read, in `load.ts` */
  flags: number;
  edgeColour: [number, number, number, number];
  edgeSize: number;
  /** index into `textures`, or -1 for a material that colours itself with no picture at all */
  texture: number;
  sphere: number;
  sphereMode: number;
  sharedToon: boolean;
  toon: number;
  /** the first face index this material owns, and how many it owns — the renderer's groups */
  first: number;
  count: number;
}

export interface Krm1Bone {
  name: string;
  nameEn: string;
  /** index into `bones`, or -1 for a root */
  parent: number;
  /** absolute in the model's own space; the skeleton wants each bone relative to its parent */
  position: [number, number, number];
  flags: number;
}

export interface Krm1MorphElement {
  vertex: number;
  /** added to the vertex's position, not a replacement for it */
  offset: [number, number, number];
}

export interface Krm1Morph {
  /** its position in the PMX morph table, which is the order `morph_names` reports */
  morphIndex: number;
  name: string;
  elements: Krm1MorphElement[];
}

export interface Krm1RigidBody {
  bone: number;
  group: number;
  mask: number;
  shape: number;
  mode: number;
  size: [number, number, number];
  position: [number, number, number];
  rotation: [number, number, number];
  mass: number;
  positionDamping: number;
  rotationDamping: number;
  restitution: number;
  friction: number;
}

export interface Krm1Constraint {
  first: number;
  second: number;
  mode: number;
  position: [number, number, number];
  rotation: [number, number, number];
  translationMin: [number, number, number];
  translationMax: [number, number, number];
  rotationMin: [number, number, number];
  rotationMax: [number, number, number];
  springPosition: [number, number, number];
  springRotation: [number, number, number];
}

export interface Krm1Mesh {
  format: number;
  vertexCount: number;
  faceIndexCount: number;
  boneCount: number;
  materialCount: number;
  textureCount: number;
  morphCount: number;
  positions: Float32Array;
  normals: Float32Array;
  uvs: Float32Array;
  /** four slots per vertex, exactly as a skinned renderer wants them */
  skinIndices: Uint32Array;
  skinWeights: Float32Array;
  faces: Uint32Array;
  textures: Krm1Texture[];
  materials: Krm1Material[];
  bones: Krm1Bone[];
  morphs: Krm1Morph[];
  rigidBodies: Krm1RigidBody[];
  constraints: Krm1Constraint[];
}

/** A little-endian cursor that refuses to read past the end, and says where it tried to. */
class Reader {
  private readonly view: DataView;
  private readonly utf8 = new TextDecoder("utf-8");
  private offset = 0;

  constructor(buffer: ArrayBuffer) {
    this.view = new DataView(buffer);
  }

  get remaining(): number {
    return this.view.byteLength - this.offset;
  }

  need(bytes: number, block: string): void {
    if (this.remaining < bytes) {
      throw new Krm1Error(`the mesh ends inside ${block}: ${this.remaining} byte(s) left, ${bytes} needed`);
    }
  }

  /** Exactly `length` raw bytes, not a length-prefixed string — the magic is the only one. */
  raw(length: number, block: string): string {
    this.need(length, block);
    const bytes = new Uint8Array(this.view.buffer, this.view.byteOffset + this.offset, length);
    this.offset += length;
    return this.utf8.decode(bytes);
  }

  byte(block: string): number {
    this.need(1, block);
    const value = this.view.getUint8(this.offset);
    this.offset += 1;
    return value;
  }

  uint32(block: string): number {
    this.need(4, block);
    const value = this.view.getUint32(this.offset, true);
    this.offset += 4;
    return value;
  }

  uint16(block: string): number {
    this.need(2, block);
    const value = this.view.getUint16(this.offset, true);
    this.offset += 2;
    return value;
  }

  int32(block: string): number {
    this.need(4, block);
    const value = this.view.getInt32(this.offset, true);
    this.offset += 4;
    return value;
  }

  float32(block: string): number {
    this.need(4, block);
    const value = this.view.getFloat32(this.offset, true);
    this.offset += 4;
    return value;
  }

  /** `u32` length, then that many UTF-8 bytes. Names arrived decoded, so no GBK handling lives here. */
  text(block: string): string {
    const length = this.uint32(`${block} name length`);
    if (length > this.remaining) {
      throw new Krm1Error(`${block} claims a ${length}-byte string with only ${this.remaining} byte(s) left`);
    }
    const value = length === 0 ? "" : this.raw(length, block);
    return value;
  }

  floats(count: number, block: string): Float32Array {
    this.need(count * 4, block);
    const out = new Float32Array(count);
    for (let at = 0; at < count; at += 1) out[at] = this.view.getFloat32(this.offset + at * 4, true);
    this.offset += count * 4;
    return out;
  }

  uint32s(count: number, block: string): Uint32Array {
    this.need(count * 4, block);
    const out = new Uint32Array(count);
    for (let at = 0; at < count; at += 1) out[at] = this.view.getUint32(this.offset + at * 4, true);
    this.offset += count * 4;
    return out;
  }

  /** A triple read as a tuple, because the colour block and the bone position are easier to assert on in pairs of three. */
  triple(block: string): [number, number, number] {
    const values = this.floats(3, block);
    return [values[0], values[1], values[2]];
  }

  quad(block: string): [number, number, number, number] {
    const values = this.floats(4, block);
    return [values[0], values[1], values[2], values[3]];
  }
}

/**
 * One blob, every block, or a refusal that names the block.
 *
 * The order is `mesh.py`'s docstring's order and nothing else — the format has no section offsets and no
 * index to seek by, which is the point: a decoder that only walks forward cannot be handed a lie about
 * where a section starts. `format` comes back so the stage can show which writer produced a mesh.
 */
export function decodeKrm1(buffer: ArrayBuffer): Krm1Mesh {
  const reader = new Reader(buffer);
  reader.need(32, "the header");
  const magic = reader.raw(4, "the header magic");
  if (magic !== KRM1_MAGIC) {
    throw new Krm1Error(
      `this is not a KRM1 mesh: it opens with ${JSON.stringify(magic)}, and ${KRM1_MAGIC} is all this stage reads`,
    );
  }
  const format = reader.uint32("the header format");
  if (format !== KRM1_FORMAT) {
    throw new Krm1Error(
      `this mesh is KRM1 format ${format}; this client reads format ${KRM1_FORMAT}, and the two are not the same blocks`,
    );
  }
  const vertexCount = reader.uint32("the vertex count");
  const faceIndexCount = reader.uint32("the face index count");
  const boneCount = reader.uint32("the bone count");
  const materialCount = reader.uint32("the material count");
  const textureCount = reader.uint32("the texture count");
  const morphCount = reader.uint32("the morph count");

  // The fixed blocks are checked as a whole before anything is allocated: a count is the only place a
  // truncated or forged header can make a decoder reserve a gigabyte.
  reader.need(vertexCount * BYTES_PER_VERTEX + faceIndexCount * BYTES_PER_FACE_INDEX, "the vertex blocks");
  const positionBlock = reader.floats(vertexCount * 3, "positions");
  const normalBlock = reader.floats(vertexCount * 3, "normals");
  const uvBlock = reader.floats(vertexCount * 2, "uvs");
  // Skin is the one block the writer interleaves — four indices and four weights per vertex, then the next
  // vertex — because a vertex's influences are one record. The renderer wants them as two flat attributes,
  // so this splits them on the way out rather than making every caller do it.
  const skinIndices = new Uint32Array(vertexCount * 4);
  const skinWeights = new Float32Array(vertexCount * 4);
  for (let vertex = 0; vertex < vertexCount; vertex += 1) {
    const slot = vertex * 4;
    for (let at = 0; at < 4; at += 1) skinIndices[slot + at] = reader.uint32("skin index");
    for (let at = 0; at < 4; at += 1) skinWeights[slot + at] = reader.float32("skin weight");
  }
  const faces = reader.uint32s(faceIndexCount, "face indices");

  const textures: Krm1Texture[] = [];
  for (let at = 0; at < textureCount; at += 1) {
    reader.need(MIN_BYTES_PER_TEXTURE, `texture ${at}`);
    const declared = reader.text(`texture ${at} declared path`);
    const relative = reader.text(`texture ${at} relative path`);
    textures.push({ declared, relative, escapes: reader.byte(`texture ${at} escapes flag`) !== 0 });
  }

  const materials: Krm1Material[] = [];
  let first = 0;
  for (let at = 0; at < materialCount; at += 1) {
    reader.need(MIN_BYTES_PER_MATERIAL, `material ${at}`);
    const name = reader.text(`material ${at} name`);
    const diffuse = reader.quad(`material ${at} diffuse`);
    const ambient = [reader.float32(`material ${at} ambient`), reader.float32(`material ${at} ambient`), reader.float32(`material ${at} ambient`)] as [number, number, number];
    const specular = [reader.float32(`material ${at} specular`), reader.float32(`material ${at} specular`), reader.float32(`material ${at} specular`)] as [number, number, number];
    const shine = reader.float32(`material ${at} shine`);
    const edgeColour = reader.quad(`material ${at} edge colour`);
    const edgeSize = reader.float32(`material ${at} edge size`);
    // The flag byte is outside the colour block here even though PMX keeps it inside the record: the writer
    // hands over the sixteen floats it needs and packs the byte with the indexes that follow.
    const flags = reader.byte(`material ${at} flags`);
    const texture = reader.int32(`material ${at} texture index`);
    const sphere = reader.int32(`material ${at} sphere index`);
    const sphereMode = reader.byte(`material ${at} sphere mode`);
    const sharedToon = reader.byte(`material ${at} shared toon`) !== 0;
    const toon = reader.int32(`material ${at} toon index`);
    const groupFirst = reader.uint32(`material ${at} first index`);
    const count = reader.uint32(`material ${at} index count`);
    // The writer accumulates this as it goes, so a decoder that recomputes it agrees with the writer for
    // the right reason and catches a blob whose ranges were spliced from two models.
    if (groupFirst !== first) {
      throw new Krm1Error(
        `material ${at} starts at face index ${groupFirst} after ${first}, so these ranges are not one mesh`,
      );
    }
    first += count;
    materials.push({
      name, diffuse, ambient, specular, shine, flags, edgeColour, edgeSize,
      texture, sphere, sphereMode, sharedToon, toon, first: groupFirst, count,
    });
  }
  if (materialCount > 0 && first !== faceIndexCount) {
    throw new Krm1Error(
      `the ${materialCount} material(s) own ${first} of the ${faceIndexCount} face indices, so part of this mesh belongs to nothing`,
    );
  }

  const bones: Krm1Bone[] = [];
  for (let at = 0; at < boneCount; at += 1) {
    reader.need(MIN_BYTES_PER_BONE, `bone ${at}`);
    const name = reader.text(`bone ${at} name`);
    const nameEn = reader.text(`bone ${at} english name`);
    const parent = reader.int32(`bone ${at} parent`);
    const position = reader.triple(`bone ${at} position`);
    const flags = reader.uint32(`bone ${at} flags`);
    // The table is a flat list of parent *indexes*, and the corpus does not write it in any particular
    // order — `astra-4ca04839` has eight bones that name a parent further down than themselves. What the
    // file cannot say is a parent that is not in it, so that is the check, and not an ordering the format
    // never promised.
    if (parent < -1 || parent >= boneCount) {
      throw new Krm1Error(`bone ${at} names ${parent} as its parent and the table has ${boneCount} bones, 0 to ${boneCount - 1}`);
    }
    bones.push({ name, nameEn, parent, position, flags });
  }
  // A loop is the other thing a hand-written table can say, and the renderer walks these edges downward,
  // so it would recurse forever rather than draw nothing. Colouring the chains costs one pass per bone.
  const state = new Uint8Array(boneCount);
  for (let start = 0; start < boneCount; start += 1) {
    if (state[start] !== 0) continue;
    const chain: number[] = [];
    let at = start;
    while (at >= 0 && state[at] === 0) {
      state[at] = 1;
      chain.push(at);
      at = bones[at]!.parent;
    }
    if (at >= 0 && state[at] === 1) {
      throw new Krm1Error(
        `bone ${[...chain, at].join(" → ")} closes a loop, so this skeleton has no root for the renderer to hang it from`,
      );
    }
    for (const index of chain) state[index] = 2;
  }

  const morphs: Krm1Morph[] = [];
  for (let at = 0; at < morphCount; at += 1) {
    reader.need(MIN_BYTES_PER_MORPH, `morph ${at}`);
    const morphIndex = reader.uint32(`morph ${at} table index`);
    const name = reader.text(`morph ${at} name`);
    const elementCount = reader.uint32(`morph ${at} element count`);
    const bytes = elementCount * (BYTES_PER_FACE_INDEX + 12);
    reader.need(bytes, `morph ${at} elements`);
    const elements: Krm1MorphElement[] = [];
    for (let element = 0; element < elementCount; element += 1) {
      const vertex = reader.uint32(`morph ${at} element ${element} vertex`);
      if (vertex >= vertexCount) {
        throw new Krm1Error(`morph ${name} moves vertex ${vertex} of a mesh that has only ${vertexCount}`);
      }
      elements.push({ vertex, offset: reader.triple(`morph ${at} element ${element} offset`) });
    }
    morphs.push({ morphIndex, name, elements });
  }

  // Physics is the last block the writer emits, and its two counts are the only place a forged blob can
  // ask for a large allocation. Check the whole block before reading a record from it, exactly as the
  // vertex blocks above are checked.
  const rigidBodyCount = reader.uint32("the rigid body count");
  const constraintCount = reader.uint32("the constraint count");
  reader.need(
    rigidBodyCount * BYTES_PER_RIGID_BODY + constraintCount * BYTES_PER_CONSTRAINT,
    "the physics blocks",
  );
  const rigidBodies: Krm1RigidBody[] = [];
  for (let at = 0; at < rigidBodyCount; at += 1) {
    const bone = reader.int32(`rigid body ${at} bone`);
    if (bone < -1 || bone >= boneCount) {
      throw new Krm1Error(
        `rigid body ${at} names bone ${bone} and the table has ${boneCount} bones, 0 to ${boneCount - 1}`,
      );
    }
    const group = reader.byte(`rigid body ${at} group`);
    const mask = reader.uint16(`rigid body ${at} collision mask`);
    const shape = reader.byte(`rigid body ${at} shape`);
    const mode = reader.byte(`rigid body ${at} mode`);
    const size = reader.triple(`rigid body ${at} size`);
    const position = reader.triple(`rigid body ${at} position`);
    const rotation = reader.triple(`rigid body ${at} rotation`);
    const physics = reader.floats(5, `rigid body ${at} physics`);
    rigidBodies.push({
      bone,
      group,
      mask,
      shape,
      mode,
      size,
      position,
      rotation,
      mass: physics[0] as number,
      positionDamping: physics[1] as number,
      rotationDamping: physics[2] as number,
      restitution: physics[3] as number,
      friction: physics[4] as number,
    });
  }
  const constraints: Krm1Constraint[] = [];
  for (let at = 0; at < constraintCount; at += 1) {
    const first = reader.int32(`constraint ${at} first body`);
    const second = reader.int32(`constraint ${at} second body`);
    if (first < 0 || first >= rigidBodyCount || second < 0 || second >= rigidBodyCount) {
      throw new Krm1Error(
        `constraint ${at} joins rigid bodies ${first} and ${second}, and the blob has ${rigidBodyCount}`,
      );
    }
    const mode = reader.byte(`constraint ${at} mode`);
    constraints.push({
      first,
      second,
      mode,
      position: reader.triple(`constraint ${at} position`),
      rotation: reader.triple(`constraint ${at} rotation`),
      translationMin: reader.triple(`constraint ${at} translation min`),
      translationMax: reader.triple(`constraint ${at} translation max`),
      rotationMin: reader.triple(`constraint ${at} rotation min`),
      rotationMax: reader.triple(`constraint ${at} rotation max`),
      springPosition: reader.triple(`constraint ${at} spring position`),
      springRotation: reader.triple(`constraint ${at} spring rotation`),
    });
  }

  if (reader.remaining !== 0) {
    throw new Krm1Error(`the mesh has ${reader.remaining} trailing byte(s) after the last block this header can name`);
  }

  return {
    format,
    vertexCount,
    faceIndexCount,
    boneCount,
    materialCount,
    textureCount,
    morphCount,
    positions: positionBlock,
    normals: normalBlock,
    uvs: uvBlock,
    skinIndices,
    skinWeights,
    faces,
    textures,
    materials,
    bones,
    morphs,
    rigidBodies,
    constraints,
  };
}
