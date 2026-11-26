# Kira unit 11 — avatar stage implementation plan

Spec: `docs/specs/2026-10-31-kira-avatar-stage-design.md`. 16 tasks, five milestones (M34–M38), one
commit each, `master`, no remote. Every task writes its test first and sees it fail for the right
reason before any code exists.

Commands: engine `cd kira-engine && .venv/Scripts/python -m pytest -q`; client
`cd kira-chat && npm run check`; contracts `node kira-contracts/check-drift.mjs`.

The ROADMAP estimated this unit at 2 milestones. It is 5, because the user chose the companion window
as well as the in-app stage; task 16 restates the arithmetic instead of quietly keeping 44.

## M34 — the importer

### T1 — a PMX header reader, and a fixture that proves it
Files: `kira-engine/src/kira/characters.py`, `tests/sample_pmx.py`, `tests/test_characters_pmx.py`.
RED: `read_pmx_head(sample_pmx(vertex_count=29287, bone_count=487, …))` returns those counts; a
truncated buffer raises `CharacterError` and never returns a partial. **Amended while writing T1:**
the line below used to read "a 3-string writer and a 4-string writer both parse", and that is the
opposite of the truth the spec records (spec §M34: the ten archives carry four model-info strings, so
a three-string read lands its counts inside the English comment). The fixture therefore writes a
3-string file to prove it is **refused** — `pmx_truncated`, not a profile with a billion vertices.
`sample_pmx.py` is a **writer** (utf-16 names, the four model-info strings
before the nine counts, the index-size bytes the real files use) so no licensed model enters a test.
Commit: `characters: read a PMX header without a GPU`.

### T2 — an archive reader that fixes what a donor reader hides
Files: `characters.py`, `tests/sample_zip.py`, `tests/test_characters_zip.py`.
RED, in this order: a GBK entry name surfaces as `颜.tga` and not as cp437 mojibake; `../../x`,
`/abs/x`, `a/../../b`, a NUL byte and a symlink entry are each refused **naming the entry**; an
archive over the entry cap or whose entries expand past 400 MB / ratio 50 fails `too_large` having
written nothing to disk. Commit: `characters: a zip reader that survives GBK names and refuses zip-slip`.

**Amended while writing T2**, three things the plan could not know:

- Measured first: **all ten donor archives are polite.** Nine put an Info-ZIP Unicode Path extra field on
  every non-ascii name and `zipfile` repairs them for free; the tenth (`深空之眼…`) sets the utf-8 flag.
  So the corpus is not the test — the format is. `zipfile` alone still returns `╤╒.tga` for the bytes a
  Chinese packaging tool writes without either courtesy, and that archive is what the reader is tested
  against, with the real ten run once through the same code (extracted to a temp dir, nothing in the
  repo): 44 entries, 71.5 MB expanded, **zero mojibake, zero refusals.** The same measurement pinned the
  caps from below — max 45 entries, max 29.4 MB an entry, max 71.5 MB expanded, max 45 MB archived.
- `zipfile` reaches into the name before any reader does: `ZipInfo.__init__` cuts it at the first NUL
  byte and replaces `os.sep` with `/`. A reader built on `info.filename` therefore never *sees* the two
  names the spec lists as hazards — it silently writes `a` for `a\0b.png` and never notices the
  backslash form of zip-slip on Windows. The repair is based on `info.orig_filename` instead, which
  keeps both, and `safe_entry()` treats `\` as a separator so the same archive refuses identically on
  either OS.
- `zipfile` cannot be asked for these fixtures (it writes utf-8 with the flag, refuses a lying header,
  and will not mark an entry a symlink), so `tests/sample_zip.py` assembles the three records by hand —
  the `sample_pmx.py` pattern, shared because T3 and T4 want the same archive. Ratio gets a 1 MB floor:
  `hair.bmp` in the corpus compresses 62:1 at 1.1 KB and is a real texture, and an absolute cap already
  bounds the damage below that. A header that *understates* its size is refused chunk by chunk, which is
  the one case the central-directory caps cannot see coming.

### T3 — the capability report and the body-vs-prop choice
Files: `characters.py`, `tests/test_characters_report.py`.
RED: a 538-vert prop and a 29 287-vert character in one archive → the character is `main`, the prop is
`companion`; every texture reference is resolved or listed missing (`hair.bmp absent`, matching the
real Jane Doe archive); backslash paths and `.tga`/`.bmp` formats appear as findings; a `使用规则.txt`
saying 请勿二次配布 becomes `license_note`, and its absence is not an error. Commit:
`characters: say what a model can and cannot render before rendering it`.

### T4 — atomic import, ids, dedupe, removal
Files: `characters.py`, `config.py` (`characters_dir`), `tests/test_characters_import.py`.
RED: import lands `<data>/characters/ellen-<sha8>/` with `model.pmx`, textures and `profile.json`; the
directory appears only after the staging dir is complete (a failure mid-way leaves nothing); identical
bytes twice → `already imported: <id>`; CJK display name survives verbatim while the id stays ascii;
`remove_character` deletes the dir and, if it was active, clears `avatar.active` in the same call.
Commit: `characters: an import that cannot leave half a body on disk`.

### T5 — the active pick, and a test that reads the real archives when they exist
Files: `characters.py`, `tests/test_characters_sample.py`.
RED: `set_active`/`get_active` over the settings table, `null` clears it; a `KIRA_CHAR_SAMPLE=1`-gated
suite imports all ten donor archives and asserts the measured table (9 characters, Ellen 29 287 verts,
Jane Doe missing `hair.bmp`), `skipif`-ing to silence when the folder is absent. Commit:
`characters: the active pick, and a proof that runs on the donor archives on demand`.

### T6 — the CLI verbs
Files: `__main__.py`, `tests/test_cli_characters.py`, `tests/test_docs_match_engine.py` (verb list).
RED: `kira-engine characters import|list|show|use|remove` parse and dispatch through the same engine
paths the routes use; the docs test goes red for the new verbs **first**, then README + the list agree.
Commit: `characters: kira-engine characters import, list, show, use, remove`.

## M35 — routes, contract, gate

### T7 — the routes
Files: `app.py`, `tests/test_character_routes.py`, `README.md` (endpoint table).
RED: list and read with `require_token`; `POST` import is `require_owner` and needs **no** confirm;
`DELETE` and `PUT active` behave per spec (delete confirm-gated; removing the active character clears
the setting); the file route serves `model.pmx` and a texture with the right media type and refuses
every traversal shape, including a URL-encoded one and a symlink planted in the dir. Commit:
`api: a character library over the same loopback gate`.

**Amended while writing T7:** T7 and T8 are one delivery, not two. `test_versioning.py` refuses a route the
contract does not publish (`UNIMPLEMENTED` must stay empty) and `test_docs_match_engine.py` refuses a route
with no README row, so the routes cannot land before `contracts.py` does. What code had to move: the wire
family `CharacterRefusal` + its 12 leaves now live beside the importer, with `ANSWER_FOR_CODE` mapping the
internal codes to them and `wire_for()` doing the translation in one place, so a route and the CLI cannot
disagree about a refusal's status; `ERROR_CODES` is built from that mapping instead of ten more hand-written
strings. Two new codes are the API's own (`unsupported_source` for a path that is not a model,
`character_file_not_found` for a folder without that file). The import answers **201** per exit criterion 11,
which is why the dashboard-success gate now accepts exactly one 2xx per operation rather than the literal
"200" — a create that said 200 would claim it replaced a row. `character_file()` unquotes the query value a
second time: httpx re-encodes `%2F` as `%252F` in a test, so a hand-built traversal arrives still encoded,
and a browser's correctly-encoded request is unaffected because the second decode is a no-op.

### T8 — the contract, additively
Files: `contracts.py`, `kira-contracts/{openapi.json,contract.json,types.ts,contract.ts}`,
`tests/test_contract_v2.py`, `test_character_routes.py`.
RED: six new schemas, `API_VERSION` 1 and `CONTRACT_VERSION` 2 **unchanged**; the bearer-write sweep
still passes with `POST /v1/kira/characters` and `PUT …/active` in the owner-only exception set and
`MEMORY_PATHS`-style lists updated; `node kira-contracts/check-drift.mjs` green after
`kira-engine contracts`. Commit: `contracts: characters join v2 without a version bump`.

**Amended while writing T8:** nine schemas, not six — `TextureFinding` and `CharacterCapability` are what the
profile actually carries, and publishing `CharacterProfile` without them would leave the TypeScript mirror
describing a shape no client can check. The published set is 86 schemas (77 + 9) and both version numbers are
still 1 and 2; `contract.ts` gained the 12 character codes and `ErrorBody` gained `entry`.

### T9 — the client half of the contract
Files: `kira-chat/src/api.ts`, `src/contracts.ts`, `src/fake-engine.ts`, tests.
RED: `KiraClient.bytes(url)` returns an `ArrayBuffer` with the bearer header and **no** query-string
token (assert on the fetch spy); `characters()`, `importCharacter(path)`, `removeCharacter(id)`,
`setActiveCharacter(id|null)` and `characterFileUrl(id, rel)` exist; `fakeEngine` answers all five so
later tests never touch the network. Commit: `client: fetch a character's bytes with the token in the header`.

**Amended while writing T9:** six calls, not five — T11's `loadCharacter(client, profile)` needs
`GET /kira/characters/{id}`, so `character(id)` joins the list; the row from `characters()` carries no
texture table. `contracts.ts` needed no edit (it re-exports `kira-contracts`, which T8 already mirrored).
The fake keeps library state — import appends a row, delete takes the row *and* the pick, an unknown pick
answers `character_not_found` — because a screen that never re-reads must not pass against a frozen
fixture, and the file branch refuses `..` with `unsafe_entry` so the traversal contract has a client-side
test even though a jsdom suite has no folder to escape from.

## M36 — the library screen

### T10 — PMX knowledge in TypeScript
Files: `kira-chat/src/avatar/pmx.ts` + `pmx.test.ts`.
RED: `texturePlan` normalises `tex\颜.tga` → `tex/颜.tga`, routes `.tga` to the TGA decoder and
`.bmp`/`.png` to the image decoder, and splits resolved from missing; `visemeMorphs` finds
あ・い・う・え・お in Ellen's real morph-name list and returns `{}` for a model with none; `moodMorphs`
finds 笑い/怒り/悲しむ/びっくり; `physicsBudget(317,462)` vs `(577,955)` chooses on and off across the
threshold. Commit: `avatar: what a PMX tells you before you render it`.

**Amended while writing T10:** the four corpus facts below came from walking all ten archives with the
engine's own reader, and every fixture in `pmx.test.ts` is one of them — a hand-written PMX would have let
this module pass by inventing shapes no exporter writes.
`texturePlan` re-normalises `declared` rather than trusting `relative`, because a report from a different
reader can hand back the Windows path unchanged, and adds the case the engine cannot see: a drive-absolute
reference (`C:\Users\me\…`) resolves on the engine's own disk and is published with `exists: true`, but the
file route refuses an absolute shape, so the client puts it in `refused` instead of fetching a 400. A slot
that names no file is `refused` too, not `missing` — nothing was ever asked for. `unsupported` exists
because the engine will serve `.dds` and `.json` bytes that no code on the page turns into a texture.
Morph matching is exact-name, proved by Ellen: her table holds both あ and あ２, え/え２/え３/え４, and
びっくり右/びっくり左 but no びっくり — a prefix match would drive a half-open mouth and call it a vowel,
or squeeze one eye and call it surprise. The kind is carried through because it is not always 1: Vivian's
怒り is a bone morph and the widest archive's 笑い is a group morph, which deforms nothing by itself.
Three of the ten (both Astras and Burnice) publish a counted morph table with **no names** behind it — the
walk resyncs past the section — so `{}` is a normal answer, not a failure, and the two look-up helpers take
`null` and a payload with missing keys without throwing.
`PHYSICS_COST_LIMIT` is 1200 for now and the test pins it between the corpus's two real readings (779 on,
1532 off) so a silent retune cannot flip a decision; exit criterion 16 replaces the number with one
measured in frames.
Separately, `vite.config.ts` now sets a 20 s test timeout: 38 per-file jsdom environments queue up for
~105 s of setup, and a screen test that passes alone was failing the full run before its page existed.

### T11 — the loader, behind a seam
Files: `kira-chat/src/avatar/load.ts`, `package.json` (`three`), tests with a stubbed stage host.
RED: `loadCharacter(client, profile)` prefetches model + textures through `KiraClient.bytes`, builds
`THREE.Texture` objects, and calls `PMXLoader.setTextures(map).parse(buffer, resourcePath)` — asserted
by a fake loader so no WebGL is required; a missing texture yields the placeholder + a finding, never a
rejected promise. Commit: `avatar: an authenticated PMX load path, no token in any URL`.

**Amended while writing T11:** this task is two, and the plan was wrong about the library.

`PMXLoader` does not exist. Checked against the registry rather than memory: `three@0.187.0` ships no
`PMXLoader.js`, no `MMDLoader.js` and no `MMDPhysics.js` anywhere in the package (verified by listing the
installed tree and grepping it), and `three@0.171.0` — pulled as a tarball and listed — ships
`MMDLoader.js`, `animation/MMDPhysics.js` and `TGALoader.js` but never a file with `pmx` in its name;
`MMDLoader` is the module that reads PMX, through `mmd-parser`. `@types/three@0.171.0` confirms the same
set (`PMXLoader` absent from the typings too). r171's `MMDLoader` constructor logs
`The module has been deprecated and will be removed with r172. Please migrate to
github.com/takahirox/three-mmd-loader`, whose published npm form is `@takahirox/three-mmd` for three
`~0.186`, and its loader takes a **URL** and fetches textures itself — no buffer-in/textures-in entry
point. Both options therefore cost Kira something it should not pay: pinning the whole renderer to a
version whose avatar dependency prints a deprecation warning on construction, or a third-party package
whose fetch-by-URL design wants the token in the request path, which T9 exists to make impossible.

So the engine exports the mesh instead of the browser parsing the format. That is the same shape the rest
of Kira already has — the engine owns the bytes, the client owns the pixels — and it keeps the one
property the security rules insist on: **untrusted PMX bytes never reach a DataView in a browser.** The
quirks the reader spent five tasks learning (inline versus header counts, memo-only materials, the two
bone-morph strides, GBK names, the boundary search) are already solved in `characters.py`; a second
implementation in TypeScript would have to re-solve every one of them, and a stride mistake there does not
fail — it renders a broken face and calls it a model.

- **T11a — engine: a flat mesh the stage can use directly.** New `kira-engine/src/kira/mesh.py`,
  `export_mesh(directory, character_id) -> bytes`, re-walking the body from the counts the walk already
  certified (`PmxModel.head()`, which is the gate that refuses a resynced or truncated file — so an export
  is only ever made from a model whose section arithmetic closes) and writing one small documented
  little-endian blob: header counts, positions, normals, uvs, 4-slot normalised skin weights, face indices,
  texture names, material bindings with their index ranges, bones as (name, parent, position *relative to
  the parent*, raw PMX flags) and vertex morphs as (name, per-vertex offsets). Vertex morphs only: a bone
  morph has no vertex payload to hand over, and Vivian's 怒り is one — `morph_kinds` already tells the
  client which names are drivable, and the screen says so instead of failing. Extra UV layers, sphere and
  toon tables stay engine-side findings, exactly as the report already calls them.
  Route `GET /v1/kira/characters/{id}/mesh` (bearer, no confirm, `application/octet-stream`), contract
  additively with an inlined binary response body (no new named schema, so the drift check and the TS
  mirror are untouched), README row, `sample_pmx.py` extended to write *distinguishable* payloads — per
  vertex positions and weights, per material index ranges, real morph offsets — because every existing
  fixture vertex is the same unit normal and a mesh export cannot be proved against a model whose parts
  are interchangeable. Tests carry a **reference decoder**: the format is only real once something other
  than the writer can read it back.
  Commit: `api: a flat mesh for the stage, exported by the reader that already walked it`.

**Amended while writing T11a — four things the plan guessed wrong.**

1. *It is one reader, not a re-walk.* The plan said `export_mesh` would "re-walk the body from the counts
   the walk already certified". A second walk is a second implementation of every quirk above, just in a
   different function, and `mesh.py` would have had to re-find the material framing and re-search the morph
   boundary to do it. Instead `read_pmx_model(data, geometry=...)` hands the collector each record the
   cursor already sliced — `widths/vertex/faces/begin_materials/material/bone/begin_morphs/vertex_morph` —
   so `pack_mesh(data)` is the pure half (bytes in, blob out) and no byte is measured twice. The cost of
   that shape is visible in the code: `characters.py` now owns the weight tables (`WEIGHT_INDICES`,
   `WEIGHT_FLOATS`, `WEIGHT_WEIGHTS`) so the walk's stride and the exporter's row cannot disagree, and the
   two sections that are legitimately re-read on a retry reset the collector (`begin_materials`,
   `begin_morphs`) with `_agree` refusing anything the *chosen* attempt did not fill.
2. *Bone positions are absolute, not relative to the parent.* The plan asked for parent-relative. PMX
   stores each bone's position in model space already, and a parent-relative export would make the client
   re-derive a transform the file gave for free — and re-deriving it wrong is a skeleton with its arms at
   the origin. `parent` travels as the signed index the file wrote, `-1` for the root.
3. *The corpus taught the weight kinds.* Measured across the ten donor archives (twenty PMX files, walked
   with this engine's own reader on 2026-11-01): only kinds 0, 1 and 2 appear — no file in the corpus uses
   BDEF4, QDEF or SDEF — and the fixture writes all five anyway, because "not in the corpus" is not "not in
   the format". SDEF's width is taken from the format rather than guessed: two bone indexes plus ten
   floats (one weight, then C, R0 and R1), which is why `WEIGHT_FLOATS[3] == 10` and the symmetry maths is
   read for its width and dropped. Skin bone slots are exported as unsigned table reads and an out-of-range
   index passes through exactly as read — a stray number is a fact about the file, and the client clamps.
4. *A `-1` was being read as 255.* `_Cursor.idx` unpacked every index unsigned, so "no texture", "no toon"
   and "no parent bone" became 255 / 65 535 / 4 294 967 295 — numbers past the end of their tables, which
   the report then counted as references. Every one of the twenty donor files writes `-1` in its sphere
   slot, so all twenty mis-reported "every material references a sphere map". `idx` is signed at all three
   widths now, and an index width outside 1, 2, 4 is refused as `not_a_pmx` instead of raising a `KeyError`
   the API would have answered with a 500. Both are tested in `tests/test_characters_pmx.py`, and the mesh
   tests assert the four-slot expansion the plan only named "normalised skin weights": BDEF1 repeats its
   one bone at `(1,0,0,0)`, BDEF2 and SDEF take `(b0,b1,b0,b1)` at `(w,1-w,0,0)`, and four-weight rows are
   divided by their own sum — with an all-zero row read as "follows the bone it named first".
- **T11b — client: build it, authenticated.** `kira-chat/src/avatar/load.ts` as originally scoped, minus
  the library: fetch the mesh and each texture through `KiraClient.bytes`, decode the blob, build
  `BufferGeometry` + `SkinnedMesh` + morph targets + `MeshToonMaterial`s in a `three@0.187` that needs no
  add-ons at all, and hand the result to an injected host so the jsdom suite constructs zero
  `WebGLRenderer`s. `.tga` still needs a decoder and `three/addons/loaders/TGARoader.js` exists in 0.187
  with a `parse` entry point, so that one add-on is the only thing imported from there. A missing texture
  yields the placeholder plus a finding, never a rejected promise.
  Commit: `avatar: an authenticated PMX load path, no token in any URL`.

**Amended while writing T11b — five things the plan guessed wrong.**

1. *The add-on is `TGALoader.js`, not `TGARoader.js`.* The name above is a typo of mine, and it survived
   into the import, where Vite refused to resolve it: `Failed to resolve import
   "three/addons/loaders/TGARoader.js"`. The file in `three@0.187` is `T-G-A-L`, confirmed by reading the
   codepoints rather than the terminal, which renders the two indistinguishably.
2. *The decoder was written against the format description, and the format description was not the
   bytes.* Two blocks came out wrong and only the engine's own blob noticed: skin is **interleaved**
   (`4 × u32` then `4 × f32`, per vertex) rather than two contiguous blocks — reading it the other way
   returned weight `2.8e-45`, which is the integer `2` reinterpreted as a float — and a material's flag
   byte sits in the index group *after* the 16-float colour block, not inside it, so `edge_colour` was
   misaligned by one byte. `tests/test_krm1_fixture.py` now base64-decodes the shipped fixture and asserts
   it equals `pack_mesh(write_pmx(…))`, which is what makes the browser suite a cross-language check
   instead of a decoder proving itself.
3. *The fixture had to become a worse model on purpose.* Its texture table went from 2 entries to 6 — a
   present PNG, a present TGA, an absent `hair.bmp`, a `..\outside.png` the engine flags `escapes: true` on
   the wire, a `C:\Users\me\face.png` that is absolute on the machine that wrote it, and a `body.dds` no
   browser opens — because the loader's four refusal buckets are the difference between a stage and a blank
   screen, and a two-texture fixture can only exercise the two success paths.
4. *`SkinnedMesh.bind` takes the skeleton in 0.187.* `mesh.bind()` with no arguments sets
   `this.skeleton = undefined` and then throws on `calculateInverses`; the call is `mesh.bind(skeleton)`,
   which also does the `updateMatrixWorld(true)` the plan said to do by hand beforehand.
5. *A texture map's insertion order is not a contract.* Placeholders are known synchronously and fetched
   textures land after their `await`, so the map fills refusals-first. Nothing looks a texture up by
   anything but its folder-relative path — materials index the table by position and then resolve to that
   path — so the suite asserts the key *set* and the size, not the order.

Delivered: `src/avatar/krm1.ts` (pure decoder, 18 tests: the six engine blocks and nine refusals — bad
magic, unknown format, a short read, a lying count refused before it allocates, ranges that do not tile one
mesh, a bone whose parent is not earlier, a morph that moves a vertex the mesh does not have, trailing
bytes, an empty buffer), `src/avatar/krm1-fixture.ts` (860 bytes, one the engine really wrote),
`src/avatar/load.ts` + 15 tests, `characterMeshUrl` in `api.ts`, the `…/mesh` route in `fake-engine.ts`
with `.tga`/`.bmp` media types, and 2 client tests for the mesh path and its refusals. The stage asks for a
**path** and puts the bearer in a header: `load.test.ts` asserts the exact recorded request URLs and a token
in every one of their headers, so a secret in a URL fails a test rather than an audit. `typecheck` clean,
`npm test` 391 passed (40 files).


### T12 — `#/avatar` in both shells
Files: `src/screens/AvatarScreen.tsx`, `src/hash-route.ts`, `src/App.tsx` (icons, labels, phone
routes, screen chain), `src/styles.css`, `src/App.test.tsx`, `screens/AvatarScreen.test.tsx`.
RED: the route renders in Chat **and** Agent shells, the table shows `7/8 — hair.bmp absent` style
readings, the path field + Import is owner-only-shaped, Use/Remove round-trip through `useWrite`, and
the empty state names the licence rule. `.app`/`.pane` containment stays green and the stage pane does
not reuse `.screen`'s `max-width`.

Delivered: `src/screens/AvatarScreen.tsx` — the library table over `client.characters()` (each row
carrying its own `texture_status`, licence note and body count), the pick and the removal through
`useWrite` (`quick` for a pick, `run` with the secret for a folder delete), the path field over
`client.importCharacter`, and a per-row walk opened through `client.character(id)` that prints the
measurements, the texture table, the missing-texture count, the morph names a mouth will need and the
files. `avatar` joins `ROUTES`, the rail, the labels, the icons and `PHONE_ROUTES` (five hot screens
now, so the phone test that counted four says five), and `.avatar-screen` keeps every property of
`.screen` except the 72rem cap — lifted in both shells, because the agent shell re-caps `.screen` at
its own reading width. The stage pane is honest: it names the body on it, and says nothing draws there.
14 screen tests, 2 App tests, 3 styles tests. `typecheck` clean, `npm test` 409 passed (41 files),
`npm run build` OK, engine `pytest` 747 passed / 8 skipped, `kira-contracts` OK.

**Two things the screen had to learn while it was being written.**

1. *A JSXText line that starts after an `{…}` loses its leading space.* `the {n} model{…}` + a newline
   + `in it {…}` rendered as `modelin it`, because the whitespace-only first line of that text node is
   dropped rather than collapsed. The test that greps for a sentence caught the UI printing a broken
   one; the sentence is now one template literal, with the rule written down where it can be re-broken.
2. *A disabled button is not an explanation.* The props-only row first shipped a greyed-out
   `use 小道具`, which says nothing about why. It now says `no body to stage` in its place, and the test
   asserts the absence of the button rather than its disabled state.

**Checked in a browser on real archives (2026-11-02).** The lab (`tools/kira_lab.py`, port 8912, kept
data dir under `%TEMP%\kira-avatar-pass`) served this bundle, and three donor archives went in through
the path field: `9y5Huh14gN.zip` → Ellen (29,287 vertices · 487 bones · physics · 1 prop · 8/8),
`1737477261288 (1).zip` → Astra (38,649 · 386 · 2 props · 11/11), and
`星临者女仆装皮肤v1.2_by_晓光忆时_….zip` → 星临者女仆装皮肤 (47,518 · 477 · 0 props · 8/8). The import
cleared the field, auto-opened the new walk, and printed the GBK texture paths (`tex/颜.tga`, 16.0 MB)
readably; `use Ellen` put the badge on the row, named her in the stage pane, and survived a reload —
which is the pick being engine state, not React state. Both shells were shot at 1440×900.

Three defects only a real browser shows, all in `styles.css`, each with a test:

1. *A badge is one fact.* `on stage` wrapped onto two lines inside a `border-radius: 999px` pill, so
   the cell that says whether a body is live looked like a broken oval. `.badge` now carries
   `white-space: nowrap`.
2. *`table-layout: auto` sizes a column by how badly its worst cell can break.* One 47-character
   donor file name with a 32-char hex tail starved the actions column until `remove 星临者女仆装皮肤`
   folded to one glyph per line, and the table then overran its grid column and slid under the sticky
   stage pane. The library table now names its five widths (34/18/12/11/25%) and lets only the first
   column break anywhere — applied to every cell, `anywhere` cut `29,287` in half, which is a worse
   defect than the one it cured. The phone opts back out to `auto`, where 25% of 390px folds the
   buttons again.

Commit: `avatar: a library screen that admits Kira has no face yet`.

## M37 — the stage

### T13 — idle motion, blink, look
Files: `kira-chat/src/avatar/animate.ts`, `src/avatar/stage.ts` + tests.
RED: pure functions first — `blinkAt(t)` never double-fires inside 1 s and always returns to 0,
`breath(t)` is bounded, `lookAt` clamps to neck limits, `visemeWeights(0)` is all-zero and a rising
level picks the nearest of the five; `stage.ts` is only reachable through an injected `StageHost`, so
the jsdom suite constructs zero `WebGLRenderer`s. Commit: `avatar: a stage whose animation is testable without a GPU`.

Delivered: `src/avatar/animate.ts` — five pure functions plus the constants that make them reviewable, and
no import outside of nothing at all (the module touches no DOM, no three, no audio). `blinkOnsets(seed)` is
a numeric-recursion LCG, so a schedule is deterministic per seed and a test can hold it still; `blinkAt(t)`
binary-searches the last onset and returns one half-sine, so the eye is shut at the peak and open
everywhere else, and it cannot double-fire because `BLINK_MIN_GAP_S` (1 s) is longer than
`BLINK_DURATION_S` (0.18 s). `breath(t)` is a 4 s sine capped at 0.035 rad. `lookAt` maps a -1..1 pointer
offset onto `NECK_LIMITS` (0.61 yaw, 0.35 pitch) and clamps beyond it. `visemeWeights(level)` snaps to the
nearest of five bands and always returns all five keys — exactly one shape open, never two. `approach` is
the exponential filter, and it is what the *noisy* inputs get: the head, the mouth and the mood, each of
which arrives from a pointer, an `AnalyserNode` or a button. The blink and the breath are written straight
through, because they are already curves that start and end at rest and filtering them would only slow the
eye down.

`src/avatar/stage.ts` — `createStage(loaded, renderer, options)` puts a `LoadedCharacter` on a `Scene`
behind a portrait camera (18°, 3:4, at `y ≈ 13.4` looking at `13.0`, because an MMD body stands ~15 units
and its head sits near 13.5) and hands back `frame({t, level, pointer})`, `setMood(mood|null)` and
`dispose()`. Every pixel is the injected `StageRenderer`'s job, so the jsdom suite builds a real rig out of
three `Bone`s and a `Mesh` with a `morphTargetInfluences` array and reads the animation back as numbers:
the lid peaks above 0.95 mid-blink and is *exactly* 0 between blinks, the chest's `rotation.x` equals
`breath(t)` while the head's stays 0, three seconds of a far pointer lands the neck at its clamp and not
past it, `0.52` opens `え` alone, and silence at 60 Hz returns every viseme under 0.02. Moods hold one at a
time and release on `setMood(null)`. A body missing a part says so — `no '上半身' bone, so this body has no
chest to breathe with` — and a body with no visemes still breathes and blinks and reports which five sounds
have no morph. `dispose()` is idempotent and returns both the rig and the host.

**Three things the suite caught while it was being written.**

1. *`new Bone("頭")` is a bone called "Bone".* three's `Bone` constructor takes no arguments, so the test rig's
   bones were nameless, `boneByName` found nothing, and the head never turned — a failure that would have
   looked like a broken stage rather than a broken fixture. Names are assigned after construction, which is
   what `load.ts` has done since T11.
2. *`import.meta.url` is not a file URL under jsdom.* The seam test that reads `stage.ts` back to pin "no
   renderer is constructed here" threw `The URL must be of scheme file`; the repo's existing pattern
   (`styles.test.ts`, `pwa.test.ts`) is `resolve(process.cwd(), ...)`, and it now matches.
3. *A pinned prohibition must not name itself.* `expect(source).not.toContain("WebGLRenderer")` failed on the
   module's own header comment, which explains the class it refuses to build. The assertion is scoped to an
   `import` list and a `new` — prose is allowed to mention what code may not do.

Gates: `typecheck` clean, `npm test` 438 passed (43 files), `npm run build` OK, `kira-contracts` OK
(v2, 86 schemas), engine `pytest` 747 passed / 8 skipped.

### T14 — lip-sync on the call
Files: `kira-chat/src/voice/audio.ts`, `src/voice/useCall.ts`, `src/screens/CallView.tsx`, tests.
RED: an `AnalyserNode` sits between the buffer source and `destination`; `onPlaybackLevel` fires while
speaking and stops cleanly with playback (no orphan rAF); `#/call` shows the stage when a character is
active and the existing barge-in and mic-meter tests stay green. Commit:
`avatar: a mouth that moves when Kira speaks`.

Delivered: `src/voice/audio.ts` grows `onPlaybackLevel(fn|null)` and one `AnalyserNode` that sits **in** the
graph — every sentence source connects to it and it alone connects to `destination`, because a tap beside
the signal path measures whatever the browser feels like feeding it. `fftSize = LEVEL_WINDOW`, one reading
per frame, and `pumpPlayback()` stops itself when no source is left: an orphan `requestAnimationFrame` is a
battery drain and a mouth that never closes. The pump only runs when a listener is registered, so a call
with no stage mounted pays for no measurement at all. `CallScreen` mounts `AvatarStage` for the active
character and feeds it that level; `AvatarStage` maps the level through `visemeWeights` and the same
`approach` filter the head uses, so a burst of TTS moves the jaw over a few frames instead of snapping.

**The browser pass, and the two defects it found.** `tools/kira_lab.py` on loopback with Ellen active
(`ellen-6081cbc6`, 29,287 vertices · 487 bones · 8/8 textures), the built bundle, captures in
`docs/qa/avatar-stage/`.

- **1280×900 desktop** (`01-desktop-1280x900.png`): the pane is `position: sticky`, `max-height: 765px`
  (85dvh), and its own `scrollHeight` equals its `clientHeight` — 777 against 763, no internal scroll. The
  drawing is 318×424 CSS px for a 360×480 buffer, so the ratio the camera was framed for survives the
  column. `take everyone off` sits at 345–380 above the canvas, the mood row at 818–895 below it, and **no
  button overlaps the canvas**; the last one is 5px inside the fold. The findings note (902–956) is the one
  thing below the fold, and the screen scrolls 160px to reach it.
- **390×844 phone** (`02-phone-390x844.png`): the card is in the page's flow, so scrolling the screen to
  its end (731px) puts all six buttons and the note fully on screen. That pass also caught a defect that
  had nothing to do with the pane: `.screen` was 410px wide inside a 375px viewport — the library table's
  min-content is 394px (a hex id, a licence line, three button labels) — and `.screen` answers a wide table
  with `overflow-x: auto`, which is the right answer for the eight-column dashboard and the wrong one here,
  because the stage shares that box: scrolling right to reach `remove` slid the body you were looking at off
  the left edge. Fixed by moving the scroll into the table (`min-width: 0; overflow-x: auto` on
  `.avatar-library` in the phone query); the re-run (`03-phone-390x844-no-side-scroll.png`) measures
  `screen.scrollWidth === clientWidth === 375`, the library scrolling 394 against 343 by itself, and the
  canvas at 294×392 still 3:4.

**What this does not claim.** The lab's TTS is `mock`, so no real audio ever reached the analyser: the
mouth is proven by the jsdom numbers (`0.52` opens `え` alone, silence returns every viseme under 0.02) and
by the wiring — the source connects to the analyser that connects to `destination` — not by a live voice
moving a jaw on a GPU. That run belongs to T16 with a real provider. The camera numbers are measured, not
guessed: `FRAME_SHARE = 0.36` came off the ten donor bodies, and a body the reader cannot see still gets
`UNKNOWN_BODY = 20` units rather than a camera at the origin.

Gates: `npm run check` — tsc clean, 47 files / 481 tests, build OK; `kira-contracts` OK (v2, 86 schemas);
engine `pytest` 794 passed / 8 skipped. Commits: `avatar: a mouth that moves when Kira speaks`,
`avatar: a stage that stays put and a camera that frames the body it is given`.

## M38 — the companion window, then the record

### T15 — the second window
Files: `kira-engine/src/kira/desktop.py` (or `companion.py`), `tests/test_cli_desktop.py`,
`tests/test_companion.py`.
RED: `--companion` opens a second window with the frameless/transparent/on_top kwargs and the
`#/companion` URL, its geometry is a separate key in `desktop.json`, the token injection reuses the
memory-only boot path and never injects the confirm secret, click-through is a `WS_EX_TRANSPARENT`
toggle behind a function that is unit-tested without a live HWND, and an unsupported transparency
falls back to the opaque card while reporting that it did. Commit:
`desktop: a companion window that sits on the desktop, not in the app`.

Delivered: `kira-engine/src/kira/companion.py` is new and holds the whole second window — the kwargs, the
URL pair, the geometry section, the Win32 bits and the object the page talks to. `desktop.py` keeps the
shell and gains `_start_companion()`, which owns the card's `loaded`/`closing`/`closed` wiring: hide
instead of destroy on close (a card you closed is a card you reopen from the tray), geometry saved under
`companion` in the same `desktop.json`, and the same 8-second `SHOW_FALLBACK_S` timer that guarantees the
app window appears, because a card that never shows is a card the user thinks they asked for. `Placement`
grew a `key=` argument and `read/write_placement` a section name, with `GEOMETRY_FIELDS` as the whitelist
on the way out — a file that can hold two windows must not be able to hold a token in either.
`boot_script = desktop.bootstrap_script` is the injection reused verbatim, which is how "never injects the
confirm secret" is true here for the same reason it is true there. `--companion` is on both
`kira-engine desktop` and `run_kira.py`, where asking for the card implies `--window`.

The window asks for `frameless`, `transparent`, `on_top`, `hidden`, `easy_drag`, `min_size` and
`shadow: False`. The last one is not decoration: a frameless window still gets an OS drop shadow, and a
shadow is a rectangle — precisely the shape a transparent client area is trying not to have.

`apply_click_through(hwnd, enabled, *, user32)` sets or clears `WS_EX_TRANSPARENT | WS_EX_LAYERED` and
leaves every other bit alone; `user32` is handed in, so the 24 tests in `tests/test_companion.py` never
need an HWND, a GUI thread or a display. `CompanionApi` answers with plain dicts — a page cannot see a
Python exception — and can reach nothing but one style word on one window of this process.

**The client half.** `companion` is a route that is not in the rail (`RAIL_ROUTES` drops it next to
`pair`), and `initialRoute()` reads `?companion=1` so the very first paint of the second window is the
card rather than a rail and a model picker squeezed into 320px. `CompanionScreen` is the card: the stage,
the name, `click through`, `hide`. No rail, no picker, no options panel, no prose. It wears the app's
theme (`data-shell="chat"` is where the palette tokens are declared, not the Chat mode) and sets
`html[data-window="companion"]`, which is the switch styles.css uses to take the opaque background off
`body` and `.app` — pywebview's `transparent` only shows the desktop through what the page leaves
unpainted. With no token it points at the other window instead of showing a second gate; with no bridge
it disables the switch and says so. 155 tests across the five files this touches, 13 of them
`CompanionScreen.test.tsx`.

**The live pass, and the four defects it found.** `kira-engine desktop --companion` on loopback port
8913 (8912 was still held by an older lab process), `--backend memory`, disposable data dir, captures in
`docs/qa/companion-window/`.

- **`TypeError: create_window() got an unexpected keyword argument 'window_frame'`.** `window_frame` was
  invented; the installed pywebview has no such parameter. Fixed by `shadow: False`, and guarded against
  a repeat by `CREATE_WINDOW_PARAMS` in the test file — the parameter list read off the installed
  `create_window` — so any keyword the card asks for that the toolkit does not take fails a test instead
  of a desktop.
- **That same TypeError took the whole app down.** `open_window` treated *any* `TypeError` as a
  transparency refusal, retried opaque, raised again, and the traceback escaped `_start_companion` →
  `run()`: no app window either. Fixed twice over — `_refuses_transparency()` only accepts a refusal that
  names `transparent`, and a card that cannot be made now logs and returns `None`, because the companion
  is an extra and the app is not.
- **`webview.errors.JavascriptException: window.pywebview._returnValuesCallbacks.get_state.… is not a
  function`.** The card called the native bridge from the *boot* document, which the navigation to
  `#/companion` was about to replace; the answer arrived at a page that no longer existed and pywebview
  raised in its own `_call` thread. Fixed by the `onTarget` gate: nothing is asked of a document seconds
  from being thrown away.
- **The mood row crowded the card.** The stage drew its five mood chips into a 320×420 window, pushing
  the name and the bar and leaving buttons that move her face with nothing on screen to show them. Fixed
  with a `moods` prop on `AvatarStage` (default `true`, `false` in the card) rather than `display: none`,
  so the buttons are absent from the accessibility tree instead of invisible in it.

**What was measured, not assumed.** Click-through was driven against the real HWND from a separate
process: exstyle `0x50008` → `0xd0028` on the toggle → `0x50008` on clearing, with `get_state()`
agreeing at both ends. Transparency was *accepted* on this machine — no refusal was logged — so the
opaque fallback and its `TRANSPARENCY_NOTE` are proven by tests only, not by a live run. `01-app-window.png`
is the app (1280×860, no Companion in the rail); `02-companion-card.png` is the card as a window
(304×381, Ellen drawn on real WebGL, name, switch, hide); `03-companion-browser-tab.png` is the same URL
in a browser tab, where the switch is disabled and the hint reads "click through only works in the desktop
window".

**What this does not claim.** The card is not a tool window: this pywebview's `create_window` has no
keyword for it, so the companion does appear in Alt-Tab. The card has no analyser — `playbackLevel` is
pinned at silence, because a pet on the desktop is not where a speaking Kira lives; the call screen is,
and it has its own window and its own measurement. Nothing in the card talks to the engine except the two
character reads. And the card does not persist anything: the token it draws with came from the app
window's `localStorage`, the confirm secret never entered this process's page, and the only file it writes
is four geometry numbers.

Gates: `npm run check` — tsc clean, 48 files / 503 tests, build OK, `dist/kira-build.json` stamped
`{"api_version":1,"contract_version":2,"api_prefix":"/v1"}`; engine `pytest` 819 passed / 8 skipped;
`kira-contracts` OK (v2, 86 schemas, 6 chunk types, 16 chain events). No new HTTP route, so no schema moved.

### T16 — docs, gates, live pass, roadmap
Files: `README.md`, `PROVENANCE.md`, `docs/qa/avatar-stage-pass.md`, `docs/ROADMAP.md`, `.gitignore`.
Do: import all ten donor archives through the CLI; render Ellen, Astra v2 and 苍鹭·托特 (the lightest,
the heaviest-textured, and the 955-constraint one) in a real browser; measure fps with physics on and
off and set the default from the measurement; drive a call and watch the visemes; traverse-test the
file route from the browser; screenshots of app content only. Record the licence posture, the
`mmd-parser`-was-throwaway note, and every gap (no `.vmd`, no model-driven mood, no installer, real
GPU is 4 GB and CPU-only for this rig). Write the `physics on/off` default honestly, and restate the
arithmetic: unit 11 delivered **5** milestones where 2 were estimated → denominator **47**.
Commit: `avatar: unit 11 closed, and the project's last unit has a number`.
