"""`kira-engine characters` — the library, reachable without a browser.

The CLI and the routes call the same functions in `kira.characters`, which is the whole reason this file
exists: an import that only the dashboard can do is an import whose rules live in the dashboard. A user
sitting at the machine that owns the model folder should be able to add, read, choose and delete a
character from a terminal, and what that terminal prints has to be what the engine then loads.

Two shapes are checked hard. Stdout stays parseable JSON on success and nothing but a `[kira]` line on
stderr after a refusal — so `... | jq` works and a failure never feeds a half-object into a pipe. And the
destructive verb asks first: `remove` deletes 45 MB of someone's licensed download, which is not a thing a
command line does on a typo.
"""

from __future__ import annotations

import io
import json
import zipfile

import pytest

from kira.__main__ import main
from kira.characters import get_active, list_characters
from kira.config import load_config, write_sample_config
from kira.store import Store
from sample_pmx import write_pmx

BODY = dict(
    vertex_count=26_798, face_index_count=1_020, texture_count=1, material_count=1, bone_count=297,
    morph_count=2, frame_count=2, rigid_body_count=2, constraint_count=2,
)
MIRROR = dict(
    vertex_count=538, face_index_count=60, texture_count=1, material_count=1, bone_count=3,
    morph_count=0, frame_count=1, rigid_body_count=0, constraint_count=0,
)


def archive(entries: "dict[str, bytes]") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as out:
        for name, data in entries.items():
            out.writestr(name, data)
    return buffer.getvalue()


@pytest.fixture
def data_dir(tmp_path):
    write_sample_config(tmp_path)
    return tmp_path


def run(data_dir, *argv: str) -> int:
    return main(["characters", *argv, "--data-dir", str(data_dir), "--backend", "memory"])


def printed_json(capsys):
    return json.loads(capsys.readouterr().out)


def library(data_dir):
    """The directory the engine itself would read, not a path this test guessed at."""
    return load_config(data_dir).characters_dir


def database(data_dir) -> Store:
    return Store(load_config(data_dir).db_path)


@pytest.fixture
def ellen_zip(tmp_path):
    path = tmp_path / "ellen.zip"
    path.write_bytes(archive({
        "Ellen.pmx": write_pmx(**BODY, name="艾莲", name_en="Ellen"),
        "Ellen/tex/颜.png": b"png",
        "补妆镜.pmx": write_pmx(**MIRROR, name="补妆镜", name_en=""),
    }))
    return path


@pytest.fixture
def ellen(data_dir, ellen_zip, capsys):
    """One character already in the library, added by the verb under test."""
    assert run(data_dir, "import", str(ellen_zip)) == 0
    return printed_json(capsys)


# --- import ------------------------------------------------------------------------------------------

def test_an_import_lands_where_the_engine_will_look_for_it(data_dir, ellen):
    #: The folder the CLI wrote to is the one `characters_dir` names — the routes in T7 read this same
    #: path, so a CLI that used its own guess would give the dashboard an empty library.
    assert ellen["id"].startswith("ellen-")
    assert (library(data_dir) / ellen["id"] / "profile.json").is_file()
    assert (library(data_dir) / ellen["id"] / "model.pmx").is_file()


def test_the_source_name_the_user_typed_travels_into_the_profile(data_dir, ellen):
    profile = json.loads((library(data_dir) / ellen["id"] / "profile.json").read_text(encoding="utf-8"))
    assert profile["source"]["file_name"] == "ellen.zip"


def test_a_bare_pmx_imports_the_same_way_an_archive_does(data_dir, tmp_path, capsys):
    path = tmp_path / "ellen.pmx"
    path.write_bytes(write_pmx(**BODY, name="艾莲", name_en="Ellen"))
    assert run(data_dir, "import", str(path)) == 0
    assert printed_json(capsys)["id"].startswith("ellen-")


def test_the_same_file_twice_answers_already_imported_and_names_the_id(data_dir, ellen_zip, ellen, capsys):
    capsys.readouterr()
    assert run(data_dir, "import", str(ellen_zip)) == 1
    err = capsys.readouterr().err
    assert "already_imported" in err and ellen["id"] in err
    assert len(list_characters(library(data_dir))) == 1


def test_bytes_that_are_not_a_model_are_refused_naming_the_path(data_dir, tmp_path, capsys):
    path = tmp_path / "notes.txt"
    path.write_text("not a model", encoding="utf-8")
    assert run(data_dir, "import", str(path)) == 1
    assert "bad_archive" in capsys.readouterr().err
    assert list_characters(library(data_dir)) == ()


def test_a_path_that_is_not_there_is_a_usage_error_not_a_traceback(data_dir, tmp_path, capsys):
    assert run(data_dir, "import", str(tmp_path / "nope.zip")) == 2
    assert "no file" in capsys.readouterr().err


# --- list and show ------------------------------------------------------------------------------------

def test_list_prints_every_row_and_who_is_on_stage(data_dir, ellen, capsys):
    capsys.readouterr()
    assert run(data_dir, "list") == 0
    listing = printed_json(capsys)
    assert listing["active"] is None
    assert [row["id"] for row in listing["characters"]] == [ellen["id"]]
    #: A row is the same object the routes will serialise: the CLI invents no second shape.
    assert listing["characters"][0]["display_name"] == "艾莲"


def test_the_pick_shows_up_in_the_list_next_to_the_rows(data_dir, ellen, capsys):
    run(data_dir, "use", ellen["id"])
    capsys.readouterr()
    assert run(data_dir, "list") == 0
    assert printed_json(capsys) == {"active": ellen["id"], "characters": [ellen]}


def test_an_empty_library_lists_empty_rather_than_failing(data_dir, capsys):
    assert run(data_dir, "list") == 0
    assert printed_json(capsys) == {"active": None, "characters": []}


def test_show_prints_the_profile_the_import_wrote(data_dir, ellen, capsys):
    capsys.readouterr()
    assert run(data_dir, "show", ellen["id"]) == 0
    profile = printed_json(capsys)
    assert profile["id"] == ellen["id"]
    assert profile["main"]["vertices"] == 26_798
    assert len(profile["companions"]) == 1
    assert any(entry["path"] == "model.pmx" for entry in profile["files"])


def test_show_of_an_id_the_library_does_not_have_is_refused(data_dir, capsys):
    assert run(data_dir, "show", "nobody-00000000") == 1
    assert "character_not_found" in capsys.readouterr().err


# --- use ----------------------------------------------------------------------------------------------

def test_use_puts_a_character_on_stage_and_off_flag_takes_it_off(data_dir, ellen, capsys):
    capsys.readouterr()
    assert run(data_dir, "use", ellen["id"]) == 0
    assert get_active(library(data_dir), database(data_dir)) == ellen["id"]
    assert printed_json(capsys) == {"active": ellen["id"]}
    assert run(data_dir, "use", "--off") == 0
    assert get_active(library(data_dir), database(data_dir)) is None


def test_the_pick_the_cli_writes_is_the_row_the_engine_reads(data_dir, ellen, capsys):
    """The setting lives in `meta` under `avatar.active` — the same key `set_active` owns.

    A CLI that kept its own note about who is on stage would show the dashboard a different character than
    the one it renders.
    """
    capsys.readouterr()
    assert run(data_dir, "use", ellen["id"]) == 0
    row = database(data_dir).conn.execute("SELECT value FROM meta WHERE key='avatar.active'").fetchone()
    assert json.loads(row["value"]) == ellen["id"]


def test_using_a_character_that_is_not_in_the_library_is_refused_and_changes_nothing(data_dir, ellen, capsys):
    run(data_dir, "use", ellen["id"])
    capsys.readouterr()
    assert run(data_dir, "use", "nobody-00000000") == 1
    assert "character_not_found" in capsys.readouterr().err
    assert get_active(library(data_dir), database(data_dir)) == ellen["id"]


def test_use_needs_an_id_or_the_off_flag(data_dir, capsys):
    assert run(data_dir, "use") == 2
    assert "needs" in capsys.readouterr().err


# --- remove -------------------------------------------------------------------------------------------

def test_remove_refuses_without_yes_and_deletes_the_folder_with_it(data_dir, ellen, capsys):
    capsys.readouterr()
    assert run(data_dir, "remove", ellen["id"]) == 2
    assert (library(data_dir) / ellen["id"]).is_dir()
    assert run(data_dir, "remove", ellen["id"], "--yes") == 0
    assert not (library(data_dir) / ellen["id"]).exists()
    assert list_characters(library(data_dir)) == ()
    assert "removed" in capsys.readouterr().out


def test_removing_the_character_on_stage_takes_it_off_stage_in_the_same_call(data_dir, ellen, capsys):
    run(data_dir, "use", ellen["id"])
    capsys.readouterr()
    assert run(data_dir, "remove", ellen["id"], "--yes") == 0
    store = database(data_dir)
    assert get_active(library(data_dir), store) is None
    #: The refusal a user would otherwise meet on the next open: a stage aimed at a folder that is gone.
    assert store.conn.execute("SELECT 1 FROM meta WHERE key='avatar.active'").fetchone() is None


def test_removing_a_character_that_is_not_there_is_refused(data_dir, capsys):
    assert run(data_dir, "remove", "nobody-00000000", "--yes") == 1
    assert "character_not_found" in capsys.readouterr().err
