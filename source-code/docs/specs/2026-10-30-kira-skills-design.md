# Kira unit 7 — skills pack: design — 2026-10-30

## What this is for

Unit 7 was reserved for two donor features that share one shape: **personas** and a **prompt
library**. Mia hardcodes personality/style/fun-mode dicts into its system prompt
(`core/agent.py:229-247`) and saves templated prompts as JSON (`core/prompts.py`); the reaction
recorded in `docs/ROADMAP.md` §project-Mia is that "a persona is a prompt pack, not an engine
feature". This unit makes that pack **data**: a directory of Markdown files that the engine loads,
lists, applies to a turn, and lets the model pull on demand.

Two things it is deliberately not:

- **Not a plugin.** Unit 2's plugins are declarative HTTP tools with a risk policy. A skill is
  text, owns no process, and spends nothing to sit on disk.
- **Not a prompt library with `{vars}`.** Filling variables from the UI is a separate feature; the
  honest first version is instructions a turn can carry, plus a way for the model to fetch a
  procedure mid-turn.

## The file

`<name>.md`, YAML frontmatter, Markdown body:

```markdown
---
name: concise
description: Answer in the fewest words that are still true.
kind: persona
---
You are terse. Prefer one sentence to three...
```

| Field | Rule |
| --- | --- |
| `name` | `^[a-z][a-z0-9_-]{2,39}$`; unique across roots, user overrides builtin |
| `description` | non-empty, one line — this is what a picker and a tool schema show |
| `kind` | `persona` or `method` |
| body | non-empty, ≤ 16 KB including frontmatter |

`kind` decides the lifetime:

- **persona** — applied to a turn as the first `system` message when the caller names it, then
  memory's block is appended to it. Not sticky in the engine: a caller sends `skill` per request.
- **method** — not injected. It is offered to the model through one built-in tool, `use_skill`,
  whose description lists every method's name and one line. Calling it returns the body. This is
  progressive disclosure: a long procedure costs tokens only when the model decides it needs it.

## Where the files live

Two roots, loaded in this order:

1. **builtin** — `kira-engine/skills/` in the repository, the starter pack.
2. **user** — `<data_dir>/skills/`, which may add skills or replace a builtin by name.

A user file with a builtin's name wins and is reported `source: "user"`. A malformed file never
stops the engine: it appears in the list as `status: "skipped"` with the reason, exactly like a bad
plugin file. The repo ships four starter skills — two personas (`concise`, `reviewer`) and two
methods (`debug`, `research`) — authored for Kira, not copied from any donor.

## API

- `GET /v1/kira/skills` → `{"skills": [...loaded...], "files": [...every file's status...]}`,
  mirroring `/v1/kira/tools`. A loaded row is
  `{name, description, kind, source, body_bytes}`; a status row is
  `{file, name, status, reason, source}`.
- `ChatRequest.skill: string | null` — a **persona** name. Unknown name → `400 config_error`
  naming it; a method name → `400 config_error` saying a method is loaded by the model, not
  pinned to a turn. The two errors differ because the fix differs.
- No write endpoints. The pack is files on disk, edited by the user; this engine has no business
  editing them over HTTP.

`use_skill` is registered only when at least one method skill loaded, the same rule that keeps
`remember` off when capture is off. It is risk `read` with default policy `allow`; a user who wants
to gate it sets a policy like any other tool.

## Assembly order, for a turn that names a persona

```
system: <persona body>          ← only when `skill` is set
        + memory block           ← appended by the existing inject()
user/assistant/tool history      ← unchanged
```

`inject()` already appends the memory block to an existing first system message, so the persona is
inserted first and everything downstream is untouched. A turn with no `skill` behaves exactly as
today.

## Errors and honesty

| Case | Answer |
| --- | --- |
| `skill` names nothing loaded | 400 `config_error`: `unknown skill 'x'` |
| `skill` names a method | 400 `config_error`: `'x' is a method skill; the model loads it with use_skill` |
| `skill` names a file that was skipped | 400, same as unknown, reason already on the list route |
| file too big / unparseable / bad kind | skipped in the list, engine keeps serving |
| duplicate name within one root | later file is skipped with the reason; across roots the user file wins |

## What is deferred, and why

- **Prompt library with `{vars}`** — a prompt template is user text plus a fill-in UI; it is a
  chat-composer feature, not an engine instruction layer. Revisit with unit 8's second surface.
- **Persona in the voice call** — the call owns a system prompt built for speech; letting a
  persona replace it would silently change turn-taking rules. Revisit if a call-specific persona
  is ever asked for.
- **Skills selecting tools** — a skill that declares `allow: [web_search]` would be a second
  permission system beside the tool policy table. One gate is enough.
- **Session summarisation** — unit 4 deferred it "to #7"; it is still a model call per session
  with the silent-spend problems extraction has, and this unit does not solve those.

## Acceptance tests (the ones that fail before the code)

Engine:

1. `concise.md`-shaped file loads, and `GET /v1/kira/skills` lists it with kind, source and size.
2. A user file with a builtin name shadows it and reads `source: "user"`.
3. A malformed file is `skipped` with a reason; a good file beside it still loads.
4. 17 KB body → skipped; empty body → skipped; bad kind → skipped.
5. `POST /v1/chat/completions {"skill": "concise"}` puts the body in the first system message, and
   the memory block is appended after it, in that order.
6. A turn without `skill` has no extra system message.
7. Unknown persona → 400 `config_error`; method name → 400 with the use_skill message.
8. `use_skill` exists iff a method skill loaded; its schema enumerates method names only; calling
   it returns the body; calling an unknown name is a tool error naming the valid ones.
9. A plugin already named `use_skill` does not crash startup (builtin wins; the plugin is skipped).

Client: `#/skills` lists name, kind, source and any skipped reason; "use" stores the choice and
opens chat; the composer shows the active skill and can clear it; the next turn sends `skill`.

## Milestones

- **M23** — loader, prompt assembly, `use_skill`, route, contract schemas, starter pack, tests.
- **M24** — `#/skills` screen in both shells, active-skill chip in the composer, client tests,
  README + ROADMAP, browser pass.
