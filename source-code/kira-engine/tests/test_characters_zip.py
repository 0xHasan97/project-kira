"""Reading an archive the way the donor corpus actually ships one.

Measured 2026-10-31 against the ten MMD archives in MYRAA's models folder: nine carry an Info-ZIP
Unicode Path extra field on every non-ascii name, the tenth sets the utf-8 flag, and `zipfile` reads
all ten correctly *because those writers were polite*. None of that is the format's promise. An
archive may equally store `颜` as two GBK bytes with no flag and no extra field — `zipfile` then hands
back `╩∩`, the importer writes a file whose name matches nothing the model references, and the
character arrives with no textures and no error. So the reading is ours.

The same measurement sets the walls: the largest archive here has 45 entries, its biggest single entry
is 29.4 MB and the widest expansion is 71.5 MB, so the caps in `characters.py` (500 entries, 64 MB an
entry, 400 MB expanded, 200 MB archive) are headroom, not a budget someone will hit on Tuesday.
"""

from __future__ import annotations

import io
import zipfile

import pytest

from kira import characters
from kira.characters import CharacterError, extract_zip
from sample_zip import STORED, SYMLINK_ATTR, Item, gbk, write_zip


def read_entry(dest, name: str) -> bytes:
    return (dest / name).read_bytes()


def test_a_gbk_name_survives_as_the_name_the_writer_meant(tmp_path):
    dest = tmp_path / "staging"
    data = write_zip([Item(name=gbk("颜.tga"), data=b"\x00\x01\x02\x03")])

    files = extract_zip(data, dest)

    assert [f.name for f in files] == ["颜.tga"]
    assert read_entry(dest, "颜.tga") == b"\x00\x01\x02\x03"
    # What `zipfile` alone gives back for the same bytes, kept on the record as the thing being fixed.
    with zipfile.ZipFile(io.BytesIO(data)) as plain:
        assert plain.namelist() == ["╤╒.tga"]


def test_a_utf8_name_written_without_the_flag_reads_as_utf8(tmp_path):
    dest = tmp_path / "staging"
    data = write_zip([Item(name="肌.png".encode("utf-8"), data=b"png")])

    with zipfile.ZipFile(io.BytesIO(data)) as plain:
        assert plain.namelist() == ["Φéî.png"]
    assert [f.name for f in extract_zip(data, dest)] == ["肌.png"]


def test_a_flagged_utf8_name_is_left_alone(tmp_path):
    dest = tmp_path / "staging"
    data = write_zip([Item(name="使用规则.txt", data=b"readme")])

    assert [f.name for f in extract_zip(data, dest)] == ["使用规则.txt"]


@pytest.mark.parametrize(
    "name",
    [
        "../../x",
        "..\\..\\x",
        "a/../../b",
        "tex/../../engine/token",
        "/abs/x",
        "\\abs\\x",
        "C:\\windows\\x",
        "a\x00b.png",
    ],
    ids=["up", "up-backslash", "there-and-back", "out-of-a-dir", "leading-slash",
         "leading-backslash", "drive-letter", "nul-byte"],
)
def test_an_entry_the_staging_directory_cannot_hold_is_refused_naming_it(tmp_path, name):
    dest = tmp_path / "staging"
    data = write_zip([Item(name=name.encode("utf-8"), data=b"x")])

    with pytest.raises(CharacterError) as excinfo:
        extract_zip(data, dest)

    assert excinfo.value.code == "unsafe_entry"
    assert excinfo.value.entry == name
    assert repr(name) in str(excinfo.value)
    assert list(dest.rglob("*")) == []


def test_a_symlink_entry_is_refused_naming_it(tmp_path):
    dest = tmp_path / "staging"
    data = write_zip([Item(name="token", data=b"../../engine/token", external_attr=SYMLINK_ATTR)])

    with pytest.raises(CharacterError) as excinfo:
        extract_zip(data, dest)

    assert excinfo.value.code == "unsafe_entry"
    assert excinfo.value.entry == "token"
    assert not dest.exists()


def test_the_caps_are_the_ones_the_spec_sets():
    assert characters.ARCHIVE_CAP_BYTES == 200 * 1024 * 1024
    assert characters.ENTRY_CAP_BYTES == 64 * 1024 * 1024
    assert characters.EXPANDED_CAP_BYTES == 400 * 1024 * 1024
    assert characters.MAX_EXPANSION_RATIO == 50


def test_an_archive_bigger_than_the_cap_is_refused(tmp_path, monkeypatch):
    # 200 MB of fixture is not a test; the rule is what is under test, and the number above is its own.
    monkeypatch.setattr(characters, "ARCHIVE_CAP_BYTES", 64)
    dest = tmp_path / "staging"
    data = write_zip([Item(name="a.png", data=b"y" * 4096)])

    with pytest.raises(CharacterError) as excinfo:
        extract_zip(data, dest)

    assert excinfo.value.code == "too_large"
    assert str(len(data)) in str(excinfo.value)
    assert "64" in str(excinfo.value)
    assert list(dest.rglob("*")) == []


def test_an_entry_bigger_than_the_cap_is_refused_naming_it(tmp_path):
    dest = tmp_path / "staging"
    oversized = 64 * 1024 * 1024 + 1
    data = write_zip(
        [Item(name="huge.pmx", data=b"x", method=STORED, declared_size=oversized,
              declared_compress_size=oversized)]
    )

    with pytest.raises(CharacterError) as excinfo:
        extract_zip(data, dest)

    assert excinfo.value.code == "too_large"
    assert excinfo.value.entry == "huge.pmx"
    assert list(dest.rglob("*")) == []


def test_entries_that_add_up_past_the_cap_are_refused(tmp_path):
    dest = tmp_path / "staging"
    each = 60 * 1024 * 1024  # under the 64 MB entry cap; seven of them are 420 MB
    items = [
        Item(name=f"tex/{i}.png", data=b"x", method=STORED, declared_size=each,
             declared_compress_size=each // 4)
        for i in range(7)
    ]

    with pytest.raises(CharacterError) as excinfo:
        extract_zip(write_zip(items), dest)

    assert excinfo.value.code == "too_large"
    assert "400" in str(excinfo.value)
    assert list(dest.rglob("*")) == []


def test_a_bomb_shaped_entry_is_refused_on_ratio(tmp_path):
    dest = tmp_path / "staging"
    data = write_zip([Item(name="zero.png", data=b"\0" * 2_000_000)])

    with pytest.raises(CharacterError) as excinfo:
        extract_zip(data, dest)

    assert excinfo.value.code == "too_large"
    assert excinfo.value.entry == "zero.png"
    assert list(dest.rglob("*")) == []


def test_a_small_fully_compressible_entry_is_not_called_a_bomb(tmp_path):
    """`hair.bmp` in the donor corpus deflates 62:1 at 1.1 KB and is a real texture.

    Ratio only bites above `RATIO_MIN_BYTES`, because below it the absolute caps have already won and
    refusing would be refusing the harmless ones.
    """
    dest = tmp_path / "staging"
    data = write_zip([Item(name="hair.bmp", data=b"\0" * 4096)])

    with zipfile.ZipFile(io.BytesIO(data)) as plain:
        info = plain.infolist()[0]
        assert info.file_size / info.compress_size > characters.MAX_EXPANSION_RATIO

    files = extract_zip(data, dest)
    assert [f.size for f in files] == [4096]


def test_an_archive_over_the_entry_count_cap_is_refused(tmp_path):
    dest = tmp_path / "staging"
    items = [Item(name=f"e{i}.bin", data=b"x") for i in range(characters.MAX_ENTRIES + 1)]

    with pytest.raises(CharacterError) as excinfo:
        extract_zip(write_zip(items), dest)

    assert excinfo.value.code == "too_large"
    assert list(dest.rglob("*")) == []


def test_a_model_archive_extracts_every_entry(tmp_path):
    dest = tmp_path / "staging"
    data = write_zip(
        [
            Item(name=gbk("耀嘉音.pmx"), data=b"PMX " + b"\0" * 60),
            Item(name="tex/", data=b"", method=STORED),
            Item(name=gbk("tex/颜.png"), data=b"png-face"),
            Item(name="toon_defo.bmp", data=b"bmp", method=STORED),
        ]
    )

    files = extract_zip(data, dest)

    assert [f.name for f in files] == ["耀嘉音.pmx", "tex/颜.png", "toon_defo.bmp"]
    assert (dest / "tex").is_dir()
    assert read_entry(dest, "tex/颜.png") == b"png-face"


def test_a_directory_only_archive_writes_directories_and_no_files(tmp_path):
    dest = tmp_path / "staging"
    files = extract_zip(write_zip([Item(name="spa/", data=b"", method=STORED)]), dest)

    assert files == []
    assert (dest / "spa").is_dir()


def test_a_password_protected_entry_is_refused_naming_it(tmp_path):
    """An entry with the encryption flag set is not unreadable data, it is *wrong* data.

    `zipfile` hands the stored bytes straight back for a weakly encrypted entry, so a reader that never
    asks would write a file that looks like a texture and decodes as nothing.
    """
    dest = tmp_path / "staging"
    data = write_zip([Item(name="secret.pmx", data=b"PMX ", flags=1, method=STORED)])

    with pytest.raises(CharacterError) as excinfo:
        extract_zip(data, dest)

    assert excinfo.value.code == "bad_archive"
    assert excinfo.value.entry == "secret.pmx"
    assert list(dest.rglob("*")) == []


def test_bytes_that_are_not_a_zip_are_refused_as_such(tmp_path):
    dest = tmp_path / "staging"

    with pytest.raises(CharacterError) as excinfo:
        extract_zip(b"PK\x03\x04 this is not an archive", dest)

    assert excinfo.value.code == "bad_archive"
    assert list(dest.rglob("*")) == []


def test_a_header_that_understates_its_size_is_refused_before_it_writes(tmp_path):
    """The cap checks are not a favour to the header: a lying size is refused, not believed.

    Declared 8 bytes, real 2.6 MB. Nothing may land for that entry, so the refusal has to arrive with
    the first chunk rather than after the file.
    """
    dest = tmp_path / "staging"
    data = write_zip([Item(name="fake.png", data=b"texture bytes" * 200_000, declared_size=8)])

    with pytest.raises(CharacterError) as excinfo:
        extract_zip(data, dest)

    assert excinfo.value.code == "bad_archive"
    assert excinfo.value.entry == "fake.png"
    assert list(dest.rglob("*")) == []


def test_the_fixture_archive_is_one_zipfile_can_open(tmp_path):
    """The writer is honest enough that the stdlib reads it: the tests are about names and caps."""
    data = write_zip([Item(name="a/b.png", data=b"z" * 300)])

    with zipfile.ZipFile(io.BytesIO(data)) as plain:
        assert plain.namelist() == ["a/b.png"]
        assert plain.read("a/b.png") == b"z" * 300
        assert plain.testzip() is None


def test_deflate_and_store_are_both_understood(tmp_path):
    dest = tmp_path / "staging"
    data = write_zip(
        [Item(name="d.bin", data=b"abc" * 100), Item(name="s.bin", data=b"abc" * 100, method=STORED)]
    )

    files = extract_zip(data, dest)

    assert [f.name for f in files] == ["d.bin", "s.bin"]
    assert read_entry(dest, "d.bin") == read_entry(dest, "s.bin") == b"abc" * 100
