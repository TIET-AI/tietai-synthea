"""GO-61 REQ-09, 10, 17 / T-GO-61-09, 10."""
import hashlib
import json
from pathlib import Path

import pytest

from synthea.export.genomics_manifest import phi_scan
from synthea.export.genomics_model import GenomicsPackError
from tests.genomics_helpers import build_pack, population


def test_manifest_hashes_counts_and_reference_regeneration(genomics_pack, tmp_path):
    pack = genomics_pack
    m = json.loads((pack / "MANIFEST.json").read_text())
    assert m["schema"] == "tietai.genomics-pack/v1" and m["tbi_source"] == "ci" and m["seed"] == 20261017
    assert set(m["modules"]) == {"breast_cancer.json", "lung_cancer.json", "colorectal_cancer.json", "prostate_cancer.json"}
    files = [p for p in pack.rglob("*") if p.is_file() and p.name != "MANIFEST.json"]
    assert set(m["files"]) == {str(p.relative_to(pack)) for p in files}
    for rel, sha in m["files"].items():
        assert hashlib.sha256((pack / rel).read_bytes()).hexdigest() == sha
    c = m["counts"]
    assert c["cases"] == len(list(pack.glob("patients/*/fhir/report-*.bundle.json")))
    assert c["vcf"] == len(list(pack.glob("patients/*/vcf/*.vcf.gz")))
    assert c["pdf"] == len(list(pack.glob("patients/*/reports/*.pdf"))) == 2 * c["cases"]
    assert c["negatives"] == len(list(pack.glob("negatives/*/bundle.json"))) == 16
    # regeneration is identical
    again = build_pack(tmp_path)
    assert (again / "MANIFEST.json").read_bytes() == (pack / "MANIFEST.json").read_bytes()


def test_reference_guard_refuses_changed_curated_table(tmp_path):
    ref = tmp_path / "ref"
    ref.mkdir()
    (ref / "MANIFEST.json").write_text(json.dumps({"curated_variants_sha256": "0" * 64}))
    with pytest.raises(GenomicsPackError) as e:
        build_pack(tmp_path / "out", exporter__genomics__reference_dir=str(ref))
    assert "--regenerate-reference" in str(e.value)
    build_pack(tmp_path / "out2", exporter__genomics__reference_dir=str(ref),
               exporter__genomics__regenerate_reference=True)


def test_phi_scan_aborts_on_seeded_identifier_and_pack_is_clean(genomics_pack, tmp_path):
    assert phi_scan("Paciente con DNI 12345678Z y más") == ["dni"]
    assert phi_scan("X1234567L") == ["nie"]
    assert phi_scan("NHC 1234567") == ["nhc"]
    assert phi_scan("teléfono 612 345 678") == ["phone"]
    assert phi_scan("correo juan@example.org") == ["email"]
    assert phi_scan("28/12345678/90") == ["nass"]
    assert phi_scan("urn:uuid:6e100001-0000-4000-8000-123456789012 SNOMED 703423002 sha 0123456789012345678901234567890123456789012345678901234567890123") == []
    for f in genomics_pack.rglob("*"):
        if f.is_file() and f.suffix in (".json", ".txt", ".hl7", ".sha256"):
            assert phi_scan(f.read_text("utf-8")) == [], f
    # a seeded identifier in a person's name aborts the run, naming the pattern and not the match
    ps = population(5)
    ps[0].attributes["last_name"] = "12345678Z"
    with pytest.raises(GenomicsPackError) as e:
        build_pack(tmp_path / "bad", persons=ps)
    assert "dni" in str(e.value) and "12345678Z" not in str(e.value)
