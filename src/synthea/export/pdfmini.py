"""Minimal text-only PDF 1.4 writer (GO-61 REQ-06).

One font (Helvetica, WinAnsi, so Spanish accents work), uncompressed content
streams, no dates, no ids: output is byte-deterministic. Layout fidelity is not
a goal; text extraction fidelity is. Every PDF has a ``.txt`` twin produced by
:func:`text_twin`, which is the text entity offsets refer to.
"""
import re
import unicodedata
from pathlib import Path
from typing import List

_FONT_SIZE = 9
_LEADING = 12
_TOP = 800
_LEFT = 40
_LINES_PER_PAGE = 62


def _enc(line: str) -> bytes:
    line = unicodedata.normalize("NFC", line)
    try:
        raw = line.encode("cp1252")
    except UnicodeEncodeError as e:
        raise ValueError(f"character not encodable in WinAnsi: {e.object[e.start]!r}")
    out = bytearray()
    for b in raw:
        if b in b"\\()":
            out += b"\\" + bytes([b])
        elif 32 <= b < 127:
            out.append(b)
        else:
            out += b"\\%03o" % b
    return bytes(out)


def text_twin(pages: List[List[str]]) -> str:
    """The NFC text of all lines, one per line, ``\\n`` terminated."""
    return "".join(unicodedata.normalize("NFC", l) + "\n" for p in pages for l in p)


def write_pdf(path: Path, pages: List[List[str]], title: str) -> None:
    pages = [p for p in pages if p] or [[""]]
    objs: List[bytes] = []  # index i -> object i+1
    n = len(pages)
    # 1 catalog, 2 pages, 3 font, 4 info, then page/content pairs
    kids = " ".join(f"{5 + 2 * i} 0 R" for i in range(n))
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode())
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    objs.append(b"<< /Title (" + _enc(title) + b") /Producer (tietai-synthea genomics pack) >>")
    for i, lines in enumerate(pages):
        if len(lines) > _LINES_PER_PAGE:
            raise ValueError("too many lines for one page")
        content = bytearray(f"BT /F1 {_FONT_SIZE} Tf {_LEADING} TL {_LEFT} {_TOP} Td\n".encode())
        for l in lines:
            content += b"(" + _enc(l) + b") Tj T*\n"
        content += b"ET"
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
                    f"/Resources << /Font << /F1 3 0 R >> >> /Contents {6 + 2 * i} 0 R >>".encode())
        objs.append(b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n"
                    + bytes(content) + b"\nendstream")
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, o in enumerate(objs):
        offsets.append(len(out))
        out += f"{i + 1} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n".encode() + b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R /Info 4 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n").encode()
    Path(path).write_bytes(bytes(out))


def extract_text(raw: bytes) -> str:
    """Text of a PDF written by :func:`write_pdf` (test and self-check helper)."""
    lines = []
    for m in re.finditer(rb"\((?:\\.|[^\\)])*\) Tj", raw):
        s = m.group(0)[1:-len(b") Tj")]
        b = bytearray()
        i = 0
        while i < len(s):
            c = s[i]
            if c == 0x5C:
                if s[i + 1:i + 2].isdigit():
                    b.append(int(s[i + 1:i + 4], 8)); i += 4
                else:
                    b.append(s[i + 1]); i += 2
            else:
                b.append(c); i += 1
        lines.append(unicodedata.normalize("NFC", bytes(b).decode("cp1252")))
    return "".join(l + "\n" for l in lines)
