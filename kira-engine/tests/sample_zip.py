"""A zip writer that can put on disk what `zipfile` refuses to write.

`kira.characters.extract_zip` is tested against the bytes the format actually allows, and three of
them are unreachable through `zipfile`'s own writer: a GBK entry name carrying no utf-8 flag, a header
that declares a size it does not have, and an entry marked a symlink. So the fixtures are assembled
from the record layouts — local header, central directory, end-of-central-directory — instead of
asked nicely.

A `name` given as `bytes` goes on disk verbatim, flag left alone. A `name` given as `str` is written as
utf-8 with the flag the format reserves for it set, like a well-behaved writer.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass

LOCAL_SIG = b"PK\x03\x04"
CENTRAL_SIG = b"PK\x01\x02"
EOCD_SIG = b"PK\x05\x06"

UTF8_FLAG = 0x800
STORED = 0
DEFLATED = 8

#: 2026-10-31 12:00:00, in the two 16-bit DOS fields every reader insists on.
DOS_TIME = 12 << 11
DOS_DATE = ((2026 - 1980) << 9) | (10 << 5) | 31

#: The high 16 bits of a central-directory `external_attr` hold a unix mode; this one is
#: `S_IFLNK | 0777`. `zipfile` will not write it, and an archive that carries it must not win.
SYMLINK_ATTR = (0o120000 | 0o777) << 16


def gbk(text: str) -> bytes:
    """The name as a Windows Chinese writer stores it: GBK bytes, no flag, no extra field."""
    return text.encode("gbk")


@dataclass
class Item:
    """One entry, with the two header sizes the writer is allowed to lie about."""

    name: str | bytes
    data: bytes = b""
    method: int = DEFLATED
    flags: int = 0
    declared_size: int | None = None
    declared_compress_size: int | None = None
    external_attr: int = 0


def _deflate(raw: bytes) -> bytes:
    """A raw deflate stream, which is what a zip entry body is (no zlib header)."""
    compressor = zlib.compressobj(9, zlib.DEFLATED, -15)
    return compressor.compress(raw) + compressor.flush()


def write_zip(items: list[Item]) -> bytes:
    """Assemble the archive: every local header, then the central directory, then the EOCD."""
    body_area = bytearray()
    central = bytearray()

    for item in items:
        raw_name = item.name.encode("utf-8") if isinstance(item.name, str) else bytes(item.name)
        flags = item.flags | (UTF8_FLAG if isinstance(item.name, str) else 0)
        body = _deflate(item.data) if item.method == DEFLATED else item.data
        crc = zlib.crc32(item.data) & 0xFFFFFFFF
        size = len(item.data) if item.declared_size is None else item.declared_size
        compress_size = len(body) if item.declared_compress_size is None else item.declared_compress_size
        offset = len(body_area)

        body_area += LOCAL_SIG + struct.pack(
            "<5H3I2H",
            20,
            flags,
            item.method,
            DOS_TIME,
            DOS_DATE,
            crc,
            compress_size,
            size,
            len(raw_name),
            0,
        )
        body_area += raw_name + body

        central += CENTRAL_SIG + struct.pack(
            "<6H", 20, 20, flags, item.method, DOS_TIME, DOS_DATE
        )
        central += struct.pack("<3I", crc, compress_size, size)
        # name length, extra length, comment length, start disk, internal attributes.
        central += struct.pack("<5H", len(raw_name), 0, 0, 0, 0)
        central += struct.pack("<II", item.external_attr, offset)
        central += raw_name

    cd_offset = len(body_area)
    cd_size = len(central)
    out = bytes(body_area) + bytes(central)
    return out + EOCD_SIG + struct.pack(
        "<4H2IH", 0, 0, len(items), len(items), cd_size, cd_offset, 0
    )


def zip_bytes(*items: Item) -> bytes:
    return write_zip(list(items))
