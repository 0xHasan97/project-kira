import { describe, expect, it } from "vitest";
import type { CharacterCapability, TextureFinding } from "../contracts.ts";
import {
  MOOD_KEYS,
  PHYSICS_COST_LIMIT,
  VISEME_KEYS,
  moodMorphs,
  physicsBudget,
  texturePlan,
  visemeMorphs,
} from "./pmx.ts";

/**
 * Every fixture below is a real donor archive as `kira-engine characters show` measured it, because a
 * hand-written PMX would let this module pass by inventing shapes no exporter writes.
 */
const model = (over: Partial<CharacterCapability>): CharacterCapability =>
  ({ morph_names: [], morph_kinds: [], textures: [], ...over }) as CharacterCapability;

const texture = (over: Partial<TextureFinding>): TextureFinding =>
  ({ declared: "", relative: "", exists: false, size: null, format: "", escapes: false, ...over });

/** Ellen — `9y5Huh14gN.zip`, 59 morphs, all of them vertex morphs (PMX kind 1). */
const ELLEN_MORPHS: Array<[string, number]> = [
  ["まばたき", 1],
  ["ウィンク２右", 1],
  ["ウィンク２", 1],
  ["笑い", 1],
  ["ウィンク右", 1],
  ["ウィンク", 1],
  ["びっくり右", 1],
  ["びっくり左", 1],
  ["じと目", 1],
  ["怒り目", 1],
  ["怒り目２", 1],
  ["悲しむ", 1],
  ["眼角下", 1],
  ["喜び", 1],
  ["挑発する", 1],
  ["真面目", 1],
  ["困る", 1],
  ["怒り", 1],
  ["にこり", 1],
  ["上", 1],
  ["上左", 1],
  ["上右", 1],
  ["下", 1],
  ["あ", 1],
  ["い", 1],
  ["う", 1],
  ["え", 1],
  ["お", 1],
  ["にやり", 1],
  ["□", 1],
  ["あ２", 1],
  ["□２", 1],
  ["い２", 1],
  ["お２", 1],
  ["え２", 1],
  ["ワ", 1],
  ["にっ", 1],
  ["▲", 1],
  ["口左", 1],
  ["口右", 1],
  ["口上", 1],
  ["口下", 1],
  ["口横広げ右", 1],
  ["口横広げ左", 1],
  ["口横狭め左", 1],
  ["口横狭め右", 1],
  ["口角下げ右", 1],
  ["口角下げ左", 1],
  ["口角上げ右", 1],
  ["口角上げ左", 1],
  ["にっこり", 1],
  ["え３", 1],
  ["え４", 1],
  ["へ", 1],
  ["口线消", 1],
  ["口横広げ", 1],
  ["口横狭め", 1],
  ["口角下げ", 1],
  ["口角上げ", 1],
];

/** Ellen's eight texture references, all of which arrived with the archive. */
const ELLEN_TEXTURES: TextureFinding[] = [
  texture({ declared: "tex/颜.tga", relative: "tex/颜.tga", exists: true, size: 1048576, format: "tga" }),
  texture({ declared: "skin.bmp", relative: "skin.bmp", exists: true, size: 512000, format: "bmp" }),
  texture({ declared: "hair.bmp", relative: "hair.bmp", exists: true, size: 512000, format: "bmp" }),
  texture({ declared: "tex/体.tga", relative: "tex/体.tga", exists: true, size: 1048576, format: "tga" }),
  texture({ declared: "toon_defo.bmp", relative: "toon_defo.bmp", exists: true, size: 1024, format: "bmp" }),
  texture({ declared: "tex/髮.tga", relative: "tex/髮.tga", exists: true, size: 1048576, format: "tga" }),
  texture({ declared: "tex/sh.png", relative: "tex/sh.png", exists: true, size: 2048, format: "png" }),
  texture({ declared: "spa/hair_s.bmp", relative: "spa/hair_s.bmp", exists: true, size: 512000, format: "bmp" }),
];

/**
 * 苍鹭·托特「扉页之吻」— `深空之眼—苍鹭...zip`, the widest physics in the corpus (577 rigid bodies,
 * 955 constraints) and the only archive whose 笑い is a group morph (kind 0), which deforms nothing
 * by itself, and whose 悲しむ does not exist under any of its 46 names.
 */
const TOTEM_MORPHS: Array<[string, number]> = [
  ["真面目", 1],
  ["困る", 1],
  ["にこり", 1],
  ["怒り", 1],
  ["上", 1],
  ["下", 1],
  ["あ", 1],
  ["あ1", 1],
  ["あ2", 1],
  ["い", 1],
  ["う", 1],
  ["え", 1],
  ["え1", 1],
  ["お", 1],
  ["あ２", 1],
  ["口右", 1],
  ["口左", 1],
  ["口上", 1],
  ["口下", 1],
  ["にやり２", 1],
  ["にやり２1", 1],
  ["口横缩げ", 1],
  ["口横広げ", 1],
  ["口角上げ", 1],
  ["口角下げ", 1],
  ["口角下げ1", 1],
  ["まばたき", 1],
  ["笑い", 0],
  ["ウィンク", 1],
  ["ウィンク右", 1],
  ["ウィンク２", 1],
  ["ｳｨﾝｸ２右", 1],
  ["びっくり", 1],
  ["びっくり1", 1],
  ["じと目", 1],
  ["じと目1", 1],
  ["ｷﾘｯ", 1],
  ["眼睑上", 1],
  ["眼角下", 1],
  ["瞳小", 1],
  ["瞳縦潰れ", 1],
  ["恐ろしい子！", 1],
  ["なごみ", 1],
  ["はちゅ目", 1],
  ["はぅ", 1],
  ["照れ", 1],
];

/** The shape Vivian's 怒り has (PMX kind 2): a bone morph moves a bone, so it is not a face to drive. */
const boneMoodShape = (): CharacterCapability => table([["怒り", 2], ["悲しむ", 1]]);

/**
 * `index` is the morph's position in the file's own table and `name` is what the exporter wrote, which
 * is the key a renderer's morph-target dictionary uses. Both come from the profile as published, so a
 * fixture built here has to keep the arrays in lockstep — a prefix of a real table still indexes it
 * correctly, but a re-ordered one would not.
 */
function table(entries: Array<[string, number]>, textures: TextureFinding[] = []): CharacterCapability {
  return model({ morph_names: entries.map((entry) => entry[0]), morph_kinds: entries.map((entry) => entry[1]), textures });
}

const ellen = (): CharacterCapability => table(ELLEN_MORPHS, ELLEN_TEXTURES);
const totem = (): CharacterCapability => table(TOTEM_MORPHS);

describe("texturePlan", () => {
  it("turns a windows path into the one the engine will serve, and picks a decoder per suffix", () => {
    const plan = texturePlan(
      model({
        textures: [
          texture({ declared: "tex\\颜.tga", relative: "tex/颜.tga", exists: true, size: 1, format: "tga" }),
          texture({ declared: "skin.bmp", relative: "skin.bmp", exists: true, size: 1, format: "bmp" }),
          texture({ declared: "tex\\sh.png", relative: "tex/sh.png", exists: true, size: 1, format: "png" }),
        ],
      }),
    );
    expect(plan.fetch).toEqual([
      { declared: "tex\\颜.tga", relative: "tex/颜.tga", path: "tex/颜.tga", decoder: "tga" },
      { declared: "skin.bmp", relative: "skin.bmp", path: "skin.bmp", decoder: "image" },
      { declared: "tex\\sh.png", relative: "tex/sh.png", path: "tex/sh.png", decoder: "image" },
    ]);
    expect(plan.missing).toEqual([]);
    expect(plan.refused).toEqual([]);
    expect(plan.unsupported).toEqual([]);
  });

  it("normalises the path it will fetch instead of trusting the one the profile carries", () => {
    // An older profile, or a report written by a different reader, can hand back the declared string
    // unchanged. Fetching that would ask the file route for a path containing a separator it never
    // separates, and get `character_file_not_found` for a texture that is sitting in the folder.
    const plan = texturePlan(
      model({ textures: [texture({ declared: "tex\\体.tga", relative: "tex\\体.tga", exists: true, size: 1, format: "tga" })] }),
    );
    expect(plan.fetch).toEqual([{ declared: "tex\\体.tga", relative: "tex/体.tga", path: "tex/体.tga", decoder: "tga" }]);
  });

  it("asks for a texture inside the folder the model itself sits in", () => {
    // 苍鹭·托特 — `model-d055bfba`. Its archive unpacks one directory deep, so the profile's `relative` is
    // measured from `model.pmx`, while the file route measures from the character's folder. The report says
    // 11/11 and the route answers 404 for all eleven unless the prefix comes along.
    const plan = texturePlan(
      model({
        path: "深空之眼—苍鹭·托特「扉页之吻」/model.pmx",
        textures: [
          texture({ declared: "衣服2.png", relative: "衣服2.png", exists: true, size: 1, format: "png" }),
          texture({ declared: "tex\\\\眼.png", relative: "tex/眼.png", exists: true, size: 1, format: "png" }),
        ],
      }),
    );
    expect(plan.fetch).toEqual([
      { declared: "衣服2.png", relative: "衣服2.png", path: "深空之眼—苍鹭·托特「扉页之吻」/衣服2.png", decoder: "image" },
      { declared: "tex\\\\眼.png", relative: "tex/眼.png", path: "深空之眼—苍鹭·托特「扉页之吻」/tex/眼.png", decoder: "image" },
    ]);
  });

  it("keeps a path that leaves the model's folder refused when the model is nested", () => {
    // The prefix is where the file lives, not a licence to climb. The engine's `escapes` answer is about
    // the model's own directory and the route's guard is about the character's folder; the stricter of the
    // two is the one that runs, so a nested model still cannot reach a sibling character.
    const plan = texturePlan(
      model({
        path: "inner/model.pmx",
        textures: [texture({ declared: "../other/颜.tga", relative: "../other/颜.tga", exists: true, size: 1, format: "tga", escapes: true })],
      }),
    );
    expect(plan.fetch).toEqual([]);
    expect(plan.refused).toEqual(["../other/颜.tga"]);
  });

  it("splits what the archive never carried from what it did", () => {
    // Jane Doe — `RoL6mVzkCH.zip`, where `hair.bmp` is referenced by the material table and absent from
    // the zip: the only archive in the corpus whose texture_status reads `7/8 — hair.bmp absent`.
    const plan = texturePlan(
      model({
        textures: [
          texture({ declared: "tex\\颜.tga", relative: "tex/颜.tga", exists: true, size: 1, format: "tga" }),
          texture({ declared: "hair.bmp", relative: "hair.bmp", exists: false, size: null, format: "bmp" }),
        ],
      }),
    );
    expect(plan.fetch.map((entry) => entry.relative)).toEqual(["tex/颜.tga"]);
    expect(plan.missing).toEqual(["hair.bmp"]);
  });

  it("never plans a fetch for a path that leaves the character's folder", () => {
    const plan = texturePlan(
      model({
        textures: [
          texture({ declared: "../other/颜.tga", relative: "../other/颜.tga", exists: true, size: 1, format: "tga", escapes: true }),
          texture({ declared: "..\\..\\secrets.png", relative: "../../secrets.png", exists: false, size: null, format: "png", escapes: true }),
          // The engine resolves this against the model's own folder on its own disk, so `exists` can be
          // true here. The file route refuses an absolute shape, so asking for it would be a 400 at best.
          texture({ declared: "C:\\Users\\me\\Pictures\\face.png", relative: "C:/Users/me/Pictures/face.png", exists: true, size: 1, format: "png" }),
          texture({ declared: "/etc/passwd.png", relative: "etc/passwd.png", exists: false, size: null, format: "png" }),
        ],
      }),
    );
    expect(plan.fetch).toEqual([]);
    expect(plan.refused).toEqual([
      "../other/颜.tga",
      "..\\..\\secrets.png",
      "C:\\Users\\me\\Pictures\\face.png",
      "/etc/passwd.png",
    ]);
  });

  it("asks once for a texture several materials reference", () => {
    const twice = texture({ declared: "tex\\颜.tga", relative: "tex/颜.tga", exists: true, size: 1, format: "tga" });
    const plan = texturePlan(model({ textures: [twice, twice] }));
    expect(plan.fetch).toHaveLength(1);
    expect(plan.missing).toEqual([]);
  });

  it("keeps a format nothing on the page decodes out of the fetch list", () => {
    // The engine will happily serve .dds and .json bytes; neither becomes a THREE.Texture.
    const plan = texturePlan(
      model({
        textures: [
          texture({ declared: "eye.dds", relative: "eye.dds", exists: true, size: 1, format: "dds" }),
          texture({ declared: "mask.json", relative: "mask.json", exists: true, size: 1, format: "json" }),
        ],
      }),
    );
    expect(plan.fetch).toEqual([]);
    expect(plan.unsupported).toEqual(["eye.dds", "mask.json"]);
  });

  it("says nothing about a model with no textures, and nothing about a prop with no body", () => {
    expect(texturePlan(model({}))).toEqual({ fetch: [], missing: [], refused: [], unsupported: [] });
    expect(texturePlan(null)).toEqual({ fetch: [], missing: [], refused: [], unsupported: [] });
    expect(texturePlan(undefined)).toEqual({ fetch: [], missing: [], refused: [], unsupported: [] });
  });

  it("names a slot that names nothing instead of fetching an empty path", () => {
    const plan = texturePlan(
      model({
        textures: [
          texture({ declared: "", relative: "", exists: false, size: null, format: "" }),
          texture({ declared: "   ", relative: "", exists: false, size: null, format: "" }),
        ],
      }),
    );
    expect(plan.fetch).toEqual([]);
    expect(plan.missing).toEqual([]);
    expect(plan.refused).toEqual(["", "   "]);
  });

  it("uses the declared path's own suffix, not the one the report guessed", () => {
    const plan = texturePlan(
      model({ textures: [texture({ declared: "TEX/颜.TGA", relative: "TEX/颜.TGA", exists: true, size: 1, format: "tga" })] }),
    );
    expect(plan.fetch).toEqual([{ declared: "TEX/颜.TGA", relative: "TEX/颜.TGA", path: "TEX/颜.TGA", decoder: "tga" }]);
  });
});

describe("visemeMorphs", () => {
  it("finds the five vowels at their real places in Ellen's table", () => {
    const found = visemeMorphs(ellen());
    expect(Object.keys(found).sort()).toEqual([...VISEME_KEYS].sort());
    expect(found).toEqual({
      あ: { name: "あ", index: 23, kind: 1 },
      い: { name: "い", index: 24, kind: 1 },
      う: { name: "う", index: 25, kind: 1 },
      え: { name: "え", index: 26, kind: 1 },
      お: { name: "お", index: 27, kind: 1 },
    });
  });

  it("matches the whole name, so あ２ and え３ are never taken for あ and え", () => {
    const found = visemeMorphs(ellen());
    expect(found.あ?.index).toBe(23);
    expect(found.え?.index).toBe(26);
  });

  it("comes back empty for the three archives whose morph table the walk could not name", () => {
    // Astra ×2 and Burnice: 43, 49 and 51 morphs counted, none named — the engine resyncs past the
    // section and publishes an empty list. No viseme is a real answer, not a failure.
    for (const capability of [model({ morph_names: [], morph_kinds: [] }), model({ morph_names: ["", ""], morph_kinds: [1, 1] })]) {
      expect(visemeMorphs(capability)).toEqual({});
    }
  });

  it("tolerates a profile with no body and a payload with no morph keys", () => {
    expect(visemeMorphs(null)).toEqual({});
    expect(visemeMorphs(model({}))).toEqual({});
    expect(moodMorphs({} as CharacterCapability)).toEqual({});
    expect(visemeMorphs({ morph_names: ["あ"] } as CharacterCapability)).toEqual({
      あ: { name: "あ", index: 0, kind: null },
    });
  });

  it("carries the kind through, because a group morph deforms nothing by itself", () => {
    expect(visemeMorphs(totem()).あ).toEqual({ name: "あ", index: 6, kind: 1 });
  });
});

describe("moodMorphs", () => {
  it("finds the moods Ellen really has and admits the one she does not", () => {
    const found = moodMorphs(ellen());
    expect(found).toEqual({
      笑い: { name: "笑い", index: 3, kind: 1 },
      怒り: { name: "怒り", index: 17, kind: 1 },
      悲しむ: { name: "悲しむ", index: 11, kind: 1 },
    });
    // Ellen ships びっくり右 and びっくり左 — one eye each. Driving "surprise" with a wink-shaped
    // morph is worse than not having it, so a partial name is not a match.
    expect(found.びっくり).toBeUndefined();
    expect(MOOD_KEYS).toContain("びっくり");
  });

  it("reports a group mood and a missing one from the heaviest archive in the corpus", () => {
    const found = moodMorphs(totem());
    expect(found.笑い).toEqual({ name: "笑い", index: 27, kind: 0 });
    expect(found.怒り?.kind).toBe(1);
    expect(found.びっくり).toEqual({ name: "びっくり", index: 32, kind: 1 });
    expect(found.悲しむ).toBeUndefined();
  });

  it("says a bone morph is a bone morph", () => {
    expect(moodMorphs(boneMoodShape()).怒り).toEqual({ name: "怒り", index: 0, kind: 2 });
    expect(moodMorphs(boneMoodShape()).悲しむ).toEqual({ name: "悲しむ", index: 1, kind: 1 });
  });

  it("comes back empty rather than throwing when a morph count has no names behind it", () => {
    expect(moodMorphs(model({ morph_names: [], morph_kinds: [] }))).toEqual({});
    expect(moodMorphs(undefined)).toEqual({});
  });
});

describe("physicsBudget", () => {
  it("keeps Ellen's cloth and hair on and turns the heaviest archive in the corpus off", () => {
    // Ellen — 317 rigid bodies, 462 constraints. 苍鹭·托特 — 577 and 955, the widest in the corpus.
    expect(physicsBudget(317, 462)).toMatchObject({ cost: 779, on: true });
    expect(physicsBudget(577, 955)).toMatchObject({ cost: 1532, on: false });
  });

  it("puts the limit between the two real readings so the decision cannot drift silently", () => {
    expect(PHYSICS_COST_LIMIT).toBeGreaterThan(779);
    expect(PHYSICS_COST_LIMIT).toBeLessThanOrEqual(1532);
    expect(physicsBudget(600, PHYSICS_COST_LIMIT - 600).on).toBe(true);
    expect(physicsBudget(600, PHYSICS_COST_LIMIT - 600 + 1).on).toBe(false);
  });

  it("leaves physics off when there is nothing to simulate", () => {
    const decision = physicsBudget(0, 0);
    expect(decision.on).toBe(false);
    expect(decision.cost).toBe(0);
    expect(decision.reason).toContain("no rigid bodies");
  });

  it("leaves physics off when the walk could not count", () => {
    // A resynced archive publishes null counts; guessing "small" would put a 60 fps model and an
    // unmeasurable one on the same path.
    const decision = physicsBudget(null, undefined);
    expect(decision.on).toBe(false);
    expect(decision.cost).toBeNull();
    expect(decision.reason).toContain("unknown");
  });

  it("counts only what both numbers say", () => {
    expect(physicsBudget(1200, null).cost).toBeNull();
    expect(physicsBudget(1000, 500).cost).toBe(1500);
  });
});
