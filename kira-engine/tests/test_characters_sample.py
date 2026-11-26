"""The character on stage, and a proof that runs on the real archives when they are on this disk.

`set_active` is one string in the settings table, so the interesting part is what it refuses: the stage
cannot be pointed at a character the library does not have, because that is a broken screen the user finds
out about by opening it. And the real corpus is the only place the numbers in `characters.py` came from, so
this file holds the test that checks them — off by default, because the donor folder is not in the repo and
must never be, and on with `KIRA_CHAR_SAMPLE=1` for anyone sitting at the machine that measured it.

The gated table is not a smoke test. It asserts the split that set the body thresholds, the two facts that
proved the reader was reading the right offsets (Ellen at 29 287 vertices, Jane Doe naming a `hair.bmp` its
archive never carried), and the four files whose sections behind the morph table only a search can reach —
which is where the certifying view says *no* and the reporting view says *here is what I found instead*.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from kira.characters import (
    ACTIVE_KEY,
    PMX_TRUNCATED,
    CharacterError,
    describe,
    get_active,
    get_character,
    import_character,
    list_characters,
    read_pmx_head,
    read_pmx_model,
    remove_character,
    set_active,
)
from kira.store import Store
from sample_pmx import write_pmx

#: The donor folder. Not in the repo, and not copied into it: a licensed model from a third party belongs
#: to the machine it was downloaded to. Nothing below the active-pick tests runs without both the flag and
#: the folder, so a clone of this repo on another machine sees them skip and stays green.
SAMPLE_DIR = Path("D:/1. Ai/project-kira (kimi)/Ai agents/MYRAA/models for MYRAA")
requires_sample = pytest.mark.skipif(
    not (os.environ.get("KIRA_CHAR_SAMPLE") == "1" and SAMPLE_DIR.is_dir()),
    reason="needs the donor folder; set KIRA_CHAR_SAMPLE=1 on the machine that has it",
)

BODY = dict(
    vertex_count=26_798, face_index_count=1_020, texture_count=1, material_count=1, bone_count=297,
    morph_count=2, frame_count=2, rigid_body_count=2, constraint_count=2,
)
MIRROR = dict(
    vertex_count=538, face_index_count=60, texture_count=1, material_count=1, bone_count=3,
    morph_count=0, frame_count=1, rigid_body_count=0, constraint_count=0,
)


@pytest.fixture
def library(tmp_path):
    directory = tmp_path / "characters"
    ellen = import_character(
        directory, write_pmx(**BODY, name="艾莲", name_en="Ellen", textures=("tex/颜.png",))
    )
    mirror = import_character(
        directory, write_pmx(**MIRROR, name="补妆镜", name_en="", textures=("tex/jing.png",))
    )
    store = Store(tmp_path / "kira.db")
    return directory, store, ellen.id, mirror.id


# --- the active pick --------------------------------------------------------------------------------

def test_nothing_is_on_stage_until_someone_picks_it(tmp_path):
    assert get_active(tmp_path / "characters", Store(tmp_path / "kira.db")) is None


def test_a_pick_is_the_id_that_was_set_and_reads_back_after_a_reopen(library, tmp_path):
    directory, store, ellen, _ = library
    assert set_active(directory, ellen, store) == ellen
    assert get_active(directory, Store(tmp_path / "kira.db")) == ellen


def test_the_pick_lives_under_the_key_removal_clears(library):
    """`set_active` and `remove_character` have to agree on one key or a deletion leaves a pointer."""
    directory, store, ellen, _ = library
    set_active(directory, ellen, store)
    row = store.conn.execute("SELECT key, value FROM meta WHERE key=?", (ACTIVE_KEY,)).fetchone()
    assert row["key"] == "avatar.active" and json.loads(row["value"]) == ellen
    remove_character(directory, ellen, store)
    assert get_active(directory, store) is None


def test_picking_a_character_the_library_does_not_have_is_refused(library):
    directory, store, ellen, _ = library
    set_active(directory, ellen, store)
    with pytest.raises(CharacterError) as refused:
        set_active(directory, "nobody-00000000", store)
    assert refused.value.code == "character_not_found"
    #: The failed call changed nothing: a typo must not put the stage out of work.
    assert get_active(directory, store) == ellen


@pytest.mark.parametrize("value", ["../../windows", "", "a" * 300])
def test_a_value_that_cannot_be_an_id_is_refused_not_crashed(library, value):
    directory, store, ellen, _ = library
    set_active(directory, ellen, store)
    with pytest.raises(CharacterError):
        set_active(directory, value, store)
    assert get_active(directory, store) == ellen


def test_null_clears_the_pick_without_touching_the_library(library):
    directory, store, ellen, mirror = library
    set_active(directory, ellen, store)
    assert set_active(directory, None, store) is None
    assert get_active(directory, store) is None
    assert [row["id"] for row in list_characters(directory)] == sorted([ellen, mirror])


def test_a_pick_points_at_a_character_that_can_be_read_back(library):
    directory, store, ellen, _ = library
    set_active(directory, ellen, store)
    profile = get_character(directory, get_active(directory, store))
    assert profile["display_name"] == "艾莲"


def test_re_picking_the_same_character_is_not_a_second_answer(library):
    directory, store, ellen, mirror = library
    assert set_active(directory, ellen, store) == ellen
    assert set_active(directory, mirror, store) == mirror
    assert set_active(directory, ellen, store) == ellen
    rows = store.conn.execute("SELECT value FROM meta WHERE key=?", (ACTIVE_KEY,)).fetchall()
    assert [json.loads(row["value"]) for row in rows] == [ellen]


def test_a_pointer_at_a_folder_that_is_gone_reads_as_nothing(tmp_path):
    """A read does not delete state, but it does not hand back a lie either.

    The normal path clears the pointer when the character goes (T4), so this is the out-of-band one: a
    folder moved by hand, a library restored from an older copy. Every caller of `get_active` is about to
    try to load those bytes, and an id that cannot be loaded is not a character on stage.
    """
    directory = tmp_path / "characters"
    store = Store(tmp_path / "kira.db")
    store.conn.execute(
        "INSERT INTO meta(key, value, updated_at) VALUES(?,?,?)",
        (ACTIVE_KEY, json.dumps("ghost-12345678"), 1.0),
    )
    store.conn.commit()
    assert get_active(directory, store) is None
    #: Left in place on purpose: the row is the evidence, and the next real write replaces it.
    row = store.conn.execute("SELECT value FROM meta WHERE key=?", (ACTIVE_KEY,)).fetchone()
    assert json.loads(row["value"]) == "ghost-12345678"


# --- the donor corpus, on the machine that has it ---------------------------------------------------

@pytest.fixture(scope="module")
def donor_directory(tmp_path_factory):
    directory = tmp_path_factory.mktemp("kira-donor-library")
    for archive in sorted(SAMPLE_DIR.glob("*.zip")):
        import_character(directory, archive.read_bytes(), source_name=archive.name)
    return directory


@requires_sample
def test_the_ten_archives_import_and_every_one_of_them_has_a_body(donor_directory):
    rows = list_characters(donor_directory)
    assert len(rows) == 10
    #: Ten archives, ten bodies: each archive's biggest rigged model is the character, and its weapons
    #: and props come along as companions of the same stage. The twenty models split eleven/nine by the
    #: body test — one archive carries two rigged models, and the second is a companion here.
    assert all(row["is_character"] for row in rows)
    assert sum(row["companion_count"] for row in rows) == 10


@requires_sample
def test_ellen_is_the_twenty_nine_thousand_vertex_character_the_corpus_says_she_is(donor_directory):
    ellen = next(row for row in list_characters(donor_directory) if row["id"].startswith("ellen"))
    profile = get_character(donor_directory, ellen["id"])
    assert profile["main"]["vertices"] == 29_287
    assert profile["main"]["bones"] == 487
    assert profile["main"]["counts"]["morph_count"] == 59
    assert profile["main"]["counts"]["rigid_body_count"] == 317


@requires_sample
def test_the_character_that_names_a_texture_its_archive_does_not_carry_is_reported(donor_directory):
    """`hair.bmp` is in the material table of 简 and in no entry of its archive.

    This is the measurement that decided `describe()` takes a directory: a loader that reads only the PMX
    finds a model with eight textures, draws seven, and says nothing.
    """
    rows = list_characters(donor_directory)
    absent = [row for row in rows if "absent" in (row["texture_status"] or "")]
    assert [row["texture_status"] for row in absent] == ["7/8 — hair.bmp absent"]
    profile = get_character(donor_directory, absent[0]["id"])
    assert profile["main"]["missing_textures"] == ["hair.bmp"]


@requires_sample
def test_the_rules_that_came_with_the_models_are_kept_with_them(donor_directory):
    rows = list_characters(donor_directory)
    noted = [row for row in rows if row["license_note"]]
    #: The 星临者 maid-skin archive ships a readme with no redistribution line in it, so its character
    #: carries no note — and that is the honest answer, not a missing one.
    assert len(noted) == 9
    assert all("二次" in row["license_note"] or "原创" in row["license_note"] for row in noted)


@requires_sample
def test_the_four_files_a_stride_cannot_reach_are_searched_and_said(donor_directory):
    """Four archives have a morph section wider than either stride the format measures.

    The reporting view walks them and finds the one offset in a megabyte whose remaining sections land
    exactly on the end of the file; the certifying view refuses them, because a boundary found by search is
    not a boundary the file stated. Both answers are asserted here, on the same bytes.
    """
    searched = []
    certified = []
    for path in sorted(donor_directory.rglob("*.pmx")):
        data = path.read_bytes()
        model = read_pmx_model(data)
        if model.resynced_from is None:
            certified.append(path)
            continue
        searched.append(path)
        with pytest.raises(CharacterError) as refused:
            read_pmx_head(data)
        assert refused.value.code == PMX_TRUNCATED
        report = describe(model, path.parent, file_name=path.name)
        assert report.counts["morph_count"] > 0
        assert not report.morph_names
        assert report.trailing_bytes == 0
    assert len(searched) == 4
    assert len(certified) == 16


@requires_sample
def test_every_donor_texture_reference_lands_where_the_model_looks(donor_directory):
    """A reference reported as resolved is a file on disk, at the path the model would ask for."""
    unresolved = []
    checked = 0
    for row in list_characters(donor_directory):
        profile = get_character(donor_directory, row["id"])
        for model in filter(None, [profile["main"], *profile["companions"]]):
            #: A texture path is relative to the file that names it, and the model's own path is relative
            #: to the character folder — so the base is the character folder plus wherever in it this
            #: model sits. Dropping either half reports a real file as missing.
            folder = donor_directory / profile["id"] / Path(model["path"]).parent
            for texture in model["textures"]:
                if not texture["exists"]:
                    continue
                checked += 1
                if not (folder / texture["relative"]).is_file():
                    unresolved.append((row["id"], texture["relative"]))
    #: The count guards against a vacuous pass: twenty models with no textures read just as clean.
    assert checked > 100
    assert unresolved == []


@requires_sample
def test_a_round_of_import_and_removal_leaves_no_trace(tmp_path, donor_bytes):
    """Real archives in, every character out, and nothing orphaned behind.

    The pointer is cleared in the same call as the delete, so after the last removal the stage is empty
    rather than aimed at a folder that used to exist.
    """
    directory = tmp_path / "library"
    store = Store(tmp_path / "round.db")
    ids = []
    for name, data in donor_bytes:
        ids.append(import_character(directory, data, source_name=name).id)
    for character_id in ids:
        set_active(directory, character_id, store)
        remove_character(directory, character_id, store)
        assert get_active(directory, store) is None
    assert list_characters(directory) == ()
    assert [p.name for p in directory.iterdir()] == []


@pytest.fixture(scope="module")
def donor_bytes():
    return [(archive.name, archive.read_bytes()) for archive in sorted(SAMPLE_DIR.glob("*.zip"))]
