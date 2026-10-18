"""GO-61 REQ-05 / T-GO-61-11: the pure-Python BGZF writer."""

import gzip
import io
import struct
import zlib

from synthea.export.bgzf import BGZF_EOF, BGZFWriter, MAX_BLOCK_INPUT


def _blocks(raw: bytes):
    """Split a BGZF stream into (header_extra, bsize, isize) per block."""
    pos, out = 0, []
    while pos < len(raw):
        assert raw[pos:pos + 4] == b"\x1f\x8b\x08\x04", "gzip magic + FEXTRA"
        xlen = struct.unpack("<H", raw[pos + 10:pos + 12])[0]
        extra = raw[pos + 12:pos + 12 + xlen]
        assert extra[:2] == b"BC" and struct.unpack("<H", extra[2:4])[0] == 2
        bsize = struct.unpack("<H", extra[4:6])[0] + 1
        isize = struct.unpack("<I", raw[pos + bsize - 4:pos + bsize])[0]
        out.append((extra, bsize, isize))
        pos += bsize
    return out


def test_bgzf_blocks_extra_field_and_eof():
    payload = bytes((i * 7 + 3) % 251 for i in range(1_000_000))
    buf = io.BytesIO()
    w = BGZFWriter(buf)
    w.write(payload[:333_333])
    w.write(payload[333_333:])
    w.close()
    raw = buf.getvalue()

    assert gzip.decompress(raw) == payload
    assert zlib.decompress(raw[-28:], 31) == b""
    assert raw.endswith(BGZF_EOF) and len(BGZF_EOF) == 28

    blocks = _blocks(raw)
    data_blocks = blocks[:-1]
    assert all(isize <= MAX_BLOCK_INPUT == 65280 for _, _, isize in data_blocks)
    assert sum(isize for _, _, isize in blocks) == len(payload)
    assert blocks[-1][2] == 0
    assert all(bsize <= 65536 for _, bsize, _ in blocks)


def test_bgzf_is_deterministic():
    def run():
        b = io.BytesIO()
        w = BGZFWriter(b)
        w.write(b"##fileformat=VCFv4.3\n" * 5000)
        w.close()
        return b.getvalue()

    assert run() == run()


def test_bgzf_empty_stream_is_just_eof():
    b = io.BytesIO()
    BGZFWriter(b).close()
    assert b.getvalue() == BGZF_EOF
