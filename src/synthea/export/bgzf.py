"""Minimal BGZF writer (GO-61 REQ-05).

BGZF is gzip with a ``BC`` extra subfield carrying the block size, blocks of
at most 64 KiB, and a fixed 28-byte empty EOF block. This is ~60 lines over
``zlib`` and avoids depending on pysam. No ``.tbi`` index is written here; the
reference pack's indexes are produced by ``tabix`` in CI.

Output is deterministic: mtime is zero and the OS byte is 0xff, as htslib does.
"""

import struct
import zlib
from typing import BinaryIO

#: Largest uncompressed payload per block (htslib uses 0xff00).
MAX_BLOCK_INPUT = 65280

#: The canonical empty block that marks end of file.
BGZF_EOF = bytes.fromhex(
    "1f8b08040000000000ff0600424302001b0003000000000000000000")


def _block(data: bytes, level: int) -> bytes:
    comp = zlib.compressobj(level, zlib.DEFLATED, -15)
    body = comp.compress(data) + comp.flush()
    total = 18 + len(body) + 8
    if total > 65536:  # incompressible data can expand; store instead
        comp = zlib.compressobj(0, zlib.DEFLATED, -15)
        body = comp.compress(data) + comp.flush()
        total = 18 + len(body) + 8
    header = (b"\x1f\x8b\x08\x04" + b"\x00\x00\x00\x00" + b"\x00\xff"
              + struct.pack("<H", 6) + b"BC" + struct.pack("<HH", 2, total - 1))
    return header + body + struct.pack("<II", zlib.crc32(data) & 0xFFFFFFFF, len(data))


class BGZFWriter:
    """Write bytes as a BGZF stream to ``fileobj``."""

    def __init__(self, fileobj: BinaryIO, level: int = 6) -> None:
        self._f = fileobj
        self._level = level
        self._buf = bytearray()
        self._closed = False

    def write(self, data: bytes) -> None:
        if self._closed:
            raise ValueError("write to closed BGZFWriter")
        self._buf += data
        while len(self._buf) >= MAX_BLOCK_INPUT:
            self._f.write(_block(bytes(self._buf[:MAX_BLOCK_INPUT]), self._level))
            del self._buf[:MAX_BLOCK_INPUT]

    def close(self) -> None:
        if self._closed:
            return
        if self._buf:
            self._f.write(_block(bytes(self._buf), self._level))
            self._buf.clear()
        self._f.write(BGZF_EOF)
        self._closed = True
