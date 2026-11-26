from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from kira.skills import (
    MAX_SKILL_BYTES,
    PACK_FILE,
    install_pack,
    load_skills,
)

DONOR = "---\nname: {name}\ndescription: {description}\n---\n\nStep one: {body}\n"
MIT = "MIT License\n\nCopyright (c) 2026 Affaan Mustafa\n"


def donor(name: str, description: str = "Do the thing well.", body: str = "the doing") -> str:
    return DONOR.format(name=name, description=description, body=body)


def make_zip(entries: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for path, text in entries.items():
            archive.writestr(path, text)
    return buffer.getvalue()


def write_zip(target: Path, entries: dict[str, str]) -> Path:
    target.write_bytes(make_zip(entries))
    return target


# --- what an import writes down -------------------------------------------------------------------


def test_a_skill_folder_is_installed_with_kira_fields(tmp_path: Path):
    pack = tmp_path / "pack"
    source = tmp_path / "source"
    (source / "skills" / "tdd").mkdir(parents=True)
    (source / "skills" / "tdd" / PACK_FILE).write_text(donor("tdd"), encoding="utf-8")

    report = install_pack(pack, source)
    assert report["counts"] == {"installed": 1}
    written = (pack / "tdd" / PACK_FILE).read_text(encoding="utf-8")
    assert "kind: method" in written
    assert "Step one: the doing" in written
    # Packs declare no kind, and Kira cannot guess one from nothing: a persona is a voice the user
    # pins, and a procedure inside `skills/` is neither.
    assert "description: Do the thing well." in written


def test_an_installed_pack_is_readable_by_the_loader_it_was_written_for(tmp_path: Path):
    pack = tmp_path / "pack"
    source = tmp_path / "source"
    for name in ("tdd", "api-design"):
        (source / "skills" / name).mkdir(parents=True)
        (source / "skills" / name / PACK_FILE).write_text(donor(name), encoding="utf-8")
    install_pack(pack, source)

    skills, statuses = load_skills(None, pack)
    assert [skill.name for skill in skills] == ["api-design", "tdd"]
    assert [skill.kind for skill in skills] == ["method", "method"]
    assert [skill.source for skill in skills] == ["user", "user"]
    assert all(status.status == "loaded" for status in statuses)


def test_a_declared_kind_survives_and_extra_fields_come_with_it(tmp_path: Path):
    pack = tmp_path / "pack"
    source = tmp_path / "source"
    folder = source / "skills" / "poet"
    folder.mkdir(parents=True)
    (folder / PACK_FILE).write_text(
        "---\nname: poet\ndescription: Write in verse.\nkind: persona\nlicense: MIT\n"
        "homepage: https://example.test/poet\n---\n\nRhyme well.\n",
        encoding="utf-8",
    )
    install_pack(pack, source)
    skills, _ = load_skills(None, pack)
    assert skills[0].kind == "persona"
    assert "license: MIT" in (pack / "poet" / PACK_FILE).read_text(encoding="utf-8")


def test_a_description_with_a_colon_is_written_as_yaml_not_concatenated(tmp_path: Path):
    pack = tmp_path / "pack"
    source = tmp_path / "source"
    folder = source / "skills" / "narrow"
    folder.mkdir(parents=True)
    # A pack writes its one-line summary as a block scalar, because the sentence has a colon in it.
    (folder / PACK_FILE).write_text(
        "---\nname: narrow\ndescription: >-\n  Two ways in: pick one, then prove it.\n---\n\nNarrow it down.\n",
        encoding="utf-8",
    )
    report = install_pack(pack, source)
    assert report["counts"] == {"installed": 1}
    skills, _ = load_skills(None, pack)
    assert skills[0].description == "Two ways in: pick one, then prove it."


def test_an_unparseable_frontmatter_is_refused_rather_than_guessed(tmp_path: Path):
    pack = tmp_path / "pack"
    source = tmp_path / "source"
    folder = source / "skills" / "sloppy"
    folder.mkdir(parents=True)
    (folder / PACK_FILE).write_text(donor("sloppy", description="Two ways in: pick one."), encoding="utf-8")
    report = install_pack(pack, source)
    assert report["rows"][0]["status"] == "skipped"
    assert "YAML" in report["rows"][0]["reason"]
    assert not pack.exists() or list(pack.iterdir()) == []


def test_non_ascii_survives_the_round_trip(tmp_path: Path):
    pack = tmp_path / "pack"
    source = tmp_path / "source"
    folder = source / "skills" / "hanzi"
    folder.mkdir(parents=True)
    (folder / PACK_FILE).write_text(
        donor("hanzi", description="阅读中文文档并核对来源。", body="先读，再引用。"), encoding="utf-8"
    )
    install_pack(pack, source)
    skills, _ = load_skills(None, pack)
    assert skills[0].description == "阅读中文文档并核对来源。"
    assert "先读，再引用。" in skills[0].body


# --- what an import refuses ----------------------------------------------------------------------


def test_only_the_pack_s_own_copy_is_installed_not_the_other_harnesses(tmp_path: Path):
    target = tmp_path / "pack"
    zip_path = write_zip(
        tmp_path / "ECC.zip",
        {
            "ECC-main/skills/tdd/SKILL.md": donor("tdd"),
            "ECC-main/.agents/skills/tdd/SKILL.md": donor("tdd", body="a second copy"),
            "ECC-main/.claude/skills/tdd/SKILL.md": donor("tdd", body="a third copy"),
            "ECC-main/docs/zh-CN/skills/tdd/SKILL.md": donor("tdd", body="a translation"),
            "ECC-main/skills/tdd/scripts/run.py": "print('never copied')",
        },
    )
    report = install_pack(target, zip_path)
    assert report["counts"]["installed"] == 1
    installed = list(target.iterdir())
    assert [path.name for path in installed] == ["tdd"]
    skills, _ = load_skills(None, target)
    assert skills[0].body == "Step one: the doing"


def test_an_oversized_skill_is_refused_before_it_is_decompressed(tmp_path: Path):
    target = tmp_path / "pack"
    zip_path = write_zip(
        tmp_path / "big.zip",
        {
            "ECC-main/skills/long/SKILL.md": donor("long", body="x" * (MAX_SKILL_BYTES + 1)),
            "ECC-main/skills/fits/SKILL.md": donor("fits"),
        },
    )
    report = install_pack(target, zip_path)
    rows = {row["name"]: row for row in report["rows"]}
    assert rows["long"]["status"] == "skipped"
    assert "16384" in rows["long"]["reason"]
    assert not (target / "long").exists()
    assert (target / "fits" / PACK_FILE).exists()


def test_a_name_that_is_not_a_kira_skill_name_never_reaches_the_filesystem(tmp_path: Path):
    target = tmp_path / "pack"
    zip_path = write_zip(
        tmp_path / "evil.zip",
        {
            "ECC-main/skills/Bad_Name/SKILL.md": donor("Bad_Name"),
        },
    )
    report = install_pack(target, zip_path)
    assert report["rows"][0]["status"] == "skipped"
    assert report["counts"] == {"skipped": 1}


def test_a_traversal_in_the_folder_name_cannot_write_outside_the_pack(tmp_path: Path):
    target = tmp_path / "pack"
    zip_path = write_zip(
        tmp_path / "slip.zip",
        {
            # Never recognised as a skill folder at all, because `skills` is no longer two parts up.
            "ECC-main/skills/../../evil/SKILL.md": donor("evil"),
            # Recognised, then refused on the name — and the name is the only part of the written path
            # that came from the archive, so refusing it is the whole guard.
            "ECC-main/skills/..x/SKILL.md": donor("dot"),
            "ECC-main/skills/Bad Name/SKILL.md": donor("space"),
        },
    )
    report = install_pack(target, zip_path)
    assert report["counts"] == {"skipped": 2}
    assert not (tmp_path / "evil").exists()
    assert not target.exists() or list(target.iterdir()) == []


def test_a_broken_frontmatter_is_a_row_with_a_reason_not_a_crash(tmp_path: Path):
    target = tmp_path / "pack"
    source = tmp_path / "source"
    for name in ("nope", "sourced"):
        (source / "skills" / name).mkdir(parents=True)
    (source / "skills" / "nope" / PACK_FILE).write_text("no frontmatter here", encoding="utf-8")
    (source / "skills" / "sourced" / PACK_FILE).write_text(donor("sourced"), encoding="utf-8")
    report = install_pack(target, source)
    rows = {row["name"]: row for row in report["rows"]}
    assert rows["nope"]["status"] == "skipped"
    assert "frontmatter" in rows["nope"]["reason"]
    assert rows["sourced"]["status"] == "installed"


def test_a_declared_kind_that_is_not_a_kind_is_refused(tmp_path: Path):
    target = tmp_path / "pack"
    source = tmp_path / "source"
    folder = source / "skills" / "spell"
    folder.mkdir(parents=True)
    (folder / PACK_FILE).write_text(
        "---\nname: spell\ndescription: Casts.\nkind: spellcraft\n---\n\nWords.\n", encoding="utf-8"
    )
    report = install_pack(target, source)
    assert report["rows"][0]["status"] == "skipped"
    assert "kind" in report["rows"][0]["reason"]


def test_a_source_with_no_skill_folders_is_a_named_refusal(tmp_path: Path):
    empty = tmp_path / "empty"
    (empty / "skills").mkdir(parents=True)
    with pytest.raises(ValueError, match="no skills"):
        install_pack(tmp_path / "pack", empty)

    other = tmp_path / "notes.txt"
    other.write_text("not an archive", encoding="utf-8")
    with pytest.raises(ValueError, match="not a .zip"):
        install_pack(tmp_path / "pack", other)

    with pytest.raises(ValueError, match="nothing at"):
        install_pack(tmp_path / "pack", tmp_path / "nowhere")


# --- re-running the same command -----------------------------------------------------------------


def test_a_second_run_reports_unchanged_and_edits_are_left_alone(tmp_path: Path):
    target = tmp_path / "pack"
    source = tmp_path / "source"
    folder = source / "skills" / "tdd"
    folder.mkdir(parents=True)
    (folder / PACK_FILE).write_text(donor("tdd"), encoding="utf-8")

    install_pack(target, source)
    assert install_pack(target, source)["counts"] == {"unchanged": 1}

    installed = target / "tdd" / PACK_FILE
    installed.write_text(installed.read_text(encoding="utf-8") + "\nMy own note.\n", encoding="utf-8")
    report = install_pack(target, source)
    assert report["counts"] == {"skipped": 1}
    assert "--force" in report["rows"][0]["reason"]
    assert "My own note." in installed.read_text(encoding="utf-8")

    assert install_pack(target, source, force=True)["counts"] == {"installed": 1}
    assert "My own note." not in installed.read_text(encoding="utf-8")


def test_a_dry_run_writes_nothing(tmp_path: Path):
    target = tmp_path / "pack"
    source = tmp_path / "source"
    folder = source / "skills" / "tdd"
    folder.mkdir(parents=True)
    (folder / PACK_FILE).write_text(donor("tdd"), encoding="utf-8")
    report = install_pack(target, source, dry_run=True)
    assert report["counts"] == {"installed": 1}
    assert report["dry_run"] is True
    assert not target.exists()


# --- attribution -------------------------------------------------------------------------------


def test_the_licence_travels_with_the_copy(tmp_path: Path):
    target = tmp_path / "pack"
    zip_path = write_zip(
        tmp_path / "lic.zip",
        {
            "ECC-main/LICENSE": MIT,
            "ECC-main/skills/tdd/SKILL.md": donor("tdd"),
            "ECC-main/skills/tdd/LICENSE": "CC-BY-4.0 for this skill only.\n",
            "ECC-main/skills/taste/scripts/LICENSE": "not a top-level notice\n",
        },
    )
    report = install_pack(target, zip_path)
    assert (target / "LICENSE").read_text(encoding="utf-8") == MIT
    assert report["licence"] == "written"
    # The skill's own notice is kept beside it; one buried in `scripts/` is not a notice for the skill.
    assert (target / "tdd" / "LICENSE").read_text(encoding="utf-8").startswith("CC-BY-4.0")
    assert not (target / "tdd" / "scripts").exists()

    again = install_pack(target, zip_path, force=True)
    assert again["licence"] == "already there"


def test_a_dry_run_says_the_licence_is_only_planned(tmp_path: Path):
    """"already there" is a statement about the disk, and a dry run has not touched it.

    A user who read that line and walked away would have no attribution on a pack they believed credited.
    """
    target = tmp_path / "pack"
    zip_path = write_zip(
        tmp_path / "lic.zip",
        {"ECC-main/LICENSE": MIT, "ECC-main/skills/tdd/SKILL.md": donor("tdd")},
    )
    report = install_pack(target, zip_path, dry_run=True)
    assert report["licence"] == "would write"
    assert not (target / "LICENSE").exists()


def test_a_skill_that_needs_sidecar_files_says_so(tmp_path: Path):
    target = tmp_path / "pack"
    source = tmp_path / "source"
    folder = source / "skills" / "deep"
    (folder / "references").mkdir(parents=True)
    (folder / PACK_FILE).write_text(donor("deep"), encoding="utf-8")
    (folder / "references" / "more.md").write_text("the rest", encoding="utf-8")
    (folder / "check.py").write_text("print(1)", encoding="utf-8")
    report = install_pack(target, source)
    reason = report["rows"][0]["reason"]
    assert "check.py" in reason
    assert "Kira does not load" in reason
    assert not (target / "deep" / "check.py").exists()
