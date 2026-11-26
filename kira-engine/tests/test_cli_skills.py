"""`kira-engine skills` — a pack someone else wrote, installed without a browser.

The CLI writes into `config.skills_dir`, the directory the engine itself reads at startup, and reads back
with the same `load_skills` an `Engine` uses. That is the whole point of the file: a skill pack that only
the dashboard could add would be a pack whose rules live in the dashboard, and a `list` that printed its
own guess of what loaded would tell a user something the next turn disagrees with.

Stdout stays one JSON object on success and nothing at all after a refusal, so `... | jq` works; every
row that was refused goes to stderr, because a 300-skill pack that refused 46 of them is not a success
the user should have to scroll for.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from kira.__main__ import main
from kira.config import load_config, write_sample_config
from kira.skills import PACK_FILE, load_skills

DONOR = "---\nname: {name}\ndescription: Summarises {name} in one line.\n---\n\nDo {name}.\n"


def pack_tree(root: Path, names: list[str], extra: dict[str, str] | None = None) -> Path:
    for name in names:
        folder = root / "skills" / name
        folder.mkdir(parents=True)
        (folder / PACK_FILE).write_text(DONOR.format(name=name), encoding="utf-8")
    for path, text in (extra or {}).items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return root


def as_zip(root: Path, target: Path) -> Path:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for path in sorted(root.rglob("*")):
            if path.is_file():
                archive.writestr(f"ECC-main/{path.relative_to(root).as_posix()}", path.read_bytes())
    target.write_bytes(buffer.getvalue())
    return target


@pytest.fixture
def data_dir(tmp_path):
    write_sample_config(tmp_path)
    return tmp_path


def run(data_dir, *argv: str) -> int:
    return main(["skills", *argv, "--data-dir", str(data_dir), "--backend", "memory"])


def printed_json(capsys):
    return json.loads(capsys.readouterr().out)


def pack_dir(data_dir) -> Path:
    """The directory the engine reads, from the config — not a path this test guessed at."""
    return load_config(data_dir).skills_dir


# --- install ---------------------------------------------------------------------------------------


def test_an_installed_pack_is_where_the_engine_will_look_for_it(data_dir, tmp_path, capsys):
    source = pack_tree(tmp_path / "source", ["tdd", "api-design"])
    assert run(data_dir, "install", str(source)) == 0
    assert printed_json(capsys)["counts"] == {"installed": 2}
    assert (pack_dir(data_dir) / "tdd" / PACK_FILE).is_file()
    assert (pack_dir(data_dir) / "api-design" / PACK_FILE).is_file()


def test_an_installed_folder_loads_as_a_method_the_model_can_pull(data_dir, tmp_path, capsys):
    source = pack_tree(tmp_path / "source", ["tdd"])
    run(data_dir, "install", str(source))
    capsys.readouterr()
    assert run(data_dir, "list") == 0
    listing = printed_json(capsys)
    assert [row["name"] for row in listing["skills"] if row["name"] == "tdd"] == ["tdd"]
    row = next(entry for entry in listing["skills"] if entry["name"] == "tdd")
    assert row["kind"] == "method" and row["source"] == "user"
    assert listing["refusals"] == []


def test_a_zip_of_the_same_tree_installs_the_same_thing(data_dir, tmp_path, capsys):
    folder = pack_tree(tmp_path / "source", ["tdd"])
    archive = as_zip(folder, tmp_path / "ecc.zip")
    assert run(data_dir, "install", str(archive)) == 0
    skills, _ = load_skills(None, pack_dir(data_dir))
    assert [skill.name for skill in skills] == ["tdd"]


def test_a_pack_written_for_several_harnesses_installs_only_its_own_copy(data_dir, tmp_path, capsys):
    root = tmp_path / "source"
    pack_tree(root, ["tdd"])
    # A real pack carries the same skill under `.agents/`, `.claude/` and the translated docs.
    for other in (".agents", ".claude"):
        folder = root / other / "skills" / "tdd"
        folder.mkdir(parents=True)
        (folder / PACK_FILE).write_text(DONOR.format(name="tdd-copy"), encoding="utf-8")
    assert run(data_dir, "install", str(root)) == 0
    assert printed_json(capsys)["counts"] == {"installed": 1}


def test_a_refusal_goes_to_stderr_and_leaves_stdout_one_json_object(data_dir, tmp_path, capsys):
    root = tmp_path / "source"
    pack_tree(root, ["tdd"], {"skills/Bad_Name/SKILL.md": DONOR.format(name="bad")})
    assert run(data_dir, "install", str(root)) == 0
    captured = capsys.readouterr()
    assert printed_json_from(captured.out) == {"source": str(root), "counts": {"installed": 1, "skipped": 1}} | {
        "pack_dir": str(pack_dir(data_dir)),
        "dry_run": False,
        "licence": "none found",
    }
    assert "skipped: Bad_Name" in captured.err


def printed_json_from(text: str) -> dict:
    return json.loads(text)


def test_a_skill_too_large_for_a_prompt_is_named_on_stderr_not_quietly_dropped(data_dir, tmp_path, capsys):
    root = tmp_path / "source"
    root.joinpath("skills", "long").mkdir(parents=True)
    (root / "skills" / "long" / PACK_FILE).write_text(
        "---\nname: long\ndescription: A very long procedure.\n---\n\n" + ("x" * 40_000) + "\n",
        encoding="utf-8",
    )
    assert run(data_dir, "install", str(root)) == 1
    captured = capsys.readouterr()
    assert printed_json_from(captured.out)["counts"] == {"skipped": 1}
    assert "16384" in captured.err
    assert not pack_dir(data_dir).exists() or list(pack_dir(data_dir).iterdir()) == []


def test_a_sidecar_the_loader_never_reads_is_reported_with_the_skill(data_dir, tmp_path, capsys):
    root = tmp_path / "source"
    pack_tree(root, ["deep"], extra={"skills/deep/run.py": "print('never installed')\n"})
    assert run(data_dir, "install", str(root)) == 0
    assert "run.py" in capsys.readouterr().err
    assert not (pack_dir(data_dir) / "deep" / "run.py").exists()


def test_a_path_that_is_not_there_is_a_refusal_with_no_json(data_dir, tmp_path, capsys):
    assert run(data_dir, "install", str(tmp_path / "nowhere")) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "[kira]" in captured.err


def test_a_dry_run_reports_and_writes_nothing(data_dir, tmp_path, capsys):
    source = pack_tree(tmp_path / "source", ["tdd"], {"skills/tdd/check.py": "print(1)\n"})
    assert run(data_dir, "install", str(source), "--dry-run") == 0
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report["dry_run"] is True and report["counts"] == {"installed": 1}
    assert not pack_dir(data_dir).exists()
    # The row is printed because it carries a note, and a note in the past tense about a file
    # that was never written is the one thing a dry run must not say.
    assert "would install: tdd" in captured.err
    assert "installed: tdd" not in captured.err


def test_re_running_reports_unchanged_and_the_engine_loads_the_pack_once(data_dir, tmp_path, capsys):
    source = pack_tree(tmp_path / "source", ["tdd", "api-design"])
    run(data_dir, "install", str(source))
    capsys.readouterr()
    assert run(data_dir, "install", str(source)) == 0
    assert printed_json(capsys)["counts"] == {"unchanged": 2}
    skills, statuses = load_skills(None, pack_dir(data_dir))
    assert [skill.name for skill in skills] == ["api-design", "tdd"]
    assert all(status.status == "loaded" for status in statuses)


def test_force_replaces_a_file_and_the_notice_keeps_the_pack_licence(data_dir, tmp_path, capsys):
    root = tmp_path / "source"
    pack_tree(root, ["tdd"], extra={"LICENSE": "MIT License\n\nCopyright (c) 2026 Affaan Mustafa\n"})
    run(data_dir, "install", str(root))
    capsys.readouterr()
    installed = pack_dir(data_dir) / "tdd" / PACK_FILE
    installed.write_text(installed.read_text(encoding="utf-8") + "\nmy note\n", encoding="utf-8")
    assert run(data_dir, "install", str(root), "--force") == 0
    assert "my note" not in installed.read_text(encoding="utf-8")
    assert (pack_dir(data_dir) / "LICENSE").read_text(encoding="utf-8").startswith("MIT License")


# --- list ------------------------------------------------------------------------------------------


def test_list_reads_the_builtin_pack_and_the_user_pack_together(data_dir, capsys):
    assert run(data_dir, "list") == 0
    listing = printed_json(capsys)
    names = {row["name"] for row in listing["skills"]}
    # The starter pack ships with the engine, so an empty user pack is not an empty answer.
    assert {"concise", "debug", "research", "reviewer"} <= names
    assert {row["source"] for row in listing["skills"]} == {"builtin"}
    assert Path(listing["builtin_dir"]).name == "skills"
    assert listing["discovery"] == "inline"


def test_a_pack_past_the_inline_limit_is_reported_as_one_the_model_searches(data_dir, tmp_path, capsys):
    """The terminal says how to reach a method, because the engine decided that out loud.

    Three user methods plus the two builtin ones is still a schema the model can read by name; 25 is a
    list nobody can hold in mind, and `discovery` is where that turn is visible without reading source.
    """
    source = pack_tree(tmp_path / "source", [f"proc-{index:02d}" for index in range(25)])
    assert run(data_dir, "install", str(source)) == 0
    capsys.readouterr()
    assert run(data_dir, "list") == 0
    assert printed_json(capsys)["discovery"] == "search"


def test_a_user_skill_shadows_a_builtin_of_the_same_name_in_the_listing(data_dir, capsys):
    (pack_dir(data_dir) / "concise.md").parent.mkdir(parents=True)
    (pack_dir(data_dir) / "concise.md").write_text(
        "---\nname: concise\ndescription: Mine.\nkind: persona\n---\n\nMy words.\n", encoding="utf-8"
    )
    assert run(data_dir, "list") == 0
    listing = printed_json(capsys)
    assert [row["source"] for row in listing["skills"] if row["name"] == "concise"] == ["user"]
    assert any(row["status"] == "shadowed" for row in listing["refusals"])
