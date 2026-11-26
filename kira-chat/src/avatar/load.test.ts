import { describe, expect, it } from "vitest";
import { DataTexture, DoubleSide, FrontSide, SRGBColorSpace } from "three";
import type { MeshToonMaterial, Texture } from "three";
import { KiraClient } from "../api.ts";
import type { CharacterCapability, CharacterProfile, TextureFinding } from "../contracts.ts";
import { ELLEN_ID, PROPS_ID, PNG_BYTES, fakeEngine } from "../fake-engine.ts";
import { loadCharacter } from "./load.ts";
import type { MeshSource, StageHost } from "./load.ts";
import { minimal } from "./krm1-test-pack.ts";

/**
 * What the stage asks for, in the order that matters: one authenticated mesh request, then only the
 * textures the walk said exist and can be decoded, and a `SkinnedMesh` at the end of it.
 *
 * The bytes come from the engine's own `pack_mesh` (see `krm1-fixture.ts`), served by the fake at the same
 * path the real route uses, so the token/header rules T9 exists for are exercised rather than described.
 * That fixture's texture table is the six ways a corpus reference can read — `tex/颜.png`, `hair.tga`, an
 * absent `hair.bmp`, a `..\outside.png` that climbs out of the folder, an absolute `C:\Users\me\face.png`
 * and a `body.dds` nothing on a page opens — and the profile below reports the same six, because the
 * loader has to agree with the walk about all four of the last ones and ask for exactly two.
 */

/** A 2 × 2 uncompressed 32-bit TGA — the one format the corpus leans on and no browser opens by itself. */
const tgaBytes = (): Uint8Array => {
  const header = [
    0, 0, 2, // no id field, no colour map, uncompressed true-colour
    0, 0, 0, 0, 0, // map origin and length
    0, 0, // x origin
    0, 0, // y origin
    2, 0, // width, little-endian
    2, 0, // height
    32, // bits per pixel
    0x28 | 0x20, // 8 alpha bits, stored top-left
  ];
  const pixels = [
    255, 0, 0, 255, // blue first: TGA is BGA, three hands back RGBA
    0, 255, 0, 255,
    0, 0, 255, 255,
    255, 255, 255, 0,
  ];
  return new Uint8Array([...header, ...pixels]);
};

const finding = (over: Partial<TextureFinding>): TextureFinding => ({
  declared: "",
  relative: "",
  exists: true,
  size: 64,
  format: "png",
  escapes: false,
  ...over,
});

const capability = (over: Partial<CharacterCapability>): CharacterCapability =>
  ({
    path: "model.pmx",
    name: "ellen",
    english_name: "Ellen",
    file_name: "model.pmx",
    version: 2.1,
    count_framing: "header",
    material_framing: "draw_and_memos",
    counts: {
      vertex_count: 4, face_index_count: 6, texture_count: 6, material_count: 2, bone_count: 3,
      morph_count: 2, frame_count: 1, rigid_body_count: 0, constraint_count: 0,
    },
    vertices: 4,
    bones: 3,
    triangles: 2,
    has_physics: false,
    is_character: true,
    texture_status: "3/6 — hair.bmp absent, 2 more",
    standard_groups: [],
    finger_bone_count: 0,
    morph_names: ["口", "まばたき"],
    morph_kinds: [1, 0],
    frame_names: [],
    textures: [
      finding({ declared: "tex\\颜.png", relative: "tex/颜.png", format: "png" }),
      finding({ declared: "hair.tga", relative: "hair.tga", format: "tga" }),
      finding({ declared: "hair.bmp", relative: "hair.bmp", exists: false, size: null, format: "bmp" }),
      finding({ declared: "..\\outside.png", relative: "../outside.png", exists: false, size: null, format: "png", escapes: true }),
      finding({ declared: "C:\\Users\\me\\face.png", relative: "C:/Users/me/face.png", exists: false, size: null, format: "png" }),
      finding({ declared: "body.dds", relative: "body.dds", format: "dds" }),
    ],
    texture_resolved: 3,
    missing_textures: ["hair.bmp", "../outside.png", "C:/Users/me/face.png"],
    sphere_texture_refs: 0,
    shared_toon_refs: 0,
    ik_bone_count: 0,
    trailing_bytes: 0,
    findings: [],
    license_note: null,
    unreadable: null,
    ...over,
  }) as CharacterCapability;

const profile = (over: Partial<CharacterProfile> = {}): CharacterProfile =>
  ({
    schema: 1,
    id: ELLEN_ID,
    display_name: "ellen",
    english_name: "Ellen",
    imported_at: "2026-10-31T10:00:00+00:00",
    source: { file_name: "Ellen.zip", sha256: "0".repeat(64), bytes: 45_000_000, archive: true },
    reason: "the only model in the archive with a face and a skeleton",
    license_note: null,
    main: capability({}),
    companions: [],
    files: [{ path: "model.pmx", bytes: 44_000_000 }],
    ...over,
  }) as CharacterProfile;

/** The files the fake serves, keyed by path, so a fetch that should not happen reads as a 404. */
const files = (over: Record<string, Uint8Array> = {}): Record<string, Uint8Array> => ({
  "tex/颜.png": PNG_BYTES,
  "hair.tga": tgaBytes(),
  ...over,
});

type Engine = ReturnType<typeof fakeEngine>;

/**
 * The pixels of a texture the loader made. Three types `Texture.image` as an opaque per-backend extension,
 * and every texture this module produces is a `DataTexture` — placeholder, TGA decode or host image alike.
 */
const pixelsOf = (texture: Texture | undefined): { data: Uint8Array; width: number; height: number } =>
  (texture?.image ?? { data: new Uint8Array(), width: 0, height: 0 }) as { data: Uint8Array; width: number; height: number };

const clientOn = (engine: Engine): MeshSource =>
  new KiraClient({ baseUrl: "http://127.0.0.1:8901", token: "sekret", fetch: engine.fetch }) as unknown as MeshSource;

const seen: string[] = [];
const host: StageHost = {
  imageTexture: (bytes, relative) => {
    seen.push(relative);
    return new DataTexture(new Uint8Array(bytes), 1, 1);
  },
};

describe("loadCharacter — the mesh", () => {
  it("builds a skinned mesh, a skeleton and the attributes three needs to draw them", async () => {
    const engine = fakeEngine({ characterFiles: files() });
    const loaded = await loadCharacter(clientOn(engine), profile(), host);

    expect(loaded.mesh.isSkinnedMesh).toBe(true);
    expect(loaded.object.children).toEqual([loaded.mesh]);
    expect(loaded.skeleton.bones).toHaveLength(3);
    expect(loaded.mesh.skeleton).toBe(loaded.skeleton);
    expect(loaded.bones.map((bone) => bone.name)).toEqual(["bone0", "bone1", "bone2"]);

    const geometry = loaded.geometry;
    // `+ 0` folds the `-0` the fixture's first vertex carries onto `0`; the loader passes positions through
    // untouched, which is the point.
    expect(Array.from(geometry.getAttribute("position").array).map((value) => value + 0)).toEqual([0, 0, 0, 1, -1, 2, 2, -2, 4, 3, -3, 6]);
    expect(geometry.getAttribute("normal").itemSize).toBe(3);
    expect(geometry.getAttribute("uv").itemSize).toBe(2);
    // The fixture's rows read [0,1],[0.0625,0.96875],[0.125,0.9375],[0.1875,0.90625] — PMX measures v from the
    // top of the picture. Three uploads every map flipped, so the loader turns v over once, here to [0,0],
    // [0.0625,0.03125] and so on: without it the face samples its own chin and the eye meshes hide behind it.
    expect(Array.from(geometry.getAttribute("uv").array)).toEqual([
      0, 0, 0.0625, 0.03125, 0.125, 0.0625, 0.1875, 0.09375,
    ]);
    expect(geometry.getAttribute("skinWeight").array).toBeInstanceOf(Float32Array);
    // Four slots per vertex, and 16-bit where the bone table fits in 16 — three's classic skinning path
    // declares `attribute vec4 skinIndex`, which is what an unsigned-short attribute feeds.
    expect(geometry.getAttribute("skinIndex").itemSize).toBe(4);
    expect(geometry.getAttribute("skinIndex").array).toBeInstanceOf(Uint16Array);
    expect(Array.from(geometry.getAttribute("skinIndex").array)).toEqual([
      0, 1, 2, 0,
      1, 2, 0, 1,
      2, 0, 1, 2,
      0, 1, 2, 0,
    ]);
    // Four weights per vertex, and the row is the engine's expansion: the fixture is a BDEF4 file, so what
    // crossed the wire is what the file said.
    expect(Array.from(geometry.getAttribute("skinWeight").array)).toEqual([
      1, 0, 0, 0,
      0.5, 0.25, 0.125, 0.125,
      1, 0, 0, 0,
      0.5, 0.25, 0.125, 0.125,
    ]);
    expect(geometry.index?.array).toBeInstanceOf(Uint16Array);
    expect(Array.from(geometry.index?.array ?? [])).toEqual([0, 3, 2, 1, 0, 3]);
    expect(() => loaded.dispose()).not.toThrow();
  });

  it("hangs each bone under its parent at the distance the file meant, not the absolute one", async () => {
    const engine = fakeEngine({ characterFiles: files() });
    const loaded = await loadCharacter(clientOn(engine), profile(), host);
    const [root, middle, tip] = loaded.bones;
    expect(root?.parent).toBe(loaded.mesh);
    expect(middle?.parent).toBe(root);
    expect(tip?.parent).toBe(middle);
    // The wire carries (0,0,0), (1,-1,0.5), (2,-2,1) — absolute. A `Bone` holds its own translation, so the
    // child of a bone at (1,-1,0.5) has to be stored at (1,-1,0.5) and not at (2,-2,1).
    expect(root?.position.toArray().map((value) => value + 0)).toEqual([0, 0, 0]);
    expect(middle?.position.toArray()).toEqual([1, -1, 0.5]);
    expect(tip?.position.toArray()).toEqual([1, -1, 0.5]);
    // `Skeleton` reads the world matrices to build the bind inverses, which is the only reason a bone that
    // starts 1 unit along x has an inverse that moves 1 unit back.
    const x = loaded.skeleton.boneInverses[1]?.elements[12];
    expect(x).toBeCloseTo(-1, 5);
  });

  it("hangs a bone under a parent the table wrote after it", async () => {
    // The order PMX's bone table happens to be in is not a fact about the skeleton. `astra-4ca04839` has
    // eight of these; a renderer that only walks backwards leaves the child at the root and moves the whole
    // limb with the wrong bone.
    const engine = fakeEngine({
      characterMesh: new Uint8Array(minimal({ boneParents: [1, -1] })),
      characterFiles: files(),
    });
    const loaded = await loadCharacter(
      clientOn(engine),
      profile({ main: capability({ textures: [], missing_textures: [] }) }),
      host,
    );
    const [child, parent] = loaded.bones;
    expect(parent?.parent).toBe(loaded.mesh);
    expect(child?.parent).toBe(parent);
    // Bone 0 sits at x=0 and its parent at x=1, so what the wire calls absolute becomes -1 here.
    expect(child?.position.toArray()).toEqual([-1, 0, 0]);
  });

  it("draws one range per material and gives each its own picture", async () => {
    const engine = fakeEngine({ characterFiles: files() });
    const loaded = await loadCharacter(clientOn(engine), profile(), host);
    expect(loaded.materials.map((material) => material.name)).toEqual(["m0", "m1"]);
    expect(loaded.geometry.groups).toEqual([
      { start: 0, count: 3, materialIndex: 0 },
      { start: 3, count: 3, materialIndex: 1 },
    ]);
    // m0 owns texture 0 — `tex/颜.png`, through the host. m1 is a memo-only material: `texture` is -1, so
    // it is drawn from its diffuse colour with no map at all rather than a placeholder for a file it never
    // asked for.
    expect(loaded.materials[0]?.map).toBeDefined();
    expect(loaded.materials[1]?.map).toBeNull();
    expect(loaded.materials[0]?.color.getHex()).toBe(0x00ff00);
    // m0 carries a map, so it is blended: MMD reads the map's own alpha, and the corpus leans on it for the
    // transparent hair layer over Burnice's blonde, the fade at Ellen's red tips and Astra's headband.
    expect(loaded.materials[0]?.transparent).toBe(true);
    expect(loaded.materials[0]?.depthWrite).toBe(true);
    expect(loaded.materials[1]?.transparent).toBe(false);
    // Bit 0 of the material flags is PMX's "draw from behind too" — m0 says 0 and m1 says 1. Reading 0x20
    // instead made both of them single-sided: m1 is where a skirt or a hair shell needs its far face.
    expect(loaded.materials[0]?.side).toBe(FrontSide);
    expect(loaded.materials[1]?.side).toBe(DoubleSide);
  });
});

describe("loadCharacter — the textures the walk named", () => {
  it("asks for the fetchable ones and decodes each with the reader the plan picked", async () => {
    seen.length = 0;
    const engine = fakeEngine({ characterFiles: files() });
    const loaded = await loadCharacter(clientOn(engine), profile(), host);

    expect(seen).toEqual(["tex/颜.png"]);
    const tga = loaded.textures.get("hair.tga");
    expect(tga).toBeInstanceOf(DataTexture);
    // A TGA decode is a colour map, and three's loader leaves a DataTexture in no colour space at all: sampled
    // as linear, every .tga face in the corpus read as a washed-out photocopy.
    expect(tga?.colorSpace).toBe(SRGBColorSpace);
    expect(pixelsOf(tga).width).toBe(2);
    expect(pixelsOf(tga).height).toBe(2);
    // BGA in, RGBA out: the first stored pixel is blue, and the texture's first pixel is blue.
    expect(Array.from(pixelsOf(tga).data.slice(0, 4))).toEqual([0, 0, 255, 255]);
  });

  it("names what it would not ask for, and draws each one in magenta", async () => {
    seen.length = 0;
    const engine = fakeEngine({ characterFiles: files() });
    const loaded = await loadCharacter(clientOn(engine), profile(), host);
    const magenta = [255, 0, 255, 255];

    // Every texture the model names still has a picture, because a material indexes the table by position
    // and a stage that left one out would draw that part of the body with nothing at all. The order the map
    // fills in is not a contract — a refusal is known synchronously and a fetched file after its await —
    // and nothing looks a texture up by anything but its path.
    expect(loaded.textures.size).toBe(6);
    expect(new Set(loaded.textures.keys())).toEqual(new Set([
      "tex/颜.png",
      "hair.tga",
      "hair.bmp",
      "../outside.png",
      "C:/Users/me/face.png",
      "body.dds",
    ]));
    for (const relative of ["hair.bmp", "../outside.png", "C:/Users/me/face.png", "body.dds"]) {
      expect(loaded.textures.get(relative)).toBeInstanceOf(DataTexture);
      expect(Array.from(pixelsOf(loaded.textures.get(relative)).data)).toEqual(magenta);
    }

    const report = loaded.findings.join("\n");
    expect(loaded.findings.filter((line) => line.includes("hair.bmp"))).toHaveLength(1);
    expect(report).toContain("the archive never carried it");
    expect(report).toContain("nothing on this page decodes that format");
    // Both of the two that escape are said out loud, and by the reason each one escapes: the engine's own
    // flag for the `..` reference, our own reading of a path that names a whole drive.
    expect(report).toContain("the reference leaves the character's folder");
    expect(loaded.findings.filter((line) => line.includes("outside.png"))).toHaveLength(1);
    expect(loaded.findings.filter((line) => line.includes("face.png"))).toHaveLength(1);
    // Not one request for a file the route would refuse, a file that is not on disk, or a format nothing
    // opens: the only fetches are the two the plan lists.
    expect(engine.calls.map((call) => call.url)).toEqual([
      `/v1/kira/characters/${ELLEN_ID}/mesh`,
      "/v1/kira/characters/ellen-9f3a2b1c/file?path=tex%2F%E9%A2%9C.png",
      "/v1/kira/characters/ellen-9f3a2b1c/file?path=hair.tga",
    ]);
  });

  it("asks the file route from inside the folder the model itself sits in", async () => {
    seen.length = 0;
    // A donor archive that packs `inner/model.pmx` resolves its textures against `inner/`, so the walk's
    // `relative` is `tex/颜.png` while the path the file route needs is `inner/tex/颜.png`. Asking with the
    // bare name is a 404 for a texture that is on disk, and the stage would call the face magenta.
    const nested = capability({
      path: "inner/model.pmx",
      textures: [finding({ declared: "tex\\颜.png", relative: "tex/颜.png", format: "png" })],
      missing_textures: [],
    });
    const engine = fakeEngine({
      characterMesh: new Uint8Array(minimal({ texturePaths: [["tex\\颜.png", "tex/颜.png", false]] })),
      characterFiles: { "inner/tex/颜.png": PNG_BYTES },
    });
    const loaded = await loadCharacter(clientOn(engine), profile({ main: nested }), host);

    expect(engine.calls.map((call) => call.url)).toEqual([
      `/v1/kira/characters/${ELLEN_ID}/mesh`,
      "/v1/kira/characters/ellen-9f3a2b1c/file?path=inner%2Ftex%2F%E9%A2%9C.png",
    ]);
    expect(seen).toEqual(["tex/颜.png"]);
    // The only finding the stage still has is the non-vertex morph the default names carry; nothing about
    // this texture, and the pixel is the host's decode of the file rather than magenta.
    expect(loaded.findings.join("\n")).not.toContain("颜.png");
    expect(Array.from(pixelsOf(loaded.textures.get("tex/颜.png")).data.slice(0, 4))).toEqual([0x89, 0x50, 0x4e, 0x47]);
  });

  it("carries the token in a header and never in a path", async () => {
    const engine = fakeEngine({ characterFiles: files() });
    await loadCharacter(clientOn(engine), profile(), host);
    for (const call of engine.calls) {
      expect(call.headers.Authorization).toBe("Bearer sekret");
      expect(call.url).not.toContain("sekret");
      expect(call.method).toBe("GET");
    }
  });

  it("survives a texture the engine refuses to serve", async () => {
    seen.length = 0;
    const engine = fakeEngine({ characterFiles: { "hair.tga": tgaBytes() } });
    const loaded = await loadCharacter(clientOn(engine), profile(), host);

    // The promise resolves: one file that is not there leaves a magenta face and a finding, not no character.
    expect(loaded.textures.get("tex/颜.png")).toBeInstanceOf(DataTexture);
    expect(seen).toEqual([]);
    expect(loaded.findings.join("\n")).toContain("tex/颜.png");
    expect(loaded.findings.join("\n")).toContain("character_file_not_found");
  });

  it("survives a host that cannot open the file it was handed", async () => {
    const engine = fakeEngine({ characterFiles: files() });
    const grumpy: StageHost = {
      imageTexture: () => {
        throw new Error("this page cannot decode a webp");
      },
    };
    const loaded = await loadCharacter(clientOn(engine), profile(), grumpy);
    expect(Array.from(pixelsOf(loaded.textures.get("tex/颜.png")).data)).toEqual([255, 0, 255, 255]);
    expect(loaded.findings.join("\n")).toContain("this page cannot decode a webp");
  });

  it("says which morph names have no offsets behind them", async () => {
    const engine = fakeEngine({ characterFiles: files() });
    const loaded = await loadCharacter(clientOn(engine), profile(), host);
    // The mesh carries `口` (a vertex morph); `まばたき` is kind 0 in the report, so there is nothing to drive.
    expect(loaded.findings.join("\n")).toContain("1 of the 2 morph name(s) this model publishes are not vertex morphs");
  });

  it("keeps quiet about morph kinds when the report has names without kinds", async () => {
    const engine = fakeEngine({ characterFiles: files() });
    const thin = profile({ main: capability({ morph_names: ["あ", "い"], morph_kinds: [] }) });
    const loaded = await loadCharacter(clientOn(engine), thin, host);
    // Three archives in the corpus do exactly this. A stage that guessed would tell the user their face is
    // broken when the report is only thin.
    expect(loaded.findings.join("\n")).not.toContain("not vertex morphs");
  });
});

describe("loadCharacter — morph targets", () => {
  it("keeps the offsets additive and the names addressable", async () => {
    const engine = fakeEngine({ characterFiles: files() });
    const loaded = await loadCharacter(clientOn(engine), profile(), host);
    const positions = loaded.geometry.morphAttributes.position ?? [];
    expect(positions).toHaveLength(1);
    expect(loaded.geometry.morphTargetsRelative).toBe(true);
    expect(positions[0]?.name).toBe("口");
    expect(loaded.morphs.get("口")).toBe(0);
    expect(loaded.morphTableIndexes.get("口")).toBe(0);
    expect(Array.from(positions[0]?.array as Float32Array)).toEqual([
      0, 0, 0, // vertex 0 moves by nothing at all — the fixture says so
      0.0625, -0.03125, 0.125,
      0, 0, 0, // the vertices this morph never mentions stay where they are
      0, 0, 0,
    ]);
    // `Mesh.updateMorphTargets` keys its own dictionary off the attribute name, so a stage can set
    // `mesh.morphTargetInfluences[mesh.morphTargetDictionary["口"]] = 1` and mean a mouth.
    expect(loaded.mesh.morphTargetDictionary?.["口"]).toBe(0);
    expect(loaded.mesh.morphTargetInfluences).toEqual([0]);
  });
});

describe("loadCharacter — what it refuses", () => {
  it("names the character when its archive has no body", async () => {
    const engine = fakeEngine({ characterFiles: files() });
    const props = profile({ id: PROPS_ID, main: null });
    await expect(loadCharacter(clientOn(engine), props, host)).rejects.toThrow(/has no body to put on the stage/);
    // and no request was made to find out
    expect(engine.calls).toEqual([]);
  });

  it("passes the engine's own refusal through when the mesh route says no", async () => {
    const engine = fakeEngine({ characterFiles: files() });
    await expect(loadCharacter(clientOn(engine), profile({ id: PROPS_ID }), host)).rejects.toMatchObject({
      body: { code: "character_file_not_found" },
    });
  });

  it("constructs no canvas and no WebGL renderer", async () => {
    const engine = fakeEngine({ characterFiles: files() });
    await loadCharacter(clientOn(engine), profile(), host);
    // Everything above happens on the CPU side of the seam. The stage that puts `loaded.object` in front of
    // a user owns the renderer; this module must not, or the suite needs a GPU.
    expect(document.querySelectorAll("canvas")).toHaveLength(0);
  });

  it("releases everything it made", async () => {
    const engine = fakeEngine({ characterFiles: files() });
    const loaded = await loadCharacter(clientOn(engine), profile(), host);
    let disposed = 0;
    for (const texture of loaded.textures.values()) {
      texture.addEventListener("dispose", () => {
        disposed += 1;
      });
    }
    for (const material of loaded.materials) {
      material.addEventListener("dispose", () => {
        disposed += 1;
      });
    }
    loaded.geometry.addEventListener("dispose", () => {
      disposed += 1;
    });
    loaded.dispose();
    // six textures (two fetched, four placeholders) + two materials + the geometry
    expect(disposed).toBe(9);
  });
});

describe("loadCharacter — the layers three's toon material does not have", () => {
  /** The three anchors every patched fragment has to have: the gradient read and the lit colour. */
  const source = [
    "#include <common>",
    "vec2 coord = vec2( dotNL * 0.5 + 0.5, 0.0 );",
    "return vec3( texture2D( gradientMap, coord ).r );",
    "vec3 outgoingLight = reflectedLight.directDiffuse + reflectedLight.indirectDiffuse + totalEmissiveRadiance;",
  ].join("\n");

  const compile = (material: MeshToonMaterial): { uniforms: Record<string, { value: unknown }>; fragmentShader: string } => {
    const shader = { uniforms: {} as Record<string, { value: unknown }>, fragmentShader: source };
    material.onBeforeCompile(shader as never, undefined as never);
    return shader;
  };

  const dress = async (over: {
    paths: Array<[string, string, boolean]>;
    material: { texture?: number; sphere?: number; sphereMode?: number; toon?: number; sharedToon?: boolean };
    missing?: string[];
  }) => {
    const engine = fakeEngine({
      characterMesh: new Uint8Array(minimal({ texturePaths: over.paths, material: over.material })),
      characterFiles: files(),
    });
    const textures = over.paths.map(([declared, relative, escapes]) =>
      finding({
        declared,
        relative,
        exists: !escapes && !(over.missing ?? []).includes(relative),
        size: escapes || (over.missing ?? []).includes(relative) ? null : 64,
        format: relative.split(".").pop() ?? "png",
        escapes,
      }),
    );
    const main = capability({ textures, missing_textures: over.missing ?? [] });
    return loadCharacter(clientOn(engine), profile({ main }), host);
  };

  it("shades with the archive's own toon ramp, read down its column", async () => {
    const loaded = await dress({
      paths: [["tex\\颜.png", "tex/颜.png", false], ["hair.tga", "hair.tga", false]],
      material: { texture: 0, toon: 1 },
    });
    const material = loaded.materials[0];
    // The ramp is the texture the material's toon index names — not the diffuse map, not a built-in row.
    expect(material.gradientMap).toBe(loaded.textures.get("hair.tga"));

    const shader = compile(material);
    // A PMX ramp runs top to bottom while three reads its gradient left to right, so the sample swaps axes;
    // and the ramp's tint is in all three channels, where three only reads red.
    expect(shader.fragmentShader).toContain("vec2 coord = vec2( 0.5, dotNL * 0.5 + 0.5 );");
    expect(shader.fragmentShader).toContain("return texture2D( gradientMap, coord ).rgb;");
    expect(shader.fragmentShader).not.toContain("vec2( dotNL * 0.5 + 0.5, 0.0 )");
  });

  it("adds the sphere map after the lights, the way MMD does", async () => {
    const loaded = await dress({
      paths: [["tex\\颜.png", "tex/颜.png", false], ["hair.tga", "hair.tga", false]],
      material: { texture: 0, sphere: 1, sphereMode: 2 },
    });
    const material = loaded.materials[0];
    const shader = compile(material);
    expect(shader.uniforms.sphereMap?.value).toBe(loaded.textures.get("hair.tga"));
    expect(shader.uniforms.sphereMode?.value).toBe(2);
    expect(shader.fragmentShader).toContain("uniform sampler2D sphereMap;");
    // Mode 2 is MMD's add: the rim light lands on the summed colour, not on the diffuse layer under it.
    expect(shader.fragmentShader).toContain("outgoingLight += sphereSample.rgb;");
    // A sphere texture is a look-up by the view normal, not a second diffuse map.
    expect(shader.fragmentShader).toContain("normalize( normal ).xy * 0.5 + 0.5");
  });

  it("calls a missing toon ramp a missing ramp, not a magenta face", async () => {
    const loaded = await dress({
      paths: [["tex\\颜.png", "tex/颜.png", false], ["hair.bmp", "hair.bmp", false]],
      material: { texture: 0, toon: 1 },
      missing: ["hair.bmp"],
    });
    // Nothing draws with it as a map, so there is no magenta pixel anywhere; the material keeps three's own
    // band and the finding says exactly that instead of sending the reader looking for a pink face.
    expect(loaded.materials[0].gradientMap).toBeNull();
    const report = loaded.findings.join("\n");
    expect(report).toContain("hair.bmp");
    expect(report).toContain("shaded by the light alone");
    expect(report).not.toContain("magenta");
  });
});
