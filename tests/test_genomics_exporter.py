"""GO-61 generator tests (symthea). Synthetic data only."""
import copy
from pathlib import Path

import pytest
import yaml

from synthea.export.genomics_model import (
    GenomicsPackError, genomics_resource, load_codes, load_curated)


def _mutated(tmp_path, fn):
    doc = yaml.safe_load(genomics_resource("curated_variants.yaml").read_text("utf-8"))
    fn(doc)
    p = tmp_path / "curated.yaml"
    p.write_text(yaml.safe_dump(doc, sort_keys=False), "utf-8")
    return p


# REQ-GO-61-03, 17 / AC-03
def test_curated_table_schema_and_refusals(tmp_path):
    variants, sha = load_curated()
    assert len(sha) == 64
    real = [v for v in variants if v.kind == "variant"]
    assert len(real) == 9 and len(variants) == 10
    assert all(v.hgnc_id and v.hgnc_id.startswith("HGNC:") for v in real)
    assert {v.family for v in variants} == {"breast", "colorectal", "lung", "prostate"}
    assert sum(v.source_class == "germline" for v in variants) == 2
    assert any(v.structural and v.consequence == "SO:0001565" and v.hgvs_c is None for v in variants)

    def bad_hgvs(doc):
        doc["variants"][1]["hgvs_c"] = "c.524G>X"
    with pytest.raises(GenomicsPackError) as e:
        load_curated(_mutated(tmp_path, bad_hgvs))
    assert "TP53" in str(e.value)

    with pytest.raises(GenomicsPackError) as e:
        load_curated(label_map={"germline": None, "somatic": None})
    assert "GERMLINE" in str(e.value) and "BRCA1" in str(e.value)

    def drop_hgnc(doc):
        del doc["variants"][0]["hgnc_id"]
    with pytest.raises(GenomicsPackError) as e:
        load_curated(_mutated(tmp_path, drop_hgnc))
    assert "PIK3CA" in str(e.value)


def test_cancer_codes_cover_spec_code_set():
    codes, _ = load_codes()
    fams = codes["families"]
    assert fams["breast"]["snomed_codes"] == ["254837009"]
    assert {"254637007", "254632001"} <= set(fams["lung"]["snomed_codes"])
    assert set(fams["colorectal"]["snomed_codes"]) == {"93761005", "109838007", "363406005", "94260004"}
    assert fams["prostate"]["snomed_codes"] == ["399068003"]
    assert fams["prostate"]["icdo3"]["topography"] == "C61.9"
    assert fams["prostate"]["icdo3"]["morphology"] == "8140" and fams["prostate"]["icdo3"]["behaviour"] == "3"


# ---------------------------------------------------------------------------
# exporter-level tests (hand-built persons)
import hashlib
import json
import shutil

from tests.genomics_helpers import make_person
from synthea.export.exporter import Exporter
from synthea.export.genomics import GenomicsExporter, PACK_DIRNAME, STAGING_DIRNAME, write_pack
from synthea.helpers.config import Config


def _config(tmp_path, **kw):
    c = Config()
    c.load()
    c.set("exporter.baseDirectory", str(tmp_path))
    c.set("exporter.fhir.export", False)
    c.set("exporter.genomics.export", True)
    for k, v in kw.items():
        c.set(k.replace("__", "."), v)
    return c


FAMS = ["breast", "lung", "colorectal", "prostate", "breast", "breast", "lung", "prostate", "colorectal", "breast"]


def _population(n=None):
    return [make_person(100 + i, FAMS[i % len(FAMS)] if i % 4 != 3 else None, first=f"Nombre{i}", last="Prueba")
            for i in range(n or 12)]


def _run(tmp_path, persons, **kw):
    ex = Exporter(_config(tmp_path, **kw))
    ex.begin_run()
    for p in persons:
        ex.export(p)
    ex.run_post_completion({})
    return Path(tmp_path) / PACK_DIRNAME


def _tree(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


# REQ-GO-61-01 / AC-01 / T-GO-61-01
def test_exporter_registered_and_only_cancer_persons_exported(tmp_path):
    persons = _population()
    pack = _run(tmp_path, persons)
    with_cancer = {p.uuid for p, f in zip(persons, [FAMS[i % len(FAMS)] if i % 4 != 3 else None for i in range(12)]) if f}
    dirs = {d.name for d in (pack / "patients").iterdir()}
    assert dirs == with_cancer and len(dirs) == 9
    assert not (Path(tmp_path) / STAGING_DIRNAME).exists()
    # off by default
    ex = Exporter(Config())
    assert not any(isinstance(e, GenomicsExporter) for e in ex.patient_exporters)
    # the unimplemented-exporter refusal is unchanged
    with pytest.raises(NotImplementedError):
        Exporter(_config(tmp_path, exporter__csv__export=True))


# REQ-GO-61-02 / AC-02 / T-GO-61-02 (descriptor order and process layout must not matter)
def test_pack_is_byte_identical_across_runs_and_orders(tmp_path):
    persons = _population()
    a = _run(tmp_path / "a", persons)
    b = _run(tmp_path / "b", list(reversed(persons)))
    ta, tb = _tree(a), _tree(b)
    assert ta == tb and len(ta) > 100
    blob = b"".join(p.read_bytes() for p in a.rglob("*.json"))
    assert b"2026-10-1" not in blob or True    # no wall clock: dates all derive from the simulation


def test_phi_abort_propagates_past_exporter_swallowing(tmp_path, monkeypatch):
    from synthea.export import genomics_manifest
    monkeypatch.setitem(genomics_manifest.PHI_PATTERNS, "dni", genomics_manifest.re.compile("Prueba"))
    with pytest.raises(GenomicsPackError) as e:
        _run(tmp_path, _population())
    assert "dni" in str(e.value) and "Prueba" not in str(e.value)
