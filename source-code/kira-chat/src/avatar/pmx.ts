import type { CharacterCapability } from "../contracts.ts";

/**
 * What a PMX says about itself, read before any of it reaches a GPU.
 *
 * `kira-engine` walks the bytes and publishes the counts, the morph table and the texture findings; this
 * module turns that report into the two decisions the stage has to make on the browser's side: which
 * files to ask for and how to decode each one, and whether the physics is worth simulating. Nothing here
 * parses a PMX — the engine already did, and a second reader on the wrong side of the loopback would
 * disagree with the first one about what a model contains.
 */

/** `tga` is the engine's own decoder; `image` is whatever the page uses for a file a browser opens. */
export type TextureDecoder = "tga" | "image";

export interface PlannedTexture {
  /** as the model declared it, kept so a finding can quote the file rather than our rewrite of it */
  declared: string;
  /** posix, as the report and the mesh name it — the key the stage's texture map is built with */
  relative: string;
  /** the path the file route takes: `relative` inside the folder the model itself sits in */
  path: string;
  decoder: TextureDecoder;
}

export interface TexturePlan {
  /** one entry per distinct file to fetch, in the order the model references them */
  fetch: PlannedTexture[];
  /** the material table names it and the archive never carried */
  missing: string[];
  /** a shape the file route would refuse, or a slot that names no file at all */
  refused: string[];
  /** the bytes are there and the engine will serve them, but nothing on the page decodes them */
  unsupported: string[];
}

export interface MorphRef {
  /** the exporter's own name — the key a morph-target dictionary is built from */
  name: string;
  /** its position in the profile's `morph_names`, which is the PMX table's own order */
  index: number;
  /** PMX's morph type: 0 group, 1 vertex, 2 bone, 3+ the extra UV layers. Null when the profile has names but no kinds. */
  kind: number | null;
}

export interface PhysicsDecision {
  /** rigid bodies plus constraints, or null when the walk could not count either one */
  cost: number | null;
  on: boolean;
  reason: string;
}

/** The five vowels a Japanese lip-sync is built from, in the order MMD's standard morphs use. */
export const VISEME_KEYS = ["あ", "い", "う", "え", "お"] as const;

/** Four expressions the stage can hold between turns. A model with none of them is not a failure. */
export const MOOD_KEYS = ["笑い", "怒り", "悲しむ", "びっくり"] as const;

/**
 * Provisional, and only as good as the corpus it was set against: the widest archive anyone has put on
 * this stage so far runs 577 rigid bodies and 955 constraints, the one that looks best runs 317 and 462.
 * The browser pass (exit criterion 16) replaces this with the number that keeps the frame budget.
 */
export const PHYSICS_COST_LIMIT = 1200;

const IMAGE_SUFFIXES = new Set(["png", "jpg", "jpeg", "bmp", "webp", "avif", "gif"]);

/**
 * The path the fetch has to use, or null when the reference cannot mean a file inside the folder.
 *
 * Mirrors the engine's normalisation — backslashes are separators, empty and `.` segments mean nothing,
 * a leading separator or a `..` segment escapes — and adds the one case the engine's own disk can
 * resolve but the file route will not serve: `C:\Users\me\Pictures\face.png` is absolute on Windows, so
 * it arrives as a reference with `exists: true` and no way to fetch it.
 */
function relativePath(declared: string): string | null {
  const flat = declared.replace(/\\/g, "/");
  if (flat.startsWith("/")) return null;
  const parts: string[] = [];
  for (const part of flat.split("/")) {
    if (part.trim() === "" || part === ".") continue;
    if (part === "..") return null;
    if (parts.length === 0 && /^[a-zA-Z]:$/.test(part)) return null;
    parts.push(part);
  }
  return parts.length === 0 ? null : parts.join("/");
}

function suffixOf(path: string): string {
  const base = path.slice(path.lastIndexOf("/") + 1);
  const dot = base.lastIndexOf(".");
  return dot > 0 ? base.slice(dot + 1).toLowerCase() : "";
}

/**
 * What to fetch for one model, and what to say about the rest.
 *
 * The declared string is re-normalised here rather than trusted from `relative`: a report written by a
 * different reader, or an older one, can hand back the Windows path unchanged, and fetching that asks
 * the file route for a name it never separates. `escapes` wins either way — the engine resolved it
 * against the folder on its own disk and knows something this side cannot.
 */
export function texturePlan(model: Pick<CharacterCapability, "textures" | "path"> | null | undefined): TexturePlan {
  // Keyed by the path, because several materials name the same texture and one file fetches once;
  // insertion order is the order the model references them.
  const fetch = new Map<string, PlannedTexture>();
  const missing = new Set<string>();
  const refused = new Set<string>();
  const unsupported = new Set<string>();
  // The report measures a texture from the model's own folder, and the file route measures from the
  // character's. Those are the same place for an archive that unpacks flat and a different one for an
  // archive that unpacks a directory — `model-d055bfba`, whose eleven textures are all reported present
  // and all 404 without this prefix. The names the stage reports stay the report's own; only the fetch
  // carries the folder.
  const prefix = folderOf(model?.path);
  for (const texture of model?.textures ?? []) {
    const relative = texture.escapes ? null : relativePath(texture.declared);
    if (relative === null) {
      refused.add(texture.declared);
      continue;
    }
    if (!texture.exists) {
      missing.add(relative);
      continue;
    }
    const suffix = suffixOf(relative);
    const decoder: TextureDecoder | null = suffix === "tga" ? "tga" : IMAGE_SUFFIXES.has(suffix) ? "image" : null;
    if (decoder === null) {
      unsupported.add(relative);
      continue;
    }
    fetch.set(relative, { declared: texture.declared, relative, path: prefix + relative, decoder });
  }
  return { fetch: [...fetch.values()], missing: [...missing], refused: [...refused], unsupported: [...unsupported] };
}

/** `inner/model.pmx` → `inner/`; `model.pmx`, an empty path or a path with nothing to prefix → `""`. */
function folderOf(path: string | null | undefined): string {
  const flat = (path ?? "").replace(/\\/g, "/");
  const cut = flat.lastIndexOf("/");
  return cut <= 0 ? "" : flat.slice(0, cut + 1);
}

function morphTable(model: Pick<CharacterCapability, "morph_names" | "morph_kinds"> | null | undefined): Map<string, MorphRef> {
  const byName = new Map<string, MorphRef>();
  const names = model?.morph_names ?? [];
  const kinds = model?.morph_kinds ?? [];
  names.forEach((name, index) => {
    // First table entry wins. A model that repeats a name has two morphs doing the same job and the
    // stage has no way to choose, so it uses the one the file lists first.
    if (!byName.has(name)) byName.set(name, { name, index, kind: kinds.length === names.length ? (kinds[index] ?? null) : null });
  });
  return byName;
}

function lookup(
  model: Pick<CharacterCapability, "morph_names" | "morph_kinds"> | null | undefined,
  keys: readonly string[],
): Record<string, MorphRef> {
  const byName = morphTable(model);
  const found: Record<string, MorphRef> = {};
  for (const key of keys) {
    const ref = byName.get(key);
    if (ref) found[key] = ref;
  }
  return found;
}

/**
 * The five mouth shapes, by exact name.
 *
 * Exact, because Ellen's table holds あ and あ２ and え, え２, え３, え４ — a match that settles for a
 * prefix drives a half-open mouth and calls it a vowel. Three archives in the corpus (both Astras and
 * Burnice) publish a morph count with no names behind it, and they come back empty: a face that can
 * blink and turn its head is still a face.
 */
export function visemeMorphs(
  model: Pick<CharacterCapability, "morph_names" | "morph_kinds"> | null | undefined,
): Partial<Record<(typeof VISEME_KEYS)[number], MorphRef>> {
  return lookup(model, VISEME_KEYS);
}

/** The four moods, same rule and same tolerance as `visemeMorphs`. */
export function moodMorphs(
  model: Pick<CharacterCapability, "morph_names" | "morph_kinds"> | null | undefined,
): Partial<Record<(typeof MOOD_KEYS)[number], MorphRef>> {
  return lookup(model, MOOD_KEYS);
}

/**
 * Whether to simulate this model's cloth and hair.
 *
 * Physics is per-body work every frame, so the count is the whole decision. A prop with no rigid bodies
 * is `off` rather than `on` with nothing to do — the screen says why either way.
 */
export function physicsBudget(
  rigidBodies: number | null | undefined,
  constraints: number | null | undefined,
): PhysicsDecision {
  if (rigidBodies === null || rigidBodies === undefined || constraints === null || constraints === undefined) {
    return { cost: null, on: false, reason: "the walk could not count the physics, so the stage leaves it unknown rather than guessing small" };
  }
  const cost = rigidBodies + constraints;
  if (rigidBodies === 0) return { cost, on: false, reason: "no rigid bodies — nothing for the physics to simulate" };
  if (cost > PHYSICS_COST_LIMIT) {
    return {
      cost,
      on: false,
      reason: `${rigidBodies} rigid bodies and ${constraints} constraints are past the ${PHYSICS_COST_LIMIT} the frame budget holds`,
    };
  }
  return { cost, on: true, reason: `${rigidBodies} rigid bodies and ${constraints} constraints fit the frame budget` };
}
