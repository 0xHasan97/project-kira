"""KRM1 — the mesh the stage draws, packed by the reader that already walked it.

The browser does not get the PMX. It could not use it: the corpus needs a framing probe, a material
retry and a morph boundary search before its counts mean anything, and `characters.py` is where all of
that was paid for and measured. Repeating it in TypeScript would be two readers of a format the files
themselves disagree about, and the second one is always the one that shows a character with no hair. So
the walk hands its records to a collector as it steps over them, and what crosses the wire is flat —
positions, normals, uvs, skin, faces, textures, materials, bones and the vertex morphs — in one order,
with no offset a browser has to go and find.

The format, little-endian, unpadded, and consumed to the last byte by
`tests/test_mesh_export.py`'s own decoder:

    header    "KRM1" | u32 format | u32 vertex | u32 face index | u32 bone
              | u32 material | u32 texture | u32 vertex morph                  (32 bytes)
    positions vertex_count × 3 × f32        — as the file wrote them, never rescaled
    normals   vertex_count × 3 × f32        — real files carry 0.9888 and 1.025 here
    uvs       vertex_count × 2 × f32        — the first layer; the additional three are not drawn
    skin      vertex_count × (4 × u32 + 4 × f32) — four slots whatever the weight type said
    faces     face_index_count × u32        — in the order the file stored them
    textures  texture_count × (text declared, text relative, u8 escapes)
    materials material_count × (text name, 16 × f32 colour block, u8 flags,
                                 i32 diffuse, i32 sphere, u8 sphere mode, u8 shared toon,
                                 i32 toon, u32 first index, u32 index count)
    bones     bone_count × (text name, text english, i32 parent, 3 × f32 position, u32 flags)
    morphs    vertex_morph_count × (u32 index in the PMX table, text name, u32 element count,
                                    elements × (u32 vertex, 3 × f32 offset))
    physics   u32 rigid body | u32 constraint
    bodies    rigid_body_count × (i32 bone, u8 group, u16 mask, u8 shape, u8 mode,
                                  3 × f32 size, 3 × f32 bone-relative position,
                                  3 × f32 rotation, 5 × f32 mass/damping/restitution/friction)
    joints    constraint_count × (i32 first body, i32 second body, 24 × f32 pose/limits/springs)

What is deliberately not here: sphere and toon *tables* (the numbers travel, the files do not), additional
UV layers, bone/UV/group/improvement morphs, and soft bodies. A model whose geometry walk needed guessing
still renders, but its physics is omitted unless the walk certified the frames, bodies, joints and tail.
"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Any

from .characters import (
    PMX_TRUNCATED,
    CharacterError,
    CharacterFileNotFound,
    WEIGHT_FLOATS,
    WEIGHT_INDICES,
    WEIGHT_WEIGHTS,
    get_character,
    normalise_texture_path,
    read_pmx_model,
)

KRM1_MAGIC = b"KRM1"
#: Bumped only by a change a decoder cannot read past. The stage checks it and refuses a blob whose number
#: it does not know, which is the difference between an old client on a new engine and a wrong mesh.
KRM1_FORMAT = 2

#: What the route answers with. A mesh is not a texture: nothing in a browser decodes it, and a type that
#: implied one would invite a caller to open it in a tab.
MESH_MEDIA_TYPE = "application/octet-stream"

#: Table indices are read unsigned wherever the field can only ever name a row — a vertex's bone slot, a
#: face, a morphed vertex — and signed wherever `-1` is an answer, which is what `characters._Cursor.idx`
#: does for the walk.
_UNSIGNED = {1: "<B", 2: "<H", 4: "<I"}


def _floats(raw: bytes, at: int, count: int) -> tuple[float, ...]:
    return struct.unpack_from(f"<{count}f", raw, at)


def _text(value: str) -> bytes:
    raw = value.encode("utf-8")
    return struct.pack("<I", len(raw)) + raw


def _skin_row(kind: int, weight: bytes, bone_size: int) -> tuple[tuple[int, ...], tuple[float, ...]]:
    """Four bone slots and four weights, whichever of the five weight types the file spoke.

    A skinned renderer is told four influences per vertex. A file that names one or two is not missing
    anything — it is saying the rest of the vertex is not influenced by another bone — so the spare slots
    repeat the bones the row already named at zero weight, and the row adds to one either way. Four
    weights that do not add to one are what converters leave behind: the row is divided by its own sum,
    which keeps which bones win and in what proportion and changes only the scale. A row that adds to
    nothing is not a blend at all, so it is read as "this vertex follows the bone it named first".
    """
    named = WEIGHT_INDICES[kind]
    code = _UNSIGNED[bone_size]
    bones = tuple(struct.unpack_from(code, weight, slot * bone_size)[0] for slot in range(named))
    floats = _floats(weight, named * bone_size, WEIGHT_FLOATS[kind]) if WEIGHT_FLOATS[kind] else ()
    if kind == 0:
        return bones * 4, (1.0, 0.0, 0.0, 0.0)
    if kind in (1, 3):
        # Two bones and one weight; the second weight is what is left of the vertex. SDEF's nine floats
        # behind it are C, R0 and R1 — symmetry maths no stage runs — so they are read for their width and
        # dropped.
        return (bones[0], bones[1], bones[0], bones[1]), (floats[0], 1.0 - floats[0], 0.0, 0.0)
    weights = floats[: WEIGHT_WEIGHTS[kind]]
    total = sum(weights)
    if total == 0.0:
        return bones, (1.0, 0.0, 0.0, 0.0)
    if total != 1.0:
        weights = tuple(value / total for value in weights)
    return bones, weights


class MeshGeometry:
    """What the walk stepped over, kept in the order it stepped over it.

    `read_pmx_model` duck-types these calls on whatever object it is handed, and this collector does not
    read a file: every record arrives already bounded by the walk, so a mesh and the report of the same
    bytes cannot end up disagreeing about where a section stopped. `widths` is the one thing it has to be
    told rather than given, because the file — not this code — says how wide its own indexes are.
    """

    def __init__(self) -> None:
        self.vertex_size = 2
        self.bone_size = 2
        self.positions: list[tuple[float, ...]] = []
        self.normals: list[tuple[float, ...]] = []
        self.uvs: list[tuple[float, ...]] = []
        self.skin: list[tuple[tuple[int, ...], tuple[float, ...]]] = []
        #: Not `faces`: that name belongs to the method the walk calls, and an attribute here would shadow it.
        self.face_indices: list[int] = []
        self.materials: list[dict[str, Any]] = []
        self.material_total = 0
        self.bones: list[dict[str, Any]] = []
        self.morphs: list[dict[str, Any]] = []
        self.morph_total = 0
        self.rigid_bodies: list[dict[str, Any]] = []
        self.rigid_total = 0
        self.constraints: list[dict[str, Any]] = []
        self.constraint_total = 0

    def widths(self, *, vertex_size: int, bone_size: int) -> None:
        self.vertex_size, self.bone_size = vertex_size, bone_size

    def vertex(self, body: bytes, kind: int, weight: bytes) -> None:
        """The record's first 32 bytes are position, normal and uv at every additional-UV count."""
        self.positions.append(_floats(body, 0, 3))
        self.normals.append(_floats(body, 12, 3))
        self.uvs.append(_floats(body, 24, 2))
        self.skin.append(_skin_row(kind, weight, self.bone_size))

    def faces(self, blob: bytes, total: int) -> None:
        code = _UNSIGNED[self.vertex_size]
        self.face_indices = [
            struct.unpack_from(code, blob, at)[0]
            for at in range(0, total * self.vertex_size, self.vertex_size)
        ]

    def begin_materials(self, total: int) -> None:
        self.materials, self.material_total = [], total

    def material(
        self, name: str, colours: bytes, diffuse: int, sphere: int, sphere_mode: int,
        shared_toon: int, toon: int, own: int,
    ) -> None:
        # The 65-byte colour block is position-in-record, not position-in-file: diffuse at 0, ambient at
        # 16, specular at 28, shine at 40, the flag byte at 44, edge colour at 45, edge size at 61.
        self.materials.append(
            {
                "name": name,
                "diffuse": _floats(colours, 0, 4),
                "ambient": _floats(colours, 16, 3),
                "specular": _floats(colours, 28, 3),
                "shine": _floats(colours, 40, 1)[0],
                "flags": colours[44],
                "edge_colour": _floats(colours, 45, 4),
                "edge_size": _floats(colours, 61, 1)[0],
                "texture": diffuse,
                "sphere": sphere,
                "sphere_mode": sphere_mode,
                "shared_toon": bool(shared_toon),
                "toon": toon,
                "count": own,
            }
        )

    def bone(self, name: str, name_en: str, position: bytes, parent: int, flags: int) -> None:
        self.bones.append(
            {
                "name": name,
                "name_en": name_en,
                "parent": parent,
                "position": _floats(position, 0, 3),
                "flags": flags,
            }
        )

    def begin_morphs(self, total: int) -> None:
        self.morphs, self.morph_total = [], total

    def vertex_morph(self, name: str, index: int, payload: bytes, size: int) -> None:
        code = _UNSIGNED[self.vertex_size]
        step = self.vertex_size + 12
        elements = [
            (
                struct.unpack_from(code, payload, at)[0],
                _floats(payload, at + self.vertex_size, 3),
            )
            for at in range(0, size * step, step)
        ]
        self.morphs.append({"morph_index": index, "name": name, "elements": elements})

    def begin_rigids(self, total: int) -> None:
        self.rigid_bodies, self.rigid_total = [], total

    def rigid(self, bone: int, group: int, mask: int, shape: int, payload: bytes, mode: int) -> None:
        values = struct.unpack("<14f", payload)
        position = list(values[3:6])
        if bone >= 0 and bone < len(self.bones):
            origin = self.bones[bone]["position"]
            position = [position[at] - origin[at] for at in range(3)]
        self.rigid_bodies.append(
            {
                "bone": bone,
                "group": group,
                "mask": mask,
                "shape": shape,
                "mode": mode,
                "size": values[:3],
                "position": tuple(position),
                "rotation": values[6:9],
                "physics": values[9:14],
            }
        )

    def begin_constraints(self, total: int) -> None:
        self.constraints, self.constraint_total = [], total

    def constraint(self, mode: int, first: int, second: int, payload: bytes) -> None:
        values = struct.unpack("<24f", payload)
        if mode == 0 and 0 <= first < len(self.rigid_bodies) and 0 <= second < len(self.rigid_bodies):
            body = self.rigid_bodies[second]
            parent = self.rigid_bodies[first]["bone"]
            if body["mode"] == 2 and body["bone"] >= 0 and self.bones[body["bone"]]["parent"] == parent:
                body["mode"] = 1
        self.constraints.append({"mode": mode, "first": first, "second": second, "values": values})


def _agree(head: Any, texture_paths: tuple[str, ...], geometry: MeshGeometry, physics: bool) -> None:
    """Every block the collector holds has to be as long as the certified count says.

    A walk that ran out of file mid-section leaves a collector holding fewer records than the file counts,
    and the certificate is what notices — but the refusal it raises is about the counts, not about the mesh.
    This is the check that stops a mesh with a hole in it from being packed anyway, and it names the block
    that came up short instead of leaving a stage to draw half a face.
    """
    checks = (
        ("vertex position", len(geometry.positions), head.vertex_count),
        ("vertex normal", len(geometry.normals), head.vertex_count),
        ("vertex uv", len(geometry.uvs), head.vertex_count),
        ("vertex weight", len(geometry.skin), head.vertex_count),
        ("face index", len(geometry.face_indices), head.face_index_count),
        ("texture", len(texture_paths), head.texture_count),
        ("material", len(geometry.materials), head.material_count),
        ("material", geometry.material_total, head.material_count),
        ("bone", len(geometry.bones), head.bone_count),
        ("morph", geometry.morph_total, head.morph_count),
        *((
            ("rigid body", len(geometry.rigid_bodies), geometry.rigid_total),
            ("rigid body", geometry.rigid_total, head.rigid_body_count),
            ("constraint", len(geometry.constraints), geometry.constraint_total),
            ("constraint", geometry.constraint_total, head.constraint_count),
        ) if physics else ()),
    )
    for what, got, want in checks:
        if got != want:
            raise CharacterError(
                f"the mesh walk reached {got} of the {want} {what}(s) the file states, so this model's "
                f"geometry is not the geometry its profile describes",
                code=PMX_TRUNCATED,
            )


def _block(values: list[tuple[float, ...]], per: int) -> bytes:
    if not values:
        return b""
    return struct.pack(f"<{per * len(values)}f", *(part for row in values for part in row))


def _pack(head: Any, texture_paths: tuple[str, ...], geometry: MeshGeometry, physics: bool) -> bytes:
    out = bytearray(KRM1_MAGIC)
    for value in (
        KRM1_FORMAT,
        head.vertex_count,
        head.face_index_count,
        head.bone_count,
        head.material_count,
        len(texture_paths),
        len(geometry.morphs),
    ):
        out += struct.pack("<I", value)

    out += _block(geometry.positions, 3)
    out += _block(geometry.normals, 3)
    out += _block(geometry.uvs, 2)
    for bones, weights in geometry.skin:
        out += struct.pack("<4I", *bones) + struct.pack("<4f", *weights)
    if geometry.face_indices:
        out += struct.pack(f"<{len(geometry.face_indices)}I", *geometry.face_indices)

    for declared in texture_paths:
        relative, escapes = normalise_texture_path(declared)
        out += _text(declared) + _text(relative) + bytes([1 if escapes else 0])

    first = 0
    for material in geometry.materials:
        out += _text(material["name"])
        out += struct.pack(
            "<16f",
            *material["diffuse"], *material["ambient"], *material["specular"], material["shine"],
            *material["edge_colour"], material["edge_size"],
        )
        out += struct.pack(
            "<BiiBBiII",
            material["flags"], material["texture"], material["sphere"], material["sphere_mode"],
            1 if material["shared_toon"] else 0, material["toon"], first, material["count"],
        )
        first += material["count"]

    for bone in geometry.bones:
        out += (
            _text(bone["name"]) + _text(bone["name_en"])
            + struct.pack("<i3fI", bone["parent"], *bone["position"], bone["flags"])
        )

    for morph in geometry.morphs:
        out += struct.pack("<I", morph["morph_index"]) + _text(morph["name"])
        out += struct.pack("<I", len(morph["elements"]))
        for vertex, offset in morph["elements"]:
            out += struct.pack("<I3f", vertex, *offset)

    bodies = geometry.rigid_bodies if physics else []
    constraints = geometry.constraints if physics else []
    out += struct.pack("<II", len(bodies), len(constraints))
    for body in bodies:
        out += struct.pack("<iBHBB", body["bone"], body["group"], body["mask"], body["shape"], body["mode"])
        out += struct.pack("<14f", *body["size"], *body["position"], *body["rotation"], *body["physics"])
    for constraint in constraints:
        out += struct.pack("<iiB", constraint["first"], constraint["second"], constraint["mode"])
        out += struct.pack("<24f", *constraint["values"])
    return bytes(out)


def pack_mesh(data: bytes) -> bytes:
    """One PMX's bytes in, one KRM1 blob out — or a refusal that says which part is uncertified.

    `read_pmx_model` walks once and collects; `render_head()` is what lets the result out. It is the same
    certificate `head()` gives, minus the three counts a KRM1 blob does not carry — frames, rigid bodies,
    joints — so a file whose *morph* table had to be searched for a boundary still gets its body: the
    search lands behind everything the stage draws, and `_agree` below re-measures every block the walk
    actually collected against the counts the file states. What still refuses is a walk that stopped early
    or left bytes it cannot place, because that is a hole in the geometry itself.
    """
    geometry = MeshGeometry()
    model = read_pmx_model(data, geometry=geometry)
    head = model.render_head()
    physics = model.unreadable is None and model.resynced_from is None and model.trailing_bytes == 0
    _agree(head, model.texture_paths, geometry, physics)
    return _pack(head, model.texture_paths, geometry, physics)


def export_mesh(directory: "Path | str", character_id: str) -> bytes:
    """The body of one character in the library, as the mesh the stage loads.

    The path comes from the profile the importer wrote, so the request can name nothing but a character
    that is already here — no traversal, no caller-supplied file, and no model that was never imported.
    A prop-only archive has no body to export, which is the same answer its library row already gives.
    """
    profile = get_character(directory, character_id)
    main = profile.get("main") if isinstance(profile, dict) else None
    path = str(main.get("path") or "") if isinstance(main, dict) else ""
    if not path:
        raise CharacterFileNotFound(
            f"character '{character_id}' has no body to put on the stage; what was imported is "
            f"{profile['reason']}",
            entry=character_id,
        )
    target = Path(directory) / character_id / path
    try:
        data = target.read_bytes()
    except OSError as exc:
        raise CharacterFileNotFound(
            f"character '{character_id}' has no mesh to export: its model '{path}' could not be read "
            f"({exc.strerror or exc.__class__.__name__})",
            entry=character_id,
        ) from exc
    return pack_mesh(data)
