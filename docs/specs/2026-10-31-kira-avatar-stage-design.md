# Kira unit 11 — the avatar stage (MMD / PMX)

Spec written 2026-10-31, the day the unit stopped being blocked. Plan:
`docs/plans/2026-10-31-kira-avatar-stage.md`. This unit reopens one rejection recorded in
`PROVENANCE.md` — "MYRAA 3D/MMD character engine — rejected: orthogonal to the agent, skins are
non-redistributable" — and closes it in the compliant half only: the **renderer and the importer**
ship, the **skins never do**.

## Why it was blocked, and what the model folder proved

The blocker on record was that MYRAA ships no character: `assets/characters/**` is empty, its
default `evelyn.ts` is absent, and `electron-builder.public.yml` excludes the assets anyway. That was
true of the source pack. It is not true of the donor folder: `Ai agents/MYRAA/models for MYRAA/` holds
**ten archives, 178 MB, 20 `.pmx` files**. Every one was opened with an archive reader (never with a
donor installer — the only `.exe` in MYRAA stayed unrunned) and the 20 models were parsed with
`mmd-parser`, the MIT library three.js vendors:

| archive | main model | verts | tris | bones | morphs | rigid / constraint | textures |
|---|---|---|---|---|---|---|---|
| `9y5Huh14gN` | 艾莲 / Ellen | 29 287 | 27 770 | 487 | 59 | 317 / 462 | 8, all present |
| `1737513796662` | 耀嘉音 / Astra (v2) | 44 479 | 46 809 | 398 | 49 | 274 / 370 | 10, all present |
| `1737477261288 (1)` | 耀嘉音 / Astra (v1) | 38 649 | 47 237 | 386 | 43 | 268 / 364 | 11, prop's texture absent |
| `1745385427487` | 薇薇安 / Vivian (+ 伞, 技能) | 31 709 | 39 037 | 479 | 45 | 360 / 561 | 10 |
| `RoL6mVzkCH` | 简 / Jane Doe | 27 959 | 33 606 | 297 | 51 | 189 / 207 | 8 — **`hair.bmp` missing from the archive** |
| `xPIr9pYwoU` | 柏妮思 / Burnice | 38 619 | 35 150 | 366 | 51 | 219 / 333 | 11 |
| `ZSHCchUKIw` | 凯撒 / Caesar | 26 798 | 31 325 | 439 | 49 | 325 / 450 | 8 |
| `无限大-里希（修复）…` | richie | 69 638 | 91 233 | 428 | 38 | 305 / 407 | 7 |
| `星临者女仆装皮肤v1.2…` | Azur Promilia maid skin | 47 518 | 75 399 | 477 | 78 | 299 / 407 | 8 |
| `深空之眼—苍鹭·托特…` | 苍鹭·托特 white + black outfit | 34 030 / 33 511 | 42 316 / 41 670 | 695 / 555 | 46 | 577 / 955 · 436 / 692 | 11 / 10 |

Six of those archives also carry props — 武器 (weapon), 补妆镜 (makeup mirror), 伞 (umbrella), 技能
(skill effect) — which are *not* humanoids and must not be picked as the body.

Facts that shape the design, all measured rather than assumed:

- **The rigs are standard MMD.** Bone names run 操作中心 / 全ての親 / センター / グルーブ / 腰 /
  下半身 / 上半身×3 / 首 / 頭 / 両目, then `Ctr_*` hair and `Ctr_R_HairA_01`-style dynamic chains, and
  30–40 finger bones. Procedural idle motion, head look and blink therefore have real targets.
- **Expressions and visemes are standard-named.** Ellen's 59 morphs include まばたき (blink),
  ウィンク (wink), 笑い / 怒り / 悲しむ / 喜び / にこり / 困る (mood) and あ・い・う・え・お plus
  □・▲・口角上げ・口角下げ (mouth). So mood and lip-sync are **name mappings**, not art work.
- **Textures are not browser-shaped.** References are Windows-style relative paths
  (`tex\颜.tga`) and the formats are `.tga` and `.bmp` as well as `.png`. Browsers do not decode TGA,
  so the loader needs `TGALoader` plus separator normalisation, or the model renders untextured.
- **Physics is heavy.** 189–577 rigid bodies and 207–955 constraints per character. On this machine —
  Ryzen 5 5600G, 24 GB, RX 5500 4 GB, **no CUDA** — that is measured, not promised; the stage must
  degrade rather than stutter, and the frame budget is an acceptance criterion, not a hope.
- **Two archives are imperfect.** Jane Doe's `hair.bmp` genuinely is not in the archive; Astra v1's
  补妆镜 prop references `tex\补妆镜.png` which is not there. That is exactly what a capability report
  is for: Kira says "this renders with white hair" instead of silently doing it.
- **The licences forbid bundling and say so in the archives.** Each readme: 请勿二次配布 (no
  redistribution), 请勿用于商业用途 (no commercial use), no R18/political/attack content, credit to the
  game companies (miHoYo, NetEase, 蛮啾, 深空之眼). MYRAA's own README says the same in English:
  *"No 3D character model. The models used while developing MYRAA have licences that forbid
  redistribution. Import your own MMD model (.pmx, or a .zip / folder containing one) in the app."*

So the unit is unblocked, and its shape is forced: **import from a path the owner names; never carry a
skin in the repo, the bundle or the installer.**

## Decisions taken with the user (2026-10-31)

1. **Default face:** none. Import everything, leave the active character unset until it is chosen in
   the UI. The library screen therefore has to be good, and the empty state is the first thing seen.
2. **Reach: "1+2"** — the in-app stage (`#/avatar`, plus the avatar on `#/call`) **and** MYRAA's
   signature desktop presence: an always-on-top, transparent, click-through companion window. That is
   why this unit is five milestones and not the two the ROADMAP estimated.
3. **Model source:** the engine's own `characters import` verb run against the donor path, to prove
   the pipeline end to end here; the app also gets a path field so anything else can be imported.

## Shape

### M34 — the importer (`kira-engine/src/kira/characters.py`)

Pure engine, no client, no contract. One function per question:

- `resolve_source(path)` → `.zip`, `.pmx` or a folder. Refuses anything else with a reason.
- Archive reading is **ours**, in Python, and it must fix what a donor reader hides: entries written
  without the UTF-8 flag carry GBK bytes misdecoded as cp437, so `Σ░ö` must become `颜` before the
  path means anything. Zip-slip is refused by resolving each entry against the staging root and
  rejecting any that escapes it, the same way `workspace.py:45 safe_path()` works; symlinks and
  entries with an absolute path or `..` are refused; sizes are capped (archive ≤ 200 MB, one entry
  ≤ 64 MB, expanded total ≤ 400 MB, ratio ≤ 50) so a zip bomb fails instead of filling the disk.
- `read_pmx_head(bytes)` parses just enough to describe a model: magic, version, global settings,
  the four model-info strings, the nine counts. That is the whole reason a PMX can be *listed* without
  a GPU. (Verified against these ten archives: model info comes **before** the counts, and 2.0 files
  here carry four strings, so a three-string read lands its counts inside the English comment.)
- `describe(model, dir)` → the capability report: counts, whether the bone names include the standard
  groups and how many finger bones, morph counts, rigid/constraint counts, and for every texture
  reference whether the file resolves next to the model. Plus the findings a renderer would otherwise
  swallow: backslash paths, `.tga`/`.bmp` formats, `spa`/`toon` refs, and the licence line if a `.txt`
  next to the model says 二次配布.
- `choose_main(models)` picks the body, not the prop: highest vertex count among entries with a
  humanoid skeleton (≥ 100 standard-group hits is not the test — bones ≥ 100 **and** verts > 20 000
  is, because 补妆镜 has 538 verts and 武器 4 499). The rest are listed as `companion` entries.
- `import_source(...)` writes `<data>/characters/<id>/` atomically: unpack to a sibling
  `.staging-<id>` dir, then `os.replace`. `id` is an ascii slug from the English name plus the first
  8 hex of the model's SHA-256, so `ellen-3f2a91c0`; re-importing the same bytes answers `already
  imported`, and two versions of the same character (Astra v1/v2) get two ids and both stay.
  `profile.json` holds display name (CJK kept verbatim), `model.pmx`, the report, the source path it
  came from, the importer version, and `license_note` — the copied readme text, so the terms travel
  with the character instead of being re-derived from memory. Textures are **copied**, never
  re-hosted: nothing leaves the machine.
- `list_characters` / `remove_character`, and the active pick in the `settings` table under
  `avatar.active` (same mechanism the memory capture switch and provider caps already use).

### M35 — routes, contract, CLI

- `GET /v1/kira/characters` (list + report) — `require_token`; a phone may show the avatar.
- `GET /v1/kira/characters/{id}` — `require_token`.
- `POST /v1/kira/characters` `{path}` — **`require_owner`, no confirm header**, the settled key-route
  shape: you are supplying something, not destroying anything, and a paired device cannot add a body
  to your machine. Answers `400 unsupported_source`, `413 too_large`, `409 already_imported`.
- `DELETE /v1/kira/characters/{id}` — `require_owner` **with** `X-Kira-Confirm`, like every other delete.
- `GET /v1/kira/characters/{id}/file?path=<rel>` — `require_token`, traversal-refused, media type from
  the extension (`.pmx` `application/octet-stream`, `.png`/`.bmp`/`.tga` their own, `.json` `application/json`).
- `PUT /v1/kira/characters/active` `{id|null}` — `require_owner`, confirm-gated? No: it changes a
  preference, not data on disk. Owner-only, no secret, matching `putKey`.
- Contract grows additively: `API_VERSION` stays 1, `CONTRACT_VERSION` stays 2, new schemas
  `CharacterProfile`, `CharacterList`, `CharacterCapability`, `TextureFinding`,
  `CharacterImportRequest`, `CharacterActiveRequest`. `kira-engine contracts` regenerates, and the
  drift gate plus `test_contract_v2.py`'s path lists and `test_docs_match_engine.py` (README endpoint
  table, CLI verb list) all have to stay green — which is the point of putting them in this milestone.
- CLI: `kira-engine characters import <path>`, `list`, `show <id>`, `use <id>`, `remove <id>`.

### M36 — the client library screen and the authenticated loader

- `three` (MIT, ~700 KB minified) plus `three/examples/jsm` `PMXLoader`, `MMDPhysics`, `TGALoader`.
  First 3D dependency in this project; the PWA shell cache grows by that much and the pass says so.
- `src/avatar/load.ts` — **all bytes come through `KiraClient` with the bearer header**, including the
  textures, and are handed to `PMXLoader.setTextures(map)` before `parse()`. The token never goes in a
  URL: that is the whole reason textures are pre-fetched rather than left to three's own loader.
  Paths are normalised (`tex\颜.tga` → `tex/颜.tga`), `.tga` goes through `TGALoader`, everything else
  through an `ImageBitmap`/`Image` decode of the same bytes.
- `src/avatar/pmx.ts` — pure functions around the loader so jsdom can test them without a GPU:
  `texturePlan(pmxTextures)` (what to fetch, in what order, with the resolved/missing split),
  `visemeMorphs(morphs)` and `moodMorphs(morphs)` (the name→morph maps, tolerant of a model that
  lacks a morph — it is then absent from the map, never a thrown error), `physicsBudget(rigid, con)`.
- `#/avatar`: library table (name, verts, bones, morphs, textures `8/8` or `7/8 — hair.bmp absent`,
  physics count, licence line), a path field + Import, Use / Remove, and an honest empty state that
  names the licence rule instead of pretending Kira has a face. `NAV_ICONS`, `NAV_LABELS`,
  `PHONE_ROUTES` and the both-shells route test all grow an `avatar` entry.
- `fakeEngine` grows the five branches and fixtures built from the same synthetic PMX bytes the
  engine tests use, so the client and the engine are tested against one description of the shape.

### M37 — the stage: idle, mood, blink, lip-sync

- `src/avatar/stage.ts` owns the renderer behind an injected seam (`StageHost`), the same trick the
  voice work used to keep `AudioContext` out of jsdom: tests drive the *pure* animation logic
  (`src/avatar/animate.ts`: `blinkAt(t)`, `breath(t)`, `lookAt(target)`, `visemeWeights(level, band)`)
  and never construct a `WebGLRenderer`.
- Idle: breathing sine on 上半身, a blink every 2.5–6 s from `まばたき`, slow weight-shift, head look
  toward the pointer. Physics runs through `MMDPhysics` when `physicsBudget` says the machine can
  afford it; over budget the stage ships with physics **off** and the toggle is in the screen.
- Mood: user-picked only. `happy / stern / sad / surprised` map onto 笑い / 怒り / 悲しむ / びっくり and
  are buttons on the stage. The chain carries no sentiment today, so having a model classify its own
  face would be a claim this unit cannot prove; the spec keeps it out.
- Lip-sync: one `AnalyserNode` between the existing playback `BufferSource` and
  `context.destination` (`voice/audio.ts:151-153` today taps nothing on the playback side), RMS per
  20 ms → five viseme weights (あ い う え お) → morph influence. On `#/call` the stage replaces the
  static self-view panel when a character is active; typed chat keeps the meter off the audio path
  because there is no audio to measure.

### M38 — the companion window, then docs, gates and the pass

- A **second** pywebview window, not a mode of the first: `frameless=True, transparent=True,
  on_top=True`, sized to a portrait card, URL `/chat/#/companion`, own geometry key in
  `desktop.json`, own close-to-tray entry ("Companion on/off"). The single-instance mutex stays one
  per data dir for the engine; the companion is a window of the same process, so `kira-engine desktop
  --companion` starts both.
- Click-through is Win32, not CSS: `SetWindowLongW` with `WS_EX_TRANSPARENT | WS_EX_LAYERED` on the
  native handle, toggled from the UI. Where pywebview cannot give real transparency on WebView2, the
  window falls back to an opaque rounded card **and the pass records that it did** — that is the
  difference between a demo and a feature.
- Token: the companion window uses the same memory-only boot injection as the main window
  (`private_mode`, never `localStorage` persistence, never the confirm secret).
- Docs: README gains the endpoints, the verbs and a "The avatar" section; `PROVENANCE.md` gains a row
  for the importer/stage (design influence: MYRAA's *product*, mechanisms: three.js + `mmd-parser`,
  assets: none), and closes the "not yet ported" rejection bullet to say precisely which half shipped.
- Gates: engine suite, client suite, drift, build — then the live pass: import all ten archives
  through the CLI, render three of them, drive a call with lip-sync, prove the file route refuses
  `../`, and screenshot the companion window only as APP-content captures.

## Security, and what this unit does not weaken

- **No skin in the repo, ever.** `.gitignore` grows `characters/`; the importer's own docstring says
  why. Nothing in `docs/qa/` is a model file; screenshots only, and only of app content.
- Owner-only writes; `kd_` device tokens can read the library and the bytes, never import or remove.
- The bearer token travels in headers for every byte, including textures — never in a query string.
- The file route resolves inside `<data>/characters/<id>` or refuses, with a test for `..`, for an
  absolute path, for a NUL, for a URL-encoded traversal and for a symlink planted in the dir.
- Import reads **only** the path the owner names, copies into `data_dir`, and never deletes the
  source. Sizes are capped before anything is expanded.
- The engine still binds loopback and gains no listener. The companion window is local; a phone
  getting the avatar over a tunnel is unit 12's TLS story, unchanged.
- No donor code, ever, is executed: not MYRAA's installer, not its importer, not its `mmd-parser`
  copy. The PMX reader here is ours in Python; the loader on the client is npm `three` (MIT), a
  dependency, not a donor. `mmd-parser` was used **once, in a throwaway scratch dir outside the
  repo**, only to measure these files for this spec — it is not a Kira dependency.
- `API_VERSION` stays 1, `CONTRACT_VERSION` stays 2.

## Files

- new `kira-engine/src/kira/characters.py`, `kira-engine/tests/test_characters.py`,
  `test_characters_zip.py`, `test_character_routes.py`, `test_cli_characters.py`,
  `test_pmx_fixture.py` (the synthetic writer's own proof)
- new `tests/sample_pmx.py` — a builder that writes valid PMX bytes with chosen counts, so every
  engine test runs without a licensed asset; plus `KIRA_CHAR_SAMPLE=1`-gated tests that read the real
  donor archives where they exist and skip where they do not (the `KIRA_LIVE` pattern, same reason)
- touched `kira-engine/src/kira/app.py` (routes), `contracts.py` (paths + schemas), `__main__.py`
  (verbs), `config.py` (`characters_dir`), `store.py`/`settings` (the `avatar.*` keys), `README.md`
- new `kira-chat/src/avatar/{pmx.ts,load.ts,animate.ts,stage.ts}`, `src/screens/AvatarScreen.tsx`,
  `src/screens/CompanionView.tsx`, and their tests
- touched `kira-chat/src/{hash-route.ts,App.tsx,api.ts,styles.css,fake-engine.ts}`,
  `src/voice/audio.ts` (the playback analyser), `src/voice/useCall.ts`, `src/screens/CallView.tsx`,
  `kira-contracts/types.ts` (mirror), `package.json` (`three`)
- new `kira-engine/src/kira/companion.py` (or `desktop.py`'s second window) + its tests

## Acceptance tests (written before the code they describe)

1. A zip entry named in GBK surfaces as `颜.tga`, not `┬║…`, and a texture reference resolves.
2. `../../Windows/win.ini`, `C:\…`, `a/../../b`, a NUL byte and a planted symlink are all refused by
   the file route and by the unpacker; the refusal names the entry.
3. An archive whose entries expand past the cap fails `413` **before** writing anything, and the
   staging dir is gone afterwards — no half-imported character.
4. A 538-vertex prop is never chosen as the body; the 29 287-vertex character is, and the prop is
   listed as a companion.
5. `read_pmx_head` on synthetic bytes returns exactly the counts written; on a truncated buffer it
   raises `CharacterError`, never a partial profile.
6. Re-importing identical bytes answers `already imported: <id>` and does not double-write.
7. The capability report says `hair.bmp absent` for a model whose texture is missing, and the client
   renders that as `7/8` in the table — a defect stated, not hidden.
8. `texturePlan` puts every `.tga` on the TGALoader path and normalises `tex\颜.tga` to
   `tex/颜.tga`; nothing in the plan contains a token or a query string.
9. `visemeMorphs` finds あ/い/う/え/お in Ellen's morph-name list fixture and returns an empty map for
   a model with none — the stage then mouths nothing instead of throwing.
10. `blinkAt` never fires twice inside 1 s and always finishes; `visemeWeights(0)` is all-zero.
11. `POST /v1/kira/characters` with a device token is `401`; with the owner token it is `201`; the
    same route asks for no confirm secret, and the sweep test that keeps that exception list honest
    still passes.
12. `DELETE /v1/kira/characters/{id}` without `X-Kira-Confirm` is refused, and removing an active
    character clears `avatar.active` in the same transaction.
13. The playback analyser is created between the buffer source and the destination, and `level`
    updates stop when playback stops (no orphan rAF loop) — the existing barge-in test stays green.
14. `#/avatar` renders in both shells, `#/companion` renders only for a companion window, and the
    route test enumerates them.
15. Adding these routes and verbs turns README + drift + `test_docs_match_engine` red **first**, then
    green — never silently.
16. The frame budget: a measured statement in the pass, `physics on/off` chosen from it, and the
    stage's own `physicsBudget()` unit-tested against the counts in the table above.

## Not in this unit

- No bundled model, no downloader, no scrape — the licences forbid it and the ground rules forbid the
  rest. Import is the feature.
- No `.vmd`/`.pmd` animation library, no dance playback, no VRM/FBX/GLB (three.js wants PMX here and
  MYRAA's own importer says VRM/FBX/GLB are not supported by the renderer either).
- No model-driven mood. Expressions are user-picked or mapped from a marker; an LLM classifying its
  own face is not something this unit will pretend to prove.
- No wake word, no screen vision, no desktop control, no gesture/eye tracking — MYRAA has them, Kira
  has decided otherwise (unit 2's record).
- No global hotkeys, no start-with-Windows, no installer or signing for the companion window — the
  unit-3 gaps stay gaps.
- No promise that 955 constraints run at 60 fps on a 4 GB RX 5500. The pass measures it and the
  default follows the measurement.
