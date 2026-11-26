"""What a model can and cannot render, said before anything asks a GPU anything.

`describe()` reads the bytes and the folder a model lives in and reports the things a loader would
otherwise swallow: a texture reference the archive does not carry (the real 简 model in `RoL6mVzkCH.zip`
names `hair.bmp` and ships no such file), a path written with backslashes that a browser never separates,
a `.tga` no browser decodes, a rig with no 肩 bone to shrug with, and the readme next to the model saying
请勿二次配布. None of it stops a model loading; all of it changes what loads.

`choose_main()` answers the one question the stage cannot answer for itself — which of the files in an
archive is the *body* — and the thresholds it uses are gaps measured across the ten donor archives, not
tuned numbers: nine props stop at 8 255 vertices and 38 bones, eleven characters start at 26 798 and 297.

Everything here is written against `tests/sample_pmx.py` bytes. No licensed model enters a test.
"""

from __future__ import annotations

import pytest

from kira.characters import (
    LICENSE_NOTE_MAX_CHARS,
    MAIN_MIN_BONES,
    MAIN_MIN_VERTS,
    CharacterError,
    choose_main,
    describe,
    read_pmx_head,
)
from sample_pmx import write_pmx

#: The same sections as the default fixture at a fraction of its bytes.
TINY = dict(
    vertex_count=40, face_index_count=12, texture_count=2, material_count=1, bone_count=3,
    morph_count=2, frame_count=2, rigid_body_count=1, constraint_count=1,
)

#: 补妆镜.pmx in the corpus: a compact mirror, 538 vertices, 3 bones, nothing that moves.
MIRROR = dict(
    TINY, vertex_count=538, texture_count=1, morph_count=0, frame_count=1,
    rigid_body_count=0, constraint_count=0, name="补妆镜",
)

#: 伞.pmx: the densest prop the corpus carries — 8 255 vertices, 38 bones, 14 rigid bodies and 17 joints
#: of its own. Physics is not a body.
UMBRELLA = dict(
    TINY, vertex_count=8_255, face_index_count=30, texture_count=4, material_count=2, bone_count=38,
    morph_count=1, frame_count=3, rigid_body_count=14, constraint_count=17, name="伞",
)

#: 艾莲.pmx in `9y5Huh14gN.zip`: 29 287 vertices, 487 bones, 59 morphs, 317 rigid bodies.
BODY = dict(
    TINY, vertex_count=29_287, face_index_count=83_310, texture_count=8, material_count=19,
    bone_count=487, morph_count=59, frame_count=13, rigid_body_count=317, constraint_count=462,
    name="艾莲",
)

#: The skeleton an MMD stage animates, spelled the way a Japanese rig spells it.
JAPANESE_RIG = (
    "全部", "センター", "下半身", "上半身", "頭", "首", "肩", "左腕", "左ひじ", "左手",
    "左足", "左ひざ", "左足首", "つま先",
)

#: The same skeleton as the converters in this corpus emit it, in English.
ENGLISH_RIG = (
    "Root", "Torso", "Neck", "Head", "Shoulder", "Left Arm", "Left Elbow", "Left Wrist",
    "Left Leg", "Left Knee", "Left Ankle", "Left Toe",
)

#: Five fingers plus two `指先` bones, which are one per limb (toetip included) and not fingers.
FINGERED_RIG = ("親指", "人差し指", "中指", "薬指", "小指", "左指先", "右指先")


@pytest.fixture(scope="module")
def body_bytes() -> bytes:
    return write_pmx(**BODY)


def test_a_prop_and_a_body_in_one_archive_leave_no_doubt_which_is_the_person(body_bytes, tmp_path):
    """The 538-vertex mirror and the 29 287-vertex character, which is the plan's own pair.

    Both numbers have to be crossed before something stands in for a person, and what does not qualify is
    not thrown away: a mirror is held *by* someone, so it comes back as a companion for the same stage.
    """
    mirror = describe(write_pmx(**MIRROR), tmp_path, file_name="补妆镜.pmx")
    body = describe(body_bytes, tmp_path, file_name="艾莲.pmx")

    assert mirror.is_character is False
    assert mirror.has_physics is False
    assert body.is_character is True
    assert body.has_physics is True
    assert body.triangle_count * 3 == body.counts["face_index_count"]
    assert body.vertex_count == 29_287 and body.vertex_count > MAIN_MIN_VERTS

    pick = choose_main((mirror, body))
    assert pick.main is body
    assert pick.companions == (mirror,)
    assert "the only entry over both" in pick.reason
    assert f"{MAIN_MIN_BONES} bones" in pick.reason


def test_the_densest_prop_in_the_corpus_is_still_not_a_body(tmp_path):
    """An umbrella with 14 rigid bodies passes the physics test and fails both body tests.

    Nothing qualifies is an answer rather than a failure to answer, so `main` stays `None` and the reason
    names the biggest thing the archive actually had instead of leaving the UI to invent one.
    """
    umbrella = describe(write_pmx(**UMBRELLA), tmp_path, file_name="伞.pmx")
    assert umbrella.has_physics is True
    assert umbrella.is_character is False

    pick = choose_main((umbrella,))
    assert pick.main is None
    assert pick.companions == (umbrella,)
    assert "no entry has both" in pick.reason
    assert "which is a prop" in pick.reason


def test_every_texture_reference_is_resolved_or_named_missing(tmp_path):
    """`hair.bmp absent` is the real state of the 简 archive, and the row shows it.

    A reference the folder cannot answer is not a warning the user finds out about later: it is the reason
    the model loads with a white face, so it is counted, named, and put in the same string as the number
    that resolved.
    """
    (tmp_path / "tex").mkdir()
    (tmp_path / "tex" / "颜.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
    (tmp_path / "skin.bmp").write_bytes(b"BM" + b"\x00" * 40)
    report = describe(
        write_pmx(textures=("tex\\颜.png", "skin.bmp", "hair.bmp"), **TINY), tmp_path
    )

    assert [t.relative for t in report.textures] == ["tex/颜.png", "skin.bmp", "hair.bmp"]
    assert [t.declared for t in report.textures][0] == "tex\\颜.png"  # kept verbatim, backslash and all
    assert report.texture_resolved == 2
    assert report.missing_textures == ("hair.bmp",)
    assert report.texture_status == "2/3 — hair.bmp absent"
    assert report.textures[0].exists and report.textures[0].size == 40
    assert report.textures[0].format == "png"
    assert not report.textures[2].exists and report.textures[2].size is None


def test_every_reference_resolving_is_said_as_that_rather_than_as_a_warning(tmp_path):
    """A model whose folder answers every reference gets a count and no prose.

    The absence of findings is the assertion: a library of twenty rows that each said "3/3, and here is
    something about your textures" would train the user to ignore the ones that say something is missing.
    """
    tex = tmp_path / "tex"
    tex.mkdir()
    for name in ("a.png", "b.png", "c.png"):
        (tex / name).write_bytes(b"\x89PNG\r\n\x1a\n")
    report = describe(write_pmx(textures=("tex\\a.png", "tex\\b.png", "tex\\c.png"), **TINY), tmp_path)
    assert report.texture_status == "3/3"
    assert report.missing_textures == ()
    assert not any("absent" in f for f in report.findings)


def test_more_than_one_missing_texture_is_counted_in_the_status(tmp_path):
    """One name plus a count, because a row is not a log.

    The library screen has a line of space; the report gives it the first thing that is missing and how
    many more behind it, which is the same shape as `texture_status` uses for the one that is there.
    """
    (tmp_path / "a.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    report = describe(write_pmx(textures=("a.png", "b.bmp", "c.tga"), **TINY), tmp_path)
    assert report.texture_status == "1/3 — b.bmp absent, 1 more"


def test_a_folder_that_is_not_there_names_every_reference_absent(tmp_path):
    """A caller with no folder passes one that is not there, and the report says so instead of guessing.

    Texture paths are relative to the file that names them, so resolving one against the process's own
    working directory would answer a different question and report it as this one.
    """
    report = describe(write_pmx(**TINY), tmp_path / "not-imported-yet")
    assert report.texture_resolved == 0
    assert len(report.missing_textures) == TINY["texture_count"]


def test_a_model_with_no_textures_says_it_has_none_rather_than_zero_of_zero(tmp_path):
    bare = dict(TINY, texture_count=0, material_count=0, face_index_count=0)
    report = describe(write_pmx(**bare), tmp_path)
    assert report.textures == ()
    assert report.texture_status == "no textures"


def test_a_backslash_path_and_a_tga_are_both_said_as_findings(tmp_path):
    """Neither is an error and both change what loads, which is exactly what a finding is for.

    `tex\\颜.tga` is one filename to a browser, not a directory and a file, and no browser decodes a tga
    without a decoder of its own; Kira ships one, and says so in the same breath.
    """
    (tmp_path / "tex").mkdir()
    report = describe(write_pmx(textures=("tex\\颜.tga", "skin.bmp"), **TINY), tmp_path)
    backslash = next(f for f in report.findings if "backslashes" in f)
    assert "tex\\\\颜.tga" in backslash  # the finding quotes `repr`, which doubles the separator
    exotic = next(f for f in report.findings if "no browser decodes" in f)
    assert ".bmp" in exotic and ".tga" in exotic
    assert "Kira reads them with its own loader" in exotic


def test_a_reference_that_climbs_out_of_the_folder_is_reported_as_an_escape(tmp_path):
    """`..` in a texture path is not zip-slip — the importer only reads inside the directory it copied.

    It is a reference Kira cannot resolve, so it is named as one instead of being quietly rewritten to a
    path that means something else.
    """
    report = describe(write_pmx(textures=("../shared/颜.png",), **TINY), tmp_path)
    ref = report.textures[0]
    assert ref.escapes is True
    assert ref.exists is False
    assert report.missing_textures == ("../shared/颜.png",)


def test_a_sphere_map_and_a_shared_toon_are_said_as_things_the_stage_does_not_draw(tmp_path):
    """Both are references into tables the walk never reads, so the honest thing is to say that.

    Counting them from the material table is what makes the sentence mean something: a model with three
    sphere materials will look wrong for a reason the user was told before rendering it.
    """
    report = describe(
        write_pmx(materials=("颜", "发"), sphere_index=0, shared_toon=True, **TINY), tmp_path
    )
    assert report.sphere_texture_refs == 2
    assert report.shared_toon_refs == 2
    assert any("sphere map" in f and "2 material(s)" in f for f in report.findings)
    assert any("shared toon index" in f for f in report.findings)


def test_the_stage_sees_the_skeleton_whatever_language_the_rig_is_in(tmp_path):
    """One group list, spelled in Japanese, Chinese and English, because half the library is converters.

    A group that only matches one spelling reports itself missing on a model that has it — which is the
    kind of finding a user cannot check without a hex editor.
    """
    japanese = describe(write_pmx(bones=JAPANESE_RIG, **TINY), tmp_path)
    assert "shoulder" in japanese.standard_groups
    assert "spine" in japanese.standard_groups and "ankle-toe" in japanese.standard_groups

    english = describe(write_pmx(bones=ENGLISH_RIG, **TINY), tmp_path)
    assert set(english.standard_groups) == set(japanese.standard_groups)


def test_a_rig_that_is_missing_a_group_says_which_group_is_missing(tmp_path):
    """No 首 and no 肩: the stage has nothing to turn the head with, and the report names both gaps.

    `standard_groups` is the list of what *is* there; the groups that are not are the ones the picker has
    to refuse an animation for, so the difference is stated as an assertion here rather than left to the
    screen to reconstruct.
    """
    report = describe(write_pmx(bones=("上半身", "左腕", "左足"), **TINY), tmp_path)
    assert set(report.standard_groups) == {"spine", "arm", "leg"}
    for group in ("neck-head", "shoulder", "hand", "knee", "ankle-toe", "root"):
        assert group not in report.standard_groups


def test_finger_bones_are_counted_and_a_toetip_is_not_a_finger(tmp_path):
    """Whether a wave animation has anything to drive is a count, not a group match.

    `指先` is deliberately not a marker: every MMD rig carries one per limb, toe included, and matching
    bare `指` would report two toes as two fingers.
    """
    report = describe(write_pmx(bones=FINGERED_RIG, **TINY), tmp_path)
    assert report.finger_bone_count == 5


def test_a_readme_that_forbids_redistribution_travels_with_the_model(tmp_path):
    """One line of terms, not the readme pasted whole.

    Every archive in the donor corpus carries a file like this one, in Chinese or Japanese, and the terms
    have to be visible at the moment the user chooses to put the character on screen.
    """
    (tmp_path / "使用规则.txt").write_text(
        "模型使用说明\n请勿二次配布、二次販売\n改変は自由です\n", encoding="utf-8"
    )
    report = describe(write_pmx(**TINY), tmp_path)
    assert report.license_note == "请勿二次配布、二次販売"
    assert len(report.license_note) <= LICENSE_NOTE_MAX_CHARS


def test_a_readme_in_gbk_says_the_same_thing_as_one_in_utf8(tmp_path):
    """The same codec fallback the archive entry names needed, because the same tools wrote both.

    A readme that decodes as nothing is a licence nobody reads, and this corpus writes them in GBK.
    """
    (tmp_path / "使用规则.txt").write_bytes("禁止二次发布该模型".encode("gbk"))
    report = describe(write_pmx(**TINY), tmp_path)
    assert report.license_note == "禁止二次发布该模型"


def test_a_long_rule_is_cut_short_rather_than_pasted_into_a_table(tmp_path):
    """A readme is not a licence note. One line, capped, and the whole file stays on disk beside it.

    The cap is what keeps a 900-character wall of terms from becoming the text a library row shows; the
    user who needs all of it has the file the importer copied.
    """
    (tmp_path / "readme.txt").write_text("请勿二次配布" + "详" * 900, encoding="utf-8")
    report = describe(write_pmx(**TINY), tmp_path)
    assert len(report.license_note) == LICENSE_NOTE_MAX_CHARS


def test_the_absence_of_a_readme_is_not_an_error(tmp_path):
    """Plenty of legal models ship without a terms file, so the report says nothing about one it did not read.

    This is the assertion that keeps the licence layer from becoming a nag: no note, and no finding.
    """
    report = describe(write_pmx(**TINY), tmp_path)
    assert report.license_note is None
    assert not any("配布" in f or "发布" in f or "redistribut" in f for f in report.findings)
    assert report.unreadable is None


def test_a_model_that_cannot_be_walked_is_described_rather_than_raising(tmp_path):
    """The reporting view keeps whatever the walk earned and names where it stopped.

    `read_pmx_head` refuses the same bytes: a profile with three counts missing is not something to put in
    front of a user, but it is something to tell them about the file they just tried to import.
    """
    data = write_pmx(**TINY)[:-40]
    report = describe(data, tmp_path)
    assert report.unreadable
    assert "the walk stops here" in " ".join(report.findings)
    assert report.vertex_count == TINY["vertex_count"]
    assert report.counts["frame_count"] is None
    assert report.is_character is False
    with pytest.raises(CharacterError):
        read_pmx_head(data)


def test_the_reporting_view_keeps_the_counts_a_searched_boundary_reached(tmp_path):
    """Where the morph table's own element sizes do not reach the end of the section, the sections behind
    it are found from the one offset whose remaining sections walk out to the end of the file.

    Those counts are reported, with the offset and the search that produced them, and they are never
    certified: the strict view refuses the same bytes. Naming the searched boundary is what lets a user
    tell a morph-less model from a corrupt one.
    """
    data = write_pmx(morph_padding=96, **TINY)
    report = describe(data, tmp_path)
    assert report.counts["frame_count"] == TINY["frame_count"]
    assert report.counts["morph_count"] == TINY["morph_count"]
    assert report.morph_names == ()
    assert any("morph section ends" in f for f in report.findings)
    with pytest.raises(CharacterError):
        read_pmx_head(data)
