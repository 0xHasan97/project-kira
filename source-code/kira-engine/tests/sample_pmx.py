"""A PMX writer that produces a file the engine can walk to the end of.

Kira cannot carry a licensed character into its suite (every model archive in the donor folder says
请勿二次配布 — no redistribution), so the engine's PMX tests need bytes that are *shaped* like real
ones. This writes them: the header order the real files use, the record layout each section is measured
to have, and a body long enough that a reader which mis-reads one count cannot possibly finish.

    "PMX "  |  float32 version  |  uint8 headerSize  |  headerSize setting bytes
    name, english name, comment, english comment     (each uint32 byte-length + bytes)
    counts and sections: each count immediately before its own section (the real files' framing), or
    all nine in the header block (what the published format note says) — `counts_inline=` picks one
    the last section ends at the end of the file, unless `trailing_comment` or `tail` says otherwise

The setting block is always read as: encoding, additional-UV count, then the **six bytes at positions
2..7** as the index sizes for vertex/texture/material/bone/morph/rigid — which is what makes a 2.0 file
(8 bytes) and a 2.1 file (11) parse with the same code. Position and not "the last six", because a 2.1
file appends three more after them.

Four things the tests need to be able to turn independently, none of which the format note settles
because the corpus disagrees with it: `counts_inline` (20 of 20 donor files write inline counts),
`material_framing` (20 of 20 write one memo and no draw flag), `bone_morph_rotation` (character rips
carry a quaternion where the note says a translation only), and `morph_padding` (4 of 20 carry morph
elements wider than anything measured, which is what the reader's boundary search is for).

A second group of knobs serves the mesh reader rather than the framing search: `varied` makes every field
depend on the record's position, `weight_kind` selects the skinning type, `morph_elements` the size of a
morph's element list, and `unboned` plants a bone number outside the bone table. See `write_pmx`.
"""

from __future__ import annotations

import struct

MAGIC = b"PMX "

#: vertex, texture, material, bone, morph, rigid body — in the order the setting block writes them.
#: These are the widths the real files use and the reason one index can be a byte while another is four.
DEFAULT_INDEX_SIZES = (2, 1, 1, 2, 1, 2)

#: The four model-info strings, in the order a real file carries them.
DEFAULT_STRINGS = ("name", "name_en", "comment", "comment_en")

#: Paths shaped like the donor corpus: a Windows separator, a format no browser decodes, and one file
#: the archive does not actually carry.
DEFAULT_TEXTURES = ("tex\\颜.png", "skin.bmp", "hair.bmp")


def _text(value: str, encoding: int) -> bytes:
    raw = value.encode("utf-16-le") if encoding == 0 else value.encode("utf-8")
    return struct.pack("<I", len(raw)) + raw


def _index(value: int, size: int) -> bytes:
    """One index at the width the setting block gave this file — `-1` meaning "none"."""
    return struct.pack({1: "<b", 2: "<h", 4: "<i"}[size], value)


def _unit_vertex(additional_uv: int, bone_size: int) -> bytes:
    """One vertex whose normal is exactly (0, 1, 0).

    The normal is the only field in a PMX that proves where the mesh starts: a framing probe reads the
    bytes twelve long at that offset and rejects anything that is not unit length. A position of all
    zeros and a weight type of BDEF1 keep the record honest about what it is not.
    """
    return (
        struct.pack("<3f", 0.0, 0.0, 0.0)
        + struct.pack("<3f", 0.0, 1.0, 0.0)
        + struct.pack("<2f", 0.0, 0.0)
        + b"\x00" * (16 * additional_uv)
        + b"\x00"  # BDEF1
        + _index(0, bone_size)
        + struct.pack("<f", 1.0)  # edge scale
    )


#: The weight types a file can name, and how many bones each one speaks for. SDEF is the odd one: the
#: format gives it two bones, one weight, and then C, R0 and R1 — nine more floats of symmetry maths no
#: stage runs. No vertex in the donor corpus uses kind 3 or 4, which is why `weight_kind` is a knob here
#: rather than something a corpus file already shows.
_WEIGHT_BONES = {0: 1, 1: 2, 2: 4, 3: 2, 4: 4}

#: The payload after the two bones of an SDEF record: one weight and C, R0, R1 as three vectors.
_SDEF_FLOATS = 1 + 9


class _Parts:
    """The widths one file's sections will be written at, so the record builders stay short."""

    def __init__(self, *, encoding: int, additional_uv: int, index_sizes: tuple[int, ...],
                 version: float, material_framing: str, bone_morph_rotation: bool,
                 morph_padding: int = 0, sphere_index: int = -1, shared_toon: bool = False,
                 varied: bool = False, weight_kind: int = 0, morph_elements: int = 1,
                 bone_count: int = 1, vertex_count: int = 1, texture_count: int = 0,
                 unboned: bool = False, weight_scale: float = 1.0,
                 unweighted_last: bool = False) -> None:
        self.encoding = encoding
        self.additional_uv = additional_uv
        self.vertex_size, self.texture_size, self.material_size, self.bone_size = index_sizes[:4]
        self.morph_size, self.rigid_size = index_sizes[4:6]
        self.version = version
        self.material_framing = material_framing
        self.bone_morph_rotation = bone_morph_rotation
        self.morph_padding = morph_padding
        self.sphere_index = sphere_index
        self.shared_toon = shared_toon
        self.varied = varied
        self.weight_kind = weight_kind
        self.morph_elements = morph_elements
        self.bone_count = max(bone_count, 1)
        self.vertex_count = max(vertex_count, 1)
        self.texture_count = texture_count
        self.unboned = unboned
        self.weight_scale = weight_scale
        self.unweighted_last = unweighted_last

    def text(self, value: str) -> bytes:
        return _text(value, self.encoding)

    def bone(self, value: int) -> bytes:
        return _index(value, self.bone_size)

    def texture(self, value: int) -> bytes:
        return _index(value, self.texture_size)

    def rigid(self, value: int) -> bytes:
        return _index(value, self.rigid_size)

    def vertex_stride(self) -> int:
        return 32 + 16 * self.additional_uv + 1 + self._weight_bytes(self.weight_kind) + 4

    def _weight_bytes(self, kind: int) -> int:
        """The payload after the type byte, which is the format's own table and nothing else."""
        if kind == 0:
            return self.bone_size
        if kind == 1:
            return 2 * self.bone_size + 4
        if kind in (2, 4):
            return 4 * self.bone_size + 16
        return 2 * self.bone_size + 4 * _SDEF_FLOATS

    def weights(self, kind: int, index: int) -> bytes:
        """The skinning payload of record `index`, at the width `kind` says it has.

        The bones a vertex names walk around the bone table, and the weights are sums of quarters — both
        exact in float32, so a test can compare what it asked for to what a reader hands back without
        either of them rounding. `weight_scale` multiplies them out of a sum of one, which is what
        converters do, and `unweighted_last` zeroes the last row entirely.
        """
        bones = [(index + slot) % self.bone_count for slot in range(_WEIGHT_BONES[kind])]
        if self.unboned and index == self.vertex_count - 1:
            # The shape a careless converter leaves behind: a bone number the bone table has never heard
            # of. An exporter that clamped it to zero would make the vertex follow a bone it did not name.
            bones = [bones[0] + self.bone_count + 3] + bones[1:]
        if kind == 0:
            return self.bone(bones[0])
        if kind == 1:
            weight = (index % 4) * 0.25 * self.weight_scale
            return self.bone(bones[0]) + self.bone(bones[1]) + struct.pack("<f", weight)
        if kind == 3:
            # SDEF's floats after the two bones are C, R0 and R1 — symmetry maths, not a blend to scale.
            symmetry = [(slot - 4) * 0.125 for slot in range(_SDEF_FLOATS)]
            return (
                self.bone(bones[0]) + self.bone(bones[1])
                + struct.pack(f"<{_SDEF_FLOATS}f", *symmetry)
            )
        if self.unweighted_last and index == self.vertex_count - 1:
            weights = [0.0, 0.0, 0.0, 0.0]
        else:
            weights = [w * self.weight_scale for w in (
                [0.5, 0.25, 0.125, 0.125] if index % 2 else [1.0, 0.0, 0.0, 0.0]
            )]
        return b"".join(self.bone(bone) for bone in bones) + struct.pack("<4f", *weights)

    def vertex(self, index: int) -> bytes:
        """One vertex record.

        A uniform file cannot prove a payload read: twenty-nine thousand identical records decode the same
        way whether the reader walks the stride or guesses at it. `varied` makes every field depend on the
        record's own number — a position and a normal that differ from each other, a uv that walks, four
        weight slots — and keeps the *first* normal at (0, 1, 0), because that is the one byte the framing
        probe measures and the probe decides the shape of the whole file.
        """
        if not self.varied:
            return _unit_vertex(self.additional_uv, self.bone_size)
        position = struct.pack("<3f", float(index), -float(index), 2.0 * index)
        normal = (
            struct.pack("<3f", 0.0, 1.0, 0.0) if index == 0
            else struct.pack("<3f", index * 0.5, index * 0.25, -index * 0.125)
        )
        uv = struct.pack("<2f", index * 0.0625, 1.0 - index * 0.03125)
        return (
            position + normal + uv
            + b"\x00" * (16 * self.additional_uv)
            + struct.pack("<B", self.weight_kind)
            + self.weights(self.weight_kind, index)
            + struct.pack("<f", 1.0)  # edge scale
        )

    def morph_step(self, kind: int) -> int:
        """One morph element of the given type, at the width this file's index sizes imply."""
        bone_step = self.bone_size + 12 + (16 if self.bone_morph_rotation else 0)
        if kind in (0, 9):
            return self.morph_size + 4
        if kind == 1:
            return self.vertex_size + 12
        if kind == 2:
            return bone_step
        if kind in (3, 4, 5, 6, 7, 8):
            return self.vertex_size + 16
        if kind == 10:
            return self.rigid_size + 25
        raise ValueError(f"morph type {kind} has no element size")

    def vertices(self, count: int) -> bytes:
        return b"".join(self.vertex(index) for index in range(count))

    def faces(self, count: int) -> bytes:
        # Every triangle points at vertex 0, which is what makes the index count a real number here.
        if not self.varied:
            return _index(0, self.vertex_size) * count
        # Walked by sevens so consecutive indices are different numbers: a reader that returns the file
        # in the order it *stored* them and one that sorted them do not give the same triangles.
        return b"".join(
            _index((position * 7) % self.vertex_count, self.vertex_size) for position in range(count)
        )

    def textures(self, paths: tuple[str, ...]) -> bytes:
        return b"".join(self.text(path) for path in paths)

    def material_colours(self, index: int) -> bytes:
        """diffuse, alpha, ambient, specular, shine, edge flag, edge colour, edge size — all distinct.

        Every value is a sum of eighths, so what a reader hands back compares equal to what was asked for
        with no rounding in the way, and no two materials in the file share a colour.
        """
        if not self.varied:
            return b"\x00" * (44 + 1 + 16 + 4)  # colours, flags, toon colour, edge size
        eighth = index * 0.125
        return (
            struct.pack("<4f", eighth, 1.0 - eighth, eighth * 0.5, 1.0)  # diffuse + alpha
            + struct.pack("<3f", eighth * 0.25, eighth * 0.5, 1.0 - eighth * 0.125)  # ambient
            + struct.pack("<3f", eighth * 0.5, 1.0 - eighth * 0.25, eighth * 0.125)  # specular
            + struct.pack("<f", eighth)  # shine
            + struct.pack("<B", index % 2)  # the draw-side flag byte, verbatim
            + struct.pack("<4f", 1.0 - eighth, eighth * 0.25, eighth * 0.5, eighth)  # edge colour
            + struct.pack("<f", eighth * 0.0625)  # edge size
        )

    def materials(self, names: tuple[str, ...], face_index_count: int) -> bytes:
        """`face_index_count` indices spread across the materials so that they add up to it exactly.

        The sum is the only thing that tells a reader which material framing a file used, so the writer
        has to keep it true: the first material draws the remainder and the rest draw nothing, which is
        a legal (if dull) split.
        """
        if not names:
            return b""
        share, remainder = divmod(face_index_count, len(names))
        out = bytearray()
        for position, name in enumerate(names):
            own = remainder + share if position == 0 else share
            # Half of the varied materials name no diffuse at all, because "no texture" and "the first
            # texture" are two different answers a renderer must not be allowed to confuse.
            diffuse = -1 if (self.varied and position % 2) else (
                position % self.texture_count if self.varied and self.texture_count else 0
            )
            out += self.text(name) + self.text("")
            out += self.material_colours(position)
            out += self.texture(diffuse) + self.texture(self.sphere_index)
            out += b"\x01" if self.sphere_index >= 0 else b"\x00"  # sphere mode: add if there is one
            out += b"\x01" if self.shared_toon else b"\x00"  # shared toon: index into the built-in table
            out += struct.pack("<B", 0) if self.shared_toon else self.texture(-1)
            if self.material_framing == "draw_and_memos":
                out += b"\x01" + self.text("memo") + self.text("memo en")
            else:
                out += self.text("memo")
            out += struct.pack("<I", own)
        return bytes(out)

    def bones(self, names: tuple[str, ...], ik_count: int) -> bytes:
        out = bytearray()
        for position, name in enumerate(names):
            english = f"{name}_en" if self.varied else ""
            out += self.text(name) + self.text(english)
            out += struct.pack("<3f", *self.bone_position(position))
            out += self.bone(max(position - 1, -1))
            out += struct.pack("<i", 0)  # deform layer
            flags = 0x0020 if position < ik_count else 0x0000
            out += struct.pack("<H", flags)
            if flags & 0x0001:
                out += self.bone(0)
            else:
                out += struct.pack("<3f", 0.0, 1.0, 0.0)
            if flags & 0x0020:
                # An IK bone in the order the format really writes: target, descendant count, angle
                # limit, then the link count as its own field and the links behind it.
                out += self.bone(0)
                out += struct.pack("<i", 2)
                out += struct.pack("<f", 3.14159)
                out += struct.pack("<I", 2)
                for link in range(2):
                    out += self.bone(link)
                    out += b"\x01" if link == 0 else b"\x00"
                    if link == 0:
                        out += struct.pack("<6f", 0.0, 1.0, 0.0, 1.0, 1.0, 0.0)
        return bytes(out)

    def bone_position(self, index: int) -> tuple[float, float, float]:
        """PMX stores a bone's position in model space, so a varied file makes each one different."""
        if not self.varied:
            return (0.0, 0.0, 0.0)
        return (float(index), -float(index), index * 0.5)

    def morph_element(self, kind: int, position: int) -> bytes:
        """One element of a morph of type `kind`, the `position`-th in its list.

        The vertex morph is the only type a stage can do something with — an index into the mesh plus the
        offset that morph pushes it to — so a varied file writes that pair for real, with each element
        pointing at a different vertex. Every other type stays zeros of the width the format measures,
        because the reader's job for them is to find the next morph, not to interpret them.
        """
        if self.varied and kind == 1:
            vertex = _index(position % self.vertex_count, self.vertex_size)
            return vertex + struct.pack(
                "<3f", position * 0.0625, -position * 0.03125, position * 0.125
            )
        return b"\x00" * self.morph_step(kind)

    def morphs(self, entries: tuple[tuple[str, int], ...]) -> bytes:
        out = bytearray()
        for name, kind in entries:
            out += self.text(name) + self.text("")
            out += struct.pack("<I", 8) if self.version >= 2.1 else b"\x08"  # panel
            out += bytes([kind])
            out += struct.pack("<I", self.morph_elements)
            for position in range(self.morph_elements):
                out += self.morph_element(kind, position)
            # Four of the twenty donor files carry morph elements wider than anything the format note
            # measures, which is what the reader's boundary search exists for. Padding is the smallest
            # shape of that: the section is longer than its own element sizes say, by the same amount
            # every record.
            out += b"\x00" * self.morph_padding
        return bytes(out)

    def frames(self, names: tuple[str, ...]) -> bytes:
        out = bytearray()
        for name in names:
            out += self.text(name) + self.text("")
            out += b"\x00"  # not the special frame
            out += struct.pack("<I", 1)
            out += b"\x00" + self.bone(0)  # one bone entry
        return bytes(out)

    def rigids(self, count: int) -> bytes:
        out = bytearray()
        for _ in range(count):
            out += self.text("rigid") + self.text("")
            out += self.bone(0)
            out += b"\x01" + struct.pack("<H", 0xFFFF)  # group, then a *two*-byte mask
            out += b"\x00"  # box
            out += struct.pack("<3f", 1.0, 1.0, 1.0)  # size
            out += struct.pack("<3f", 0.0, 0.0, 0.0)  # position
            out += struct.pack("<3f", 0.0, 0.0, 0.0)  # rotation
            out += struct.pack("<5f", 1.0, 0.9, 0.9, 0.9, 0.9)  # mass + 4 damping/restitution/friction
            out += b"\x00"  # follow bone
        return bytes(out)

    def joints(self, count: int) -> bytes:
        out = bytearray()
        for _ in range(count):
            out += self.text("joint") + self.text("")
            out += b"\x00"  # mode
            out += self.rigid(0) + self.rigid(0)
            out += struct.pack("<24f", *([0.0] * 12 + [1.0] * 12))  # 96 bytes of limits and springs
        return bytes(out)


def write_pmx(
    *,
    version: float = 2.0,
    encoding: int = 0,
    additional_uv_num: int = 3,
    index_sizes: tuple[int, ...] = DEFAULT_INDEX_SIZES,
    extra_setting_bytes: bytes = b"",
    counts_inline: bool = True,
    material_framing: str = "memo_only",
    bone_morph_rotation: bool = False,
    morph_padding: int = 0,
    sphere_index: int = -1,
    shared_toon: bool = False,
    varied: bool = False,
    weight_kind: int = 0,
    morph_elements: int = 1,
    unboned: bool = False,
    weight_scale: float = 1.0,
    unweighted_last: bool = False,
    name: str = "エレン",
    name_en: str = "Ellen",
    comment: str = "",
    comment_en: str = "",
    strings: tuple[str, ...] | None = None,
    vertex_count: int = 29_287,
    face_index_count: int = 83_310,
    texture_count: int = 8,
    material_count: int = 19,
    bone_count: int = 487,
    morph_count: int = 59,
    frame_count: int = 13,
    rigid_body_count: int = 317,
    constraint_count: int = 462,
    textures: tuple[str, ...] | None = None,
    materials: tuple[str, ...] | None = None,
    bones: tuple[str, ...] | None = None,
    morphs: tuple[tuple[str, int], ...] | None = None,
    frames: tuple[str, ...] | None = None,
    ik_bones: int = 0,
    trailing_comment: str | None = None,
    tail: bytes = b"",
) -> bytes:
    """One complete PMX, every section written in the order the format and the corpus agree on.

    The `*_count` integers are what a test asks for and what the reader must give back; the name-list
    arguments (`textures=`, `bones=`, `morphs=`, `frames=`) override both the count and the content for
    the sections a test cares about naming, which is why 29 287 anonymous vertices can stand behind a
    model whose bones are worth reading.

    Four knobs exist for tests that read the mesh rather than only its header. `varied` makes every
    vertex, colour, face index, bone position and vertex-morph element depend on the record's own number,
    which is the only way to tell a reader that walks the stride from one that re-derives a value it has
    already lost — and it keeps vertex 0's normal at (0, 1, 0), because the framing probe measures that
    one byte. `weight_kind` picks the skinning type the whole file speaks, `morph_elements` how many
    elements each morph carries, and `unboned` gives the last vertex a bone number the bone table has
    never heard of. `weight_scale` multiplies a row's weights out of a sum of one and `unweighted_last`
    zeroes the last row, which are the two shapes of bad skinning the corpus actually shows. Left alone
    they produce the byte-identical uniform file every header test sizes.
    """
    texture_paths = textures if textures is not None else tuple(f"tex/t{i}.png" for i in range(texture_count))
    material_names = materials if materials is not None else tuple(f"m{i}" for i in range(material_count))
    bone_names = bones if bones is not None else tuple(f"bone{i}" for i in range(bone_count))
    morph_entries = morphs if morphs is not None else tuple((f"morph{i}", 1) for i in range(morph_count))
    frame_names = frames if frames is not None else tuple(f"frame{i}" for i in range(frame_count))

    parts = _Parts(
        encoding=encoding, additional_uv=additional_uv_num, index_sizes=index_sizes, version=version,
        material_framing=material_framing, bone_morph_rotation=bone_morph_rotation,
        morph_padding=morph_padding, sphere_index=sphere_index, shared_toon=shared_toon,
        varied=varied, weight_kind=weight_kind, morph_elements=morph_elements, unboned=unboned,
        weight_scale=weight_scale, unweighted_last=unweighted_last,
        vertex_count=vertex_count, bone_count=len(bone_names), texture_count=len(texture_paths),
    )

    settings = bytes([encoding, additional_uv_num, *index_sizes]) + extra_setting_bytes
    header = MAGIC + struct.pack("<f", version) + struct.pack("<B", len(settings)) + settings
    fields = strings if strings is not None else (name, name_en, comment, comment_en)
    body = bytearray(header + b"".join(_text(value, encoding) for value in fields))

    counts = (
        len(texture_paths),
        len(material_names),
        len(bone_names),
        len(morph_entries),
        len(frame_names),
        rigid_body_count,
        constraint_count,
    )
    if not counts_inline:
        body += struct.pack("<9I", vertex_count, face_index_count, *counts)

    def section(count: int, payload: bytes) -> bytes:
        return (struct.pack("<I", count) + payload) if counts_inline else payload

    body += section(vertex_count, parts.vertices(vertex_count))
    body += section(face_index_count, parts.faces(face_index_count))
    body += section(len(texture_paths), parts.textures(texture_paths))
    body += section(len(material_names), parts.materials(material_names, face_index_count))
    body += section(len(bone_names), parts.bones(bone_names, ik_bones))
    body += section(len(morph_entries), parts.morphs(morph_entries))
    body += section(len(frame_names), parts.frames(frame_names))
    body += section(rigid_body_count, parts.rigids(rigid_body_count))
    body += section(constraint_count, parts.joints(constraint_count))

    if version >= 2.1:
        # The 2.1 soft-body section: a count of none, which is all any file in the corpus has, and the
        # only shape of it that has been measured.
        body += struct.pack("<I", 0)
    if trailing_comment is not None:
        body += _text(trailing_comment, encoding)
    body += tail
    return bytes(body)


def sample_pmx(**kwargs) -> bytes:
    """The one file every header test reads: a legal 2.0 character with a CJK name."""
    return write_pmx(**kwargs)


def write_three_string_pmx(**kwargs) -> bytes:
    """A file that skipped the English comment — which the format does not allow.

    Reading it as if it were legal is the bug this fixture exists to catch: the vertex count would land
    inside what the reader thinks is a string length, and a reader that trusts its offsets would report
    a model with hundreds of millions of vertices instead of failing.
    """
    fields = {
        "name": kwargs.pop("name", "エレン"),
        "name_en": kwargs.pop("name_en", "Ellen"),
        "comment": kwargs.pop("comment", ""),
    }
    kwargs.pop("comment_en", None)
    return write_pmx(strings=tuple(fields.values()), **kwargs)
