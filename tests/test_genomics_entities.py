"""GO-61 REQ-06 / T-GO-61-06: reports, offsets, quotes and C5 closed sets."""
import hashlib
import unicodedata
from datetime import date

import pytest

from synthea.export.genomics_fhir import CaseContext
from synthea.export.genomics_model import CaseDescriptor, load_codes, load_curated
from synthea.export.genomics_reports import (
    entities_json, render_genetic_report, render_pathology_report, validate_c5)
from synthea.export.pdfmini import extract_text, text_twin, write_pdf

SNOMED = {"breast": "254837009", "lung": "254637007", "colorectal": "93761005", "prostate": "399068003"}


def _ctx(fam):
    codes, _ = load_codes()
    vs, _ = load_curated()
    d = CaseDescriptor(
        person_uuid="11111111-2222-4333-8444-5555666677aa", first_name="Íñigo", last_name="Núñez",
        gender="F" if fam == "breast" else "M", birth_date="1960-05-04", family=fam, snomed=SNOMED[fam],
        onset="2026-03-02", stage_obs=[],
        markers=([{"loinc": "16112-5", "display": "ER", "value": "positive"},
                  {"loinc": "16113-3", "display": "PR", "value": "negative"},
                  {"loinc": "48676-1", "display": "HER2", "value": "negative"}] if fam == "breast" else []))
    fv = [v for v in vs if v.family == fam]
    return CaseContext(desc=d, case_id="oc_0003", codes=codes, variants=fv,
                       vafs={v.label: v.vaf for v in fv if v.vaf}, onset=date(2026, 3, 2),
                       collected=date(2026, 3, 15), issued=date(2026, 4, 5))


@pytest.mark.parametrize("fam", ["breast", "lung", "colorectal", "prostate"])
def test_entity_offsets_quotes_and_c5_closed_sets(fam, tmp_path):
    ctx = _ctx(fam)
    for render, schema in ((render_genetic_report, "tietai.genomic-extraction/v1"),
                           (render_pathology_report, "tietai.synoptic-pathology/v1")):
        text, ents, _ = render(ctx)
        assert text == unicodedata.normalize("NFC", text)
        assert "Núñez" in text            # code points, not bytes
        doc = entities_json(schema, text, ents, "0" * 64)   # validates against C5
        assert doc["needs_review"] is True
        for e in doc["entities"]:
            assert text[e["char_start"]:e["char_end"]] == e["quote"]
            assert e["quote_sha256"] == hashlib.sha256(e["quote"].encode()).hexdigest()
            assert "needs_review" not in e
        pdf = tmp_path / "r.pdf"
        write_pdf(pdf, [text.splitlines()], "t")
        extracted = extract_text(pdf.read_bytes())
        assert extracted == text_twin([text.splitlines()])
        assert all(e["quote"] in extracted for e in doc["entities"])
        assert max(len(l) for l in text.splitlines()) <= 118


def test_genetic_entities_cover_kinds_and_links():
    text, ents, _ = render_genetic_report(_ctx("breast"))
    doc = entities_json("tietai.genomic-extraction/v1", text, ents, "0" * 64)
    kinds = [e["kind"] for e in doc["entities"]]
    for k in ("assay", "specimen", "variant", "implication", "knowledge_release", "recommendation"):
        assert k in kinds
    ids = {e["entity_id"] for e in doc["entities"]}
    for e in doc["entities"]:
        for link in e.get("linked_variant_ids", []):
            assert link in ids
            assert next(x for x in doc["entities"] if x["entity_id"] == link)["kind"] == "variant"
    assert sum(k == "variant" for k in kinds) == 3
    lung, _, _ = (None, None, None)
    t2, e2, _ = render_genetic_report(_ctx("colorectal"))
    assert any(e.kind == "msi" for e in e2)


def test_c5_rejects_value_outside_closed_set():
    text, ents, _ = render_genetic_report(_ctx("breast"))
    doc = entities_json("tietai.genomic-extraction/v1", text, ents, "0" * 64)
    doc["entities"][4]["source_class"] = "maybe"
    with pytest.raises(ValueError):
        validate_c5(doc)
