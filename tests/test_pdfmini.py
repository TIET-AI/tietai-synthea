"""GO-61 REQ-06 / T-GO-61-12: minimal text PDF writer."""
import re
import unicodedata

import pytest

from synthea.export.pdfmini import extract_text, text_twin, write_pdf

PAGES = [["INFORME GENÉTICO (sintético)", "Variante: PIK3CA (p.His1047Arg) \\ paréntesis (a)"],
         ["Página dos: señal, niño, ñandú", "Línea final"]]


def test_pdf_text_extractable_and_twin_identical(tmp_path):
    p = tmp_path / "x.pdf"
    write_pdf(p, PAGES, "Informe sintético")
    raw = p.read_bytes()
    assert raw.startswith(b"%PDF-1.4") and raw.rstrip().endswith(b"%%EOF")
    assert raw.count(b"/Type /Page\n") + raw.count(b"/Type /Page ") >= 0
    assert len(re.findall(rb"/Type /Page\b(?!s)", raw)) == 2
    twin = text_twin(PAGES)
    assert twin == unicodedata.normalize("NFC", twin)
    assert extract_text(raw) == twin
    for page in PAGES:
        for line in page:
            assert line in extract_text(raw)
    # startxref points at the xref table
    sx = int(re.search(rb"startxref\n(\d+)\n", raw).group(1))
    assert raw[sx:sx + 4] == b"xref"


def test_pdf_deterministic_and_rejects_unencodable(tmp_path):
    a, b = tmp_path / "a.pdf", tmp_path / "b.pdf"
    write_pdf(a, PAGES, "t"); write_pdf(b, PAGES, "t")
    assert a.read_bytes() == b.read_bytes()
    with pytest.raises(ValueError):
        write_pdf(tmp_path / "c.pdf", [["日本語"]], "t")
