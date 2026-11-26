"""Reading a PMX from bytes nobody has to licence.

`tests/sample_pmx.py` writes the shape; these tests are the promise the rest of unit 11 rests on: a
character can be *listed* — name, counts, what it would cost to render — without a GPU, without a
third-party loader, and without ever trusting an offset the file did not earn. Every refusal here
names what it ran out of, because the alternative is a silent profile with 1.2 billion vertices.

`read_pmx_head` is the strict view and `read_pmx_model` the reporting one: the first certifies a
profile, the second describes a file even where it had to search for a boundary. Which is which is
what most of this file is about.
"""

from __future__ import annotations

import struct

import pytest

from kira.characters import (
    COUNTS_HEADER,
    COUNTS_INLINE,
    MATERIAL_DRAW_AND_MEMOS,
    MATERIAL_MEMO_ONLY,
    CharacterError,
    read_pmx_head,
    read_pmx_model,
)
from sample_pmx import DEFAULT_INDEX_SIZES, write_pmx, write_three_string_pmx

#: A file with the same sections as the default one and a fraction of its bytes, for the tests that cut
#: it up or walk it many times. `write_pmx`'s defaults are shaped like a real character (29 287 vertices,
#: 83 310 face indices) and are what the count read-back test has to prove against.
TINY = dict(
    vertex_count=40, face_index_count=12, texture_count=2, material_count=1, bone_count=3,
    morph_count=2, frame_count=2, rigid_body_count=1, constraint_count=1,
)


def test_every_count_reads_back_as_written():
    data = write_pmx(
        vertex_count=29_287,
        face_index_count=83_310,
        texture_count=8,
        material_count=19,
        bone_count=487,
        morph_count=59,
        frame_count=13,
        rigid_body_count=317,
        constraint_count=462,
    )
    head = read_pmx_head(data)
    assert head.vertex_count == 29_287
    assert head.face_index_count == 83_310
    assert head.triangle_count == 27_770
    assert head.texture_count == 8
    assert head.material_count == 19
    assert head.bone_count == 487
    assert head.morph_count == 59
    assert head.frame_count == 13
    assert head.rigid_body_count == 317
    assert head.constraint_count == 462


def test_the_setting_block_is_read_the_way_the_real_files_write_it():
    head = read_pmx_head(write_pmx(encoding=0, additional_uv_num=3, index_sizes=DEFAULT_INDEX_SIZES))
    assert head.encoding == 0
    assert head.additional_uv_num == 3
    assert head.index_sizes == DEFAULT_INDEX_SIZES


def test_a_cjk_display_name_survives_the_round_trip():
    head = read_pmx_head(write_pmx(name="エレン", name_en="Ellen", comment="テスト", comment_en="test"))
    assert (head.name, head.name_en, head.comment, head.comment_en) == ("エレン", "Ellen", "テスト", "test")


def test_utf8_names_are_decoded_as_utf8():
    head = read_pmx_head(write_pmx(encoding=1, name="Ellen", comment="plain ascii"))
    assert head.name == "Ellen"
    assert head.comment == "plain ascii"


def test_a_2_1_file_with_three_extra_setting_bytes_parses_with_the_same_code():
    # 2.0 writes an 8-byte setting block, 2.1 writes 11; the six index sizes are at positions 2..7
    # either way, which is the only reason one reader serves both.
    data = write_pmx(version=2.1, extra_setting_bytes=b"\x01\x01\x01", bone_count=577, constraint_count=955)
    head = read_pmx_head(data)
    assert head.version == pytest.approx(2.1)
    assert head.bone_count == 577
    assert head.constraint_count == 955


def test_the_inline_counts_the_whole_donor_corpus_writes_are_reported_as_inline():
    head = read_pmx_head(write_pmx(**TINY))
    assert head.count_framing == COUNTS_INLINE


def test_the_documented_nine_count_block_is_read_by_the_same_code_and_said_so():
    """A file written the way the format note says is legal too, and the report names which one it is.

    Kira cannot assume the corpus: a model a user downloads tomorrow may well carry the nine counts in
    the header block, and the framing the reader found is the thing that tells the user whether the
    loader downstream has to read it the same way.
    """
    data = write_pmx(counts_inline=False, **TINY)
    head = read_pmx_head(data)
    assert head.count_framing == COUNTS_HEADER
    assert head.vertex_count == TINY["vertex_count"]
    assert head.constraint_count == TINY["constraint_count"]


def test_a_file_missing_its_fourth_string_is_refused_not_misread():
    """The format carries four model-info strings; three is a file whose counts are somewhere else.

    Read naively, the English comment's length becomes a vertex count and the nine counts land inside
    the name — the exact failure a donor loader can survive because it never shows the number to
    anyone. Kira lists the model in a table, so it has to say no instead, and it says which of the
    four strings it could not decode.
    """
    with pytest.raises(CharacterError) as excinfo:
        read_pmx_head(write_three_string_pmx())
    assert excinfo.value.code == "not_a_pmx"
    assert "English model comment" in excinfo.value.message


@pytest.mark.parametrize("encoding", [0, 1])
def test_no_cut_of_a_legal_file_ever_returns_a_partial(encoding):
    # Every section's count sits before its own payload, so a cut stamps the numbers and only the bytes
    # are missing. The counts surviving is exactly why `head()` has to refuse on anything else it can
    # prove — here that the walk ran out, or that it had to search for a boundary the file never stated.
    data = write_pmx(encoding=encoding, name="エレン" if encoding == 0 else "Ellen", **TINY)
    for cut in range(len(data)):
        with pytest.raises(CharacterError):
            read_pmx_head(data[:cut])


def test_a_walk_that_ends_before_the_file_blanks_what_it_never_reached():
    """A truncated file keeps the counts it states before its payload and loses the ones behind it.

    The numbers that survive are read from offsets the walk earned; the three behind the morph table are
    not numbers at all until a stride says where the section ends, so they stay `None` and `head()` says so
    instead of answering with the profile of a whole file.
    """
    model = read_pmx_model(write_pmx(**TINY)[:-40])
    assert model.counts["frame_count"] is None
    assert model.counts["rigid_body_count"] is None
    assert model.counts["constraint_count"] is None
    assert model.unreadable
    assert "no later section boundary walks out to the end of the file" in model.unreadable
    # Everything the file itself earned still reads back.
    assert model.counts["bone_count"] == TINY["bone_count"]
    assert model.counts["morph_count"] == TINY["morph_count"]
    with pytest.raises(CharacterError) as excinfo:
        model.head()
    assert excinfo.value.code == "pmx_truncated"


def test_bytes_the_walk_cannot_place_are_reported_as_unplaced():
    """Leftover bytes are unread, not an exporter's note — two donor files said so.

    The region those two left was three quarters nonzero float data, which is what a morph section wider
    than anything measured looks like once the walk stops on the zeros inside it. So a leftover is only
    ever called what it is, and a model with one is not certified: reading a run of zeros as three empty
    sections is a legal reading of the bytes and a false statement about the model.
    """
    model = read_pmx_model(write_pmx(morph_padding=96, tail=b"\xff" * 220, **TINY))
    assert model.trailing_bytes > 0
    assert any("could not account for" in f for f in model.findings)
    assert not any("appended" in f for f in model.findings)
    assert model.counts["bone_count"] == TINY["bone_count"]
    with pytest.raises(CharacterError) as excinfo:
        model.head()
    assert excinfo.value.code == "pmx_truncated"
    assert "not part of any section it can name" in excinfo.value.message


def test_a_morph_section_wider_than_the_format_measures_is_counted_not_named():
    """Four of the twenty donor files put their frames this far out of reach, so the search exists.

    It is allowed to answer only with an offset whose remaining sections reach the very end of the file,
    and it counts how many do — one is a proved boundary, several is a window full of places a short walk
    can finish. The report says which, which is also why `head()`, the view that puts numbers in front of
    a user, refuses a model that needed it at all.
    """
    data = write_pmx(morph_padding=96, **TINY)
    model = read_pmx_model(data)
    assert model.resynced_from is not None
    assert model.counts["frame_count"] == TINY["frame_count"]
    assert model.counts["rigid_body_count"] == TINY["rigid_body_count"]
    assert model.counts["constraint_count"] == TINY["constraint_count"]
    assert model.frame_names  # the sections behind the morph table are readable after all
    assert model.morph_names == ()
    assert model.trailing_bytes == 0
    finding = next(f for f in model.findings if "morph section ends" in f)
    assert "byte(s) past its count" in finding
    assert f"{TINY['morph_count']} morph(s) are counted and none is named" in finding
    assert "the only offset in the window whose remaining sections walk out to the end of the file" in finding
    with pytest.raises(CharacterError) as excinfo:
        model.head()
    assert "read from offset" in excinfo.value.message


def test_a_bone_morph_that_also_carries_a_rotation_is_said_so():
    """The narrow stride is the format note's; a quarter of the corpus writes a quaternion as well."""
    data = write_pmx(
        bone_morph_rotation=True,
        morphs=(("まばたき", 2), ("ウィンク", 2)),
        **TINY,
    )
    model = read_pmx_model(data)
    assert model.morph_names == ("まばたき", "ウィンク")
    assert model.morph_kinds == (2, 2)
    assert model.trailing_bytes == 0
    assert any("a translation and a rotation" in f for f in model.findings)


def test_materials_written_with_a_draw_flag_and_two_memos_read_back_as_that():
    """Which framing a material table uses is proved by arithmetic, and the report says which won."""
    data = write_pmx(material_framing=MATERIAL_DRAW_AND_MEMOS, materials=("颜", "发"), **TINY)
    model = read_pmx_model(data)
    assert model.material_framing == MATERIAL_DRAW_AND_MEMOS
    assert model.material_names == ("颜", "发")
    assert not any("one memo" in f for f in model.findings)


def test_the_memo_only_materials_the_converters_emit_are_named_as_one():
    model = read_pmx_model(write_pmx(material_framing=MATERIAL_MEMO_ONLY, **TINY))
    assert model.material_framing == MATERIAL_MEMO_ONLY
    assert any("one memo and no draw flag" in f for f in model.findings)


def test_an_ik_bone_counts_its_links_from_their_own_field():
    """Iterating the loop count instead of the link count desynchronises every two-byte-bone file.

    Which is most of them, so this is the one test that keeps the skeleton honest: the walk has to end on
    the last byte of the file with the IK bones counted, and a stride that is wrong by four bytes per
    link would not.
    """
    data = write_pmx(
        bones=("上半身", "左足", "左足IK", "左ひざ"), ik_bones=1, **TINY
    )
    model = read_pmx_model(data)
    assert model.ik_bone_count == 1
    assert model.bone_names == ("上半身", "左足", "左足IK", "左ひざ")
    assert model.trailing_bytes == 0


def test_a_sphere_and_a_shared_toon_reference_are_counted_from_the_material_table():
    """Neither is read as pixels here, so the only honest thing is to count how many there are.

    A sphere map is a second texture blended over the diffuse one and a shared toon is an index into a
    built-in table no PMX carries; both change what a renderer shows and neither is in the bytes the walk
    reads, so they travel as counts and as findings.
    """
    data = write_pmx(materials=("m0", "m1"), sphere_index=1, shared_toon=True, **TINY)
    model = read_pmx_model(data)
    assert model.counts["material_count"] == 2
    assert model.sphere_refs == 2
    assert model.shared_toon_refs == 2
    assert model.trailing_bytes == 0


def test_a_texture_index_of_minus_one_is_read_as_minus_one_at_every_width():
    """`-1` in a texture field means "this material has no diffuse map", and that is the whole story.

    Read unsigned it is 255, 65 535 or four billion — a number past the end of a table, which is what every
    one of the twenty donor files writes for its sphere slot. Under the unsigned reading each of their
    materials "referenced a sphere map", and the report told a user to go and look for textures that no
    file asks for. All three widths have to answer the same way, because which one a converter picked is
    the converter's business.
    """
    for width in (1, 2, 4):
        sizes = list(DEFAULT_INDEX_SIZES)
        sizes[1] = width
        model = read_pmx_model(write_pmx(**TINY, index_sizes=tuple(sizes), sphere_index=-1))
        assert model.sphere_refs == 0, f"a -1 at texture width {width} was not read as -1"
        assert model.counts["texture_count"] == TINY["texture_count"]


def test_an_index_width_the_format_never_writes_is_refused_not_walked_off():
    """A setting byte of 3 used to raise a `KeyError` out of the struct table — which the API answers 500.

    The six widths are the file telling the reader how to measure every index that follows, so a value
    outside 1, 2 and 4 is not a model with an unusual exporter, it is a header that cannot be walked at
    all. Refusing it by code is the difference between "this file is not a PMX" and a crash report.
    """
    for position in range(6):
        broken = bytearray(write_pmx(**TINY))
        at = 11 + position  # MAGIC | f32 version | u8 setting length | u8 encoding | u8 uv count | 6 widths
        broken[at] = 3
        with pytest.raises(CharacterError) as excinfo:
            read_pmx_model(bytes(broken))
        assert excinfo.value.code == "not_a_pmx", f"width byte {position} saying 3 was accepted"


def test_something_that_is_not_a_pmx_says_so():
    with pytest.raises(CharacterError) as excinfo:
        read_pmx_head(b"PK\x03\x04" + b"\x00" * 64)
    assert excinfo.value.code == "not_a_pmx"


def test_a_version_this_reader_does_not_know_is_named():
    with pytest.raises(CharacterError) as excinfo:
        read_pmx_head(write_pmx(version=2.2))
    assert excinfo.value.code == "pmx_version_unsupported"
    assert "2.2" in str(excinfo.value)


def test_an_encoding_byte_outside_the_two_the_format_defines_is_not_a_pmx():
    with pytest.raises(CharacterError) as excinfo:
        read_pmx_head(write_pmx(encoding=7))
    assert excinfo.value.code == "not_a_pmx"


def test_a_setting_block_too_short_to_hold_the_index_sizes_is_not_a_pmx():
    # Six index sizes plus encoding plus the UV count is the floor; a header claiming four bytes is
    # either not PMX or is broken in a way that must not be guessed at.
    broken = b"PMX " + struct.pack("<f", 2.0) + struct.pack("<B", 4) + b"\x00\x03\x02\x01"
    with pytest.raises(CharacterError) as excinfo:
        read_pmx_head(broken)
    assert excinfo.value.code == "not_a_pmx"
