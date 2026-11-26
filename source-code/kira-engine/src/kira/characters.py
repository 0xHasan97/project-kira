"""What Kira can say about a character before anything renders it.

A PMX is a file whose first kilobyte is worth reading on its own: the name, the setting block and the
counts after it decide whether a model is a body or a prop, whether physics is worth turning on, and
whether the stage can carry it at all — none of which needs a GPU or a loader. But the counts are not all
in the header, and the ones that are not can only be read by walking the rest of the file, so this module
walks it. What it refuses to do is *guess* while walking: every number it reports was earned at an offset
the file itself states, and the two or three it could not earn stay blank and are named.

Three views, deliberately not one. `read_pmx_head` (and `PmxModel.head()`) is the certifying view: it
answers with the nine counts and the display name or raises, and it refuses a truncated file, a file with
an unexplained byte left over at the end, and a file whose sections behind the morph table had to be
*found by search* rather than read. `PmxModel.render_head()` is the same certificate for a body: it lets
out the six counts the morph table's own element sizes reach — vertices, faces, textures, materials, bones,
morphs — and still refuses the two ways a walk can leave a hole in the geometry. `read_pmx_model` and
`describe()` are the reporting view: they hand back the same numbers plus the offsets and the findings,
because a user who is told "43 morphs are counted and none is named, and here is why" can act, and a user
who is told nothing is a user who finds out when the model draws torn.

Most characters do not arrive as one PMX but as an archive of a PMX and its textures, and the container
gets the same treatment: an entry name is decoded as the writer meant it, an entry that points outside the
staging directory is refused by name, and every size cap is checked against the central directory before a
single byte is written.

The shape is not invented here. It is what the ten archives in the donor folder — twenty PMX models —
actually contain, measured byte by byte, and four of those measurements contradict the published format
note:

    "PMX "  |  float32 version  |  uint8 headerSize  |  headerSize setting bytes
    name, english name, comment, english comment   (each uint32 byte-length + bytes)
    counts, then sections

The setting block is `[encoding, additional-UV count, vertex, texture, material, bone, morph, rigid]`, so
the six index sizes are found by *position*: a 2.1 file appends three more for soft bodies, and taking the
last six bytes reads the wrong ones there. Then, each proved by an arithmetic that needs no memory of the
note —

* not one of the twenty files writes the documented nine-count block; each states its count immediately
  before its own section. At the offset the inline layout gives, the first vertex's normal is a unit
  vector in 20 of 20; at the documented block's offset the same twelve bytes are a denormal or a 59 455-unit
  vector in 20 of 20.
* no material record carries a draw flag or an English memo; the index counts of every material add up to
  the file's own face count only when the record ends after one memo.
* a quarter of the corpus writes a bone morph with a rotation as well as the translation the note names.
* four files have a morph section wider than either stride, so the sections behind it are only reachable
  from an offset the file never states — and in all four, exactly one offset in the window has remaining
  sections that walk out to the *end of the file*, which is what makes it a measurement and not a guess.

Both framings of the first two are therefore read, the file decides which, and the report says which one it
found: a browser loader that assumes the documented ones will draw a torn model without ever saying so.

And what the report says is the other half of the job. Two files that look equally like PMX are not
equally renderable: one names `hair.bmp` and its archive does not carry it, one says `tex\\颜.tga` where a
browser sees one filename with a backslash in it and no decoder for the format besides, one has no 肩 bone
for the stage to shrug with, and one came with a readme saying 请勿二次配布. A reader that guesses returns a
character with 1.2 billion vertices, and Kira would put that number in a table for the user to believe.

The third half is where the bytes end up. An import unpacks into a staging directory inside the library
and renames it into place only after its profile is written, so a refusal — a zip-slip entry, an archive
with no PMX in it, the same bytes a second time — leaves the library byte for byte as it was found, and a
character is never half a body. The folder is named for the bytes it came from, and the display name is
kept in the profile exactly as the file wrote it, because 耀嘉音 in a path is a name the next codepage will
eat.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import os
import re
import shutil
import stat
import struct
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote

from .errors import ConfigError, KiraError

MAGIC = b"PMX "

#: The versions whose header this reader is willing to walk. 2.0 and 2.1 differ only in how many
#: setting bytes precede the six index sizes, which is why one reader serves both.
VERSIONS = (2.0, 2.1)

NOT_A_PMX = "not_a_pmx"
PMX_VERSION_UNSUPPORTED = "pmx_version_unsupported"
PMX_TRUNCATED = "pmx_truncated"

#: The nine counts, in the order the format writes them. `face_index_count` is an index count, not a
#: triangle count — the format divides by three, and so does everything downstream.
COUNT_FIELDS = (
    "vertex_count",
    "face_index_count",
    "texture_count",
    "material_count",
    "bone_count",
    "morph_count",
    "frame_count",
    "rigid_body_count",
    "constraint_count",
)

#: The counts a KRM1 mesh is built from: everything up to and including the morph table. The three behind
#: it — frames, rigid bodies, joints — are what a report answers and a body does not need.
MESH_COUNT_FIELDS = COUNT_FIELDS[:6]

#: encoding byte, additional-UV count, then six index sizes. A 2.0 file writes 8, a 2.1 file writes 11.
MIN_SETTING_BYTES = 8

#: Where a section's count sits. `header` is what the published format note says; `inline` is what all
#: twenty donor archives write. See the module docstring.
COUNTS_HEADER = "header"
COUNTS_INLINE = "inline"

#: How a material record ends. `draw_and_memos` is the documented tail (draw flag, memo, English memo);
#: `memo_only` is the one the converters in this corpus emit, and the arithmetic of the index counts
#: decides which one a file used.
MATERIAL_DRAW_AND_MEMOS = "draw_and_memos"
MATERIAL_MEMO_ONLY = "memo_only"

#: A model-info string is a name or a comment, not a mesh. Anything longer than this is an offset that
#: landed on a count, and reading it would turn a refusal into a wrong answer.
HEADER_STRING_CAP_BYTES = 64 * 1024

#: Fewest bytes one record of each section can occupy, whatever the setting block says. A count that
#: needs more room than the file has left in front of this table is a count read at the wrong offset,
#: and stopping there is the difference between a blank report and a billion-vertex model. Keyed by the
#: count's own field name so `count()` below cannot index two lists that disagree.
_MIN_RECORD = {
    "vertex_count": 32,
    "face_index_count": 1,
    "texture_count": 4,
    "material_count": 44,
    "bone_count": 24,
    "morph_count": 12,
    "frame_count": 8,
    "rigid_body_count": 40,
    "constraint_count": 40,
}

#: When a morph payload turns out to be wider than anything measured, the walk looks forward for an
#: offset whose remaining sections not only walk but *end at the end of the file*, and it counts every
#: offset that does. Four of the twenty donor files need this: 耀嘉音 twice (the frames start 331 976 and
#: 332 084 byte(s) past a morph count of 43 and 49), 柏妮思 (341 824 past 51) and 伞 (816 past 1). In all
#: four the exact landing is unique among the 15-334 plausible candidates in the window, which is what
#: turns the boundary from a guess into a measurement. A megabyte covers the widest of them with room to
#: spare; scanning a whole 200 MB model byte by byte is what this cap is for.
RESYNC_WINDOW_BYTES = 1024 * 1024
#: How many candidates get a full tail walk. The cheap prefilter rejects nearly every offset in a float
#: blob, and this bounds the cost if a file is made of nothing but plausible-looking bytes.
RESYNC_CANDIDATES = 4096


class CharacterError(Exception):
    """A character that cannot be read, or an import that must not happen.

    Internal, and it stays internal: the CLI prints it and the routes turn it into one of the
    `CharacterRefusal` answers below. It is not a `KiraError` because nothing in the engine catches it as
    one — the importer's own vocabulary is wider than the codes the API publishes, and a
    `pmx_truncated` that reached a caller as its own wire code would be a promise the contract has to keep
    forever about a byte pattern nobody asked for.

    Codes are per-file (`not_a_pmx`, `pmx_truncated`, `pmx_version_unsupported`) or per-entry
    (`unsafe_entry`, `too_large`, `bad_archive`) because the user has to be able to tell "this is not a
    model" from "this model is cut off" from "the fourth entry in this archive is trying to write outside
    the directory" without opening a hex editor.
    """

    status = 400

    def __init__(self, message: str, *, code: str, entry: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        #: The archive entry a refusal is about, when there is one — so a route can name it in an
        #: answer without parsing the message.
        self.entry = entry


@dataclass(frozen=True)
class PmxHead:
    """Everything a PMX says about itself before its first vertex."""

    version: float
    encoding: int
    additional_uv_num: int
    index_sizes: tuple[int, ...]
    name: str
    name_en: str
    comment: str
    comment_en: str
    vertex_count: int
    face_index_count: int
    texture_count: int
    material_count: int
    bone_count: int
    morph_count: int
    frame_count: int
    rigid_body_count: int
    constraint_count: int
    #: Which framing the file's own geometry proved it uses — `inline` for everything in the donor
    #: corpus, `header` for a file written to the published note.
    count_framing: str = COUNTS_HEADER

    @property
    def triangle_count(self) -> int:
        return self.face_index_count // 3

    @property
    def display_name(self) -> str:
        """The name the file was made to be called by, with the ascii one behind it."""
        return self.name or self.name_en

    def counts(self) -> dict[str, int]:
        return {field: getattr(self, field) for field in COUNT_FIELDS}


class _Cursor:
    """A byte reader that says what it ran out of, so a refusal names the field and not an offset.

    Every read is bounds-checked before it happens. That is the only difference between this and a
    reader that trusts the header, and it is the difference between an error and a wrong number.
    """

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0

    def take(self, size: int, what: str) -> bytes:
        if size < 0 or len(self.data) - self.pos < size:
            raise CharacterError(
                f"PMX ended while reading {what}: wanted {size} byte(s), "
                f"{max(0, len(self.data) - self.pos)} left at offset {self.pos}",
                code=PMX_TRUNCATED,
            )
        chunk = self.data[self.pos : self.pos + size]
        self.pos += size
        return chunk

    def u8(self, what: str) -> int:
        return self.take(1, what)[0]

    def u16(self, what: str) -> int:
        return struct.unpack("<H", self.take(2, what))[0]

    def u32(self, what: str) -> int:
        return struct.unpack("<I", self.take(4, what))[0]

    def idx(self, size: int, what: str) -> int:
        """One index, as wide as the setting block said this file's indexes are. -1 means "none".

        Signed at every width, because PMX writes "no texture", "no parent bone" and "no toon" as `-1` in
        the same field that holds a table index. Read unsigned, `-1` becomes 255 — a number the texture
        table does have — and every material in a model with no sphere map gets counted as one that does:
        measured across the donor corpus, that is twenty files of none-to-one-byte texture indexes all
        answering "every material references a sphere map".

        A width outside 1, 2 and 4 is a file that cannot be walked, so it is refused in the words the rest
        of the header uses instead of raising a `KeyError` the API would answer with a 500.
        """
        code = {1: "<b", 2: "<h", 4: "<i"}.get(size)
        if code is None:
            raise CharacterError(
                f"not a PMX: {what} is read at {size} byte(s) wide, which is none of 1, 2 or 4",
                code=NOT_A_PMX,
            )
        return struct.unpack(code, self.take(size, what))[0]

    def take_more(self, size: int, what: str) -> None:
        """Skip a fixed-width field, still bounds-checked — the walk's only job for most of a mesh."""
        self.take(size, what)


def _decode_text(raw: bytes, encoding: int, what: str) -> str:
    """One of the two codecs the setting block chooses between, with the refusal named."""
    codec = "utf-16-le" if encoding == 0 else "utf-8"
    try:
        return raw.decode(codec)
    except UnicodeDecodeError as exc:
        raise CharacterError(
            f"not a PMX: {what} is not valid {codec}", code=NOT_A_PMX
        ) from exc


def _header_text(cursor: _Cursor, encoding: int, what: str) -> str:
    """One of the four model-info strings, with a ceiling a misread offset cannot clear.

    A length is four bytes and so is a count, which is the whole reason a file whose strings are in
    the wrong order is refused rather than described: the reader takes the vertex count for a string
    length, reads the geometry as a name, and then walks on. Capping the header strings at 64 KB makes
    that offset land on a refusal, and a 64 KB comment is not a thing anyone loads.
    """
    size = cursor.u32(f"{what} length")
    if size > HEADER_STRING_CAP_BYTES:
        raise CharacterError(
            f"not a PMX: {what} claims {size} byte(s), which is a count being read as a length",
            code=NOT_A_PMX,
        )
    return _decode_text(cursor.take(size, what), encoding, what)


#: The five weight types a vertex can name, and how much of a record each one writes after its type
#: byte: how many bone indices, how many float32s, and how many of those floats are blend weights rather
#: than SDEF's symmetry maths (C, R0 and R1, which no stage runs). The walk uses the first two to size a
#: record and `mesh.py` uses all three to unpack one, which is the only way a mesh and the report of the
#: same file can be certain they counted the same bytes.
WEIGHT_INDICES = {0: 1, 1: 2, 2: 4, 3: 2, 4: 4}
WEIGHT_FLOATS = {0: 0, 1: 1, 2: 4, 3: 10, 4: 4}
WEIGHT_WEIGHTS = {0: 0, 1: 1, 2: 4, 3: 1, 4: 4}


def _weight_bytes(kind: int, bone_size: int) -> int:
    """The payload of one vertex's skinning, after the type byte."""
    return WEIGHT_INDICES[kind] * bone_size + WEIGHT_FLOATS[kind] * 4


def _morph_step(kind: int, *, vertex_size: int, bone_step: int, morph_size: int, rigid_size: int) -> int:
    """One morph element, by the type byte. `None` is a type this importer cannot measure."""
    if kind in (0, 9):
        return morph_size + 4
    if kind == 1:
        return vertex_size + 12
    if kind == 2:
        return bone_step
    if kind in (3, 4, 5, 6, 7, 8):
        return vertex_size + 16
    if kind == 10:
        return rigid_size + 25
    return None  # type: ignore[return-value]


def _first_vertex_is_geometry(data: bytes, at: int, *, additional_uv: int, bone_size: int) -> bool:
    """Ask the mesh where the mesh starts.

    Two framings put the counts in two places, and a normal vector is the one field in a PMX that
    cannot lie about its own offset: it is unit length, and its neighbours are a position small enough
    to be metres and a weight type in 0..4. Read at the wrong offset those twelve bytes are a denormal
    or a five-thousand-unit vector — which is exactly what the twenty donor files show at the offset
    the format note implies.
    """
    stride = 32 + 16 * additional_uv
    if len(data) - at < stride + 5:
        return False
    if data[at + stride] > 4:
        return False
    nx, ny, nz = struct.unpack("<3f", data[at + 12 : at + 24])
    length = math.sqrt(nx * nx + ny * ny + nz * nz)
    return 0.99 <= length <= 1.01


class _StopsWalking(Exception):
    """A section that does not fit the file. Everything after it is unknown, and that is the answer."""


@dataclass(frozen=True)
class PmxModel:
    """A PMX walked far enough to describe, plus the receipts for how far that was.

    Counts stay `None` when the walk could not reach them. A report with a blank is a defect stated; a
    report with a guessed number is a defect hidden, and the second one is the reason this file exists.
    """

    version: float
    encoding: int
    additional_uv_num: int
    index_sizes: tuple[int, ...]
    name: str
    name_en: str
    comment: str
    comment_en: str
    counts: dict[str, int | None]
    count_framing: str
    material_framing: str
    bone_names: tuple[str, ...] = ()
    morph_names: tuple[str, ...] = ()
    morph_kinds: tuple[int, ...] = ()
    frame_names: tuple[str, ...] = ()
    material_names: tuple[str, ...] = ()
    texture_paths: tuple[str, ...] = ()
    sphere_refs: int = 0
    shared_toon_refs: int = 0
    ik_bone_count: int = 0
    trailing_bytes: int = 0
    #: The offset the sections after the morph table were read from when the file's own element sizes did
    #: not reach one. Set only when a boundary was *searched for* rather than earned, which is why
    #: `head()` refuses a model that carries it and `describe()` still reports it with the finding.
    resynced_from: int | None = None
    findings: tuple[str, ...] = ()
    unreadable: str | None = None

    @property
    def display_name(self) -> str:
        return self.name or self.name_en

    @property
    def triangle_count(self) -> int | None:
        face = self.counts.get("face_index_count")
        return None if face is None else face // 3

    def head(self) -> PmxHead:
        """The strict view: every count, a walk that finished, and no boundary that was guessed. Nothing
        in between.

        A cut inside a section still leaves the counts stamped — a file states a count before its
        payload, so the numbers survive the payload that did not. Returning them anyway would answer a
        truncated file with the profile of a whole one, which is the exact failure this function exists
        to make impossible.

        A resynced walk is refused for the same reason: after a morph table wider than the format
        measures, the sections behind it are found by *search*, and a search over a truncated file can
        land on an offset whose remaining sections are all empty. `describe()` reports such a model with
        the counts, the offset and the finding; `head()` will not certify it.

        Leftover bytes are refused too, for the same reason in the other direction. A walk that stops
        early can look like a walk that finished: reading a run of zeros as three empty sections is a
        legal reading of the bytes and a false statement about the model, and the bytes the walk did not
        take are what prove it. A file whose last byte is accounted for has no such gap.
        """
        return self._certify(after_morphs=True)

    def render_head(self) -> PmxHead:
        """The body's view: every byte a mesh is built from, certified, and nothing asked about what sits
        behind the morph table.

        This is the same file as `head()` refuses. Frames, rigid bodies and joints are a searched walk's
        uncertainty, and a KRM1 blob carries none of them — positions, normals, uvs, skin, faces,
        textures, materials, bones and vertex morphs are all read from offsets the file states, before the
        boundary that had to be found. `mesh.pack_mesh` follows with `_agree`, which compares the records
        the walk actually collected against the counts those same offsets earned; that is the check a hole
        inside a body cannot pass.

        What it still refuses is a walk that stopped early or left bytes it cannot place. Either one means
        the uncertainty is inside the body rather than behind it.
        """
        return self._certify(after_morphs=False)

    def _certify(self, *, after_morphs: bool) -> PmxHead:
        missing = [key for key in MESH_COUNT_FIELDS if self.counts.get(key) is None]
        if after_morphs:
            missing = [key for key in COUNT_FIELDS if self.counts.get(key) is None]
            if self.resynced_from is not None:
                raise CharacterError(
                    f"the sections after the morph table were read from offset {self.resynced_from}, which "
                    f"is the first offset whose remaining sections reach the end of the file rather than an "
                    f"offset the file's own element sizes state; the counts are reported by `describe()` "
                    f"and are not certified here",
                    code=PMX_TRUNCATED,
                )
        if self.trailing_bytes:
            raise CharacterError(
                f"{self.trailing_bytes} byte(s) after the last section the walk reached are not part of "
                f"any section it can name, so the counts past the morph table are not certified here",
                code=PMX_TRUNCATED,
            )
        if missing or self.unreadable:
            raise CharacterError(
                self.unreadable or f"the counts of {', '.join(missing)} were not reachable",
                code=PMX_TRUNCATED,
            )
        return PmxHead(
            version=self.version,
            encoding=self.encoding,
            additional_uv_num=self.additional_uv_num,
            index_sizes=self.index_sizes,
            name=self.name,
            name_en=self.name_en,
            comment=self.comment,
            comment_en=self.comment_en,
            count_framing=self.count_framing,
            **self.counts,
        )


def read_pmx_model(data: bytes, geometry: "object | None" = None) -> PmxModel:
    """Walk a PMX and say what rendering it would cost — stopping honestly where the walk stops paying.

    Tolerant in one direction only: a section whose records do not fit the format's own arithmetic ends
    the walk instead of continuing on a guess, and the report then states what is unknown. Header-level
    refusals (magic, version, encoding, the four strings) still raise, because those mean the file is
    not a PMX at all rather than a PMX with a part this importer cannot measure.

    `geometry` is the walk handed over while it happens, to a caller that wants the mesh rather than the
    report: a duck-typed collector told the widths, then each record the cursor steps over, then the
    blocks a retry re-reads. Nothing is decoded here that the report does not need — the collector gets
    the bytes the walk already took — because a second reader of a format this corpus disagrees about is
    two answers, and the mesh on a stage and the numbers in the library have to be one answer.
    """
    cursor = _Cursor(data)
    if cursor.take(4, "the magic") != MAGIC:
        raise CharacterError("not a PMX: the file does not start with 'PMX '", code=NOT_A_PMX)

    version = struct.unpack("<f", cursor.take(4, "the version"))[0]
    known = next((v for v in VERSIONS if abs(version - v) < 1e-6), None)
    if known is None:
        raise CharacterError(
            f"PMX version {version:g} is not one Kira reads ({', '.join(f'{v:g}' for v in VERSIONS)})",
            code=PMX_VERSION_UNSUPPORTED,
        )

    header_size = cursor.u8("the header size")
    if header_size < MIN_SETTING_BYTES:
        raise CharacterError(
            f"not a PMX: a header size of {header_size} byte(s) cannot hold the encoding, the "
            f"additional-UV count and the six index sizes",
            code=NOT_A_PMX,
        )
    settings = cursor.take(header_size, "the setting block")
    encoding = settings[0]
    if encoding not in (0, 1):
        raise CharacterError(
            f"not a PMX: encoding {encoding} is neither 0 (utf-16-le) nor 1 (utf-8)", code=NOT_A_PMX
        )
    additional_uv_num = settings[1]
    index_sizes = tuple(settings[2:8])
    vertex_size, texture_size, _material_size, bone_size, morph_size, rigid_size = index_sizes
    if any(size not in (1, 2, 4) for size in index_sizes):
        raise CharacterError(
            f"not a PMX: the setting block says its index widths are {index_sizes}, and a PMX index is "
            f"one, two or four bytes wide",
            code=NOT_A_PMX,
        )
    if geometry is not None:
        # The collector reads the bytes the walk points at, so it needs the widths the walk read them at.
        geometry.widths(vertex_size=vertex_size, bone_size=bone_size)

    name = _header_text(cursor, encoding, "the model name")
    name_en = _header_text(cursor, encoding, "the English model name")
    comment = _header_text(cursor, encoding, "the model comment")
    comment_en = _header_text(cursor, encoding, "the English model comment")

    counts_at = cursor.pos
    inline = _first_vertex_is_geometry(
        data, counts_at + 4, additional_uv=additional_uv_num, bone_size=bone_size
    )
    header_counts: list[int] | None = None
    findings: list[str] = []
    if inline:
        count_framing = COUNTS_INLINE
        findings.append(
            "counts stated inline: each section names its own count immediately before it, which is "
            "what all twenty donor archives do and is not the documented nine-count header block"
        )
    else:
        count_framing = COUNTS_HEADER
        header_counts = list(struct.unpack("<9I", cursor.take(4 * 9, "the nine counts")))

    counts: dict[str, int | None] = {key: None for key in COUNT_FIELDS}

    def count(key: str, what: str) -> int:
        if header_counts is None:
            value = cursor.u32(what)
        else:
            value = header_counts[COUNT_FIELDS.index(key)]
        room = len(data) - cursor.pos
        if value > room // _MIN_RECORD[key]:
            raise _StopsWalking(
                f"{what} says {value}, which does not fit in the {room} byte(s) left to it"
            )
        return value

    def read_vertices() -> None:
        total = count("vertex_count", "the vertex count")
        counts["vertex_count"] = total
        stride = 32 + 16 * additional_uv_num
        for index in range(total):
            body = cursor.take(stride, "a vertex")
            kind = cursor.u8("a vertex weight type")
            if kind > 4:
                raise CharacterError(
                    f"not a PMX: vertex {index} says its weight type is {kind}, which is none of "
                    f"BDEF1, BDEF2, BDEF4, SDEF or QDEF",
                    code=NOT_A_PMX,
                )
            weight = cursor.take(_weight_bytes(kind, bone_size), "a vertex weight")
            cursor.take(4, "an edge scale")
            if geometry is not None:
                geometry.vertex(body, kind, weight)

    def read_faces() -> int:
        total = count("face_index_count", "the face index count")
        counts["face_index_count"] = total
        indices = cursor.take(total * vertex_size, "the face indices")
        if geometry is not None:
            geometry.faces(indices, total)
        return total

    def read_textures() -> list[str]:
        total = count("texture_count", "the texture count")
        counts["texture_count"] = total
        return [_header_text(cursor, encoding, "a texture path") for _ in range(total)]

    def read_materials(framing: str) -> tuple[list[str], int, int, int]:
        total = count("material_count", "the material count")
        counts["material_count"] = total
        if geometry is not None:
            # This section is read twice whenever the first framing does not add up, so the collector has
            # to forget the attempt rather than hand over a model with twice the materials it has.
            geometry.begin_materials(total)
        names: list[str] = []
        index_sum = spheres = shared = 0
        for _ in range(total):
            name = _header_text(cursor, encoding, "a material name")
            _header_text(cursor, encoding, "a material English name")
            colours = cursor.take(44 + 1 + 16 + 4, "a material's colours")
            diffuse = cursor.idx(texture_size, "a diffuse texture index")
            sphere = cursor.idx(texture_size, "a sphere texture index")
            if sphere >= 0:
                spheres += 1
            sphere_mode = cursor.u8("a sphere mode")
            toon_shared = cursor.u8("a shared-toon flag")
            toon = cursor.idx(1 if toon_shared else texture_size, "a toon index")
            shared += 1 if toon_shared else 0
            if framing == MATERIAL_DRAW_AND_MEMOS:
                cursor.u8("a draw mode")
                _header_text(cursor, encoding, "a material memo")
                _header_text(cursor, encoding, "a material English memo")
            else:
                _header_text(cursor, encoding, "a material memo")
            own = cursor.u32("a material's index count")
            index_sum += own
            names.append(name)
            if geometry is not None:
                geometry.material(
                    name, colours, diffuse, sphere, sphere_mode, toon_shared, toon, own
                )
        return names, index_sum, spheres, shared

    def read_bones() -> tuple[tuple[str, ...], int]:
        total = count("bone_count", "the bone count")
        counts["bone_count"] = total
        names: list[str] = []
        ik = 0
        for _ in range(total):
            name = _header_text(cursor, encoding, "a bone name")
            name_en = _header_text(cursor, encoding, "a bone English name")
            position = cursor.take(12, "a bone position")
            parent = cursor.idx(bone_size, "a bone parent")
            cursor.take(4, "a deform layer")
            flags = cursor.u16("bone flags")
            if flags & 0x0001:
                cursor.idx(bone_size, "a bone tail index")
            else:
                cursor.take(12, "a bone tail position")
            if flags & 0x0100 or flags & 0x0200:
                cursor.idx(bone_size, "a grant parent")
                cursor.take(4, "an inflight rate")
            if flags & 0x0400:
                cursor.take(12, "a fixed axis")
            if flags & 0x0800:
                cursor.take(24, "a local axis pair")
            if flags & 0x2000:
                cursor.take(4, "an external parent key")
            if flags & 0x0020:
                ik += 1
                cursor.idx(bone_size, "an IK target")
                cursor.take(4, "an IK loop count")
                cursor.take(4, "an IK angle limit")
                # The link count is its own field. Iterating the loop count instead desynchronises
                # every file whose bones are two bytes wide, which is most of them.
                for _ in range(cursor.u32("an IK link count")):
                    cursor.idx(bone_size, "an IK link")
                    if cursor.u8("an IK link limit flag"):
                        cursor.take(24, "an IK link limit")
            if geometry is not None:
                # Handed over once the record is read in full: a bone the walk ran out of halfway is not a
                # bone the model has, and a collector holding it would be a mesh with a hole in it.
                geometry.bone(name, name_en, position, parent, flags)
            names.append(name)
        return tuple(names), ik

    def read_morphs(bone_step: int) -> tuple[list[str], list[int]]:
        total = count("morph_count", "the morph count")
        counts["morph_count"] = total
        if geometry is not None:
            # Read twice when the bone morph's element width is the thing being tried, so the collector
            # starts each attempt clean.
            geometry.begin_morphs(total)
        names: list[str] = []
        kinds: list[int] = []
        for index in range(total):
            name = _header_text(cursor, encoding, "a morph name")
            morph_at = cursor.pos
            try:
                _header_text(cursor, encoding, "a morph English name")
                if known >= 2.1:
                    cursor.u32("a morph panel")
                else:
                    cursor.u8("a morph panel")
                kind = cursor.u8("a morph type")
                size = cursor.u32("a morph element count")
                step = _morph_step(
                    kind, vertex_size=vertex_size, bone_step=bone_step,
                    morph_size=morph_size, rigid_size=rigid_size,
                )
                if step is None:
                    raise CharacterError(
                        f"morph {index} says its type is {kind}, which is not one Kira can measure",
                        code=NOT_A_PMX,
                    )
                payload = cursor.take(size * step, "a morph payload")
            except CharacterError as exc:
                # Which expression the file broke on is the difference between "this model's morphs are
                # unreadable" and a sentence the user can act on, so the name travels with the refusal.
                raise CharacterError(
                    f"morph {index} ({name}) at offset {morph_at}: {exc.message}", code=exc.code
                ) from exc
            if geometry is not None and kind == 1:
                # The vertex morph is the one animation the stage can run, and the only one whose elements
                # mean anything without a bone table, a UV set or a rigid body behind them.
                geometry.vertex_morph(name, index, payload, size)
            names.append(name)
            kinds.append(kind)
        return names, kinds

    def read_frames() -> list[str]:
        total = count("frame_count", "the frame count")
        counts["frame_count"] = total
        names: list[str] = []
        for _ in range(total):
            names.append(_header_text(cursor, encoding, "a frame name"))
            _header_text(cursor, encoding, "a frame English name")
            cursor.u8("a special-frame flag")
            for _ in range(cursor.u32("a frame element count")):
                kind = cursor.u8("a frame element kind")
                cursor.idx(bone_size if kind == 0 else morph_size, "a frame element index")
        return names

    def read_rigids() -> None:
        total = count("rigid_body_count", "the rigid body count")
        counts["rigid_body_count"] = total
        if geometry is not None:
            geometry.begin_rigids(total)
        for _ in range(total):
            _header_text(cursor, encoding, "a rigid body name")
            _header_text(cursor, encoding, "a rigid body English name")
            bone = cursor.idx(bone_size, "a rigid body bone")
            group = cursor.u8("a rigid body collision group")
            mask = cursor.u16("a rigid body collision mask")
            shape = cursor.u8("a rigid body shape")
            if shape > 2:
                raise CharacterError(
                    f"a rigid body says its shape is {shape}, which is none of box, sphere or capsule",
                    code=NOT_A_PMX,
                )
            payload = cursor.take(12 + 12 + 12 + 20, "a rigid body's pose and physics")
            mode = cursor.u8("a rigid body mode")
            if mode > 4:
                raise CharacterError(
                    f"a rigid body says its mode is {mode}, which is none of static, kinematic or "
                    f"animated-to-bone",
                    code=NOT_A_PMX,
                )
            if geometry is not None:
                geometry.rigid(bone, group, mask, shape, payload, mode)

    def read_constraints() -> None:
        total = count("constraint_count", "the constraint count")
        counts["constraint_count"] = total
        if geometry is not None:
            geometry.begin_constraints(total)
        for _ in range(total):
            _header_text(cursor, encoding, "a constraint name")
            _header_text(cursor, encoding, "a constraint English name")
            mode = cursor.u8("a constraint mode")
            first = cursor.idx(rigid_size, "a constraint's first rigid body")
            second = cursor.idx(rigid_size, "a constraint's second rigid body")
            payload = cursor.take(96, "a constraint's limits and springs")
            if geometry is not None:
                geometry.constraint(mode, first, second, payload)

    def read_trailing() -> int:
        """The comment(s) a file may end with, and however many bytes it really did leave.

        A trailing text is only accepted when its own declared length reaches the end of the file — for
        2.1, when it reaches the start of one more text that then reaches the end. Nothing else can tell
        a comment from an exporter's blob, and guessing wrong here would report a model's real comment as
        unreadable bytes or, worse, a blob as a comment.
        """
        if known >= 2.1:
            total = cursor.u32("the soft body count")
            if total:
                raise _StopsWalking(
                    f"the file declares {total} soft body/ies, which is a PMX 2.1 section this "
                    f"importer has not measured"
                )
        end = len(data)

        def comment(at: int) -> tuple[str, int] | None:
            return _printable_text_at(
                data, at, encoding, max_bytes=HEADER_STRING_CAP_BYTES, allow_empty=True
            )

        one = comment(cursor.pos)
        if one is not None and one[1] == end:
            cursor.pos = end
            return 0
        if known >= 2.1:
            two = comment(cursor.pos)
            if two is not None:
                three = comment(two[1])
                if three is not None and three[1] == end:
                    cursor.pos = end
                    return 0
        return end - cursor.pos

    def read_tail() -> dict[str, object]:
        frames = read_frames()
        read_rigids()
        read_constraints()
        return {"frame_names": tuple(frames), "trailing_bytes": read_trailing()}

    unreadable: str | None = None
    bone_names: tuple[str, ...] = ()
    morph_names: tuple[str, ...] = ()
    morph_kinds: tuple[int, ...] = ()
    material_names: tuple[str, ...] = ()
    texture_paths: tuple[str, ...] = ()
    frame_names: tuple[str, ...] = ()
    sphere_refs = shared_toon_refs = ik_bone_count = 0
    trailing_bytes = 0
    resynced_from: int | None = None
    material_framing = MATERIAL_MEMO_ONLY
    tail: dict[str, object] = {}

    try:
        read_vertices()
        face_total = read_faces()
        texture_paths = tuple(read_textures())

        # The two material framings are told apart by arithmetic, not by a header byte: a material
        # states how many face indices it draws, and the materials of a whole model add up to the
        # face count it stated earlier. Only one framing in a file can satisfy that.
        materials_at = cursor.pos
        complaint = ""
        for framing in (MATERIAL_MEMO_ONLY, MATERIAL_DRAW_AND_MEMOS):
            cursor.pos = materials_at
            try:
                names, index_sum, spheres, shared = read_materials(framing)
            except CharacterError as exc:
                complaint = exc.message
                continue
            if index_sum == face_total:
                material_framing = framing
                material_names, sphere_refs, shared_toon_refs = tuple(names), spheres, shared
                break
            complaint = (
                f"the materials' index counts add to {index_sum}, not the {face_total} face "
                f"index/indices the file states"
            )
        else:
            raise _StopsWalking(complaint or "the material section does not fit")
        if material_framing == MATERIAL_MEMO_ONLY:
            findings.append(
                "material records carry one memo and no draw flag or English memo, which is what "
                "converter-emitted files write and is not the documented material layout"
            )

        bone_names, ik_bone_count = read_bones()

        # Bone morphs split the corpus: the format note says index plus a translation, and character
        # rips here also carry a rotation. Whichever fits is the one the file uses, proved by the
        # sections after it landing where the format says they must. Both readings are tried, because
        # the narrow one can also "succeed" by stopping on a run of zeros inside a wide element and
        # reporting a rigged character as having no physics at all — which is what makes an exact
        # landing the tie-breaker rather than whichever walk happened to finish first.
        morphs_at = cursor.pos
        first_morph_record = morphs_at if header_counts is not None else morphs_at + 4
        furthest: tuple[int, str] | None = None
        attempts: list[tuple[int, str, list[str], list[int], dict[str, object]]] = []
        for bone_step, label in (
            (bone_size + 12, "a translation"),
            (bone_size + 28, "a translation and a rotation"),
        ):
            cursor.pos = morphs_at
            try:
                names, kinds = read_morphs(bone_step)
                outcome = read_tail()
            except (CharacterError, _StopsWalking) as exc:
                message = exc.message if isinstance(exc, CharacterError) else str(exc)
                if furthest is None or cursor.pos > furthest[0]:
                    furthest = (cursor.pos, f"with {label} ({bone_step}-byte elements): {message}")
                continue
            attempts.append((bone_step, label, names, kinds, outcome))
            if bone_step == bone_size + 12 and int(outcome["trailing_bytes"]) == 0:
                break
        def use_attempt(attempt: tuple[int, str, list[str], list[int], dict[str, object]]) -> dict[str, object]:
            nonlocal morph_names, morph_kinds
            stride, stride_label, names, kinds, outcome = attempt
            morph_names, morph_kinds = tuple(names), tuple(kinds)
            if stride != bone_size + 12:
                findings.append(
                    f"bone morph elements carry {stride_label} ({stride} byte(s) each, where the "
                    f"format note says {bone_size + 12})"
                )
            return outcome

        exact = next((a for a in attempts if int(a[4]["trailing_bytes"]) == 0), None)
        # A walk that runs out of file, and a walk that reaches the end with bytes still to its name,
        # have the same cause: a section whose records are wider than anything measured here. Both are
        # answered by the only boundary that can be proved — the offset whose remaining sections reach
        # the very end of the file — so the search runs for either. Leftover bytes are not evidence of
        # an exporter's padding; two donor files whose "padding" turned out to hold 39 860 nonzero bytes
        # of float data are what settled that.
        leftover = int(attempts[0][4]["trailing_bytes"]) if (attempts and exact is None) else 0
        # The search below walks candidate sections, and a walk writes the counts it reads. Anything it
        # tries and rejects has to leave the numbers earned before the morph table exactly as they were,
        # or a failed search reports a file as having sections it was never proved to have.
        before = dict(counts)
        landings, capped = (
            ([], False)
            if exact is not None
            else _find_section_after(
                data,
                first_morph_record,
                encoding,
                count_inline=header_counts is None,
                read_tail=read_tail,
                cursor=cursor,
            )
        )
        if not landings:
            counts.clear()
            counts.update(before)
        if exact is not None:
            tail = use_attempt(exact)
        elif landings:
            landing = landings[0]
            why = (
                furthest[1]
                if furthest is not None
                else f"the walk leaves {leftover} byte(s) after what it takes for the last section"
            )
            if leftover:
                findings.append(
                    f"the {leftover} byte(s) a stride said the exporter appended are the sections after "
                    f"the morph table"
                )
            cursor.pos = landing
            tail = read_tail()
            resynced_from = landing
            whose = (
                "the only offset in the window whose remaining sections walk out to the end of the file"
                if len(landings) == 1 and not capped
                else f"the first of {len(landings)} offsets in the window whose remaining sections walk "
                f"out to the end of the file"
            )
            findings.append(
                f"the morph section ends {landing - morphs_at} byte(s) past its count, ahead of where "
                f"its element sizes said it would ({why}); {counts['morph_count']} morph(s) are counted "
                f"and none is named, and the sections after it are read from {whose}"
            )
        elif attempts:
            tail = use_attempt(attempts[0])
        else:
            # The counts behind the morph table were read at offsets a wrong element size implies, so
            # they are unknown and stay blank; everything before the table was earned and stands.
            for key in ("frame_count", "rigid_body_count", "constraint_count"):
                counts[key] = None
            raise _StopsWalking(
                f"the morph section fits neither element size Kira measures ({furthest[1]}); no "
                f"later section boundary walks out to the end of the file within "
                f"{RESYNC_WINDOW_BYTES} byte(s) of offset {first_morph_record}"
            )

        frame_names = tuple(tail["frame_names"])  # type: ignore[arg-type]
        trailing_bytes = int(tail["trailing_bytes"])  # type: ignore[arg-type]
        if trailing_bytes:
            # Reachable only when an element size walked the file with bytes left over and no offset in
            # the window proved a boundary: the bytes are unread, and saying they are the exporter's
            # padding would be a guess dressed up as a finding.
            findings.append(
                f"{trailing_bytes} byte(s) the walk could not account for after the last section it "
                f"reached: no trailing comment runs to the end of the file from there, and no offset "
                f"within {RESYNC_WINDOW_BYTES} byte(s) of the morph table lands the sections after it on "
                f"the end of the file either"
            )
    except (_StopsWalking, CharacterError) as exc:
        unreadable = exc.message if isinstance(exc, CharacterError) else str(exc)
        if unreadable:
            findings.append(f"the walk stops here: {unreadable}")

    return PmxModel(
        version=known,
        encoding=encoding,
        additional_uv_num=additional_uv_num,
        index_sizes=index_sizes,
        name=name,
        name_en=name_en,
        comment=comment,
        comment_en=comment_en,
        counts=counts,
        count_framing=count_framing,
        material_framing=material_framing,
        bone_names=bone_names,
        morph_names=morph_names,
        morph_kinds=morph_kinds,
        frame_names=frame_names,
        material_names=material_names,
        texture_paths=texture_paths,
        sphere_refs=sphere_refs,
        shared_toon_refs=shared_toon_refs,
        ik_bone_count=ik_bone_count,
        trailing_bytes=trailing_bytes,
        resynced_from=resynced_from,
        findings=tuple(findings),
        unreadable=unreadable,
    )


def _printable_text_at(
    data: bytes, at: int, encoding: int, *, max_bytes: int = 512, allow_empty: bool = False
) -> tuple[str, int] | None:
    """One length-prefixed name read without raising, or `None` where the bytes refuse to be a name.

    A probe and not a reader: it answers "could a section start here", never raises, and never returns a
    length the file cannot supply. The bounds checks are the whole point — a misread offset hands it a
    vertex count in place of a length, which is either past the end or a blob no frame name is.
    """
    if len(data) - at < 4:
        return None
    size = struct.unpack("<I", data[at : at + 4])[0]
    if size > max_bytes or len(data) - at - 4 < size or (size == 0 and not allow_empty):
        return None
    if encoding == 0 and size % 2:
        return None
    raw = data[at + 4 : at + 4 + size]
    try:
        text = raw.decode("utf-16-le" if encoding == 0 else "utf-8")
    except UnicodeDecodeError:
        return None
    if not text.isprintable():
        return None
    return text, at + 4 + size


def _u32_in_range(data: bytes, at: int, low: int, high: int) -> bool:
    """A uint32 that is neither past the end nor out of range."""
    if len(data) - at < 4:
        return False
    return low <= struct.unpack("<I", data[at : at + 4])[0] <= high


def _find_section_after(
    data: bytes, start: int, encoding: int, *, count_inline: bool, read_tail, cursor: _Cursor
) -> tuple[list[int], bool]:
    """Every offset in the window whose remaining sections walk out to the end of the file.

    The answer is the list and not the first hit because the list is the proof: one exact landing says
    where the section ends, three hundred say only that the file has a lot of places a short walk can
    finish. The caller reports which of those it got.

    A candidate clears two tests to be listed. First it has to look like the head of a frame section: a
    count in range, a non-empty printable name, a second name that may be empty, and a special-frame flag
    of 0 or 1. Then everything remaining has to walk — frames, rigid bodies, joints, the trailing comment
    — and land exactly at the end of the file.

    The exact landing is what makes this more than a guess, and measuring it is what proved that: the four
    donor files that need it each have one offset in the window that lands, out of 15 to 334 that look
    like a section head. `bool` says whether the candidate cap stopped the scan early, which is when the
    list stops being a count of all the landings.
    """
    limit = min(len(data), start + RESYNC_WINDOW_BYTES)
    landings: list[int] = []
    tried = 0
    capped = False
    for at in range(start, limit):
        probe = at
        if count_inline:
            if not _u32_in_range(data, probe, 0, 4096):
                continue
            probe += 4
        first = _printable_text_at(data, probe, encoding)
        if first is None:
            continue
        second = _printable_text_at(data, first[1], encoding, allow_empty=True)
        if second is None or second[1] >= len(data) or data[second[1]] > 1:
            continue
        tried += 1
        if tried > RESYNC_CANDIDATES:
            capped = True
            break
        cursor.pos = at
        try:
            tail = read_tail()
        except (CharacterError, _StopsWalking):
            continue
        if int(tail["trailing_bytes"]) == 0:  # type: ignore[arg-type]
            landings.append(at)
    return landings, capped


def read_pmx_head(data: bytes) -> PmxHead:
    """Parse a PMX's header. Raises `CharacterError` rather than returning anything partial.

    The counts are not all in the header: every donor file states each section's count before that
    section, so the only way to read all nine truthfully is to walk the file, and this does. That is
    also what makes the number safe to put in front of a user — see the module docstring.
    """
    return read_pmx_model(data).head()


# --- what a model can and cannot render ---------------------------------------------------------------

#: The two numbers that say "this is a body and not a thing the body holds". Measured on the donor
#: corpus, where the nine props stop at 8 255 vertices and 38 bones (an umbrella with 14 rigid bodies on
#: it — the densest thing a character holds) and the eleven characters start at 26 798 vertices and 297
#: bones and run to 69 638 and 695. Both numbers are used because they mean different things — a mesh can
#: grow dense without growing a skeleton, and a rig can be elaborate on something that is not a body — and
#: each one sits in the gap the corpus leaves: 20 000 vertices is above the densest prop and below the
#: leanest character, and 100 bones is 2.6× above the most rigged prop and a third of the least rigged
#: character.
MAIN_MIN_VERTS = 20_000
MAIN_MIN_BONES = 100

#: The skeleton a stage animates, by the names a rig actually carries. Both the Japanese MMD names and
#: the Chinese and English ones the converters in this corpus emit, because a group that is only spelled
#: one way is a group that reports missing on half the library.
BONE_GROUPS: dict[str, tuple[str, ...]] = {
    "spine": ("上半身", "下半身", "センター", "体", "Spine", "spine", "Torso"),
    "neck-head": ("頭", "首", "Head", "Neck"),
    "shoulder": ("肩", "Shoulder"),
    "arm": ("腕", "Arm"),
    "elbow": ("ひじ", "肘", "Elbow"),
    "hand": ("手", "Hand", "Wrist"),
    "leg": ("足", "脚", "Leg"),
    "knee": ("ひざ", "膝", "Knee"),
    "ankle-toe": ("足首", "つま先", "Ankle", "Toe"),
    "root": ("全部", "Root", "root", "グルーブ"),
}

#: A bone that moves a finger. Counted rather than matched as a group: how many of them a model carries
#: is what decides whether a wave animation has anything to drive. Bare `指` is deliberately not one of
#: these — every MMD rig has 指先 (fingertip/toetip) bones that are one per limb, not fingers.
FINGER_MARKERS = (
    "親指", "人差し指", "中指", "薬指", "小指",
    "拇指", "食指", "无名指",
    "Thumb", "Index", "Middle", "Ring", "Pinky", "Finger",
)

#: The words a readme in this corpus uses to say what may not be done with the model inside it.
LICENSE_MARKERS = ("二次配布", "二次发布", "再配布", "redistribut")

#: One line of it is enough to show the user; a readme pasted whole is not a licence note.
LICENSE_NOTE_MAX_CHARS = 400

TEXTURE_FORMATS_WITHOUT_A_BROWSER = (".tga", ".bmp")


@dataclass(frozen=True)
class TextureRef:
    """One path the material table named, and whether Kira can actually get those bytes.

    `declared` is kept verbatim next to `relative` on purpose. A model that says `tex\\颜.tga` is telling
    you the exporter ran on Windows and wrote a native path; normalising it away would hide the only
    clue a loader has for why it looked in the wrong place.
    """

    declared: str
    relative: str
    exists: bool
    size: int | None = None
    format: str = ""
    escapes: bool = False

    @property
    def suffix(self) -> str:
        return Path(self.relative).suffix.lower()


@dataclass(frozen=True)
class ModelReport:
    """Everything the stage needs to know before it asks a GPU anything."""

    name: str
    english_name: str
    file_name: str
    version: float
    count_framing: str
    material_framing: str
    counts: dict[str, int | None]
    standard_groups: tuple[str, ...]
    finger_bone_count: int
    morph_names: tuple[str, ...]
    morph_kinds: tuple[int, ...]
    frame_names: tuple[str, ...]
    textures: tuple[TextureRef, ...]
    texture_resolved: int
    missing_textures: tuple[str, ...]
    sphere_texture_refs: int
    shared_toon_refs: int
    ik_bone_count: int
    trailing_bytes: int
    findings: tuple[str, ...]
    license_note: str | None
    unreadable: str | None

    @property
    def vertex_count(self) -> int:
        return int(self.counts.get("vertex_count") or 0)

    @property
    def bone_count(self) -> int:
        return int(self.counts.get("bone_count") or 0)

    @property
    def triangle_count(self) -> int:
        face = self.counts.get("face_index_count")
        return 0 if face is None else int(face) // 3

    @property
    def has_physics(self) -> bool:
        return int(self.counts.get("rigid_body_count") or 0) > 0

    @property
    def is_character(self) -> bool:
        """The body test, stated once so the library table and the picker cannot drift apart."""
        return self.bone_count >= MAIN_MIN_BONES and self.vertex_count > MAIN_MIN_VERTS

    @property
    def texture_status(self) -> str:
        """What the library row shows: `8/8`, or `7/8 — hair.bmp absent`."""
        total = len(self.textures)
        if not total:
            return "no textures"
        if len(self.missing_textures) == 0:
            return f"{total}/{total}"
        first, rest = self.missing_textures[0], self.missing_textures[1:]
        tail = f", {len(rest)} more" if rest else ""
        return f"{self.texture_resolved}/{total} — {first} absent{tail}"


def normalise_texture_path(declared: str) -> tuple[str, bool]:
    """The path a texture has to be looked up by, and whether it tries to leave the model's folder.

    A PMX texture path is relative to the file that names it and, for anything made on Windows, uses
    backslashes. `..` in one is not a zip-slip and is not refused here — the model is on the user's own
    disk and the importer only ever reads inside the directory it copied — but it is a reference Kira
    cannot resolve, so it is reported as an escape instead of being silently rewritten.

    Public because `mesh.py` tags the same paths for the stage with it: one rule, so the library's report
    and the mesh's texture table cannot call the same reference two different things.
    """
    flat = declared.replace("\\", "/")
    parts = [part for part in flat.split("/") if part not in ("", ".")]
    escapes = flat.startswith("/") or any(part == ".." for part in parts)
    return "/".join(parts), escapes


def _license_line(directory: Path) -> str | None:
    """The one line in a readme next to the model that says what may not be done with it.

    Every archive in the donor corpus carries such a file, written in Chinese or Japanese, and the terms
    have to travel with the character. Absence is not an error and not a finding: plenty of legal models
    ship without a readme, and the report says nothing about a licence it did not read.
    """
    for readme in sorted(directory.rglob("*.txt")):
        try:
            raw = readme.read_bytes()
        except OSError:
            continue
        for codec in ("utf-8", "gbk", "shift_jis"):
            try:
                text = raw.decode(codec)
            except UnicodeDecodeError:
                continue
            for line in text.splitlines():
                stripped = line.strip()
                if stripped and any(marker in stripped for marker in LICENSE_MARKERS):
                    return stripped[:LICENSE_NOTE_MAX_CHARS]
            break
    return None


def describe(model: "bytes | PmxModel", directory: "Path | str", file_name: str = "model.pmx") -> ModelReport:
    """Say what one model can and cannot render, from its bytes and the folder it lives in.

    Everything a renderer would otherwise swallow is said here instead: a texture that is not in the
    folder, a path written with backslashes, a `.tga` a browser cannot decode without a decoder of its
    own, a sphere or shared-toon reference that points at a table the walk never reads. None of it stops
    the model from loading, all of it changes what loads, and a user who is told afterwards is a user who
    has to open a hex editor.

    The folder is not an optional argument. A PMX texture path means *relative to the file that names it*,
    so resolving one against whatever directory the process happens to stand in would answer a different
    question and report it as this one; a caller that has no folder to name says so by passing one that is
    not there, and every reference comes back absent.
    """
    walked = model if isinstance(model, PmxModel) else read_pmx_model(model)

    directory = Path(directory)
    findings = list(walked.findings)

    textures: list[TextureRef] = []
    missing: list[str] = []
    for declared in walked.texture_paths:
        relative, escapes = normalise_texture_path(declared)
        suffix = Path(relative).suffix.lower()
        target = directory / relative
        exists = not escapes and target.is_file()
        if not exists:
            missing.append(relative or declared)
        textures.append(
            TextureRef(
                declared=declared,
                relative=relative,
                exists=exists,
                size=target.stat().st_size if exists else None,
                format=suffix.lstrip("."),
                escapes=escapes,
            )
        )

    backslash = [t.declared for t in textures if "\\" in t.declared]
    if backslash:
        findings.append(
            f"{len(backslash)} texture path(s) are written with backslashes, which a browser never "
            f"separates: {', '.join(repr(name) for name in backslash[:3])}"
        )
    exotic = sorted({t.format for t in textures if f".{t.format}" in TEXTURE_FORMATS_WITHOUT_A_BROWSER})
    if exotic:
        findings.append(
            f"textures come in {', '.join('.' + name for name in exotic)}, which no browser decodes on "
            f"its own; Kira reads them with its own loader"
        )
    if walked.sphere_refs:
        findings.append(
            f"{walked.sphere_refs} material(s) reference a sphere map, which the stage does not blend "
            f"into the toon shading"
        )
    if walked.shared_toon_refs:
        findings.append(
            f"{walked.shared_toon_refs} material(s) use a shared toon index; the built-in toon table "
            f"behind those numbers is not read here"
        )

    groups = tuple(
        group
        for group, markers in BONE_GROUPS.items()
        if any(any(marker in bone for marker in markers) for bone in walked.bone_names)
    )
    fingers = sum(
        1
        for bone in walked.bone_names
        if any(marker in bone for marker in FINGER_MARKERS)
    )

    return ModelReport(
        name=walked.display_name,
        english_name=walked.name_en,
        file_name=file_name,
        version=walked.version,
        count_framing=walked.count_framing,
        material_framing=walked.material_framing,
        counts=dict(walked.counts),
        standard_groups=groups,
        finger_bone_count=fingers,
        morph_names=walked.morph_names,
        morph_kinds=walked.morph_kinds,
        frame_names=walked.frame_names,
        textures=tuple(textures),
        texture_resolved=sum(1 for texture in textures if texture.exists),
        missing_textures=tuple(missing),
        sphere_texture_refs=walked.sphere_refs,
        shared_toon_refs=walked.shared_toon_refs,
        ik_bone_count=walked.ik_bone_count,
        trailing_bytes=walked.trailing_bytes,
        findings=tuple(findings),
        license_note=_license_line(directory) if directory.is_dir() else None,
        unreadable=walked.unreadable,
    )


@dataclass(frozen=True)
class ModelPick:
    """The body in a folder of models, and everything else that came with it."""

    main: object | None
    companions: tuple[object, ...]
    reason: str


def choose_main(models: "list | tuple") -> ModelPick:
    """Pick the body, not the prop.

    The test is bones *and* vertices, not a skeleton-matching score. The corpus is what set both: nine
    props stop at 8 255 vertices and 38 bones — an umbrella with 14 rigid bodies, the densest thing a
    character holds — while eleven characters start at 26 798 vertices and 297 bones, so nothing in that
    library is near either line from the wrong side. What is left over is not discarded: a weapon and a
    mirror are held *by* someone, so they come back as companions for the same stage.

    Nothing qualifies is an answer, not a failure to answer: `main` stays `None` and `reason` says the
    biggest thing the folder actually had.
    """
    candidates = list(models)
    bodies = [model for model in candidates if model.is_character]
    ranked = tuple(sorted(candidates, key=lambda model: model.vertex_count, reverse=True))
    if bodies:
        main = max(bodies, key=lambda model: model.vertex_count)
        reason = (
            f"{main.name} has {main.bone_count} bones and {main.vertex_count} vertices, the only entry "
            f"over both {MAIN_MIN_BONES} bones and {MAIN_MIN_VERTS:,} vertices"
            if len(bodies) == 1
            else f"{len(bodies)} entries pass the body test; {main.name} has the most vertices"
        )
    else:
        main = None
        biggest = ranked[0] if ranked else None
        reason = (
            "the archive holds no PMX"
            if biggest is None
            else f"no entry has both {MAIN_MIN_BONES}+ bones and more than {MAIN_MIN_VERTS:,} vertices; "
            f"the largest is {biggest.name} at {biggest.vertex_count} vertices and "
            f"{biggest.bone_count} bones, which is a prop"
        )
    return ModelPick(main=main, companions=tuple(model for model in ranked if model is not main), reason=reason)


# --- the archive a character usually arrives in -------------------------------------------------------

#: An archive is read into memory before anything is written, so the wall is on the bytes supplied, and
#: the donor corpus peaks at 45 MB. 200 MB is headroom, not a budget.
ARCHIVE_CAP_BYTES = 200 * 1024 * 1024
#: The widest single entry measured here is a 29.4 MB texture; 64 MB leaves room for a 4K map.
ENTRY_CAP_BYTES = 64 * 1024 * 1024
#: A character with its textures, spares and morphs expands to 71.5 MB at worst. 400 MB is the wall.
EXPANDED_CAP_BYTES = 400 * 1024 * 1024
#: Below 1 MB an entry is too small to matter next to the caps above, and real ones do compress hard:
#: `hair.bmp` in the donor corpus is 1.1 KB out of 18 bytes (62:1) and is a legitimate texture.
RATIO_MIN_BYTES = 1024 * 1024
MAX_EXPANSION_RATIO = 50
#: The busiest donor archive has 45 entries. 500 is a wall, not a budget.
MAX_ENTRIES = 500

CHUNK_BYTES = 1 << 20

BAD_ARCHIVE = "bad_archive"
UNSAFE_ENTRY = "unsafe_entry"
TOO_LARGE = "too_large"

_UTF8_FLAG = 0x800
_ENCRYPTED_FLAG = 0x1


@dataclass(frozen=True)
class ArchivedFile:
    """One entry that made it onto disk."""

    name: str
    path: Path
    size: int


def entry_name(info: zipfile.ZipInfo) -> str:
    """The name the writer meant, not the one cp437 guessed.

    `zipfile` decodes an entry name as utf-8 only when the flag says so and as cp437 otherwise, so an
    archive that stores GBK bytes with no flag — the ordinary output of a Chinese packaging tool —
    arrives as `╤╒`. The importer then writes `╤╒.tga` while the model references `颜.tga`, and the
    character loads with no textures and nothing to complain about. Repairing it means getting the bytes
    back, and a cp437 re-encode is exact for a name cp437 produced.

    Order matters once the bytes are in hand: utf-8 first, because a writer that forgot the flag is more
    common than a writer that used a legacy codepage, and GBK pairs rarely form valid utf-8 anyway. A
    name that cannot be re-encoded at all is one `zipfile` already repaired from an Info-ZIP Unicode
    Path field — nine of the ten donor archives use that field, and the repair lands on the same string
    either way.

    `orig_filename` and not `filename`: the latter has already been cut at the first NUL byte and had
    every backslash replaced, which is precisely the evidence an entry-name refusal has to keep.
    """
    raw_name = info.orig_filename
    if info.flag_bits & _UTF8_FLAG:
        return raw_name
    try:
        raw = raw_name.encode("cp437")
    except UnicodeEncodeError:
        return raw_name
    for codec in ("utf-8", "gbk"):
        try:
            return raw.decode(codec)
        except UnicodeDecodeError:
            continue
    return raw_name


def safe_entry(name: str) -> str:
    """The relative posix path an entry is allowed to write, or a refusal that names it.

    Backslashes count as separators: `tex\\..\\..\\x` escapes just as surely as the unix form, and on
    Windows it would while a unix reader waved it through as one odd filename. Normalising here is also
    what makes the layout identical on either OS.
    """
    if "\x00" in name:
        raise CharacterError(
            f"archive entry {name!r} has a NUL byte in its name", code=UNSAFE_ENTRY, entry=name
        )
    flat = name.replace("\\", "/")
    head, _, _ = flat.partition("/")
    if flat.startswith("/") or (len(head) == 2 and head[1] == ":" and head[0].isalpha()):
        raise CharacterError(f"archive entry {name!r} is an absolute path", code=UNSAFE_ENTRY, entry=name)

    parts = [part for part in flat.split("/") if part not in ("", ".")]
    if any(part == ".." for part in parts):
        raise CharacterError(
            f"archive entry {name!r} climbs out of the staging directory", code=UNSAFE_ENTRY, entry=name
        )
    if not parts:
        raise CharacterError(f"archive entry {name!r} resolves to nothing", code=UNSAFE_ENTRY, entry=name)
    # The folder the importer itself writes into must not arrive from the archive too. A nested
    # `<something>/profile.json` is the dangerous one: the importer only rewrites the *top-level*
    # profile after unpacking, so a nested copy survives into the installed character and is then
    # served by `GET /kira/characters/{id}/file?path=<something>/profile.json` — attacker-controlled
    # JSON handed out as a library profile. Reserving the two names at every depth closes that
    # without needing to guess which subfolder a later reader might treat as a character.
    if parts[-1] in _RESERVED_ENTRY_NAMES:
        raise CharacterError(
            f"archive entry {name!r} uses the reserved name '{parts[-1]}', which Kira writes itself",
            code=UNSAFE_ENTRY,
            entry=name,
        )
    return "/".join(parts)


def _check_entry(info: zipfile.ZipInfo) -> tuple[str, bool]:
    """One entry's destination and size, checked in full before anything is written."""
    name = entry_name(info)
    if stat.S_ISLNK(info.external_attr >> 16):
        raise CharacterError(
            f"archive entry {name!r} is a symlink; Kira writes files, not links",
            code=UNSAFE_ENTRY,
            entry=name,
        )
    if info.flag_bits & _ENCRYPTED_FLAG:
        raise CharacterError(
            f"archive entry {name!r} is password-protected, which no reader here can open",
            code=BAD_ARCHIVE,
            entry=name,
        )
    rel = safe_entry(name)
    if info.file_size > ENTRY_CAP_BYTES:
        raise CharacterError(
            f"archive entry {name!r} declares {info.file_size} byte(s), over the "
            f"{ENTRY_CAP_BYTES} byte (64 MB) limit for one entry",
            code=TOO_LARGE,
            entry=name,
        )
    if (
        info.file_size >= RATIO_MIN_BYTES
        and info.compress_size
        and info.file_size > MAX_EXPANSION_RATIO * info.compress_size
    ):
        raise CharacterError(
            f"archive entry {name!r} expands {info.file_size // info.compress_size} times from its "
            f"{info.compress_size} stored byte(s), past the {MAX_EXPANSION_RATIO}:1 a bomb hides behind",
            code=TOO_LARGE,
            entry=name,
        )
    return rel, name.endswith(("/", "\\"))


#: What reading a zip can raise once the archive as a whole has opened. `zipfile` does not confine
#: itself to `BadZipFile`: an entry whose header names a compression method this build cannot decode
#: raises `NotImplementedError`, and an entry flagged encrypted (or whose method defeats the core
#: reader) raises `RuntimeError`. Neither is a `CharacterError`, so before this tuple existed a
#: corrupt-but-parseable download reached the caller as an unhandled 500 and the CLI as a traceback,
#: instead of the documented `bad_archive`.
ZIP_READ_FAILURES = (zipfile.BadZipFile, NotImplementedError, RuntimeError)


def _read_entry(archive: zipfile.ZipFile, info: zipfile.ZipInfo, rel: str) -> bytes:
    """Read one entry, stopping the moment it outgrows what its own header declared.

    The declared size is a ceiling and not a hint, and it is checked chunk by chunk because the entry
    caps in the pre-flight pass only see what the header chose to admit. A header that understates its
    own size is the one the caps cannot catch, so the refusal lands with the first chunk over it — before
    this entry is written at all.
    """
    chunks: list[bytes] = []
    read = 0
    try:
        with archive.open(info) as source:
            while chunk := source.read(CHUNK_BYTES):
                read += len(chunk)
                if read > info.file_size:
                    raise CharacterError(
                        f"archive entry {rel!r} expands past the {info.file_size} byte(s) its header "
                        f"declares",
                        code=BAD_ARCHIVE,
                        entry=rel,
                    )
                chunks.append(chunk)
    except ZIP_READ_FAILURES as exc:
        raise CharacterError(
            f"archive entry {rel!r} cannot be read: {exc}", code=BAD_ARCHIVE, entry=rel
        ) from exc
    return b"".join(chunks)


def extract_zip(data: bytes, dest: Path) -> list[ArchivedFile]:
    """Unpack an archive under `dest`, refusing everything the path rules and the caps forbid.

    Two passes on purpose. Every entry name and every size in the central directory is checked before a
    byte is written — including the sum of what the entries declare — so a refusal leaves the staging
    directory empty rather than half a character. Each entry is then read whole, stopped the moment it
    outgrows its own declaration, and written only once it is known good, which is why no refusal here
    ever leaves a partial file. `dest` belongs to the caller — the importer points this at a staging
    directory and renames.
    """
    if len(data) > ARCHIVE_CAP_BYTES:
        raise CharacterError(
            f"the archive is {len(data)} byte(s), over the {ARCHIVE_CAP_BYTES} byte (200 MB) limit",
            code=TOO_LARGE,
        )
    dest = Path(dest)
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_ENTRIES:
                raise CharacterError(
                    f"the archive holds {len(infos)} entries, over the {MAX_ENTRIES} Kira imports",
                    code=TOO_LARGE,
                )
            declared = sum(info.file_size for info in infos)
            if declared > EXPANDED_CAP_BYTES:
                raise CharacterError(
                    f"the archive declares {declared} byte(s) across {len(infos)} entries, over the "
                    f"{EXPANDED_CAP_BYTES} byte (400 MB) limit",
                    code=TOO_LARGE,
                )
            targets = [_check_entry(info) for info in infos]

            written: list[ArchivedFile] = []
            for info, (rel, is_dir) in zip(infos, targets):
                if is_dir:
                    (dest / rel).mkdir(parents=True, exist_ok=True)
                    continue
                payload = _read_entry(archive, info, rel)
                target = dest / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(payload)
                written.append(ArchivedFile(name=rel, path=target, size=len(payload)))
            return written
    except ZIP_READ_FAILURES as exc:
        # `CharacterError` is deliberately not in this tuple: a refusal raised by the caps above must
        # keep its own code rather than being relabelled `bad_archive` on its way out.
        raise CharacterError(f"not a readable zip archive: {exc}", code=BAD_ARCHIVE) from exc


# --- the library: an import that cannot leave half a body on disk -----------------------------------

#: Where the library lives: `<data>/characters/<id>/`. `Config.characters_dir` is the one place that says
#: so, because the agent's workspace and the character library must not be the same folder — a character
#: is 45 MB the model is not allowed to edit.
CHARACTERS_FOLDER_NAME = "characters"
PROFILE_NAME = "profile.json"
#: The body is always loaded under this name, so the stage never has to guess which of the three PMX
#: files in an archive goes on screen. Props keep the names their archive gave them.
MODEL_NAME = "model.pmx"
#: Names the importer writes itself, so no archive entry may carry one at any depth. The top-level
#: versions are overwritten by the importer anyway; the nested ones are the ones that used to survive
#: and then be served back as a trusted profile.
_RESERVED_ENTRY_NAMES = frozenset({PROFILE_NAME})
#: Written into every profile so a later reader knows which report fields it was made from.
PROFILE_SCHEMA = 1
#: The id is `<slug>-<sha8>`. Eight hex digits is a collision this library's size cannot reach, and
#: dedupe and removal both answer by name — so a short id has to be a real one, and the four files that
#: share a name in the donor corpus share nothing else.
ID_SLUG_MAX_CHARS = 24
ID_DIGEST_CHARS = 8
#: The character on stage, in the same `meta` table memory keeps its switches in.
ACTIVE_KEY = "avatar.active"

ALREADY_IMPORTED = "already_imported"
CHARACTER_EXISTS = "character_exists"
CHARACTER_NOT_FOUND = "character_not_found"
NO_PMX_IN_ARCHIVE = "no_pmx_in_archive"
#: The thing a caller pointed at is not a character file at all — wrong extension, or no file there. The
#: routes answer this for both, because "I cannot read that path" and "that path is not a model" send the
#: user to the same place: the file picker.
UNSUPPORTED_SOURCE = "unsupported_source"
#: A member the character's own folder does not have. Separate from `character_not_found`: the library has
#: the body, the stage asked for a texture that did not ship with it, and only one of those is a broken
#: import.
CHARACTER_FILE_NOT_FOUND = "character_file_not_found"


@dataclass(frozen=True)
class CharacterEntry:
    """One character that landed, and the folder it landed in."""

    id: str
    directory: Path
    profile: dict
    report: "ModelReport | None"

    @property
    def model_path(self) -> "Path | None":
        """The file the stage loads, or None when the archive held no body."""
        main = self.profile["main"]
        return None if main is None else self.directory / str(main["path"])


def _slug(value: str) -> str:
    """The ascii part of a name, or nothing.

    CJK is left out rather than transliterated: a wrong romanisation is a folder name the user cannot
    connect to the character they imported, and 耀嘉音 in a folder called `yaojiayin-…` is only right as
    long as the reader guessed the reading correctly.
    """
    cleaned = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return cleaned[:ID_SLUG_MAX_CHARS].strip("-")


def character_id(display_name: str, english_name: str, source_sha256: str) -> str:
    """The folder name a character gets: a slug, and eight hex digits of the bytes it came from.

    The digits come from the *source*, not from the model inside it. A character and the same character
    repacked with one more texture are then two imports, which is the honest answer: the archive carries
    the textures, and the textures are what changed.
    """
    for candidate in (display_name, english_name):
        slug = _slug(candidate)
        if slug:
            return f"{slug}-{source_sha256[:ID_DIGEST_CHARS]}"
    return f"model-{source_sha256[:ID_DIGEST_CHARS]}"


def report_dict(report: ModelReport, path: str) -> dict:
    """One report as it goes into a profile and out of a route.

    Explicit rather than `asdict`, because this is the wire shape: the derived numbers the stage actually
    uses (`vertices`, `texture_status`, `is_character`) travel next to the raw counts they came from, so a
    client cannot reimplement the body test and drift from it.
    """
    return {
        "path": path,
        "name": report.name,
        "english_name": report.english_name,
        "file_name": report.file_name,
        "version": report.version,
        "count_framing": report.count_framing,
        "material_framing": report.material_framing,
        "counts": dict(report.counts),
        "vertices": report.vertex_count,
        "bones": report.bone_count,
        "triangles": report.triangle_count,
        "has_physics": report.has_physics,
        "is_character": report.is_character,
        "texture_status": report.texture_status,
        "standard_groups": list(report.standard_groups),
        "finger_bone_count": report.finger_bone_count,
        "morph_names": list(report.morph_names),
        "morph_kinds": list(report.morph_kinds),
        "frame_names": list(report.frame_names),
        "textures": [
            {
                "declared": texture.declared,
                "relative": texture.relative,
                "exists": texture.exists,
                "size": texture.size,
                "format": texture.format,
                "escapes": texture.escapes,
            }
            for texture in report.textures
        ],
        "texture_resolved": report.texture_resolved,
        "missing_textures": list(report.missing_textures),
        "sphere_texture_refs": report.sphere_texture_refs,
        "shared_toon_refs": report.shared_toon_refs,
        "ik_bone_count": report.ik_bone_count,
        "trailing_bytes": report.trailing_bytes,
        "findings": list(report.findings),
        "license_note": report.license_note,
        "unreadable": report.unreadable,
    }


def _folder_is_an_id(value: str) -> bool:
    """Whether a string can name a character folder at all: one segment, and nothing pointing up.

    A route hands this a value out of a URL. `str.isidentifier` would reject `ellen-a1b2c3d4`, which is
    the shape real ids have, so the test is the one that matters: no separator, no NUL, no dot-dot, and no
    reaching for a staging directory.
    """
    return (
        bool(value)
        and "\x00" not in value
        and "/" not in value
        and "\\" not in value
        and value not in (".", "..")
        and not value.startswith(".")
    )


def _profiles(directory: Path) -> "list[tuple[str, dict]]":
    """Every profile in the library, in id order. A folder with no profile is not in the library.

    Staging directories are skipped by name and not by state: they are the only thing that can sit in this
    folder while an import is in flight, and a listing that half-reads one would show a character that
    does not exist yet.
    """
    if not directory.is_dir():
        return []
    found: "list[tuple[str, dict]]" = []
    for child in sorted(directory.iterdir(), key=lambda path: path.name):
        if not child.is_dir() or child.name.startswith("."):
            continue
        try:
            profile = json.loads((child / PROFILE_NAME).read_bytes().decode("utf-8"))
        except (OSError, UnicodeDecodeError, ValueError):
            continue
        if isinstance(profile, dict) and profile.get("id") == child.name:
            found.append((child.name, profile))
    return found


def _find_by_digest(directory: Path, digest: str) -> "str | None":
    for name, profile in _profiles(directory):
        if str((profile.get("source") or {}).get("sha256", "")) == digest:
            return name
    return None


def _row(profile: dict) -> dict:
    """The library row: enough to choose a character without opening its folder."""
    main = profile["main"]
    return {
        "id": profile["id"],
        "display_name": profile["display_name"],
        "english_name": profile["english_name"],
        "source_file_name": profile["source"]["file_name"],
        "sha256": profile["source"]["sha256"],
        "imported_at": profile["imported_at"],
        "is_character": main is not None,
        "main_name": None if main is None else main["name"],
        "path": None if main is None else main["path"],
        "vertices": 0 if main is None else main["vertices"],
        "bones": 0 if main is None else main["bones"],
        "has_physics": False if main is None else main["has_physics"],
        "texture_status": None if main is None else main["texture_status"],
        "companion_count": len(profile["companions"]),
        "license_note": profile["license_note"],
        "reason": profile["reason"],
    }


def list_characters(directory: "Path | str") -> "tuple[dict, ...]":
    """The library as rows, read from the profiles alone.

    Walking a PMX costs up to 0.18 s and pages a 45 MB file; a list that did it per row would make the
    library the slowest screen in Kira. The profile already holds every number a row shows, measured at
    import by the same code `describe()` would use, so re-walking would buy nothing and cost everything.
    """
    return tuple(_row(profile) for _, profile in _profiles(Path(directory)))


def get_character(directory: "Path | str", value: str) -> dict:
    """One profile, whole, or a refusal that names the id it looked for."""
    if not _folder_is_an_id(value):
        raise CharacterError(
            f"'{value}' is not a character id", code=CHARACTER_NOT_FOUND, entry=value
        )
    try:
        profile = json.loads((Path(directory) / value / PROFILE_NAME).read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise CharacterError(
            f"no character '{value}' here ({exc.__class__.__name__})",
            code=CHARACTER_NOT_FOUND,
            entry=value,
        ) from exc
    if not isinstance(profile, dict) or profile.get("id") != value:
        raise CharacterError(
            f"the folder '{value}' holds no profile that claims that id",
            code=CHARACTER_NOT_FOUND,
            entry=value,
        )
    return profile


def _unpack(data: bytes, staging: Path, source_name: str) -> "tuple[list[Path], bool]":
    """Put the bytes in the staging directory and return the PMX files found there, plus whether they
    arrived in an archive.

    A bare PMX lands as `model.pmx`. An archive is unpacked where the archive put each entry, because a
    texture reference is relative to the file that names it — flattening `Ellen/tex/颜.png` up to the root
    would break every model that reads it. Which of the found models is the body is `choose_main`'s call.
    """
    if data.startswith(MAGIC):
        target = staging / MODEL_NAME
        target.write_bytes(data)
        return [target], False
    if data[:2] == b"PK":
        extract_zip(data, staging)
        pmx_files = sorted(
            path for path in staging.rglob("*") if path.is_file() and path.suffix.lower() == ".pmx"
        )
        return pmx_files, True
    raise CharacterError(
        f"'{source_name}' is neither a PMX (its first four bytes are not {MAGIC!r}) nor a zip archive",
        code=BAD_ARCHIVE,
        entry=source_name,
    )


def _active_id(store) -> "str | None":
    row = store.conn.execute("SELECT value FROM meta WHERE key=?", (ACTIVE_KEY,)).fetchone()
    if row is None:
        return None
    value = json.loads(row["value"])
    return None if value is None else str(value)


def _clear_active(store, removed_id: str) -> None:
    if _active_id(store) == removed_id:
        store.conn.execute("DELETE FROM meta WHERE key=?", (ACTIVE_KEY,))
        store.conn.commit()


def import_character(
    directory: "Path | str", data: bytes, *, source_name: str = "character"
) -> CharacterEntry:
    """Land one character, or land nothing.

    The order is the design. Unpack into a staging directory *inside* the library, walk every model there,
    rename the body to `model.pmx`, write the profile, and only then rename the staging directory to its
    id. `os.replace` within one volume is atomic, so anyone listing the library sees either the finished
    character or nothing — never the `hair.bmp` of a body whose profile was never written. Any refusal,
    and any exception at all, leaves the library byte for byte as it was found: the staging directory goes
    in the `finally`, and the id folder is created by nothing but that rename.

    Two different byte streams can want the same id — `character_id` keeps eight hex digits, not
    sixty-four — and that is a refusal rather than an overwrite. Replacing a character the user is looking
    at is the one thing an importer must never do quietly.

    Import never makes the newcomer the active character: that is `set_active`'s call, and an import that
    repainted the stage behind the user's back would be a surprise with a 45 MB payload.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(data).hexdigest()
    duplicate = _find_by_digest(directory, digest)
    if duplicate is not None:
        raise CharacterError(f"already imported: {duplicate}", code=ALREADY_IMPORTED)

    staging = Path(tempfile.mkdtemp(prefix=f".staging-{digest[:ID_DIGEST_CHARS]}-", dir=directory))
    try:
        found, in_archive = _unpack(data, staging, source_name)
        if not found:
            raise CharacterError(
                f"'{source_name}' unpacked to {len(list(staging.rglob('*')))} file(s) and not one of them "
                f"is a .pmx, so there is no model here to import",
                code=NO_PMX_IN_ARCHIVE,
                entry=source_name,
            )
        reports = [
            describe(read_pmx_model(path.read_bytes()), path.parent, file_name=path.name)
            for path in found
        ]
        pick = choose_main(reports)

        main_report = pick.main
        main_path: Path | None = None
        if main_report is not None:
            main_path = found[reports.index(main_report)]
            if main_path.name != MODEL_NAME:
                renamed = main_path.with_name(MODEL_NAME)
                os.replace(main_path, renamed)
                # Re-describe the renamed file: `file_name` is a claim about what the stage will open,
                # and after a rename the old one would be a lie. The texture paths do not move, so the
                # counts and the resolution come back exactly as they were.
                main_report = describe(
                    read_pmx_model(renamed.read_bytes()), renamed.parent, MODEL_NAME
                )
                main_path = renamed

        # What the library calls this character: the body if the archive has one, and otherwise the
        # biggest thing it does have — `choose_main` ranks its companions by vertices, so [0] is that.
        named = main_report if main_report is not None else pick.companions[0]
        profile = {
            "schema": PROFILE_SCHEMA,
            "id": character_id(named.name, named.english_name, digest),
            "display_name": named.name,
            "english_name": named.english_name,
            "imported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source": {
                "file_name": source_name,
                "sha256": digest,
                "bytes": len(data),
                "archive": in_archive,
            },
            "reason": pick.reason,
            "license_note": named.license_note,
            "main": (
                None if main_report is None or main_path is None
                else report_dict(main_report, main_path.relative_to(staging).as_posix())
            ),
            "companions": [
                report_dict(report, path.relative_to(staging).as_posix())
                for path, report in zip(found, reports)
                if report is not pick.main
            ],
            "files": [
                {"path": path.relative_to(staging).as_posix(), "bytes": path.stat().st_size}
                for path in sorted(staging.rglob("*"))
                if path.is_file()
            ],
        }
        target = directory / str(profile["id"])
        if target.exists():
            raise CharacterError(
                f"the id '{profile['id']}' already names a character here, and its bytes are not "
                f"these; nothing was overwritten",
                code=CHARACTER_EXISTS,
                entry=str(profile["id"]),
            )
        (staging / PROFILE_NAME).write_bytes(
            json.dumps(profile, ensure_ascii=False, indent=2).encode("utf-8")
        )
        os.replace(staging, target)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return CharacterEntry(
        id=str(profile["id"]), directory=target, profile=profile, report=main_report
    )


def remove_character(directory: "Path | str", value: str, store) -> dict:
    """Delete a character and, if it was the one on stage, take it off stage in the same call.

    The pick is cleared first and the files go after. The other order can leave a pointer at a folder that
    no longer exists, which the stage then fails to load every time it opens; clearing first costs at most
    a character the user has to click again if the delete is the part that fails.
    """
    profile = get_character(directory, value)
    _clear_active(store, value)
    shutil.rmtree(Path(directory) / value)
    return profile


def get_active(directory: "Path | str", store) -> "str | None":
    """Who is on stage now, or None.

    A pointer at a folder that is not in the library answers None rather than the stale id: every caller
    of this is about to try to load those bytes, and an id that cannot be loaded is not a character. The
    row itself is left where it is — a read does not delete state the user can still look at, and
    `set_active` or `remove_character` will overwrite it on the next real change.
    """
    stored = _active_id(store)
    if stored is None or not _folder_is_an_id(stored):
        return None
    try:
        get_character(directory, stored)
    except CharacterError:
        return None
    return stored


def set_active(directory: "Path | str", value: "str | None", store) -> "str | None":
    """Put a character on stage, or take everyone off.

    The id has to name a character that is actually in the library, checked here and not left to the next
    loader: a typo in a settings row is a screen that fails to open, and the user should find out from the
    call that made it. `None` is the one other answer a caller may write, and it clears the key instead of
    storing the word for nothing — a stage with no character and a stage with a character called `null` are
    not the same claim.

    Setting the pick is not a rendering decision and it is not an import side effect. `import_character`
    never calls this: repainting the stage behind the user with a 45 MB model is a surprise, not a result.
    """
    if value is None:
        store.conn.execute("DELETE FROM meta WHERE key=?", (ACTIVE_KEY,))
        store.conn.commit()
        return None
    get_character(directory, value)
    store.conn.execute(
        """INSERT INTO meta(key, value, updated_at) VALUES(?,?,?)
           ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
        (ACTIVE_KEY, json.dumps(value), datetime.now(timezone.utc).timestamp()),
    )
    store.conn.commit()
    return value


# --- the wire: a refusal, in the shape an answer takes -------------------------------------------------


class CharacterRefusal(KiraError):
    """One importer's refusal, wearing the shape the API answers in.

    Never raised itself: it inherits `internal_error` and a 500 from `KiraError`, which is exactly what
    keeps the error-code gate honest. That gate reads the published list off the class tree, so every code
    a route can answer with has to be a class of its own — and a base class that adds no code and answers
    with nothing is the one thing a caller will never see.

    `entry` travels in the body because three of these are about a named thing — the archive entry that
    climbed out, the id that is not in the library, the path a caller supplied — and a sentence the user
    has to read is a weak way of saying which.
    """

    status = 400

    def __init__(self, message: str, *, entry: str | None = None) -> None:
        super().__init__(message)
        self.entry = entry

    def to_dict(self) -> dict:
        body = super().to_dict()
        if self.entry is not None:
            body["error"]["entry"] = self.entry
        return body


class NotAPmx(CharacterRefusal):
    code = NOT_A_PMX


class PmxTruncated(CharacterRefusal):
    code = PMX_TRUNCATED


class PmxVersionUnsupported(CharacterRefusal):
    code = PMX_VERSION_UNSUPPORTED


class BadArchive(CharacterRefusal):
    code = BAD_ARCHIVE


class UnsafeEntry(CharacterRefusal):
    code = UNSAFE_ENTRY


class TooLarge(CharacterRefusal):
    """413, not 400: the caller's file is the problem and its size is the whole answer."""

    code = TOO_LARGE
    status = 413


class NoPmxInArchive(CharacterRefusal):
    code = NO_PMX_IN_ARCHIVE


class AlreadyImported(CharacterRefusal):
    """409: the bytes are already here under a name the message gives. Nothing was overwritten."""

    code = ALREADY_IMPORTED
    status = 409


class CharacterExists(CharacterRefusal):
    code = CHARACTER_EXISTS
    status = 409


class CharacterNotFound(CharacterRefusal):
    code = CHARACTER_NOT_FOUND
    status = 404


class UnsupportedSource(CharacterRefusal):
    code = UNSUPPORTED_SOURCE


class CharacterFileNotFound(CharacterRefusal):
    code = CHARACTER_FILE_NOT_FOUND
    status = 404


#: Every refusal code the importer can raise, and the answer it becomes. Read off the class tree rather
#: than written beside it: a new refusal that forgets this table would answer the wrong code, and
#: `test_every_refusal_code_has_an_answer` turns that into a failing test instead of a confusing one.
ANSWER_FOR_CODE = {cls.code: cls for cls in CharacterRefusal.__subclasses__()}


def wire_for(exc: CharacterError) -> KiraError:
    """The answer this refusal means, with its message and its entry carried over."""
    answer = ANSWER_FOR_CODE.get(exc.code)
    if answer is None:
        # A code with no published answer is this file's bug, not the caller's bad request — but the caller
        # still gets the reason in words and a 400, rather than a 500 that blames the machine for a file
        # it never asked for.
        return ConfigError(f"{exc.code}: {exc.message}")
    return answer(exc.message, entry=exc.entry)


# --- what the routes hand these functions --------------------------------------------------------------

#: A caller points the importer at a file, not a folder: a folder has no bytes to hash, so dedupe cannot
#: answer for it and two imports of the same directory could disagree about what changed. `.pmx` and
#: `.zip` are the two shapes real characters arrive in, and the donor corpus is all `.zip`.
SOURCE_SUFFIXES = (".pmx", ".zip")


def read_source_capped(source: Path) -> bytes:
    """The bytes of an import source, refused by size *before* they are read.

    The cap is checked with `stat` and not against the bytes: a two-gigabyte mistake in a file picker
    should cost one syscall, not two gigabytes of RAM. `ARCHIVE_CAP_BYTES` is the same wall
    `import_character` enforces once the bytes are in hand, so the check here is only about who pays for
    the read. It raises `OSError` for a path that is not there — the caller decides what that means, since
    the route calls it a bad request and the CLI calls it a usage error.
    """
    size = source.stat().st_size
    if size > ARCHIVE_CAP_BYTES:
        raise TooLarge(
            f"'{source.name}' is {size:,} bytes, over the {ARCHIVE_CAP_BYTES:,} Kira imports",
            entry=str(source),
        )
    return source.read_bytes()


def import_from_path(
    directory: "Path | str", path: "Path | str", *, source_name: str | None = None
) -> CharacterEntry:
    """Import the file at `path`, refusing anything that is not a character file before reading it.

    The suffix is checked first and the size second, both before a byte is read; see `read_source_capped`
    for why the cap is a `stat`. The same wall `import_character` enforces once the bytes are in hand, so
    the check here is only about who pays for the read.
    """
    source = Path(path)
    suffix = source.suffix.lower()
    if suffix not in SOURCE_SUFFIXES:
        raise UnsupportedSource(
            f"'{source.name}' is a {suffix or 'extension-less'} file; Kira imports a .pmx or a .zip of one",
            entry=str(source),
        )
    try:
        data = read_source_capped(source)
    except OSError as exc:
        raise UnsupportedSource(
            f"no {suffix} file to import at '{source}' ({exc.strerror or exc.__class__.__name__})",
            entry=str(source),
        ) from exc
    return import_character(directory, data, source_name=source_name or source.name)


#: The extensions a stage asks for, and what it must be told they are. A type missing from this table is
#: refused before the disk is read, which is what keeps this from being a file server: a character folder
#: holds a model, its textures and its profile, and an `.html` in it would be an answer this engine sends
#: with its own origin and its own token in front of it.
FILE_MEDIA_TYPES = {
    ".pmx": "application/octet-stream",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".bmp": "image/bmp",
    ".tga": "image/x-tga",
    ".dds": "image/vnd-directx",
    ".json": "application/json",
}


def character_file(directory: "Path | str", value: str, relative: str) -> tuple[Path, str]:
    """One file inside one character's folder, resolved and checked, with the media type to call it.

    The refusal is about where the path lands, not about what characters it contains. `tex/../tex/颜.png`
    is a way of asking for a texture that exists, and a loader that normalises before it asks — which is
    what joining two paths does — would otherwise fail for a reason nobody could name. What gets refused is
    a path that resolves outside the character's own folder, which is where the three shapes that have made
    static servers leak end up: a percent-encoded separator, an absolute path, and a symlink planted inside
    and pointing out. `Path.resolve()` is what judges all three, because it follows the link and the
    dot-dots and hands back the one answer that can be compared to the folder.
    """
    get_character(directory, value)
    text = unquote(relative or "")
    if not text or "\x00" in text:
        raise UnsafeEntry(f"'{relative}' is not a file inside a character folder", entry=relative)
    flat = text.replace("\\", "/")
    head, _, _ = flat.partition("/")
    if flat.startswith("/") or (len(head) == 2 and head[1] == ":" and head[0].isalpha()):
        raise UnsafeEntry(f"'{relative}' is an absolute path", entry=relative)
    parts = [part for part in flat.split("/") if part not in ("", ".")]
    if not parts:
        raise UnsafeEntry(f"'{relative}' resolves to nothing", entry=relative)

    folder = Path(directory) / value
    try:
        home = folder.resolve()
        resolved = folder.joinpath(*parts).resolve()
    except OSError as exc:
        raise UnsafeEntry(
            f"'{relative}' cannot be resolved ({exc.strerror or exc.__class__.__name__})",
            entry=relative,
        ) from exc
    if resolved != home and home not in resolved.parents:
        raise UnsafeEntry(
            f"'{relative}' climbs out of the folder of character '{value}'", entry=relative
        )

    media = FILE_MEDIA_TYPES.get(resolved.suffix.lower())
    if media is None:
        raise UnsupportedSource(
            f"'{relative}' is not a file the stage loads; ask for one of {', '.join(sorted(FILE_MEDIA_TYPES))}",
            entry=relative,
        )
    if not resolved.is_file():
        raise CharacterFileNotFound(
            f"character '{value}' has no file '{relative}'", entry=relative
        )
    return resolved, media
