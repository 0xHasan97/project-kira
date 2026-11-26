"""The mesh the stage draws, in the one shape the engine and the browser agree on.

`kira.mesh` does not read a PMX. It asks `characters.read_pmx_model` to walk one and to hand the walk
over while it happens, because that is the only way the mesh on the stage and the report in the library
can be the same model — two readers of a format the corpus disagrees about is two answers, and the second
one is always the one a user finds. What comes back is flat: positions, normals, uvs, skin, faces,
textures, materials, bones and the vertex morphs, in the order `KRM1` states, with no offset a browser
has to go and find and no `..` resolved by anything but the engine.

The blob is a contract, so these tests read it with a decoder written here rather than the packer's own
reader borrowed from `src/kira/mesh.py`: a decoder that shares code with the encoder passes when both are
wrong the same way. Every test asserts that decoder consumed every byte it was handed, which is the
promise that keeps the format from growing a field nobody reads.
"""

from __future__ import annotations

import io
import json
import struct
import zipfile

import pytest
from sample_pmx import write_pmx

from kira.characters import (
    CharacterError,
    CharacterFileNotFound,
    import_character,
    read_pmx_model,
)
from kira.mesh import KRM1_FORMAT, KRM1_MAGIC, export_mesh, pack_mesh

#: A file with the same sections as a real character and a fraction of its bytes, all of them varied so
#: a reader that re-derives a value it never read fails here instead of on a stage.
MESH = dict(
    vertex_count=12, face_index_count=9, texture_count=3, material_count=3,
    bone_count=5, frame_count=1, rigid_body_count=1, constraint_count=1,
)

#: A body, in the importer's own sense: enough bones and vertices that `choose_main` calls it the model
#: rather than the thing the model holds.
BODY = dict(
    vertex_count=26_798, face_index_count=1_020, texture_count=2, material_count=1, bone_count=297,
    morph_count=2, frame_count=2, rigid_body_count=2, constraint_count=2,
)

TEXTURES = ("tex\\颜.png", "../escape.bmp", "hair.tga")
BONES = ("center", "upper_body", "head", "arm_l", "arm_r")
MORPHS = (("口a", 1), ("まばたき", 0), ("首", 2))

#: How many bones each weight type names, and how many of the floats that follow are weights rather than
#: the symmetry maths SDEF carries. This is the test's own reading of the published format; the fixture
#: writes the payload and the packer has to expand it into the four slots a skinned renderer uses.
WEIGHT_TYPE = {0: (1, 0), 1: (2, 1), 2: (4, 4), 3: (2, 1), 4: (4, 4)}


def mesh_data(**kwargs) -> bytes:
    return write_pmx(**{**MESH, "varied": True, **kwargs})


# --- the reference decoder ----------------------------------------------------------------------------


class _Unpack:
    """A reader that refuses to leave a byte behind, because the format promises it will not."""

    def __init__(self, blob: bytes) -> None:
        self.blob = blob
        self.pos = 0

    def take(self, size: int, what: str) -> bytes:
        if len(self.blob) - self.pos < size:
            raise AssertionError(f"{what} wanted {size} byte(s) at {self.pos}, {len(self.blob) - self.pos} left")
        chunk = self.blob[self.pos : self.pos + size]
        self.pos += size
        return chunk

    def u8(self, what: str) -> int:
        return self.take(1, what)[0]

    def u32(self, what: str) -> int:
        return struct.unpack("<I", self.take(4, what))[0]

    def i32(self, what: str) -> int:
        return struct.unpack("<i", self.take(4, what))[0]

    def floats(self, count: int, what: str) -> tuple[float, ...]:
        return struct.unpack(f"<{count}f", self.take(4 * count, what))

    def text(self, what: str) -> str:
        size = self.u32(f"{what} length")
        return self.take(size, what).decode("utf-8")

    def finished(self) -> None:
        assert self.pos == len(self.blob), (
            f"the decoder used {self.pos} of {len(self.blob)} byte(s); "
            f"{len(self.blob) - self.pos} left over means the format grew a field nobody reads"
        )


def read_krm1(blob: bytes) -> dict:
    """The whole KRM1 answer, as plain Python. See `docs/plans/2026-10-31-kira-avatar-stage.md`."""
    cursor = _Unpack(blob)
    assert cursor.take(4, "the magic") == KRM1_MAGIC
    assert cursor.u32("the format version") == KRM1_FORMAT
    counts = {
        name: cursor.u32(f"the {name} count")
        for name in (
            "vertex", "face_index", "bone", "material", "texture", "vertex_morph",
        )
    }
    positions = [
        cursor.floats(3, "a position") for _ in range(counts["vertex"])
    ]
    normals = [cursor.floats(3, "a normal") for _ in range(counts["vertex"])]
    uvs = [cursor.floats(2, "a uv") for _ in range(counts["vertex"])]
    skin = [
        (
            struct.unpack("<4I", cursor.take(16, "a bone quad")),
            cursor.floats(4, "a weight quad"),
        )
        for _ in range(counts["vertex"])
    ]
    faces = [cursor.u32("a face index") for _ in range(counts["face_index"])]
    textures = [
        {
            "declared": cursor.text("a declared texture path"),
            "relative": cursor.text("a relative texture path"),
            "escapes": bool(cursor.u8("an escape flag")),
        }
        for _ in range(counts["texture"])
    ]
    materials = []
    for _ in range(counts["material"]):
        materials.append(
            {
                "name": cursor.text("a material name"),
                "diffuse": cursor.floats(4, "a diffuse colour"),
                "ambient": cursor.floats(3, "an ambient colour"),
                "specular": cursor.floats(3, "a specular colour"),
                "shine": cursor.floats(1, "a shine")[0],
                "edge_colour": cursor.floats(4, "an edge colour"),
                "edge_size": cursor.floats(1, "an edge size")[0],
                "flags": cursor.u8("a material flag byte"),
                "texture": cursor.i32("a diffuse texture index"),
                "sphere": cursor.i32("a sphere texture index"),
                "sphere_mode": cursor.u8("a sphere mode"),
                "shared_toon": bool(cursor.u8("a shared-toon flag")),
                "toon": cursor.i32("a toon index"),
                "first": cursor.u32("a material's first index"),
                "count": cursor.u32("a material's index count"),
            }
        )
    bones = []
    for _ in range(counts["bone"]):
        bones.append(
            {
                "name": cursor.text("a bone name"),
                "name_en": cursor.text("a bone English name"),
                "parent": cursor.i32("a bone parent"),
                "position": cursor.floats(3, "a bone position"),
                "flags": cursor.u32("a bone flag word"),
            }
        )
    morphs = []
    for _ in range(counts["vertex_morph"]):
        morph = {
            "morph_index": cursor.u32("a morph's index in the PMX table"),
            "name": cursor.text("a morph name"),
        }
        size = cursor.u32("a morph element count")
        morph["elements"] = [
            (cursor.u32("a morphed vertex"), cursor.floats(3, "a morph offset"))
            for _ in range(size)
        ]
        morphs.append(morph)
    rigid_body_count = cursor.u32("the rigid body count")
    constraint_count = cursor.u32("the constraint count")
    rigid_bodies = []
    for _ in range(rigid_body_count):
        rigid_bodies.append(
            {
                "bone": cursor.i32("a rigid body bone"),
                "group": cursor.u8("a rigid body collision group"),
                "mask": struct.unpack("<H", cursor.take(2, "a rigid body collision mask"))[0],
                "shape": cursor.u8("a rigid body shape"),
                "mode": cursor.u8("a rigid body mode"),
                "values": cursor.floats(14, "a rigid body's dimensions, pose and physics"),
            }
        )
    constraints = []
    for _ in range(constraint_count):
        constraints.append(
            {
                "first": cursor.i32("a constraint's first body"),
                "second": cursor.i32("a constraint's second body"),
                "mode": cursor.u8("a constraint mode"),
                "values": cursor.floats(24, "a constraint's pose, limits and springs"),
            }
        )
    cursor.finished()
    return {
        "counts": counts,
        "positions": positions,
        "normals": normals,
        "uvs": uvs,
        "skin": skin,
        "faces": faces,
        "textures": textures,
        "materials": materials,
        "bones": bones,
        "morphs": morphs,
        "rigid_bodies": rigid_bodies,
        "constraints": constraints,
    }


# --- the geometry ------------------------------------------------------------------------------------


def test_the_header_states_the_counts_the_walk_certified():
    data = mesh_data(morphs=MORPHS)
    model = read_pmx_model(data)
    mesh = read_krm1(pack_mesh(data))
    assert mesh["counts"] == {
        "vertex": model.counts["vertex_count"],
        "face_index": model.counts["face_index_count"],
        "bone": model.counts["bone_count"],
        "material": model.counts["material_count"],
        "texture": model.counts["texture_count"],
        "vertex_morph": 1,  # only `口a` is a vertex morph
    }


def test_the_positions_and_uvs_are_the_ones_the_file_wrote():
    mesh = read_krm1(pack_mesh(mesh_data()))
    assert mesh["positions"] == [
        (float(index), -float(index), 2.0 * index) for index in range(MESH["vertex_count"])
    ]
    assert mesh["uvs"] == [
        (index * 0.0625, 1.0 - index * 0.03125) for index in range(MESH["vertex_count"])
    ]


def test_a_normal_is_handed_over_as_stored_and_not_rescaled():
    """The stage normalises; the exporter does not invent geometry.

    Real files carry normals that are not quite unit length (measured: 0.9888 and 1.025 in two donor
    bodies). Dividing them here would quietly redraw the model, and a mesh that differs from the file
    by a rounding step is a mesh nobody can debug against the bytes on disk.
    """
    mesh = read_krm1(pack_mesh(mesh_data()))
    assert mesh["normals"][0] == (0.0, 1.0, 0.0)
    assert mesh["normals"][7] == (3.5, 1.75, -0.875)
    assert len({mesh["normals"][index] for index in range(MESH["vertex_count"])}) == MESH["vertex_count"]


def test_the_face_indices_arrive_in_the_order_the_file_stored_them():
    mesh = read_krm1(pack_mesh(mesh_data()))
    assert mesh["faces"] == [
        (position * 7) % MESH["vertex_count"] for position in range(MESH["face_index_count"])
    ]


@pytest.mark.parametrize("kind", [0, 1, 2, 3, 4])
def test_a_weight_lands_as_four_bones_and_four_weights_that_add_to_one(kind):
    """BDEF1, BDEF2, BDEF4, SDEF and QDEF all become the four slots a skinned renderer reads.

    A renderer is told four bone numbers per vertex. A file that only names one or two is not missing
    anything — it is saying the rest of the row is not influenced — so the missing slots are filled with
    the bones the row already names and zero weights, and the row adds to one either way.
    """
    bones_per_row, weights_per_row = WEIGHT_TYPE[kind]
    mesh = read_krm1(pack_mesh(mesh_data(weight_kind=kind)))
    bones = MESH["bone_count"]

    for index, (row_bones, row_weights) in enumerate(mesh["skin"]):
        assert len(row_bones) == 4 and len(row_weights) == 4
        assert sum(row_weights) == pytest.approx(1.0), f"vertex {index} of type {kind}"
        assert set(row_bones) <= set(range(MESH["bone_count"]))
        assert row_bones[0] == index % bones

    rows = [row for row, _ in mesh["skin"]]
    if kind == 0:
        assert all(row == (row[0],) * 4 for row in rows)
        assert all(weights == (1.0, 0.0, 0.0, 0.0) for _, weights in mesh["skin"])
    if kind in (1, 3):
        # Two bones, one weight: the second weight is what is left, and SDEF's C, R0 and R1 are symmetry
        # maths the stage does not run, so the row is four slots wide and two bones deep.
        assert all(row == (row[0], row[1], row[0], row[1]) for row in rows)
        assert all(row[1] == (index + 1) % bones for index, row in enumerate(rows))
        assert all(weights[2:] == (0.0, 0.0) for _, weights in mesh["skin"])
        assert all(weights[0] + weights[1] == pytest.approx(1.0) for _, weights in mesh["skin"])
    if kind in (2, 4):
        assert all(
            row == tuple((index + slot) % bones for slot in range(4))
            for index, row in enumerate(rows)
        )
        assert [weights for _, weights in mesh["skin"]][0] == (1.0, 0.0, 0.0, 0.0)
        assert [weights for _, weights in mesh["skin"]][1] == (0.5, 0.25, 0.125, 0.125)
    if kind == 3:
        # The one weight SDEF writes is the first float after its two bones; the fixture makes it -0.5.
        assert mesh["skin"][0][1][0] == pytest.approx(-0.5)


def test_a_row_that_does_not_add_to_one_is_normalised_and_not_rewritten():
    """Weights that sum to anything but one are a thing converters do, and the stage must not go dark.

    Dividing by the sum keeps the *shape* of the blend — which bones win, in what proportion — and only
    changes the scale, which is the one thing a skinned renderer actually needs. Dropping the row's bones
    or moving weights between them would be the exporter deciding the model is wrong.
    """
    mesh = read_krm1(pack_mesh(mesh_data(weight_kind=2, weight_scale=2.0)))
    assert mesh["skin"][1] == ((1, 2, 3, 4), (0.5, 0.25, 0.125, 0.125))
    assert mesh["skin"][0][1] == (1.0, 0.0, 0.0, 0.0)


def test_a_row_that_adds_to_nothing_keeps_the_bone_it_named_first():
    """A zero-sum row is not a blend at all, so it is read as 'this vertex follows this bone'."""
    mesh = read_krm1(pack_mesh(mesh_data(weight_kind=2, unweighted_last=True)))
    last = mesh["skin"][-1]
    assert last[1] == (1.0, 0.0, 0.0, 0.0)
    assert last[0][0] == (MESH["vertex_count"] - 1) % MESH["bone_count"]


def test_a_bone_number_the_model_does_not_have_is_exported_exactly_as_read():
    """The engine reports what the file says; the client is what keeps a renderer from crashing.

    A careless converter can leave a vertex pointing past the end of the bone table. Clamping it here
    would make the exported mesh describe a bone the model never named, and the model on the stage would
    disagree with the report in the library about how many bones there are.
    """
    mesh = read_krm1(pack_mesh(mesh_data(weight_kind=2, unboned=True)))
    stray = (MESH["vertex_count"] - 1) % MESH["bone_count"] + MESH["bone_count"] + 3
    assert mesh["skin"][-1][0][0] == stray
    assert mesh["counts"]["bone"] == MESH["bone_count"]


def test_a_texture_comes_with_the_path_the_loader_asks_for_and_whether_it_climbs_out():
    """The declared path is the file's own words; the relative one is what a loader can fetch.

    Backslashes are how Windows converters write texture paths and a browser never separates on one, so
    the normalised form travels next to the original. A path that climbs out of the character's folder is
    still exported, still marked — the stage refuses to fetch it, and the user is told why the hair is
    the wrong colour rather than being handed a placeholder with no explanation.
    """
    mesh = read_krm1(pack_mesh(mesh_data(textures=TEXTURES)))
    assert [t["declared"] for t in mesh["textures"]] == list(TEXTURES)
    # The normalised form keeps the climb — `escapes` is what tells the stage not to fetch it. Stripping
    # `../` here would silently retarget a texture onto a different file in the character's folder.
    assert [t["relative"] for t in mesh["textures"]] == ["tex/颜.png", "../escape.bmp", "hair.tga"]
    assert [t["escapes"] for t in mesh["textures"]] == [False, True, False]


def test_a_material_names_its_textures_its_colours_and_the_range_of_indices_it_draws():
    mesh = read_krm1(pack_mesh(mesh_data()))
    materials = mesh["materials"]
    assert [m["name"] for m in materials] == ["m0", "m1", "m2"]
    # The three materials split the file's nine indices, so `first` is the running sum of the one before.
    assert [(m["first"], m["count"]) for m in materials] == [(0, 3), (3, 3), (6, 3)]
    assert materials[1]["diffuse"] == (0.125, 0.875, 0.0625, 1.0)
    assert materials[1]["ambient"] == (0.03125, 0.0625, 0.984375)
    assert materials[1]["specular"] == (0.0625, 0.96875, 0.015625)
    assert materials[1]["shine"] == 0.125
    assert materials[1]["edge_colour"] == (0.875, 0.03125, 0.0625, 0.125)
    assert materials[1]["edge_size"] == 0.0078125
    assert [m["flags"] for m in materials] == [0, 1, 0]
    assert [m["sphere"] for m in materials] == [-1, -1, -1]
    assert [m["sphere_mode"] for m in materials] == [0, 0, 0]
    assert [m["shared_toon"] for m in materials] == [False, False, False]
    assert [m["toon"] for m in materials] == [-1, -1, -1]


def test_a_material_that_draws_nothing_is_not_answered_with_the_first_texture():
    """"No diffuse" and "texture 0" are two different answers, and a renderer may not confuse them."""
    mesh = read_krm1(pack_mesh(mesh_data()))
    assert [m["texture"] for m in mesh["materials"]] == [0, -1, 2]
    assert [m["texture"] for m in read_krm1(
        pack_mesh(mesh_data(textures=("a.png", "b.png", "c.png")))
    )["materials"]] == [0, -1, 2]


def test_a_shared_toon_and_a_sphere_map_are_exported_as_the_numbers_they_are():
    mesh = read_krm1(pack_mesh(mesh_data(materials=("颜",), texture_count=2, sphere_index=1,
                                         shared_toon=True, face_index_count=3)))
    assert mesh["materials"] == [
        {
            "name": "颜",
            "diffuse": (0.0, 1.0, 0.0, 1.0),
            "ambient": (0.0, 0.0, 1.0),
            "specular": (0.0, 1.0, 0.0),
            "shine": 0.0,
            "edge_colour": (1.0, 0.0, 0.0, 0.0),
            "edge_size": 0.0,
            "flags": 0,
            "texture": 0,
            "sphere": 1,
            "sphere_mode": 1,
            "shared_toon": True,
            "toon": 0,
            "first": 0,
            "count": 3,
        }
    ]


def test_a_bone_position_is_the_absolute_one_the_file_stands_at():
    """PMX writes a bone's position in model space, so the export hands over exactly that.

    A relative-to-parent reading would need the parent's position first, which makes the export depend on
    the order the file happens to list its bones in — and the corpus does not agree with itself about
    that order.
    """
    mesh = read_krm1(pack_mesh(mesh_data(bones=BONES, ik_bones=1)))
    assert [b["name"] for b in mesh["bones"]] == list(BONES)
    assert [b["name_en"] for b in mesh["bones"]] == [f"{name}_en" for name in BONES]
    assert [b["parent"] for b in mesh["bones"]] == [-1, 0, 1, 2, 3]
    assert [b["position"] for b in mesh["bones"]] == [
        (float(index), -float(index), index * 0.5) for index in range(len(BONES))
    ]
    assert [b["flags"] for b in mesh["bones"]] == [0x0020, 0, 0, 0, 0]


def test_only_vertex_morphs_reach_the_stage_and_they_keep_their_place_in_the_table():
    """A bone, UV or group morph is a different animation, and the stage does not run any of them.

    The index into the file's own morph table travels with each one, so a morph the client is told about
    by name can be checked against the library's report of the same model rather than assumed to be in
    the same order.
    """
    mesh = read_krm1(pack_mesh(mesh_data(morphs=MORPHS, morph_elements=3)))
    assert len(mesh["morphs"]) == 1
    morph = mesh["morphs"][0]
    assert morph["name"] == "口a"
    assert morph["morph_index"] == 0
    assert morph["elements"] == [
        (index, (index * 0.0625, -index * 0.03125, index * 0.125)) for index in range(3)
    ]


def test_a_model_with_no_vertex_morph_still_carries_the_empty_block():
    mesh = read_krm1(pack_mesh(mesh_data(morphs=(("group", 0), ("bone", 2)))))
    assert mesh["counts"]["vertex_morph"] == 0
    assert mesh["morphs"] == []


def test_certified_rigid_bodies_and_constraints_reach_the_stage():
    mesh = read_krm1(pack_mesh(mesh_data()))
    assert len(mesh["rigid_bodies"]) == 1
    body = mesh["rigid_bodies"][0]
    assert body["bone"] == 0
    assert (body["group"], body["mask"], body["shape"], body["mode"]) == (1, 0xFFFF, 0, 0)
    # The physics block is 32-bit floats, so 0.9 comes back as 0.8999999761581421. Compare by
    # value, not by the decimal spelling the PMX writer was handed.
    assert body["values"] == pytest.approx((
        1.0, 1.0, 1.0,
        0.0, 0.0, 0.0,
        0.0, 0.0, 0.0,
        1.0, 0.9, 0.9, 0.9, 0.9,
    ))
    assert mesh["constraints"] == [{
        "first": 0,
        "second": 0,
        "mode": 0,
        "values": (0.0,) * 12 + (1.0,) * 12,
    }]


def test_the_wide_uv_layers_a_stage_does_not_use_are_left_behind_on_purpose():
    """Three additional UV layers ride in every file the corpus holds, and none of them is drawn.

    The export says so by its own length: a decoder that consumed every byte read none of them, and the
    stride the walk used to step over them is the only place they were ever measured.
    """
    narrow = pack_mesh(mesh_data(additional_uv_num=0))
    wide = pack_mesh(mesh_data(additional_uv_num=3))
    assert read_krm1(narrow) == read_krm1(wide)
    assert len(wide) == len(narrow)


# --- what refuses, and why ---------------------------------------------------------------------------


def test_a_file_whose_morph_table_had_to_be_searched_for_still_gets_its_mesh():
    """The boundary that was searched for sits *behind* everything the blob carries.

    A resynced walk means the sections after the morph table — frames, rigid bodies, joints — were read
    from an offset the file's own element sizes never stated, and `head()` is right to refuse to certify
    those counts. A KRM1 mesh carries none of them. Positions, normals, uvs, skin, faces, textures,
    materials, bones and vertex morphs all come from offsets the file states, and `_agree` checks the
    collector against the counts those offsets earned. Refusing here held back three of the ten donor
    bodies on the strength of bytes the stage never asks for.
    """
    searched = read_krm1(pack_mesh(mesh_data(morphs=MORPHS, morph_padding=96)))
    earned = read_krm1(pack_mesh(mesh_data(morphs=MORPHS)))
    assert searched["rigid_bodies"] == []
    assert searched["constraints"] == []
    assert {key: value for key, value in searched.items() if key not in ("rigid_bodies", "constraints")} == {
        key: value for key, value in earned.items() if key not in ("rigid_bodies", "constraints")
    }


def test_a_resynced_walk_still_refuses_to_certify_the_counts_behind_the_morph_table():
    """The mesh is looser than the report, on purpose: the physics counts stay uncertified.

    Same bytes, different question. `head()` answers "what does this model hold", and past the morph table
    the answer here came from a search, so it says no. `pack_mesh` answers "draw the body", and the body
    was earned.
    """
    model = read_pmx_model(mesh_data(morphs=MORPHS, morph_padding=96))
    assert model.resynced_from is not None
    with pytest.raises(CharacterError) as excinfo:
        model.head()
    assert excinfo.value.code == "pmx_truncated"
    assert "were read from offset" in excinfo.value.message


def test_a_file_with_bytes_the_walk_cannot_place_has_no_mesh():
    with pytest.raises(CharacterError) as excinfo:
        pack_mesh(mesh_data(tail=b"\xff" * 220))
    assert excinfo.value.code == "pmx_truncated"
    assert "not part of any section" in excinfo.value.message


def test_a_file_cut_inside_its_vertices_has_no_mesh():
    with pytest.raises(CharacterError) as excinfo:
        pack_mesh(mesh_data()[:400])
    assert excinfo.value.code == "pmx_truncated"


def test_something_that_is_not_a_pmx_still_says_that():
    with pytest.raises(CharacterError) as excinfo:
        pack_mesh(b"not a model at all")
    assert excinfo.value.code == "not_a_pmx"


# --- the folder lookup -------------------------------------------------------------------------------


def imported_body(directory, *, data: bytes | None = None):
    """A real import, so the profile the lookup reads is the profile the importer writes."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as out:
        out.writestr("Ellen.pmx", data if data is not None else write_pmx(**BODY, name="艾莲"))
        out.writestr("tex/颜.png", b"\x89PNG\r\n\x1a\npixel")
    entry = import_character(directory, buffer.getvalue(), source_name="ellen.zip")
    return entry.profile, directory


def test_a_body_is_exported_from_the_path_its_profile_names(tmp_path):
    profile, directory = imported_body(tmp_path)
    mesh = read_krm1(export_mesh(directory, profile["id"]))
    assert mesh["counts"]["vertex"] == BODY["vertex_count"]
    assert mesh["counts"]["bone"] == BODY["bone_count"]
    assert mesh["counts"]["face_index"] == BODY["face_index_count"]


def test_a_character_that_is_only_a_prop_has_no_mesh_to_export(tmp_path):
    """A weapon is held by someone; there is no body to put on the stage from it.

    The refusal is the one the file route already answers with — `main` is `None`, so there is no path to
    read — and the library row already says `is_character: false`, so the screen that asks can say why
    the stage stayed empty in words the user has already seen.
    """
    prop = write_pmx(
        vertex_count=538, face_index_count=12, texture_count=1, material_count=1, bone_count=4,
        morph_count=1, frame_count=1, rigid_body_count=2, constraint_count=2, name="补妆镜",
    )
    profile, directory = imported_body(tmp_path, data=prop)
    assert profile["main"] is None
    with pytest.raises(CharacterFileNotFound) as excinfo:
        export_mesh(directory, profile["id"])
    assert excinfo.value.entry == profile["id"]


def test_an_id_that_is_not_in_the_library_is_answered_with_the_id(tmp_path):
    imported_body(tmp_path)
    with pytest.raises(CharacterError) as excinfo:
        export_mesh(tmp_path, "nope-nope")
    assert excinfo.value.code == "character_not_found"
    assert excinfo.value.entry == "nope-nope"


def test_a_folder_whose_profile_lies_about_its_own_id_is_not_a_character(tmp_path):
    imported_body(tmp_path)
    (tmp_path / "ghost").mkdir()
    (tmp_path / "ghost" / "profile.json").write_text(
        json.dumps({"id": "someone_else", "main": {"path": "model.pmx"}}), encoding="utf-8"
    )
    with pytest.raises(CharacterError) as excinfo:
        export_mesh(tmp_path, "ghost")
    assert excinfo.value.code == "character_not_found"
    assert excinfo.value.entry == "ghost"


# --- the route ---------------------------------------------------------------------------------------


PREFIX = "/v1/kira/characters"


async def served(harness, tmp_path) -> dict:
    """Import a body the way the library does, and hand back its row."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as out:
        out.writestr("Ellen.pmx", write_pmx(**BODY, name="艾莲", name_en="Ellen"))
        out.writestr("tex/颜.png", b"\x89PNG\r\n\x1a\npixel")
    path = tmp_path / "ellen.zip"
    path.write_bytes(buffer.getvalue())
    answer = await harness.api.post(PREFIX, headers=harness.auth, json={"path": str(path)})
    assert answer.status_code == 201, answer.text
    return answer.json()


async def test_the_route_serves_the_bytes_the_exporter_makes(harness, tmp_path):
    row = await served(harness, tmp_path)
    answer = await harness.api.get(f"{PREFIX}/{row['id']}/mesh", headers=harness.auth)
    assert answer.status_code == 200
    assert answer.headers["content-type"].startswith("application/octet-stream")
    assert answer.content == export_mesh(harness.config.characters_dir, row["id"])
    assert read_krm1(answer.content)["counts"]["vertex"] == BODY["vertex_count"]


async def test_the_mesh_needs_the_bearer_token(harness, tmp_path):
    row = await served(harness, tmp_path)
    assert (await harness.api.get(f"{PREFIX}/{row['id']}/mesh")).status_code == 401


async def test_a_paired_device_can_ask_for_the_mesh(harness, tmp_path):
    """Showing the avatar is what a phone is for, so the read gate is the same one the list uses."""
    row = await served(harness, tmp_path)
    code = (await harness.api.post("/v1/kira/pairing-code", headers=harness.signed)).json()["code"]
    pair = await harness.api.post("/v1/kira/pair", json={"code": code, "name": "phone"})
    token = {"Authorization": f"Bearer {pair.json()['token']}"}
    assert (await harness.api.get(f"{PREFIX}/{row['id']}/mesh", headers=token)).status_code == 200


async def test_a_mesh_for_a_character_that_is_not_here_is_a_404_naming_it(harness):
    answer = await harness.api.get(f"{PREFIX}/nope-nope/mesh", headers=harness.auth)
    assert answer.status_code == 404
    assert answer.json()["error"]["code"] == "character_not_found"
    assert answer.json()["error"]["entry"] == "nope-nope"


async def test_a_prop_only_character_answers_the_same_way_the_cli_did(harness, tmp_path):
    path = tmp_path / "mirror.zip"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as out:
        out.writestr(
            "mirror.pmx",
            write_pmx(vertex_count=538, face_index_count=12, texture_count=1, material_count=1,
                      bone_count=4, morph_count=1, frame_count=1, rigid_body_count=2,
                      constraint_count=2, name="补妆镜"),
        )
    path.write_bytes(buffer.getvalue())
    row = (await harness.api.post(PREFIX, headers=harness.auth, json={"path": str(path)})).json()
    answer = await harness.api.get(f"{PREFIX}/{row['id']}/mesh", headers=harness.auth)
    assert answer.status_code == 404
    assert answer.json()["error"]["code"] == "character_file_not_found"
