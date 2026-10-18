"""GO-61 B2: size, T, N, stage group and dates of every generated case agree with TNM 8.

The rules below are written independently of ``genomics_staging.py`` (from the AJCC 8th edition
definitions) so the generator's tables are checked, not echoed. Synthetic data.
"""
import json
import re
from datetime import date
from pathlib import Path

import pytest

REFERENCE = Path(__file__).resolve().parents[1] / "examples" / "genomics-oncology-pack"


def size_ok(site, t, size):
    t = re.sub(r"^[cp]", "", t)
    if site == "breast":
        return {"T1": size <= 20, "T1c": 10 < size <= 20, "T2": 20 < size <= 50, "T3": size > 50}[t]
    if site == "lung":
        return {"T1b": 10 < size <= 20, "T1c": 20 < size <= 30, "T2a": 30 < size <= 40,
                "T2b": 40 < size <= 50, "T3": 50 < size <= 70}[t]
    if site == "prostate":
        return t in ("T2", "T3a") and 0 < size <= 60
    return size > 0


def nodes_ok(site, n, positive):
    n = re.sub(r"^[cp]", "", n)
    if n == "N0":
        return positive == 0
    if site == "breast":
        return {"N1a": 1 <= positive <= 3, "N2": 4 <= positive <= 9}[n]
    if site == "colorectal":
        return {"N1a": positive == 1, "N1b": 2 <= positive <= 3}[n]
    return positive >= 1


def group_ok(site, t, n, m, group, psa=None, gg=None):
    t, n, m = (re.sub(r"^[cp]", "", x) for x in (t, n, m))
    tb = re.match(r"T\d", t).group(0)
    nb = re.match(r"N\d", n).group(0)
    if site == "breast":
        if m == "M1":
            return group == "IV"
        want = {("T2", "N0"): "IIA", ("T2", "N1"): "IIB", ("T3", "N0"): "IIB", ("T3", "N1"): "IIIA",
                ("T1", "N0"): "IA", ("T1", "N1"): "IIA"}[(tb, nb)]
        return group == want
    if site == "lung":
        if m == "M1c":
            return group == "IVB"
        if nb == "N0":
            want = {"T1b": "IA", "T1c": "IA", "T2a": "IB", "T2b": "IIA", "T3": "IIB"}[t]
        elif nb == "N1":
            want = "IIB" if tb in ("T1", "T2") else "IIIA"
        else:
            want = "IIIA" if tb in ("T1", "T2") else "IIIB"
        return group == want
    if site == "colorectal":
        if m == "M1a":
            return group == "IVA"
        if nb == "N0":
            want = {"T1": "I", "T2": "I", "T3": "IIA", "T4a": "IIB", "T4b": "IIC"}[t]
        else:
            want = "IIIA" if tb in ("T1", "T2") else "IIIB"
        return group == want
    if site == "prostate":     # pathological prognostic group, 8th edition
        if nb != "N0" or m != "M0" or t not in ("T2", "T3a"):   # there is no pathological pT1
            return False
        if t == "T3a":
            return group == "IIIB" and gg in (1, 2, 3, 4)
        if psa >= 20:
            return group == "IIIA" and gg in (1, 2, 3, 4)
        if gg == 1:
            return group == ("I" if psa < 10 else "IIA")
        return group == {2: "IIB", 3: "IIC", 4: "IIC"}.get(gg)
    raise AssertionError(site)


SITE = {"254837009": "breast", "254637007": "lung", "254632001": "lung", "363406005": "colorectal",
        "93761005": "colorectal", "109838007": "colorectal", "94260004": "colorectal", "399068003": "prostate"}
GG = {"3+3=6": 1, "3+4=7": 2, "4+3=7": 3, "4+4=8": 4, "4+5=9": 5, "5+5=10": 5}


def _cases(pack):
    for rep in sorted(pack.glob("patients/*/reports/informe-ap-*.entities.json")):
        case = rep.name.split("informe-ap-")[1].split(".")[0]
        doc = json.loads(rep.read_text("utf-8"))
        onc = json.loads(next(rep.parent.parent.glob(f"fhir/oncology-{case}.bundle.json")).read_text("utf-8"))
        gen = json.loads(next(rep.parent.parent.glob(f"fhir/report-{case}.bundle.json")).read_text("utf-8"))
        yield case, doc, onc, gen


def _check(pack):
    n = 0
    for case, doc, onc, gen in _cases(pack):
        ents = {}
        for e in doc["entities"]:
            ents.setdefault(e["kind"], []).append(e)
        cond = next(e["resource"] for e in onc["entry"] if e["resource"]["resourceType"] == "Condition")
        site = SITE[next(c["code"] for c in cond["code"]["coding"] if c["system"].endswith("sct"))]
        p = ents["ptnm"][0]
        size = ents["size_mm"][0]["value"]
        positive = ents["nodes"][0]["positive"]
        psa = gg = None
        if site == "prostate":
            psa = next(e["value"]["value"] for e in ents["biomarker"] if e["code"] == "2857-1")
            gg = GG[ents["grade"][0]["value_text"].split()[-1]]
        ctx = (case, site, p["t"], p["n"], p["m"], p["stage_group"], size, positive, psa, gg)
        assert p["edition"] == "8" and p["t"].startswith("pT") and p["n"].startswith("pN"), ctx
        assert size_ok(site, p["t"], size), ctx
        assert nodes_ok(site, p["n"], positive), ctx
        assert group_ok(site, p["t"], p["n"], p["m"], p["stage_group"], psa, gg), ctx
        assert p["quote"].endswith(f"estadio {p['stage_group']}") and f"{p['t']} {p['n']} {p['m']}" in p["quote"]
        # the oncology bundle states the same pathological values, in the 8th edition and in its era
        tnm = [e["resource"] for e in onc["entry"] if e["resource"]["resourceType"] == "Observation"
               and any(pr.endswith("tietai-tnm-observation") for pr in e["resource"].get("meta", {}).get("profile", []))]
        path = {o["code"]["coding"][0]["code"]: o for o in tnm}
        assert path["21899-0"]["valueCodeableConcept"]["text"] == p["t"]
        assert path["21902-2"]["valueCodeableConcept"]["text"] == p["stage_group"]
        for o in tnm:
            assert o["extension"][0]["valueString"] == "8" and o["effectiveDateTime"] >= "2018-01-01", ctx
        if site == "prostate":
            v = next(o for o in onc["entry"] if o["resource"]["resourceType"] == "Observation"
                     and o["resource"]["code"]["coding"][0]["code"] == "2857-1")["resource"]
            assert v["valueQuantity"]["value"] == psa
        # the cited ClinVar release (2026-09-01) exists before the report is issued
        rep = next(e["resource"] for e in gen["entry"] if e["resource"]["resourceType"] == "DiagnosticReport")
        assert rep["issued"][:10] > "2026-09-01", ctx
        n += 1
    return n


def test_generated_cases_are_consistent_with_tnm8(genomics_pack):
    assert _check(genomics_pack) >= 8


@pytest.mark.skipif(not REFERENCE.is_dir(), reason="reference pack not present")
def test_reference_pack_cases_are_consistent_with_tnm8():
    assert _check(REFERENCE) >= 50


def test_staging_rules_reject_the_old_contradictions():
    assert not size_ok("lung", "T1c", 40)
    assert not size_ok("breast", "pT1", 29)
    assert not group_ok("breast", "pT2", "pN1a", "cM0", "IB")
    assert not group_ok("prostate", "pT1", "pN0", "cM0", "I", 6.0, 1)
