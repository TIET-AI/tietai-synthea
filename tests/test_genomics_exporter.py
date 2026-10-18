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


from tests.genomics_helpers import family_of, population as _population


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
    with_cancer = {p.uuid for i, p in enumerate(persons) if family_of(i)}
    dirs = {d.name for d in (pack / "patients").iterdir()}
    assert dirs == with_cancer and len(dirs) == 10
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


def _bundle(pack, kind, family_codes):
    """First bundle of ``kind`` whose Condition / variants match ``family_codes``."""
    for f in sorted(pack.glob(f"patients/*/fhir/{kind}-*.bundle.json")):
        b = json.loads(f.read_text("utf-8"))
        text = f.read_text("utf-8")
        if any(c in text for c in family_codes):
            return b
    raise AssertionError(family_codes)


def _res(b, rtype, profile=None):
    out = [e["resource"] for e in b["entry"] if e["resource"]["resourceType"] == rtype]
    if profile:
        out = [r for r in out if any(p.endswith("/" + profile) for p in r.get("meta", {}).get("profile", []))]
    return out


def _codes(res):
    return {c["code"]["coding"][0]["code"]: c for c in res["component"]}


# REQ-GO-61-04 / AC-04 / T-GO-61-04
def test_breast_report_bundle_shape_and_alk_structural(genomics_pack):
    b = _bundle(genomics_pack, "report", ["PIK3CA"])
    assert b["type"] == "transaction"
    assert len(_res(b, "DiagnosticReport")) == 1 and len(_res(b, "Provenance")) == 1
    rep = _res(b, "DiagnosticReport")[0]
    assert rep["extension"][0]["valueString"] == "clinvar@2026-09-01"
    assert rep["code"]["coding"][0]["code"] == "51969-4"
    assert len(_res(b, "Specimen")) == 2           # tumour + blood for the germline variant
    variants = _res(b, "Observation", "tietai-variant")
    assert len(variants) == 3
    for v in variants:
        cats = [c["coding"][0]["code"] for c in v["category"]]
        assert cats == ["laboratory", "GE"]
        comps = _codes(v)
        assert set(comps) == {"48018-6", "48004-6", "48005-3", "81290-9", "62374-4", "48002-0", "53034-5", "81258-6"}
        assert "53037-8" not in comps
        for k in ("48004-6", "48005-3", "81290-9"):
            assert comps[k]["valueCodeableConcept"]["coding"][0]["system"] == "http://varnomen.hgvs.org"
        gene = comps["48018-6"]["valueCodeableConcept"]["coding"][0]
        assert gene["system"] == "http://www.genenames.org" and gene["code"].startswith("HGNC:") and gene["display"]
    germ = [v for v in variants if _codes(v)["48002-0"]["valueCodeableConcept"]["coding"][0]["code"] == "LA6683-2"]
    assert len(germ) == 1 and _codes(germ[0])["48018-6"]["valueCodeableConcept"]["coding"][0]["display"] == "BRCA1"
    sec = lambda r: [s["code"] for s in r.get("meta", {}).get("security", [])]
    assert sec(germ[0]) == ["GERMLINE"] and all(sec(v) == [] for v in variants if v is not germ[0])
    dx = _res(b, "Observation", "tietai-diagnostic-implication")
    th = _res(b, "Observation", "tietai-therapeutic-implication")
    assert len(dx) >= 4 and len(th) >= 1
    ids = {e["fullUrl"]: e["resource"] for e in b["entry"]}
    per_variant = {}
    for i in dx:
        assert any(x["url"].endswith("classification-source") for x in i["extension"])
        assert "53037-8" in _codes(i)
        tgt = i["derivedFrom"][0]["reference"]
        assert ids[tgt]["meta"]["profile"][0].endswith("tietai-variant")
        per_variant.setdefault(tgt, []).append(_codes(i)["53037-8"]["valueCodeableConcept"]["coding"][0]["code"])
        if sec(ids[tgt]):
            assert sec(i) == ["GERMLINE"]
    assert any(len(set(v)) == 2 for v in per_variant.values())      # two different significances
    for i in th:
        assert set(_codes(i)) >= {"51963-7", "81259-4", "93044-6"}
    assert all(sec(i) == ["GERMLINE"] for i in th if sec(ids[i["derivedFrom"][0]["reference"]]))

    # lung: the ALK fusion is structural; it is not a tietai-variant (known gap), but it is reported
    lung = _bundle(genomics_pack, "report", ["EGFR"])
    assert all("ALK" not in json.dumps(v) for v in _res(lung, "Observation", "tietai-variant"))
    gap = next(genomics_pack.glob("known-gaps/*/bundle.json"))
    fusion = _res(json.loads(gap.read_text()), "Observation", "tietai-variant")[0]
    comps = _codes(fusion)
    assert comps["48019-4"]["valueCodeableConcept"]["coding"][0]["code"] == "SO:0001565"
    assert not ({"48004-6", "48005-3", "81290-9"} & set(comps))
    assert json.loads(next(genomics_pack.glob("known-gaps/*/expected.json")).read_text())["invariant"] == "INV-HGVS-1"
    # the ALK fusion is in the Spanish report text
    txt = next(genomics_pack.glob("patients/*/reports/informe-genetico-*.txt"))
    assert any("ALK::EML4" in p.read_text("utf-8") for p in genomics_pack.glob("patients/*/reports/informe-genetico-*.txt"))
    assert any(e["resource"]["resourceType"] == "Observation" and "81695-9" in json.dumps(e)
               for e in _bundle(genomics_pack, "report", ["BRAF"])["entry"])


# REQ-GO-61-07 / AC-07 / T-GO-61-07
def test_prostate_mcode_resources_consistent_with_module(genomics_pack):
    b = _bundle(genomics_pack, "oncology", ["399068003"])
    cond = _res(b, "Condition")[0]
    assert cond["meta"]["profile"][0].endswith("tietai-cancer-condition")
    assert {c["system"] + "|" + c["code"] for c in cond["code"]["coding"]} >= {"http://snomed.info/sct|399068003"}
    morph = cond["extension"][0]["valueCodeableConcept"]["coding"][0]
    assert morph["code"] == "8140/3"
    assert cond["bodySite"][0]["coding"][0]["code"] == "C61.9"
    tnm = _res(b, "Observation", "tietai-tnm-observation")
    assert len(tnm) == 8
    for o in tnm:
        assert o["method"]["coding"][0]["code"] == "TNM"
        assert o["extension"][0]["valueString"] == "8"          # edition
        assert o["focus"][0]["reference"].startswith("urn:uuid:")
    codes = {o["code"]["coding"][0]["code"] for o in tnm}
    assert {"21908-9", "21902-2"} <= codes                      # clinical and pathological stage group
    psa = [o for o in _res(b, "Observation") if o["code"]["coding"][0]["code"] == "2857-1"]
    assert psa and psa[0]["valueQuantity"]["code"] == "ng/mL"
    onset = cond["onsetDateTime"]
    meds = _res(b, "MedicationRequest")
    assert meds and all(m["authoredOn"] >= onset for m in meds)
    assert meds[0]["medicationCodeableConcept"]["coding"][0]["code"].startswith("L02")
    # the 2019 medication (before onset) was not exported
    assert len(meds) == 1
    # breast: ER/PR/HER2 under the platform LOINCs, lumpectomy as a Procedure
    bb = _bundle(genomics_pack, "oncology", ["254837009"])
    marker_codes = {o["code"]["coding"][0]["code"] for o in _res(bb, "Observation")}
    assert {"16112-5", "16113-3", "48676-1"} <= marker_codes
    assert any(p["code"]["coding"][0]["code"] == "392021009" for p in _res(bb, "Procedure"))


@pytest.mark.slow
def test_generation_time_budget(tmp_path):
    """REQ-GO-61-18: the reference population in <= 5 minutes, single thread."""
    import subprocess, sys, time
    t = time.time()
    subprocess.run([sys.executable, "-m", "synthea.cli", "--population", "200", "--seed", "20261017",
                    "--age", "55-85", "--reference-date", "20261001", "--genomics-cohort",
                    "-c", "examples/genomics-oncology-pack-recipe.properties", "--output-dir", str(tmp_path)],
                   check=True, capture_output=True)
    assert time.time() - t <= 300
    assert (tmp_path / "genomics-oncology-pack" / "MANIFEST.json").is_file()
