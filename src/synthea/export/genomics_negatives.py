"""The 16 negative fixtures of the genomics pack (GO-61 REQ-08).

Each negative is derived from a valid bundle by one targeted mutation, so it
differs from the valid bundle in exactly the violating element (plus, for the
two cross-patient cases, the support entry the mutation points at). The
``expected.json`` sidecar uses the fhir-service fixture format
``{fhirVersion, note, expected:[{code, detailCode, severity}], seed}`` and adds
``invariant``, ``variant`` and ``layer`` so the list can be audited against the
spec. ``expected`` records what the platform validator answers in enforce mode
(verified against the real engine and the real variant checker; the fhir-service
fixture test re-verifies it).

``layer``:
  fhir-validate   $validate returns the listed error issues
  write-labelling the profile validator accepts it; GO-05 adds the GERMLINE
                  label at write time (no validator rule exists for a missing label)
  hydra-tool      accepted by $validate; Hydra ``validate_tnm`` flags it
                  (STAGE_WITHOUT_CATEGORIES, needs_review)
"""
import copy
import json
from typing import Any, Callable, Dict, List, Tuple

from synthea.export.genomics_fhir import (
    HGVS, LOINC, OBS_CAT, SD, SECURITY, V2_0074, cc, entry, uid)

Bundle = Dict[str, Any]


def _find(bundle: Bundle, rtype: str, pred: Callable[[Dict[str, Any]], bool] = lambda r: True) -> Dict[str, Any]:
    for e in bundle["entry"]:
        r = e["resource"]
        if r["resourceType"] == rtype and pred(r):
            return r
    raise KeyError(rtype)


def _is_profile(name: str) -> Callable[[Dict[str, Any]], bool]:
    return lambda r: (SD + name) in r.get("meta", {}).get("profile", [])


def _variant(bundle: Bundle, gene: str = None, germline: bool = None) -> Dict[str, Any]:
    def pred(r):
        if (SD + "tietai-variant") not in r.get("meta", {}).get("profile", []):
            return False
        comps = {c["code"]["coding"][0]["code"]: c for c in r["component"]}
        if gene and comps["48018-6"]["valueCodeableConcept"]["coding"][0]["display"] != gene:
            return False
        if germline is not None:
            is_g = comps["48002-0"]["valueCodeableConcept"]["coding"][0]["code"] == "LA6683-2"
            if is_g != germline:
                return False
        return True
    return _find(bundle, "Observation", pred)


def _comp(res: Dict[str, Any], code: str) -> Dict[str, Any]:
    return next(c for c in res["component"] if c["code"]["coding"][0]["code"] == code)


def _extra_patient(bundle: Bundle, tag: str) -> str:
    pid = uid("go61-neg-patient", tag)
    bundle["entry"].insert(2, entry("Patient", pid, {
        "identifier": [{"system": "urn:tietai:synthetic", "value": f"neg-{tag}"}],
        "name": [{"family": "Sintético", "given": ["Otro"]}], "gender": "unknown"}))
    return pid


# ---- mutations (report bundle) -------------------------------------------------

def m_no_build(b: Bundle) -> None:
    v = _variant(b, "PIK3CA")
    v["component"].remove(_comp(v, "62374-4"))


def m_hg19(b: Bundle) -> None:
    c = _comp(_variant(b, "PIK3CA"), "62374-4")
    c["valueCodeableConcept"] = {"text": "hg19"}


def m_source_class(b: Bundle) -> None:
    c = _comp(_variant(b, "PIK3CA"), "48002-0")
    c["valueCodeableConcept"] = cc(LOINC, "LA26807-0", "Likely germline")


def m_hgvs_invalid(b: Bundle) -> None:
    c = _comp(_variant(b, "TP53"), "48004-6")
    c["valueCodeableConcept"] = cc(HGVS, "NM_000546.6:c.524G>X", "NM_000546.6:c.524G>X")


def m_hgvs_text_only(b: Bundle) -> None:
    c = _comp(_variant(b, "PIK3CA"), "48004-6")
    c["valueCodeableConcept"] = {"text": "NM_006218.4:c.3140A>G"}


def m_no_ge(b: Bundle) -> None:
    v = _variant(b, "PIK3CA")
    v["category"] = [x for x in v["category"] if x["coding"][0]["code"] != "GE"]


def m_no_classification_source(b: Bundle) -> None:
    r = _find(b, "Observation", _is_profile("tietai-diagnostic-implication"))
    r["extension"] = [x for x in r["extension"] if not x["url"].endswith("classification-source")]
    if not r["extension"]:
        del r["extension"]


def m_significance_on_variant(b: Bundle) -> None:
    v = _variant(b, "PIK3CA")
    v["component"].append({"code": cc(LOINC, "53037-8", "Genetic variation clinical significance [Imp]"),
                           "valueCodeableConcept": cc(LOINC, "LA6668-3", "Pathogenic")})


def m_specimen_other_patient(b: Bundle) -> None:
    other = _extra_patient(b, "specimen")
    sid = uid("go61-neg-specimen", "other")
    # insert the foreign specimen before the variants
    idx = next(i for i, e in enumerate(b["entry"]) if e["resource"]["resourceType"] == "DocumentReference")
    b["entry"].insert(idx, entry("Specimen", sid, {
        "status": "available", "type": cc("http://snomed.info/sct", "119376003", "Tissue specimen"),
        "subject": {"reference": f"urn:uuid:{other}"}}))
    _variant(b, "PIK3CA")["specimen"] = {"reference": f"urn:uuid:{sid}"}


def m_no_knowledge(b: Bundle) -> None:
    r = _find(b, "DiagnosticReport")
    r["extension"] = [x for x in r.get("extension", []) if not x["url"].endswith("knowledge-release")]
    if not r["extension"]:
        del r["extension"]


def m_subject_mismatch(b: Bundle) -> None:
    other = _extra_patient(b, "subject")
    _variant(b, "TP53")["subject"] = {"reference": f"urn:uuid:{other}"}


def m_germline_unlabelled(b: Bundle) -> None:
    v = _variant(b, germline=True)
    v["meta"].pop("security", None)


def m_no_provenance(b: Bundle) -> None:
    b["entry"] = [e for e in b["entry"] if e["resource"]["resourceType"] != "Provenance"]


# ---- mutations (oncology bundle) -----------------------------------------------

def m_no_morphology(b: Bundle) -> None:
    c = _find(b, "Condition")
    c["extension"] = [x for x in c["extension"] if "histology-morphology" not in x["url"]]
    if not c["extension"]:
        del c["extension"]


def m_tnm_no_method(b: Bundle) -> None:
    o = _find(b, "Observation", _is_profile("tietai-tnm-observation"))
    del o["method"]


def m_stage_without_tnm(b: Bundle) -> None:
    keep = []
    for e in b["entry"]:
        r = e["resource"]
        if (SD + "tietai-tnm-observation") in r.get("meta", {}).get("profile", []):
            code = r["code"]["coding"][0]["code"]
            if code in ("21905-5", "21906-3", "21907-1", "21899-0", "21900-6", "21901-4"):
                continue
        keep.append(e)
    b["entry"] = keep


def _issue(code: str, detail: str) -> Dict[str, str]:
    return {"detailCode": detail, "code": code, "severity": "error"}


#: (slug, invariant, variant, base, mutation, layer, expected issues, note)
SPECS: List[Tuple[str, str, str, str, Callable[[Bundle], None], str, List[Dict[str, str]], str]] = [
    ("build-missing", "INV-BUILD-1", "no-build", "report", m_no_build, "fhir-validate",
     [_issue("invariant", "INV-BUILD-1"), _issue("required", "STRUCT_SLICE_REQUIRED")],
     "variant without the genome build component"),
    ("build-hg19", "INV-BUILD-1", "hg19", "report", m_hg19, "fhir-validate",
     [_issue("code-invalid", "BIND_REQUIRED"), _issue("invariant", "INV-BUILD-1")],
     "build given as the alias hg19 in text only"),
    ("source-class", "INV-SOURCE-CLASS-1", "outside-set", "report", m_source_class, "fhir-validate",
     [_issue("code-invalid", "BIND_REQUIRED"), _issue("invariant", "INV-SOURCE-CLASS-1")],
     "source class outside the platform set (likely germline)"),
    ("hgvs-invalid", "INV-HGVS-1", "invalid-base", "report", m_hgvs_invalid, "fhir-validate",
     [_issue("invariant", "INV-HGVS-1")], "NM_000546.6:c.524G>X is not an HGVS expression"),
    ("hgvs-text-only", "INV-HGVS-1", "text-only", "report", m_hgvs_text_only, "fhir-validate",
     [_issue("code-invalid", "BIND_REQUIRED"), _issue("invariant", "INV-HGVS-1")],
     "HGVS component with text only and no varnomen coding"),
    ("variant-no-ge-category", "GO-10-GE-CATEGORY", "missing-ge", "report", m_no_ge, "fhir-validate",
     [_issue("required", "STRUCT_REQUIRED"), _issue("required", "STRUCT_SLICE_REQUIRED")],
     "variant lacking the v2-0074 GE category"),
    ("classification-source", "INV-CLASSIFICATION-1", "no-source", "report", m_no_classification_source,
     "fhir-validate", [_issue("required", "INV-CLASSIFICATION-1")],
     "diagnostic implication with 53037-8 and no classification-source"),
    ("significance-on-variant", "GO-10-VARIANT-CLOSED-COMPONENTS", "53037-8-on-variant", "report",
     m_significance_on_variant, "fhir-validate", [_issue("structure", "STRUCT")],
     "clinical significance 53037-8 carried by the variant"),
    ("specimen-other-patient", "INV-SPECIMEN-1", "foreign-specimen", "report", m_specimen_other_patient,
     "fhir-validate", [_issue("invariant", "INV-SPECIMEN-1"), _issue("invariant", "INV-SUBJECT-1")],
     "variant specimen belongs to another patient"),
    ("knowledge-release", "INV-KNOWLEDGE-1", "neither", "report", m_no_knowledge, "fhir-validate",
     [_issue("invariant", "INV-KNOWLEDGE-1")], "report with no release and no unknown-knowledge reason"),
    ("icdo-no-morphology", "INV-ICDO-1", "no-morphology", "oncology", m_no_morphology, "fhir-validate",
     [_issue("required", "STRUCT_SLICE_REQUIRED"), _issue("invariant", "INV-ICDO-1")],
     "cancer condition without ICD-O-3 morphology"),
    ("staging-no-method", "INV-STAGING-METHOD-1", "no-method", "oncology", m_tnm_no_method, "fhir-validate",
     [_issue("required", "STRUCT_REQUIRED"), _issue("invariant", "INV-STAGING-METHOD-1")],
     "TNM observation without method"),
    ("subject-mismatch", "INV-SUBJECT-1", "variant-other-subject", "report", m_subject_mismatch, "fhir-validate",
     [_issue("invariant", "INV-SPECIMEN-1"), _issue("invariant", "INV-SUBJECT-1"),
      _issue("not-found", "SLICE_UNRESOLVED"), _issue("invariant", "INV-DERIVED-1"),
      _issue("invariant", "INV-RESULT-1")],
     "variant subject differs from the report subject"),
    ("germline-unlabelled", "GO-05-LABEL-ON-WRITE", "no-germline-label", "report", m_germline_unlabelled,
     "write-labelling", [], "germline variant carrying no GERMLINE security label; GO-05 labels on write"),
    ("report-no-provenance", "INV-PROVENANCE-1", "no-provenance", "report", m_no_provenance, "fhir-validate",
     [_issue("invariant", "INV-PROVENANCE-1")], "report without a Provenance"),
    ("stage-without-tnm", "STAGE_WITHOUT_CATEGORIES", "group-only", "oncology", m_stage_without_tnm,
     "hydra-tool", [], "stage group observations without T, N and M; flagged by Hydra validate_tnm (needs_review)"),
]


def build_negatives(report_bundle: Bundle, oncology_bundle: Bundle) -> List[Dict[str, Any]]:
    """Return ``[{dir, bundle, expected, base, mutation}]`` in spec order."""
    out = []
    for n, (slug, inv, var, base, fn, layer, issues, note) in enumerate(SPECS, 1):
        b = copy.deepcopy(report_bundle if base == "report" else oncology_bundle)
        fn(b)
        out.append({
            "dir": f"{n:02d}-{inv}-{slug}",
            "base": base,
            "bundle": b,
            "expected": {
                "fhirVersion": "R4", "note": note, "invariant": inv, "variant": var, "layer": layer,
                "expected": issues, "seed": [],
            },
        })
    return out


def diff_paths(a: Any, b: Any, path: str = "") -> List[str]:
    """Paths (within entries present in both) where ``a`` and ``b`` differ.

    Entries are matched by ``fullUrl``; an entry only in ``b`` is a support
    entry and does not count; an entry only in ``a`` counts as one removed path.
    """
    ea = {e["fullUrl"]: e for e in a["entry"]}
    eb = {e["fullUrl"]: e for e in b["entry"]}
    paths: List[str] = []
    for url in ea:
        if url not in eb:
            paths.append(f"entry[{url}] removed")
            continue
        paths += _diff(ea[url], eb[url], f"entry[{url}]")
    return paths


def _diff(a: Any, b: Any, path: str) -> List[str]:
    if isinstance(a, dict) and isinstance(b, dict):
        out: List[str] = []
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                out.append(f"{path}.{k}")
            elif k.startswith("value") and a[k] != b[k]:
                out.append(f"{path}.{k}")      # a value[x] element is one path
            else:
                out += _diff(a[k], b[k], f"{path}.{k}")
        return out
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return [path]
        out = []
        for i, (x, y) in enumerate(zip(a, b)):
            out += _diff(x, y, f"{path}[{i}]")
        return out
    return [] if a == b else [path]


def dumps(obj: Any) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
