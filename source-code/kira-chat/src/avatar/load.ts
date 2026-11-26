/**
 * The stage's load path: one authenticated mesh request, the textures the walk said to ask for, and a
 * `SkinnedMesh` built from bytes the engine already certified.
 *
 * Two rules shape everything below.
 *
 * **No PMX reaches a `DataView` in this browser.** The engine exports KRM1 (see
 * `kira-engine/src/kira/mesh.py`) because the quirks of the source format — inline counts, memo-only
 * materials, the two bone-morph strides, GBK names, the boundary search — were paid for once, on the side
 * that owns the bytes. A second reader here would re-solve them and disagree.
 *
 * **No token in any URL.** Every byte comes through `MeshSource.bytes`, which puts the bearer in a header;
 * `characterMeshUrl` and `characterFileUrl` return paths, so nothing that lands in an access log, a `<img>`
 * element or a loader's `resourcePath` can carry a secret.
 *
 * And the seam that makes this testable at all: a page that opens a `.png` needs `createImageBitmap` or an
 * `<img>`, neither of which decodes in jsdom, so the host supplies those pixels. That is the only thing the
 * caller owns, and it is why this module constructs no `WebGLRenderer` and touches no canvas.
 */

import {
  Bone,
  BufferAttribute,
  BufferGeometry,
  Color,
  DataTexture,
  DoubleSide,
  Float32BufferAttribute,
  FrontSide,
  Group,
  MeshToonMaterial,
  Skeleton,
  SkinnedMesh,
  SRGBColorSpace,
  Uint16BufferAttribute,
  Uint32BufferAttribute,
} from "three";
import type { Texture } from "three";
import { TGALoader } from "three/addons/loaders/TGALoader.js";
import type { CharacterCapability, CharacterProfile } from "../contracts.ts";
import type { Krm1Mesh } from "./krm1.ts";
import { decodeKrm1 } from "./krm1.ts";
import type { TexturePlan } from "./pmx.ts";
import { texturePlan } from "./pmx.ts";

/** The part of `KiraClient` a load needs — structural, so a test can hand it a recording double. */
export interface MeshSource {
  bytes(path: string): Promise<ArrayBuffer>;
  characterMeshUrl(id: string): string;
  characterFileUrl(id: string, relative: string): string;
}

/** What only the page can do: decode a file a browser opens, into a texture the stage can bind. */
export interface StageHost {
  imageTexture(bytes: ArrayBuffer, relative: string): Texture;
}

export interface LoadedCharacter {
  /** put this on the stage: it holds the mesh, and the mesh holds the skeleton */
  object: Group;
  mesh: SkinnedMesh;
  geometry: BufferGeometry;
  materials: MeshToonMaterial[];
  skeleton: Skeleton;
  bones: Bone[];
  /** the file the model referenced, by its folder-relative path, to the texture it became — placeholder included */
  textures: Map<string, Texture>;
  /** a morph's own name to the slot in `mesh.morphTargetInfluences` that drives it */
  morphs: Map<string, number>;
  /** and that slot's position in the PMX morph table, which is the order `morph_names` reports */
  morphTableIndexes: Map<string, number>;
  /** what the stage could not do with what it was given, in the order it found out */
  findings: string[];
  dispose(): void;
}

/** PMX's material flag for "visible from behind too": bit 0, the same bit MMD reads. The walk hands the byte over untouched. */
const DOUBLE_SIDED_BIT = 0x01;

/**
 * One pixel, magenta, for every texture the stage could not get.
 *
 * A placeholder rather than nothing because `MeshToonMaterial` with no `map` draws flat colour, and a flat
 * grey face looks like the model is fine and the light is bad. Magenta says "a file is missing here" the way
 * the texture itself cannot, and the finding underneath says which.
 */
function placeholder(): DataTexture {
  const texture = new DataTexture(new Uint8Array([255, 0, 255, 255]), 1, 1);
  texture.needsUpdate = true;
  // A ramp or a sphere map must never sample this: magenta shading is worse than no shading at all.
  texture.userData.placeholder = true;
  return texture;
}

/** Which slots a texture table entry feeds: the diffuse map, a toon ramp, a sphere map. */
type TextureUse = Set<"map" | "toon" | "sphere">;

/** One pass over the material table, so a finding can say what a missing file actually costs. */
function textureUse(meshData: Krm1Mesh): Map<string, TextureUse> {
  const uses = new Map<string, TextureUse>();
  const note = (index: number, kind: "map" | "toon" | "sphere"): void => {
    if (index < 0) return;
    const named = meshData.textures[index];
    if (named === undefined) return;
    const set = uses.get(named.relative) ?? new Set<"map" | "toon" | "sphere">();
    set.add(kind);
    uses.set(named.relative, set);
  };
  for (const material of meshData.materials) {
    note(material.texture, "map");
    if (!material.sharedToon) note(material.toon, "toon");
    note(material.sphere, "sphere");
  }
  return uses;
}

/**
 * What a file the stage could not get costs it, said for the slot that names it.
 *
 * A missing diffuse map is magenta, because that is what a face with no texture looks like. A missing toon
 * ramp is not: the material still draws, lit, with three's own band. A missing sphere map costs the rim and
 * nothing else. Saying "magenta" for every absent file was true for the face and a lie for the rest.
 */
function consequence(use: TextureUse | undefined): string {
  if (use === undefined) return "nothing on the stage draws with it";
  if (use.has("map")) return "that part of the body is drawn in magenta";
  if (use.has("toon")) return "those materials are shaded by the light alone";
  return "those materials lose their sphere shading";
}

/** The finding for one texture the plan said not to ask for, in the plan's own words. */
function refusedFinding(
  relative: string,
  declared: string,
  plan: TexturePlan,
  use: TextureUse | undefined,
): string | null {
  if (plan.missing.includes(relative)) {
    return `${declared} — the material names it and the archive never carried it, so ${consequence(use)}`;
  }
  if (plan.refused.includes(declared)) {
    return `${declared} — the reference leaves the character's folder, so the file route would refuse it, and ${consequence(use)}`;
  }
  if (plan.unsupported.includes(relative)) {
    return `${relative} — the bytes are here and the engine will serve them, but nothing on this page decodes that format, so ${consequence(use)}`;
  }
  return null;
}

/**
 * Fetch and decode every texture the mesh names, in parallel, and never fail for one of them.
 *
 * The plan comes from `texturePlan(profile.main)` — the walk's own answer about what exists, what escapes
 * and what needs a decoder — so this cannot ask for a file the route would refuse. Anything that still goes
 * wrong (a 404, a half-written `.tga`, a host that cannot open a webp) becomes a placeholder plus a finding:
 * one absent `hair.bmp` is not a reason to leave the stage with no character.
 */
async function loadTextures(
  source: MeshSource,
  id: string,
  meshData: Krm1Mesh,
  plan: TexturePlan,
  host: StageHost,
  findings: string[],
): Promise<Map<string, Texture>> {
  const planned = new Map(plan.fetch.map((entry) => [entry.relative, entry]));
  const uses = textureUse(meshData);
  const textures = new Map<string, Texture>();
  await Promise.all(
    meshData.textures.map(async (record) => {
      const refusal = refusedFinding(record.relative, record.declared, plan, uses.get(record.relative));
      if (refusal !== null) {
        findings.push(refusal);
        textures.set(record.relative, placeholder());
        return;
      }
      const entry = planned.get(record.relative);
      if (entry === undefined) {
        // The report and the mesh are two views of one walk, so this only happens if they disagree.
        findings.push(`${record.relative} — the mesh names it and the character's report does not, so nothing was fetched for it`);
        textures.set(record.relative, placeholder());
        return;
      }
      try {
        const bytes = await source.bytes(source.characterFileUrl(id, entry.path));
        // `.tga` is the one format the corpus leans on and no browser opens, so the decoder is ours; every
        // other suffix goes through the host, which is the seam a jsdom suite cannot cross on its own.
        textures.set(record.relative, entry.decoder === "tga" ? decodeTga(bytes) : host.imageTexture(bytes, record.relative));
      } catch (error) {
        const reason = error instanceof Error ? error.message : String(error);
        findings.push(`${record.relative} — asked for it and got "${reason}", so ${consequence(uses.get(record.relative))}`);
        textures.set(record.relative, placeholder());
      }
    }),
  );
  return textures;
}

/**
 * Decode one `.tga` with three's own reader.
 *
 * The loader hands back a `DataTexture` in no colour space at all, and a colour map sampled as linear
 * reads as a photocopy: pale skin, grey clothes, a face that looks lit from inside. A diffuse map is
 * painted in sRGB like every other texture the host sees, so it is labelled here, on the one path that
 * cannot go through the host.
 */
function decodeTga(bytes: ArrayBuffer): Texture {
  const texture = new TGALoader().createDataTexture(bytes);
  texture.colorSpace = SRGBColorSpace;
  return texture;
}

/**
 * Turn PMX texture coordinates into three's.
 *
 * PMX names a pixel with v=0 at the top of the image, the way DirectX does. Three uploads every image
 * flipped (`Texture.flipY`), so in its UV space v=0 is the bottom row. As the file had it, every body in
 * the corpus sampled its face upside down: the painted eye sockets landed near the mouth, the real eye
 * and iris meshes sat behind the skin, and the clothes read as the back of the atlas. The decode owns
 * this array, so the flip happens in place.
 */
function flipUV(uvs: Float32Array): Float32Array {
  for (let at = 1; at < uvs.length; at += 2) uvs[at] = 1 - uvs[at];
  return uvs;
}

/** Four influences per vertex, as wide as the biggest bone index actually needs. */
function skinIndexAttribute(meshData: Krm1Mesh): BufferAttribute {
  let widest = 0;
  for (let at = 0; at < meshData.skinIndices.length; at += 1) {
    const value = meshData.skinIndices[at];
    if (value > widest) widest = value;
  }
  // A 45 MB model is 26 798 vertices and 101 bones, so 16 bits is the normal answer and saves half the
  // attribute. Three's classic skinning path declares `attribute vec4 skinIndex`, and an unsigned-short
  // attribute is what its own FBXLoader ships.
  const attribute = widest < 65_536
    ? new Uint16BufferAttribute(new Uint16Array(meshData.skinIndices.length), 4)
    : new Uint32BufferAttribute(new Uint32Array(meshData.skinIndices.length), 4);
  (attribute.array as Uint16Array | Uint32Array).set(meshData.skinIndices);
  return attribute;
}

/** The face indices, narrowed the same way — a model with 65 536 vertices or fewer is the common case. */
function indexAttribute(meshData: Krm1Mesh): BufferAttribute {
  let widest = 0;
  for (let at = 0; at < meshData.faces.length; at += 1) {
    const value = meshData.faces[at];
    if (value > widest) widest = value;
  }
  if (widest < 65_536) {
    const short = new Uint16Array(meshData.faces.length);
    short.set(meshData.faces);
    return new Uint16BufferAttribute(short, 1);
  }
  return new Uint32BufferAttribute(meshData.faces, 1);
}

/**
 * The morph slots, in the order the mesh lists them.
 *
 * A KRM1 vertex morph is a set of *offsets*, and three's morph targets are additive when
 * `morphTargetsRelative` is on, so the payload crosses the wire as it was written. Vertices the morph does
 * not move stay at zero — that is what "this morph leaves this vertex alone" means.
 */
function applyMorphs(meshData: Krm1Mesh, geometry: BufferGeometry, morphs: Map<string, number>, tableIndexes: Map<string, number>, findings: string[]): void {
  if (meshData.morphs.length === 0) return;
  const positions: Float32BufferAttribute[] = [];
  for (const morph of meshData.morphs) {
    const deltas = new Float32Array(meshData.vertexCount * 3);
    for (const element of morph.elements) {
      const at = element.vertex * 3;
      deltas[at] = element.offset[0];
      deltas[at + 1] = element.offset[1];
      deltas[at + 2] = element.offset[2];
    }
    const attribute = new Float32BufferAttribute(deltas, 3);
    // `Mesh.updateMorphTargets` keys its dictionary off the attribute's name, so this is what makes
    // `morphTargetDictionary["え"]` mean anything.
    attribute.name = morph.name;
    positions.push(attribute);
    if (morphs.has(morph.name)) {
      findings.push(`${morph.name} appears twice in the morph table; the stage drives the first one it met`);
    } else {
      morphs.set(morph.name, positions.length - 1);
      tableIndexes.set(morph.name, morph.morphIndex);
    }
  }
  geometry.morphAttributes.position = positions;
  // Offsets, not replacements. Without this the unmoved vertices collapse onto the origin instead of the
  // face they were built on.
  geometry.morphTargetsRelative = true;
}

/** What the walk named and the mesh could not carry: a morph with no vertex payload. */
function undrivableMorphs(main: CharacterCapability, morphs: Map<string, number>): string[] {
  const named = main.morph_names ?? [];
  const kinds = main.morph_kinds ?? [];
  // The same rule `avatar/pmx.ts` uses: without a kind beside every name, nothing here can say which
  // morphs are drivable, and guessing would tell the user a face is broken when the report is just thin.
  if (named.length === 0 || kinds.length !== named.length) return [];
  const missing = named.filter((name, index) => !morphs.has(name) && kinds[index] !== 1);
  if (missing.length === 0) return [];
  return [
    `${missing.length} of the ${named.length} morph name(s) this model publishes are not vertex morphs, so the stage has no offsets to drive for them`,
  ];
}

/** The gradient sample three ships, and the vertical read a PMX toon ramp needs. */
const GRADIENT_SAMPLE = "vec2 coord = vec2( dotNL * 0.5 + 0.5, 0.0 );";
const GRADIENT_VERTICAL = "vec2 coord = vec2( 0.5, dotNL * 0.5 + 0.5 );";
/** three reads the red channel of a gradient map; a PMX toon ramp carries its tint in all three. */
const GRADIENT_RED = "return vec3( texture2D( gradientMap, coord ).r );";
const GRADIENT_RGB = "return texture2D( gradientMap, coord ).rgb;";
/** The line every toon fragment reaches after the lights have been summed, where a sphere map belongs. */
const LIT_COLOUR =
  "vec3 outgoingLight = reflectedLight.directDiffuse + reflectedLight.indirectDiffuse + totalEmissiveRadiance;";

/**
 * Give one material the two surface layers three's toon material does not have.
 *
 * A toon ramp is a gradient map: the archive carries it as a texture table entry, and every material that
 * names one is shaded by those bands, including the ramp's tint. A sphere map is the other half of MMD's
 * shading — a second texture sampled by the view-space normal, multiplied, added or alpha-laid over the
 * lit colour depending on the mode. MMD applies it after the lights, which is where this patch runs.
 */
function dress(
  material: MeshToonMaterial,
  toon: Texture | null,
  sphere: { texture: Texture; mode: number } | null,
): void {
  if (toon !== null) material.gradientMap = toon;
  material.onBeforeCompile = (shader) => {
    if (toon !== null) {
      shader.fragmentShader = shader.fragmentShader
        .replace(GRADIENT_SAMPLE, GRADIENT_VERTICAL)
        .replace(GRADIENT_RED, GRADIENT_RGB);
    }
    if (sphere !== null) {
      shader.uniforms.sphereMap = { value: sphere.texture };
      shader.uniforms.sphereMode = { value: sphere.mode };
      shader.fragmentShader = shader.fragmentShader
        .replace("#include <common>", "#include <common>\nuniform sampler2D sphereMap;\nuniform int sphereMode;")
        .replace(
          LIT_COLOUR,
          `${LIT_COLOUR}
  vec2 sphereUv = normalize( normal ).xy * 0.5 + 0.5;
  vec4 sphereSample = texture2D( sphereMap, sphereUv );
  if ( sphereMode == 1 ) outgoingLight *= sphereSample.rgb;
  else if ( sphereMode == 2 ) outgoingLight += sphereSample.rgb;
  else if ( sphereMode == 3 ) outgoingLight = mix( outgoingLight, sphereSample.rgb, sphereSample.a );`,
        );
    }
  };
  // The patched source differs from a bare toon program, so it needs its own cache key. The sphere mode is
  // a uniform rather than a branch in the source, so every material with this pair shares one program.
  material.customProgramCacheKey = () =>
    `pmx-${toon === null ? "plain" : "ramp"}-${sphere === null ? "plain" : "sphere"}`;
}

function buildMaterials(meshData: Krm1Mesh, textures: Map<string, Texture>, findings: string[]): MeshToonMaterial[] {
  let sharedToon = 0;
  const materials = meshData.materials.map((record) => {
    const [red, green, blue, alpha] = record.diffuse;
    let map: Texture | null = null;
    if (record.texture >= 0) {
      const named = meshData.textures[record.texture];
      if (named === undefined) {
        findings.push(`${record.name || "a material"} names texture ${record.texture}, which the mesh does not carry`);
      } else {
        map = textures.get(named.relative) ?? placeholder();
      }
    }
    const surface = (index: number): Texture | null => {
      if (index < 0) return null;
      const named = meshData.textures[index];
      if (named === undefined) return null;
      const texture = textures.get(named.relative);
      // A failed fetch is a magenta placeholder; a ramp or a sphere in magenta would be worse than none.
      return texture !== undefined && texture.userData.placeholder !== true ? texture : null;
    };
    // A shared toon index names one of MMD's ten built-in ramps, which are not files in the archive.
    const toon = record.sharedToon ? null : surface(record.toon);
    if (record.sharedToon) sharedToon += 1;
    const sphereAt = surface(record.sphere);
    const sphere =
      sphereAt !== null && record.sphereMode >= 1 && record.sphereMode <= 3
        ? { texture: sphereAt, mode: record.sphereMode }
        : null;
    const material = new MeshToonMaterial({
      name: record.name,
      color: new Color(red, green, blue),
      map,
      // MMD blends the diffuse map's own alpha, and the corpus depends on it: Burnice's blonde hair is one
      // layer of hair under another that is mostly transparent, Ellen's red tips are the fade at the end of
      // her hair cards, and Astra's headband sits under the same kind of layer. Treated as opaque, every one
      // of those pixels paints its transparent half as solid colour, so the hair turns black and the band
      // disappears. A material with a map is therefore blended even when its own alpha is 1.
      transparent: alpha < 1 || map !== null,
      opacity: alpha,
      // Blending without a depth write would let a hair card behind the face draw over it; MMD itself keeps
      // the depth test while blending, and the material order in the file is the order this mesh draws in.
      depthWrite: true,
      side: (record.flags & DOUBLE_SIDED_BIT) === 0 ? FrontSide : DoubleSide,
    });
    dress(material, toon, sphere);
    return material;
  });
  if (sharedToon > 0) {
    findings.push(
      `${sharedToon} material(s) use a built-in toon row; that ramp is one of MMD's ten and is not a file in the archive, so those pixels are shaded by the light alone`,
    );
  }
  return materials;
}

function buildBones(meshData: Krm1Mesh): { bones: Bone[]; roots: Bone[] } {
  const bones = meshData.bones.map((record) => {
    const bone = new Bone();
    bone.name = record.name;
    const [x, y, z] = record.position;
    const parent = record.parent >= 0 ? meshData.bones[record.parent] : undefined;
    // The wire carries absolute positions because that is what the file stores; a `Bone` holds its own
    // translation relative to whatever it is hung from, so the subtraction happens here.
    bone.position.set(
      x - (parent?.position[0] ?? 0),
      y - (parent?.position[1] ?? 0),
      z - (parent?.position[2] ?? 0),
    );
    return bone;
  });
  const roots: Bone[] = [];
  bones.forEach((bone, at) => {
    // Every object exists by now, so the edge can point anywhere in the table — the decoder has proved the
    // index is inside it and that the chain reaches a root.
    const parent = meshData.bones[at].parent;
    if (parent >= 0) bones[parent]?.add(bone);
    else roots.push(bone);
  });
  return { bones, roots };
}

/**
 * Put one character's body on the stage.
 *
 * `profile` is the library's own answer for that character — the loader takes the id from it, fetches the
 * mesh the engine certifies for it, and uses the report's texture findings to decide what else to ask for.
 * A character with no body is the one thing that makes this reject: there is no geometry to draw, and a
 * placeholder for a face would be a lie.
 */
export async function loadCharacter(source: MeshSource, profile: CharacterProfile, host: StageHost): Promise<LoadedCharacter> {
  const main = profile.main;
  if (main === null || main === undefined) {
    throw new Error(`character '${profile.id}' has no body to put on the stage: ${profile.reason}`);
  }
  const meshData = decodeKrm1(await source.bytes(source.characterMeshUrl(profile.id)));
  const findings: string[] = [];
  const plan = texturePlan(main);
  const textures = await loadTextures(source, profile.id, meshData, plan, host, findings);

  const geometry = new BufferGeometry();
  geometry.name = `${profile.id}:body`;
  // Each of these arrays belongs to this decode alone — `decodeKrm1` makes a fresh one per blob — so the
  // attributes take them as they are instead of copying a 45 MB model's worth of floats.
  geometry.setAttribute("position", new BufferAttribute(meshData.positions, 3));
  geometry.setAttribute("normal", new BufferAttribute(meshData.normals, 3));
  geometry.setAttribute("uv", new BufferAttribute(flipUV(meshData.uvs), 2));
  geometry.setAttribute("skinIndex", skinIndexAttribute(meshData));
  geometry.setAttribute("skinWeight", new Float32BufferAttribute(meshData.skinWeights, 4));
  geometry.setIndex(indexAttribute(meshData));

  const morphs = new Map<string, number>();
  const morphTableIndexes = new Map<string, number>();
  applyMorphs(meshData, geometry, morphs, morphTableIndexes, findings);

  const materials = buildMaterials(meshData, textures, findings);
  // One draw range per material, in the order the file listed them — the corpus gives a face its skin, its
  // hair and its clothes as separate ranges over the same vertices, and a mesh that ignores the ranges is a
  // model wearing its own hair.
  meshData.materials.forEach((record, at) => geometry.addGroup(record.first, record.count, at));

  const mesh = new SkinnedMesh(geometry, materials);
  mesh.name = `${profile.id}:mesh`;
  const { bones, roots } = buildBones(meshData);
  for (const root of roots) mesh.add(root);
  // `bind` re-reads every bone's world matrix to make the inverse bind matrices, so the hierarchy has to be
  // assembled and updated before it — after the fact, every bone would bind to the origin.
  const skeleton = new Skeleton(bones);
  mesh.bind(skeleton);

  const object = new Group();
  object.name = profile.id;
  object.add(mesh);

  for (const finding of undrivableMorphs(main, morphs)) findings.push(finding);

  const dispose = (): void => {
    // Every texture the loader made — placeholder included — is in `textures` exactly once, so this is the
    // one list a stage that swaps characters has to walk.
    geometry.dispose();
    for (const material of materials) material.dispose();
    for (const texture of textures.values()) texture.dispose();
    skeleton.dispose();
  };

  return {
    object,
    mesh,
    geometry,
    materials,
    skeleton,
    bones,
    textures,
    morphs,
    morphTableIndexes,
    findings,
    dispose,
  };
}
