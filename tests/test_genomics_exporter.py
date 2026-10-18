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
