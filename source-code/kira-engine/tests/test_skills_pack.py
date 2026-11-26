from __future__ import annotations

import asyncio
import json
from pathlib import Path

from kira.skills import (
    INLINE_LIMIT,
    MAX_SKILL_BYTES,
    PACK_FILE,
    Skill,
    discovery_mode,
    load_skills,
    register_skill_tool,
)
from kira.tools import ToolRegistry

USER = {"role": "user", "content": "hi"}


def skill_md(name: str, kind: str = "method", body: str = "Step one.", description: str | None = None) -> str:
    text = description or f"What {name} does when the task asks for it."
    return f"---\nname: {name}\ndescription: {text}\nkind: {kind}\n---\n{body}\n"


def folder(root: Path, name: str, text: str) -> Path:
    path = root / name / PACK_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def flat(root: Path, name: str, text: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{name}.md"
    path.write_text(text, encoding="utf-8")
    return path


# --- the loader reads a pack the way packs ship ------------------------------------------------


def test_a_skill_folder_loads_and_is_labelled_with_its_folder(tmp_path: Path):
    user = tmp_path / "user"
    folder(user, "tdd", skill_md("tdd", body="Red, green, refactor."))
    skills, statuses = load_skills(None, user)
    assert [skill.name for skill in skills] == ["tdd"]
    assert skills[0].body == "Red, green, refactor."
    # A pack of 300 folders would otherwise report 300 rows all called `SKILL.md`.
    assert statuses[0].file == f"tdd/{PACK_FILE}"
    assert statuses[0].status == "loaded"


def test_a_flat_file_and_a_folder_in_one_root_are_both_found(tmp_path: Path):
    user = tmp_path / "user"
    flat(user, "loose", skill_md("loose", kind="persona"))
    folder(user, "boxed", skill_md("boxed"))
    skills, statuses = load_skills(None, user)
    assert [skill.name for skill in skills] == ["boxed", "loose"]
    assert [status.file for status in statuses] == [f"boxed/{PACK_FILE}", "loose.md"]


def test_a_folder_without_a_skill_file_is_not_a_skill(tmp_path: Path):
    user = tmp_path / "user"
    (user / "notes" / "readme.md").parent.mkdir(parents=True)
    (user / "notes" / "readme.md").write_text(skill_md("notes"), encoding="utf-8")
    skills, statuses = load_skills(None, user)
    assert skills == []
    assert statuses == []


def test_an_oversized_skill_file_is_skipped_by_name(tmp_path: Path):
    user = tmp_path / "user"
    folder(user, "huge", skill_md("huge", body="x" * (MAX_SKILL_BYTES + 1)))
    folder(user, "fits", skill_md("fits", body="short"))
    skills, statuses = load_skills(None, user)
    assert [skill.name for skill in skills] == ["fits"]
    row = next(status for status in statuses if status.status == "skipped")
    assert row.file == f"huge/{PACK_FILE}"
    assert "16384" in row.reason


def test_a_folder_skill_shadows_a_builtin_flat_file_of_the_same_name(tmp_path: Path):
    builtin = tmp_path / "builtin"
    flat(builtin, "debug", skill_md("debug", body="Builtin words."))
    user = tmp_path / "user"
    folder(user, "my-debug-folder", skill_md("debug", body="My words."))
    skills, statuses = load_skills(builtin, user)
    assert [skill.body for skill in skills] == ["My words."]
    assert skills[0].source == "user"
    shadowed = next(status for status in statuses if status.status == "shadowed")
    assert "my-debug-folder/SKILL.md" in shadowed.reason


# --- the tool survives a pack that is not hand-written -----------------------------------------


def methods(count: int) -> list[Skill]:
    return [
        Skill(
            name=f"method-{index:03d}",
            description=f"Does procedure number {index} for a task that needs it.",
            kind="method",
            body=f"Step one of {index}.",
            source="user",
            file=f"method-{index:03d}/SKILL.md",
        )
        for index in range(count)
    ]


def registered(count: int) -> ToolRegistry:
    registry = ToolRegistry()
    register_skill_tool(registry, methods(count))
    return registry


def test_a_small_pack_still_lists_its_methods_and_needs_no_search():
    registry = registered(INLINE_LIMIT)
    assert registry.get("search_skills") is None
    tool = registry.get("use_skill")
    assert tool.parameters["properties"]["name"]["enum"] == [skill.name for skill in methods(INLINE_LIMIT)]


def test_a_big_pack_stops_naming_every_method_in_the_schema():
    registry = registered(INLINE_LIMIT + 1)
    tool = registry.get("use_skill")
    assert "enum" not in tool.parameters["properties"]["name"]
    assert "search_skills" in tool.description
    # The count is in the description; the names are not. A kilobyte of names on every turn is the bug.
    assert str(INLINE_LIMIT + 1) in tool.description
    assert not any(name in tool.description for name in ("method-000", "method-024"))
    assert registry.get("search_skills") is not None
    assert registry.get("search_skills").risk == "read"
    assert registry.get("search_skills").default_policy == "allow"


def test_the_pack_reports_which_of_the_two_ways_a_model_reaches_a_method():
    """`discovery` is the rule above, named — so the screen never repeats the limit it cannot see.

    A dashboard that guessed 24 would say "the model picks from the list" the turn the engine changed
    its mind, and the user would search the schema for a name that was never there.
    """
    assert discovery_mode([]) == "none"
    assert discovery_mode(methods(INLINE_LIMIT)) == "inline"
    assert discovery_mode(methods(INLINE_LIMIT + 1)) == "search"


def test_a_pack_of_personals_only_offers_no_method_at_all():
    pack = [
        Skill(
            name="concise",
            description="Answer in the fewest words that are still true.",
            kind="persona",
            body="Be brief.",
            source="builtin",
            file="concise.md",
        )
    ]
    assert discovery_mode(pack) == "none"
    registry = ToolRegistry()
    assert register_skill_tool(registry, pack) is False
    assert registry.get("use_skill") is None


def test_search_ranks_a_name_hit_above_a_description_hit():
    registry = registered(INLINE_LIMIT + 1)
    answer = asyncio.run(registry.execute("search_skills", {"query": "method-024"}))
    assert answer.ok
    found = json.loads(answer.content)["skills"]
    assert found[0]["name"] == "method-024"
    assert answer.summary == "search_skills(method-024)"


def test_search_returns_names_for_a_word_that_only_appears_in_descriptions():
    registry = ToolRegistry()
    pack = methods(1)
    pack[0].description = "Trace a failure back to the line that caused it."
    pack[0].name = "find-root-cause"
    pack += methods(INLINE_LIMIT)
    register_skill_tool(registry, pack)
    answer = asyncio.run(registry.execute("search_skills", {"query": "failure"}))
    names = [row["name"] for row in json.loads(answer.content)["skills"]]
    assert names == ["find-root-cause"]


def test_search_cuts_the_list_at_its_limit_and_reports_the_total():
    registry = registered(INLINE_LIMIT + 1)
    answer = asyncio.run(registry.execute("search_skills", {"query": "procedure", "limit": 3}))
    body = json.loads(answer.content)
    assert len(body["skills"]) == 3
    assert body["installed"] == INLINE_LIMIT + 1


def test_search_refuses_an_empty_query_and_a_bad_limit():
    registry = registered(INLINE_LIMIT + 1)
    assert not asyncio.run(registry.execute("search_skills", {"query": "  "})).ok
    assert not asyncio.run(registry.execute("search_skills", {"query": "x", "limit": 0})).ok
    assert not asyncio.run(registry.execute("search_skills", {"query": "x", "limit": "3"})).ok


def test_a_miss_in_a_big_pack_points_at_the_search_instead_of_a_name_list():
    registry = registered(INLINE_LIMIT + 1)
    answer = asyncio.run(registry.execute("use_skill", {"name": "nope"}))
    assert not answer.ok
    assert "search_skills" in answer.content
    assert "method-000" not in answer.content


def test_a_hit_in_a_big_pack_still_returns_the_body():
    registry = registered(INLINE_LIMIT + 1)
    answer = asyncio.run(registry.execute("use_skill", {"name": "method-007"}))
    assert answer.ok and answer.content == "Step one of 7."
