from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from conftest import Harness, ok, openai_text_chunks
from kira.memory import BLOCK_HEADER
from kira.skills import MAX_SKILL_BYTES, load_skills, register_skill_tool
from kira.tools import ToolRegistry

USER = {"role": "user", "content": "hi"}


def skill_md(name: str, kind: str = "persona", body: str = "You are terse.", description: str = "Be brief.") -> str:
    return f"---\nname: {name}\ndescription: {description}\nkind: {kind}\n---\n{body}\n"


def write(directory: Path, filename: str, text: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    path.write_text(text, encoding="utf-8")
    return path


def load(tmp_path, builtin: dict[str, str] | None = None, user: dict[str, str] | None = None):
    builtin_dir = tmp_path / "builtin"
    user_dir = tmp_path / "user"
    for name, text in (builtin or {}).items():
        write(builtin_dir, name, text)
    for name, text in (user or {}).items():
        write(user_dir, name, text)
    return load_skills(builtin_dir if builtin is not None else None, user_dir)


def test_a_persona_and_a_method_load_with_their_kind_and_source(tmp_path):
    skills, statuses = load(
        tmp_path,
        builtin={"concise.md": skill_md("concise"), "debug.md": skill_md("debug", kind="method", body="Reproduce first.")},
    )
    by_name = {skill.name: skill for skill in skills}
    assert by_name["concise"].kind == "persona" and by_name["concise"].source == "builtin"
    assert by_name["debug"].kind == "method" and by_name["debug"].body == "Reproduce first."
    assert [status.status for status in statuses] == ["loaded", "loaded"]


def test_a_user_file_shadows_the_builtin_of_the_same_name(tmp_path):
    skills, statuses = load(
        tmp_path,
        builtin={"concise.md": skill_md("concise", body="Builtin words.")},
        user={"concise.md": skill_md("concise", body="My words.")},
    )
    assert [skill.body for skill in skills] == ["My words."]
    assert skills[0].source == "user"
    states = {(status.file, status.source): status for status in statuses}
    assert states[("concise.md", "user")].status == "loaded"
    assert states[("concise.md", "builtin")].status == "shadowed"


def test_a_broken_file_is_skipped_and_its_neighbour_still_loads(tmp_path):
    skills, statuses = load(
        tmp_path,
        user={"bad.md": "no frontmatter at all", "good.md": skill_md("good")},
    )
    assert [skill.name for skill in skills] == ["good"]
    bad = next(status for status in statuses if status.file == "bad.md")
    assert bad.status == "skipped" and "frontmatter" in bad.reason


def test_size_empty_body_and_bad_kind_are_all_refused(tmp_path):
    big = skill_md("big", body="x" * (MAX_SKILL_BYTES + 1))
    empty = "---\nname: hollow\ndescription: Nothing.\nkind: persona\n---\n\n"
    wrong = skill_md("wrong", kind="spell")
    skills, statuses = load(tmp_path, user={"big.md": big, "empty.md": empty, "wrong.md": wrong})
    assert skills == []
    reasons = {status.file: status.reason for status in statuses}
    assert "larger than" in reasons["big.md"]
    assert "body" in reasons["empty.md"]
    assert "kind" in reasons["wrong.md"]


def test_a_duplicate_name_in_one_root_keeps_the_first_file(tmp_path):
    skills, statuses = load(
        tmp_path,
        user={"a.md": skill_md("twin", body="first"), "b.md": skill_md("twin", body="second")},
    )
    assert [skill.body for skill in skills] == ["first"]
    assert {status.file: status.status for status in statuses} == {"a.md": "loaded", "b.md": "skipped"}


def test_use_skill_exists_only_when_a_method_loaded(tmp_path):
    personas_only, _ = load(tmp_path, user={"p.md": skill_md("persona_one")})
    registry = ToolRegistry()
    assert register_skill_tool(registry, personas_only) is False
    assert registry.get("use_skill") is None

    with_methods, _ = load(tmp_path / "b", user={"d.md": skill_md("debug", kind="method", body="Reproduce first.")})
    registry = ToolRegistry()
    assert register_skill_tool(registry, with_methods) is True
    tool = registry.get("use_skill")
    assert tool is not None and tool.risk == "read" and tool.default_policy == "allow"
    schema = tool.parameters["properties"]["name"]
    assert schema["enum"] == ["debug"]


def test_use_skill_returns_the_body_and_names_valid_choices_on_a_miss(tmp_path):
    skills, _ = load(
        tmp_path,
        user={
            "d.md": skill_md("debug", kind="method", body="Reproduce first."),
            "r.md": skill_md("research", kind="method", body="Search, then cite."),
        },
    )
    registry = ToolRegistry()
    register_skill_tool(registry, skills)
    hit = asyncio.run(registry.execute("use_skill", {"name": "debug"}))
    assert hit.ok and hit.content == "Reproduce first."
    miss = asyncio.run(registry.execute("use_skill", {"name": "missing"}))
    assert not miss.ok and "debug" in miss.content and "research" in miss.content


def prepared_harness(tmp_path, persona_body: str = "You are terse.") -> Harness:
    write(tmp_path / ".kira-data" / "skills", "concise.md", skill_md("concise", body=persona_body))
    return Harness(tmp_path)


async def test_a_named_persona_leads_the_system_message_and_memory_follows_it(tmp_path):
    harness = prepared_harness(tmp_path)
    harness.engine.memory.add("I prefer pnpm.", pinned=True)
    harness.script.queue("fast1", ok(openai_text_chunks("ok")))
    resp = await harness.api.post(
        "/v1/chat/completions",
        headers=harness.auth,
        json={"messages": [USER], "model": "mini", "skill": "concise"},
    )
    assert resp.status_code == 200, resp.text
    sent = harness.script.body_for("fast1")["messages"]
    assert sent[0]["role"] == "system"
    assert sent[0]["content"].startswith("You are terse.")
    assert BLOCK_HEADER in sent[0]["content"]
    assert sent[0]["content"].index("You are terse.") < sent[0]["content"].index(BLOCK_HEADER)


async def test_a_turn_without_a_skill_gets_no_system_message(harness):
    harness.script.queue("fast1", ok(openai_text_chunks("ok")))
    resp = await harness.api.post(
        "/v1/chat/completions", headers=harness.auth, json={"messages": [USER], "model": "mini"}
    )
    assert resp.status_code == 200, resp.text
    assert [message["role"] for message in harness.script.body_for("fast1")["messages"]] == ["user"]


async def test_an_unknown_skill_is_a_named_config_error(harness):
    resp = await harness.api.post(
        "/v1/chat/completions",
        headers=harness.auth,
        json={"messages": [USER], "model": "mini", "skill": "nope"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "config_error"
    assert "nope" in resp.json()["error"]["message"]


async def test_a_method_cannot_be_pinned_to_a_turn(harness):
    resp = await harness.api.post(
        "/v1/chat/completions",
        headers=harness.auth,
        json={"messages": [USER], "model": "mini", "skill": "debug"},
    )
    assert resp.status_code == 400
    assert "use_skill" in resp.json()["error"]["message"]


async def test_the_skills_route_lists_loaded_files_and_refusals(tmp_path):
    harness = prepared_harness(tmp_path)
    write(harness.config.data_dir / "skills", "broken.md", "nope")
    # The engine read the pack at startup; a second engine sees the new file.
    from kira.app import Engine, create_app

    engine = Engine(harness.config, vault=harness.vault, http_client=harness.client)
    app = create_app(harness.config, engine=engine)
    import httpx

    api = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://kira.test")
    resp = await api.get("/v1/kira/skills", headers=harness.auth)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "concise" in [row["name"] for row in body["skills"]]
    assert ("broken.md", "skipped") in [(row["file"], row["status"]) for row in body["files"]]
    # Two builtin methods: the model still picks from the schema, so the screen says so.
    assert body["discovery"] == "inline"
