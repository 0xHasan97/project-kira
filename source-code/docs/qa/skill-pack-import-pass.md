# Skill pack import — CLI + browser pass, 2026-11-04

M35. The donor is `Source code/skills/ECC-main.zip`: 314 canonical skills in the
`ECC-main/skills/<name>/SKILL.md` shape, MIT at the root, and the same skill repeated under
`.agents/`, `.claude/`, `.kiro/` and `docs/*` for other harnesses. Nothing from the archive
was executed and nothing but `SKILL.md` + `LICENSE*` was read; no donor file entered the repo.

The engine was `tools/kira_lab.py` on loopback with `--data-dir` pointed at the kept lab
directory, `mock_openai` as the provider, and both secrets disposable. The user's Locker and
real providers were not touched, and this pass spent nothing.

## What the CLI did

```
kira-engine skills install "…/ECC-main.zip" --data-dir "…/.kira-lab"
kira-engine skills install "…/ECC-main.zip" --data-dir "…/Kira/.kira-data"
```

Both answered the same report:

```json
{"counts": {"installed": 266, "skipped": 48}, "licence": "written", "dry_run": false}
```

The 48 refusals went to stderr, one line each, and every one names why: 45 are `SKILL.md is
NNNNN bytes, over the 16384`, one is a folder name that is not a Kira skill name, and the rest
crossed the cap only after Kira's own frontmatter fields were added on top of the donor's. The
per-harness copies never appeared as rows at all — `<top>/skills/` is the only tree read.

`kira-engine skills list` on the live data dir then reported what the engine would actually
load: **270 skills** (266 user + the 4 builtin starters), 2 persona / 268 method, 0 refusals at
load time, largest body 15 826 B, `discovery: "search"`.

## What the screen said

`http://127.0.0.1:8912/chat/#/skills`, Agent shell, after the lab token went into
`localStorage` and the page reloaded.

- The line above the table read: `270 loaded · 268 methods are installed — too many to name on
  every turn, so the model finds one with the search_skills tool and loads it by the exact name
  it was given.` That sentence is the engine's `discovery`, not the client's guess.
- The table rendered all 270 rows with real donor descriptions (`accessibility` 6140 B,
  `agent-architecture-audit` 9672 B, `agent-eval` 4288 B …), each method marked
  `the model loads it`.
- Typing `tdd` into **search skills** narrowed it to 6 rows — `brownfield-retrospective`,
  `orch-add-feature`, `orch-pipeline`, `perl-testing`, `rust-testing`, `springboot-tdd` — by
  description, not just name. Clearing it returned 270.
- **files** said `270 of 270 files read` and listed nothing, because a pack that was refused at
  install has no load-time complaint. The refusal path is still visible: `tests/…/SkillsScreen.test.tsx`
  and `test_skills.py` both keep a `skipped` file with its reason in the list.

## What the model did

Two turns in the Agent composer, each with a scripted tool call from the lab mock:

| Turn | Tool round | What the chip showed |
| --- | --- | --- |
| `findskill please` | `search_skills` | `✓ Read search_skills(tdd) · 1629 chars`, then `2 served · 0 failed · 1 tool runs` |
| `loadskill please` | `use_skill` | `✓ Read use_skill(agent-eval) · 3880 chars`, then the same completed second step |

3880 characters is the donor's own `agent-eval/SKILL.md` body arriving in the turn — proof the
installed folder is loadable by the model, not merely listable by the screen. `GET /v1/kira/tools`
in the same session returned both `search_skills` and `use_skill` among the 11 registered tools.

## What this pass does not claim

- **One capture, not three.** `docs/qa/skill-pack-import/01-skills-filtered-tdd.png` is the screen with
  `tdd` typed in the search box: 6 rows out of 270, the counts line naming `search_skills`, and FILES
  reading `270 of 270 files read`. The two tool rounds above are recorded as DOM text, because the
  browser tool that drove them writes only inside its own roots; the screen state in them is the same one
  the capture shows.
- **The mock cannot choose a skill.** Its tool call is scripted by prompt keyword
  (`tools/mock_openai.py`, `TOOL_ROUTES`), so this proves the wire and the UI for
  `search_skills`/`use_skill`, not that a real model picks the right procedure out of 268. The
  ranking itself is engine-tested (`test_skills_pack.py`).
- **No live provider was called and no key was read.** The lab vault is in-process memory; the
  user's Locker entries are untouched.
- 48 donor skills are **not installed** and were not made installable by trimming them. A
  25 KB procedure is over the prompt-weight cap Kira sets for itself; the reason is printed, and
  the donor's own copy stays in the user's zip.
