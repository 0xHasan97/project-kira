"""The blob the browser decoder is proved against, checked back into the writer that made it.

`kira-chat/src/avatar/krm1.ts` reads KRM1, and its suite decodes one fixture rather than a blob its own
author invented. That is only worth anything if the fixture really is `pack_mesh` output, so this module
base64-decodes the string the client ships and compares it, byte for byte, with what this engine packs for
the parameters named in the file's own comment — and then checks that the comment still names them. A
stale provenance line is how a fixture quietly becomes a different model, and the browser tests would go
on passing against a transcript of nothing.
"""

from __future__ import annotations

import base64
import re
import struct
from pathlib import Path

from sample_pmx import write_pmx

from kira.mesh import KRM1_FORMAT, KRM1_MAGIC, pack_mesh

#: The model the browser fixture is: four vertices, two materials (the second memo-only), three bones, one
#: vertex morph, and the six texture references a real corpus contains — a subfolder with a CJK filename,
#: the TGA only Kira decodes, a file the archive never carried, a `..` escape the engine flags on the wire,
#: a path that is absolute on the machine that wrote it, and a format no browser opens.
FIXTURE_PARAMS = dict(
    vertex_count=4, face_index_count=6, texture_count=6, material_count=2, bone_count=3,
    frame_count=1, rigid_body_count=1, constraint_count=1,
)
FIXTURE_TEXTURES = ("tex\\颜.png", "hair.tga", "hair.bmp", "..\\outside.png", "C:\\Users\\me\\face.png", "body.dds")
FIXTURE_MORPHS = (("口", 1), ("まばたき", 0))

#: The three lines the fixture module's doc comment has to keep, word for word.
PROVENANCE = (
    "The model behind it is `write_pmx(vertex_count=4, face_index_count=6, texture_count=6, material_count=2,",
    'bone_count=3, varied=True, weight_kind=2, morphs=(("口", 1), ("まばたき", 0)), morph_elements=2,',
    'textures=("tex\\颜.png", "hair.tga", "hair.bmp", "..\\outside.png", "C:\\Users\\me\\face.png", "body.dds"))`.',
)

#: What the header's seven little-endian words state, in the order the format publishes them.
FIXTURE_COUNTS = (KRM1_FORMAT, 4, 6, 3, 2, 6, 1)

FIXTURE_PATH = Path(__file__).parents[2] / "kira-chat" / "src" / "avatar" / "krm1-fixture.ts"


def packed() -> bytes:
    return pack_mesh(write_pmx(**FIXTURE_PARAMS, varied=True, weight_kind=2, morphs=FIXTURE_MORPHS,
                              morph_elements=2, textures=FIXTURE_TEXTURES))


def shipped() -> bytes:
    """The bytes the client file carries.

    The base64 is written in 76-character runs so the module stays readable in a diff; joining every
    literal after the declaration is the whole of what the browser does with `atob`.
    """
    _, _, declarations = FIXTURE_PATH.read_text(encoding="utf-8").partition("KRM1_FIXTURE_BASE64")
    parts = re.findall(r'"([A-Za-z0-9+/=]*)"', declarations)
    assert parts, "krm1-fixture.ts declares no base64 string"
    return base64.b64decode("".join(parts))


def test_the_mesh_the_client_decodes_is_the_mesh_this_engine_packed():
    # The one assertion that makes the browser suite a cross-language check instead of a self-test.
    assert shipped() == packed()


def test_the_shipped_blob_states_the_counts_the_fixture_was_written_with():
    blob = shipped()
    magic, words = blob[:4], struct.unpack_from("<7I", blob, 4)
    assert magic == KRM1_MAGIC
    assert words == FIXTURE_COUNTS


def test_the_fixture_still_names_the_parameters_it_was_packed_from():
    comment = FIXTURE_PATH.read_text(encoding="utf-8").partition("KRM1_FIXTURE_BASE64")[0]
    for line in PROVENANCE:
        assert line in comment, f"the provenance comment no longer says: {line}"
