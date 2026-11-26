"""An import either lands whole or leaves nothing.

A character is a folder: the PMX, every texture it names, the readme that carries its licence, and a
profile that says what the reader made of all of it. Six of those can go wrong in six different ways —
an entry that climbs out of the directory, a zip whose fifth entry is a bomb, a name that transliterates
to nothing, a model imported twice from the same bytes — and the promise this file guards is the one the
user cannot verify by hand: *after a refusal, the library looks exactly like it did before*. So the bytes
land in a staging directory, are only renamed into place once the profile is written, and the id is a
function of the source bytes, which is what makes "already imported" answerable without reading a PMX.

The display name is kept verbatim and the id is not. That is deliberate: 耀嘉音 is what the user calls the
character, and a folder named 耀嘉音-a1b2c3d4 is a folder that will be mangled by the next tool that
touches it — a shell, a zip, a Windows codepage. The id is the ascii part; the profile carries the name.
"""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import zipfile
from pathlib import Path

import pytest

from kira.characters import (
    ALREADY_IMPORTED,
    BAD_ARCHIVE,
    CHARACTER_EXISTS,
    CHARACTER_NOT_FOUND,
    NO_PMX_IN_ARCHIVE,
    UNSAFE_ENTRY,
    CharacterError,
    character_id,
    get_character,
    import_character,
    list_characters,
    read_pmx_model,
    remove_character,
)
from kira.config import Config
from kira.store import Store
from sample_pmx import write_pmx

#: A body: over both thresholds `choose_main()` uses (20 000 vertices, 100 bones), at the size the least
#: rigged character in the donor corpus actually comes in at.
BODY = dict(
    vertex_count=26_798, face_index_count=1_020, texture_count=2, material_count=1, bone_count=297,
    morph_count=4, frame_count=2, rigid_body_count=6, constraint_count=4,
)
#: A prop: 538 vertices and 3 bones, which is the mirror from the real corpus.
MIRROR = dict(
    vertex_count=538, face_index_count=60, texture_count=1, material_count=1, bone_count=3,
    morph_count=0, frame_count=1, rigid_body_count=0, constraint_count=0,
)
TEXTURES = ("tex/颜.png", "skin.bmp")
RULES = "请勿二次配布".encode("gbk")


def archive(entries: "dict[str, bytes]") -> bytes:
    """A zip with exactly these names and bytes. `writestr` sets the utf-8 flag, so a CJK name in a
    fixture arrives the way a modern packer writes it; the GBK path is the container test's job."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as out:
        for name, payload in entries.items():
            out.writestr(name, payload)
    return buffer.getvalue()


@pytest.fixture(scope="module")
def body_pmx() -> bytes:
    return write_pmx(**BODY, name="艾莲", name_en="Ellen", textures=TEXTURES,
                     bones=tuple(f"bone{i}" for i in range(BODY["bone_count"])))


@pytest.fixture(scope="module")
def mirror_pmx() -> bytes:
    return write_pmx(**MIRROR, name="补妆镜", name_en="", textures=("tex/jing.png",),
                     bones=("root", "骨1", "骨2"))


@pytest.fixture(scope="module")
def ellen_zip(body_pmx: bytes, mirror_pmx: bytes) -> bytes:
    return archive({
        "ellen.pmx": body_pmx,
        "mirror.pmx": mirror_pmx,
        "tex/颜.png": b"\x89PNG fake",
        "tex/jing.png": b"\x89PNG fake",
        "skin.bmp": b"BM fake",
        "使用规则.txt": RULES,
    })


# --- the id -----------------------------------------------------------------------------------------

def test_the_id_is_ascii_and_carries_the_bytes_it_came_from():
    made = character_id("艾莲", "Ellen", "a1b2c3d4e5f6")
    assert made == "ellen-a1b2c3d4"
    assert made.isascii()


def test_a_name_with_no_ascii_letters_falls_back_and_stays_ascii():
    assert character_id("耀嘉音", "", "0f1e2d3c4b5a") == "model-0f1e2d3c"


def test_eight_hex_digits_are_enough_and_a_longer_slug_is_trimmed():
    assert character_id("Ellen Midosuji", "", "abc123456789")[-9:] == "-abc12345"
    assert len(character_id("x" * 90, "", "abc12345")) <= 24 + 9


# --- landing ----------------------------------------------------------------------------------------

def test_an_import_lands_the_model_its_textures_and_a_profile(tmp_path, ellen_zip):
    library = tmp_path / "characters"
    entry = import_character(library, ellen_zip, source_name="ellen.zip")

    assert entry.id == f"ellen-{_sha8(ellen_zip)}"
    folder = library / entry.id
    assert (folder / "model.pmx").is_file()
    assert (folder / "tex" / "颜.png").is_file()
    assert (folder / "skin.bmp").is_file()
    assert json.loads((folder / "profile.json").read_text("utf-8"))["id"] == entry.id
    #: The body is the one named `model.pmx`; a prop keeps the name its archive gave it.
    assert (folder / "model.pmx").read_bytes() != (folder / "mirror.pmx").read_bytes()
    assert entry.report.name == "艾莲"


def test_the_profile_keeps_the_display_name_verbatim(tmp_path, ellen_zip):
    profile = import_character(tmp_path / "characters", ellen_zip, source_name="ellen.zip").profile
    assert profile["display_name"] == "艾莲"
    assert profile["english_name"] == "Ellen"
    assert profile["main"]["name"] == "艾莲"
    assert profile["main"]["path"] == "model.pmx"
    assert profile["companions"][0]["path"] == "mirror.pmx"
    assert profile["source"]["file_name"] == "ellen.zip"
    assert profile["source"]["archive"] is True


def test_a_bare_pmx_imports_without_an_archive(tmp_path, body_pmx):
    entry = import_character(tmp_path / "characters", body_pmx, source_name="艾莲.pmx")
    profile = entry.profile
    assert (entry.directory / "model.pmx").read_bytes() == body_pmx
    assert profile["source"]["archive"] is False
    #: Nothing came with it, so nothing is present — and the profile says which references went missing.
    assert profile["main"]["texture_status"].startswith("0/2")
    assert "颜.png" in profile["main"]["texture_status"]


def test_the_license_note_travels_with_the_character(tmp_path, ellen_zip):
    profile = import_character(tmp_path / "characters", ellen_zip).profile
    assert profile["license_note"] == "请勿二次配布"


def test_every_file_the_profile_lists_is_on_disk(tmp_path, ellen_zip):
    entry = import_character(tmp_path / "characters", ellen_zip)
    listed = {item["path"] for item in entry.profile["files"]}
    on_disk = {
        p.relative_to(entry.directory).as_posix()
        for p in entry.directory.rglob("*")
        if p.is_file()
    }
    assert listed == on_disk - {"profile.json"}
    assert all(item["bytes"] > 0 for item in entry.profile["files"])


def test_a_prop_only_archive_imports_and_says_there_is_no_body(tmp_path, mirror_pmx):
    entry = import_character(tmp_path / "characters", archive({"jing.pmx": mirror_pmx}))
    assert entry.profile["main"] is None
    assert entry.profile["companions"][0]["name"] == "补妆镜"
    assert "prop" in entry.profile["reason"]
    assert not (entry.directory / "model.pmx").exists()


def test_a_model_nested_in_the_archive_keeps_its_textures_beside_it(tmp_path, body_pmx):
    data = archive({"Ellen/モデル.pmx": body_pmx, "Ellen/tex/颜.png": b"x", "Ellen/skin.bmp": b"y"})
    entry = import_character(tmp_path / "characters", data)
    folder = entry.directory
    assert (folder / "Ellen" / "model.pmx").is_file()
    #: The reference is relative to the file that names it, so it resolves only if the folder stayed.
    assert entry.profile["main"]["texture_status"] == "2/2"


# --- refusing, and what a refusal costs -------------------------------------------------------------

def test_identical_bytes_twice_is_refused_by_name(tmp_path, ellen_zip):
    library = tmp_path / "characters"
    first = import_character(library, ellen_zip)
    with pytest.raises(CharacterError) as refused:
        import_character(library, ellen_zip)
    assert refused.value.code == ALREADY_IMPORTED
    assert str(refused.value) == f"already imported: {first.id}"


def test_removal_frees_the_bytes_for_a_second_import(tmp_path, ellen_zip):
    library = tmp_path / "characters"
    import_character(library, ellen_zip)
    remove_character(library, _id_of(library, "ellen"), Store(tmp_path / "kira.db"))
    again = import_character(library, ellen_zip)
    assert again.id.startswith("ellen-")


def test_the_same_model_in_a_different_archive_is_a_different_import(tmp_path, body_pmx):
    library = tmp_path / "characters"
    one = import_character(library, archive({"ellen.pmx": body_pmx}))
    two = import_character(library, archive({"ellen.pmx": body_pmx, "extra.txt": b"x"}))
    assert one.id != two.id
    assert len(list_characters(library)) == 2


@pytest.mark.parametrize(
    ("entries", "code"),
    [
        ({"../escape.png": b"x", "ellen.pmx": b"PMX not"}, UNSAFE_ENTRY),
        ({"ellen.pmx": b"PMX not", "C:/Windows/x": b"x"}, UNSAFE_ENTRY),
        ({"readme.txt": b"no model in here"}, NO_PMX_IN_ARCHIVE),
        ({"not-a-model.bin": b"just bytes"}, BAD_ARCHIVE),
    ],
)
def test_a_refused_import_leaves_the_library_exactly_as_it_was(tmp_path, entries, code):
    library = tmp_path / "characters"
    before = sorted(p.name for p in library.iterdir()) if library.exists() else []
    data = archive(entries) if code != BAD_ARCHIVE else entries["not-a-model.bin"]
    with pytest.raises(CharacterError) as refused:
        import_character(library, data)
    assert refused.value.code == code
    after = sorted(p.name for p in library.iterdir()) if library.exists() else []
    #: Not "nothing but the staging directory" — nothing at all. A half-imported body is worse than no
    #: body, and a leftover `.staging-…` is a folder the user has to guess the meaning of.
    assert after == before


def test_an_entry_that_escapes_is_refused_by_name(tmp_path, body_pmx):
    data = archive({"../outside.png": b"x", "e.pmx": body_pmx})
    with pytest.raises(CharacterError) as refused:
        import_character(tmp_path / "characters", data)
    assert refused.value.entry == "../outside.png"


def test_a_second_bytes_set_claiming_the_same_id_is_refused(tmp_path, ellen_zip, monkeypatch):
    """The id is the slug plus eight hex digits, so two different archives can want the same folder."""
    library = tmp_path / "characters"
    first = import_character(library, ellen_zip)
    other = archive({"Ellen-mismatch.pmx": write_pmx(**BODY, name="Ellen", name_en="Ellen")})
    monkeypatch.setattr(
        "kira.characters.character_id",
        lambda name, english, digest: first.id,
    )
    with pytest.raises(CharacterError) as refused:
        import_character(library, other)
    assert refused.value.code == CHARACTER_EXISTS
    assert sorted(p.name for p in library.iterdir()) == [first.id]


# --- listing, reading, removing ---------------------------------------------------------------------

def _sha8(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:8]


def _id_of(library: Path, slug: str) -> str:
    return next(row["id"] for row in list_characters(library) if row["id"].startswith(slug))


@pytest.fixture
def two_characters(tmp_path):
    library = tmp_path / "characters"
    ellen = import_character(library, archive({
        "ellen.pmx": write_pmx(**BODY, name="艾莲", name_en="Ellen", textures=TEXTURES),
    }))
    mirror = import_character(library, archive({
        "jing.pmx": write_pmx(**MIRROR, name="补妆镜", name_en="", textures=("tex/jing.png",)),
    }))
    return library, ellen.id, mirror.id


def test_listing_reads_profiles_and_not_models(tmp_path, two_characters, monkeypatch):
    library, _, _ = two_characters
    monkeypatch.setattr(
        "kira.characters.read_pmx_model",
        lambda data: pytest.fail("listing a library must not re-walk a 20 MB model"),
    )
    rows = list_characters(library)
    assert [row["id"] for row in rows] == sorted(row["id"] for row in rows)
    assert {row["display_name"] for row in rows} == {"艾莲", "补妆镜"}
    body = next(row for row in rows if row["display_name"] == "艾莲")
    assert body["vertices"] == BODY["vertex_count"]
    assert body["texture_status"] == "0/2 — tex/颜.png absent, 1 more"
    assert body["is_character"] is True
    prop = next(row for row in rows if row["display_name"] == "补妆镜")
    assert prop["is_character"] is False


def test_a_folder_that_vanished_is_not_a_character_anymore(tmp_path, two_characters):
    library, ellen, mirror = two_characters
    shutil.rmtree(library / ellen)
    assert [row["id"] for row in list_characters(library)] == [mirror]
    with pytest.raises(CharacterError) as refused:
        get_character(library, ellen)
    assert refused.value.code == CHARACTER_NOT_FOUND


def test_get_character_returns_the_profile_that_was_written(tmp_path, two_characters):
    library, ellen, _ = two_characters
    stored = json.loads((library / ellen / "profile.json").read_text("utf-8"))
    assert get_character(library, ellen) == stored


def test_unknown_ids_are_refused_by_name(tmp_path, two_characters):
    library, _, _ = two_characters
    for call in (lambda: get_character(library, "nope-00000000"),
                 lambda: remove_character(library, "nope-00000000", Store(tmp_path / "kira.db"))):
        with pytest.raises(CharacterError) as refused:
            call()
        assert refused.value.code == CHARACTER_NOT_FOUND


def test_a_name_that_could_only_be_a_folder_is_refused(tmp_path, two_characters):
    library, _, _ = two_characters
    with pytest.raises(CharacterError) as refused:
        get_character(library, "../..")
    assert refused.value.code == CHARACTER_NOT_FOUND


def test_removal_deletes_the_directory(tmp_path, two_characters):
    library, ellen, mirror = two_characters
    removed = remove_character(library, ellen, Store(tmp_path / "kira.db"))
    assert removed["display_name"] == "艾莲"
    assert not (library / ellen).exists()
    assert (library / mirror).is_dir()


def test_removal_clears_the_active_pick_when_it_was_the_active_one(tmp_path, two_characters):
    library, ellen, mirror = two_characters
    store = Store(tmp_path / "kira.db")
    store.conn.execute("INSERT INTO meta(key, value, updated_at) VALUES('avatar.active', ?, 1.0)",
                       (json.dumps(ellen),))
    store.conn.commit()
    remove_character(library, ellen, store)
    assert store.conn.execute("SELECT value FROM meta WHERE key='avatar.active'").fetchone() is None


def test_removal_leaves_an_unrelated_active_pick_alone(tmp_path, two_characters):
    library, ellen, mirror = two_characters
    store = Store(tmp_path / "kira.db")
    store.conn.execute("INSERT INTO meta(key, value, updated_at) VALUES('avatar.active', ?, 1.0)",
                       (json.dumps(mirror),))
    store.conn.commit()
    remove_character(library, ellen, store)
    row = store.conn.execute("SELECT value FROM meta WHERE key='avatar.active'").fetchone()
    assert json.loads(row["value"]) == mirror


# --- where the library lives ------------------------------------------------------------------------

def test_the_data_directory_names_the_characters_folder(tmp_path):
    config = Config(data_dir=tmp_path)
    assert config.characters_dir == tmp_path / "characters"
    #: Not inside the workspace: a character is not a file the agent may edit, and it is 45 MB apiece.
    assert config.characters_dir != config.workspace_path


def test_an_import_does_not_report_a_model_it_cannot_walk(tmp_path, body_pmx):
    """The profile is the reader's own answer, so the bytes on disk have to walk to the same counts."""
    entry = import_character(tmp_path / "characters", body_pmx)
    on_disk = read_pmx_model((entry.directory / "model.pmx").read_bytes())
    assert on_disk.counts["vertex_count"] == entry.profile["main"]["counts"]["vertex_count"]
    assert on_disk.counts["bone_count"] == entry.profile["main"]["counts"]["bone_count"]
