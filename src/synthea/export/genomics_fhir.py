"""FHIR builders of the genomics pack (GO-61 REQ-04, 07).

Builds, for one cancer case, the ``tietai-genomic-report`` transaction bundle
(GO-10 shape) and the mCODE oncology bundle (GO-21 shape). Everything is
synthetic and derived from the simulation clock and a seeded RNG; no wall-clock
value is written. Entries reference only earlier ``urn:uuid`` entries (the
platform's INV-BUNDLE-REF-1).
"""
import base64
import hashlib
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from synthea.export.fhir import _stable_uuid
from synthea.export.genomics_model import (
    GENOME_BUILD, KNOWLEDGE_RELEASE, Classification, CaseDescriptor, CuratedVariant)

SD = "https://tiet.ai/fhir/StructureDefinition/"
LOINC = "http://loinc.org"
SNOMED = "http://snomed.info/sct"
HGVS = "http://varnomen.hgvs.org"
HGNC = "http://www.genenames.org"
ATC = "http://www.whocc.no/atc"
RXNORM = "http://www.nlm.nih.gov/research/umls/rxnorm"
ICDO3 = "http://terminology.hl7.org/CodeSystem/icd-o-3"
CIE10ES = "https://tiet.ai/fhir/CodeSystem/cie10-es"
TIETAI_GEN = "https://tiet.ai/fhir/CodeSystem/tietai-genomics"
SECURITY = "https://tiet.ai/fhir/security"
TBD = "http://hl7.org/fhir/uv/genomics-reporting/CodeSystem/tbd-codes-cs"
OBS_CAT = "http://terminology.hl7.org/CodeSystem/observation-category"
V2_0074 = "http://terminology.hl7.org/CodeSystem/v2-0074"
SYNTH_ID = "urn:tietai:synthetic"
MORPH_EXT = "http://hl7.org/fhir/us/mcode/StructureDefinition/mcode-histology-morphology-behavior"
DRS_HOST = "synthetic.tiet.ai"

#: LOINC / platform codes of the classification value set.
_CLASS_CODING = {
    "pathogenic": (LOINC, "LA6668-3", "Pathogenic"),
    "likely-pathogenic": (LOINC, "LA26332-9", "Likely pathogenic"),
    "uncertain-significance": (LOINC, "LA26333-7", "Uncertain significance"),
}
_ALLELIC = {"heterozygous": ("LA6706-1", "Heterozygous"), "homozygous": ("LA6705-3", "Homozygous"),
            "hemizygous": ("LA6707-9", "Hemizygous")}


def uid(namespace: str, *parts: str) -> str:
    return _stable_uuid(namespace, ":".join(parts))


def cc(system: str, code: str, display: Optional[str] = None, text: Optional[str] = None) -> Dict[str, Any]:
    c: Dict[str, Any] = {"system": system, "code": code}
    if display:
        c["display"] = display
    out: Dict[str, Any] = {"coding": [c]}
    if text:
        out["text"] = text
    return out


def ref(u: str) -> Dict[str, str]:
    return {"reference": f"urn:uuid:{u}"}


def entry(rtype: str, rid: str, resource: Dict[str, Any], if_none_exist: Optional[str] = None) -> Dict[str, Any]:
    resource = dict(resource)
    resource["resourceType"] = rtype
    req: Dict[str, Any] = {"method": "POST", "url": rtype}
    if if_none_exist:
        req["ifNoneExist"] = if_none_exist
    return {"fullUrl": f"urn:uuid:{rid}", "resource": resource, "request": req}


def iso(d: date) -> str:
    return d.isoformat()


def classification_coding(c: Classification) -> Dict[str, Any]:
    if c.value in _CLASS_CODING:
        s, code, disp = _CLASS_CODING[c.value]
        return cc(s, code, disp)
    return cc(TIETAI_GEN, c.value, c.value.replace("-", " ").capitalize())


@dataclass
class CaseContext:
    desc: CaseDescriptor
    case_id: str
    codes: Dict[str, Any]
    variants: List[CuratedVariant]
    vafs: Dict[str, float]
    onset: date
    collected: date
    issued: date
    pdf_sha256: bytes = b""
    pdf_size: int = 0
    pdf_object: str = ""
    release: str = KNOWLEDGE_RELEASE
    lab_name: str = "Laboratorio de Genética Molecular (sintético)"

    @property
    def family(self) -> Dict[str, Any]:
        return self.codes["families"][self.desc.family]

    def i(self, role: str, *parts: str) -> str:
        return uid(f"go61-{role}", self.desc.person_uuid, self.case_id, *parts)


def patient_entry(ctx: CaseContext) -> Dict[str, Any]:
    d = ctx.desc
    ident = f"{SYNTH_ID}|{d.person_uuid}"
    res = {
        "identifier": [{"system": SYNTH_ID, "value": d.person_uuid}],
        "active": True,
        "name": [{"use": "official", "family": d.last_name, "given": [d.first_name]}],
        "gender": {"M": "male", "F": "female"}.get(d.gender, "unknown"),
        "birthDate": d.birth_date,
    }
    return entry("Patient", uid("go61-patient", d.person_uuid), res, f"identifier={ident}")


def _patient_id(ctx: CaseContext) -> str:
    return uid("go61-patient", ctx.desc.person_uuid)


def _knowledge_ext(release: str) -> Dict[str, str]:
    return {"url": SD + "knowledge-release", "valueString": release}


def _security(v: CuratedVariant) -> Optional[Dict[str, Any]]:
    if v.security_label:
        return {"security": [{"system": SECURITY, "code": v.security_label}]}
    return None


def _categories() -> List[Dict[str, Any]]:
    return [cc(OBS_CAT, "laboratory"), cc(V2_0074, "GE")]


def _component(code: str, value: Dict[str, Any], display: Optional[str] = None) -> Dict[str, Any]:
    key = "valueQuantity" if "value" in value else "valueCodeableConcept"
    return {"code": cc(LOINC, code, display), key: value}


def variant_observation(ctx: CaseContext, v: CuratedVariant, perf: str, spec: str, pat: str) -> Dict[str, Any]:
    comps = [
        _component("48018-6", cc(HGNC, v.hgnc_id, v.gene_symbol), "Gene studied [ID]"),
        _component("48004-6", cc(HGVS, v.hgvs_c, v.hgvs_c), "DNA change (c.HGVS)"),
        _component("48005-3", cc(HGVS, v.hgvs_p, v.hgvs_p), "Amino acid change (pHGVS)"),
        _component("81290-9", cc(HGVS, v.hgvs_g, v.hgvs_g), "Genomic DNA change (gHGVS)"),
        _component("62374-4", cc(LOINC, "LA26806-2", GENOME_BUILD), "Human reference sequence assembly version"),
        _component("48002-0", cc(LOINC, "LA6683-2" if v.source_class == "germline" else "LA6684-0",
                                 "Germline" if v.source_class == "germline" else "Somatic"),
                   "Genomic source class"),
    ]
    if v.zygosity in _ALLELIC:
        code, disp = _ALLELIC[v.zygosity]
        comps.append(_component("53034-5", cc(LOINC, code, disp), "Allelic state"))
    comps.append(_component("81258-6", {"value": ctx.vafs[v.label], "system": "http://unitsofmeasure.org", "code": "1"},
                            "Sample VAF"))
    res: Dict[str, Any] = {
        "meta": {"profile": [SD + "tietai-variant"]},
        "status": "final",
        "category": _categories(),
        "code": cc(LOINC, "69548-6", "Genetic variant assessment"),
        "subject": ref(pat),
        "effectiveDateTime": iso(ctx.collected),
        "performer": [ref(perf)],
        "specimen": ref(spec),
        "component": comps,
    }
    sec = _security(v)
    if sec:
        res["meta"].update(sec)
    return res


def _implication_base(profile: str, code: str, v: CuratedVariant, ctx: CaseContext, perf: str,
                      spec: str, pat: str, derived: str) -> Dict[str, Any]:
    res: Dict[str, Any] = {
        "meta": {"profile": [SD + profile]},
        "status": "final",
        "category": _categories(),
        "code": cc(TBD, code),
        "subject": ref(pat),
        "effectiveDateTime": iso(ctx.issued),
        "performer": [ref(perf)],
        "specimen": ref(spec),
        "derivedFrom": [ref(derived)],
    }
    sec = _security(v)
    if sec:
        res["meta"].update(sec)
    return res


def diagnostic_implication(ctx: CaseContext, v: CuratedVariant, c: Classification, perf: str,
                           spec: str, pat: str, derived: str) -> Dict[str, Any]:
    res = _implication_base("tietai-diagnostic-implication", "diagnostic-implication", v, ctx, perf, spec, pat, derived)
    fam = ctx.family
    res["component"] = [
        _component("53037-8", classification_coding(c), "Genetic variation clinical significance [Imp]"),
        _component("81259-4", cc(SNOMED, ctx.desc.snomed, fam["snomed_display"]), "Associated phenotype"),
    ]
    res["extension"] = [{"url": SD + "classification-source", "valueString": c.source},
                        _knowledge_ext(ctx.release)]
    return res


def therapeutic_implication(ctx: CaseContext, v: CuratedVariant, t, perf: str,
                            spec: str, pat: str, derived: str) -> Dict[str, Any]:
    res = _implication_base("tietai-therapeutic-implication", "therapeutic-implication", v, ctx, perf, spec, pat, derived)
    fam = ctx.family
    res["component"] = [
        _component("51963-7", {**cc(ATC, t.atc, t.display), "text": t.display}, "Medication assessed"),
        _component("81259-4", cc(SNOMED, ctx.desc.snomed, fam["snomed_display"]), "Associated phenotype"),
        _component("93044-6", {"text": t.evidence}, "Level of evidence"),
    ]
    res["extension"] = [_knowledge_ext(ctx.release)]
    return res


def msi_observation(ctx: CaseContext, v: CuratedVariant, perf: str, spec: str, pat: str) -> Dict[str, Any]:
    return {
        "status": "final",
        "category": _categories(),
        "code": cc(LOINC, "81695-9", "Microsatellite instability [Interpretation] in Cancer specimen"),
        "subject": ref(pat),
        "effectiveDateTime": iso(ctx.collected),
        "performer": [ref(perf)],
        "specimen": ref(spec),
        "valueCodeableConcept": {"text": v.msi},
    }


def pdf_object_id(sha: bytes) -> str:
    alphabet = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
    n = int.from_bytes(sha[:16], "big")
    chars = []
    for _ in range(26):
        chars.append(alphabet[n & 31])
        n >>= 5
    return "obj_" + "".join(reversed(chars))


def build_report_bundle(ctx: CaseContext, pdf_title: str) -> Dict[str, Any]:
    d = ctx.desc
    pat = _patient_id(ctx)
    org = ctx.i("lab")
    entries: List[Dict[str, Any]] = []
    entries.append(entry("Organization", org, {"name": ctx.lab_name}))
    entries.append(patient_entry(ctx))

    fam = ctx.family
    spec_t = ctx.i("specimen", "tumour")
    entries.append(entry("Specimen", spec_t, {
        "status": "available",
        "type": cc(SNOMED, "119376003", "Tissue specimen"),
        "subject": ref(pat),
        "receivedTime": iso(ctx.collected) + "T10:00:00Z",
        "collection": {"collectedDateTime": iso(ctx.collected),
                       "bodySite": cc(SNOMED, fam["specimen"]["snomed"], fam["specimen"]["display"])},
    }))
    spec_ids = [spec_t]
    has_germline = any(v.source_class == "germline" for v in ctx.variants)
    spec_b = None
    if has_germline:
        spec_b = ctx.i("specimen", "blood")
        entries.append(entry("Specimen", spec_b, {
            "status": "available",
            "type": cc(SNOMED, "119297000", "Blood specimen"),
            "subject": ref(pat),
            "collection": {"collectedDateTime": iso(ctx.collected)},
        }))
        spec_ids.append(spec_b)

    doc = ctx.i("document")
    entries.append(entry("DocumentReference", doc, {
        "meta": {"profile": [SD + "tietai-genomic-document"]},
        "status": "current",
        "type": cc(LOINC, "51969-4", "Genetic analysis report"),
        "category": [cc(TIETAI_GEN, "genomic")],
        "subject": ref(pat),
        "date": iso(ctx.issued) + "T08:00:00Z",
        "content": [{"attachment": {
            "contentType": "application/pdf",
            "url": f"drs://{DRS_HOST}/{ctx.pdf_object}",
            "hash": base64.b64encode(ctx.pdf_sha256).decode(),
            "size": ctx.pdf_size,
            "title": pdf_title}}],
    }))

    results: List[str] = []
    var_ids: Dict[str, str] = {}
    for v in ctx.variants:
        if v.kind == "msi":
            mid = ctx.i("msi", v.label)
            entries.append(entry("Observation", mid, msi_observation(ctx, v, org, spec_t, pat)))
            results.append(mid)
            continue
        if v.structural:
            continue  # known gap: no tietai-variant form without HGVS (see known-gaps/)
        spec = spec_b if (v.source_class == "germline" and spec_b) else spec_t
        vid = ctx.i("variant", v.label)
        var_ids[v.label] = vid
        entries.append(entry("Observation", vid, variant_observation(ctx, v, org, spec, pat)))
        results.append(vid)
    for v in ctx.variants:
        if v.label not in var_ids:
            continue
        spec = spec_b if (v.source_class == "germline" and spec_b) else spec_t
        for n, c in enumerate([x for x in (v.classification, v.second_classification) if x]):
            iid = ctx.i("dx", v.label, str(n))
            entries.append(entry("Observation", iid, diagnostic_implication(
                ctx, v, c, org, spec, pat, var_ids[v.label])))
            results.append(iid)
        for n, t in enumerate(v.therapies):
            tid = ctx.i("rx", v.label, str(n))
            entries.append(entry("Observation", tid, therapeutic_implication(
                ctx, v, t, org, spec, pat, var_ids[v.label])))
            results.append(tid)

    rep = ctx.i("report")
    entries.append(entry("DiagnosticReport", rep, {
        "meta": {"profile": [SD + "tietai-genomic-report"]},
        "identifier": [{"system": "urn:tietai:synthetic:report", "value": f"{ctx.case_id}-{d.person_uuid[:8]}"}],
        "status": "final",
        "category": [cc(V2_0074, "GE")],
        "code": cc(LOINC, "51969-4", "Genetic analysis report"),
        "subject": ref(pat),
        "issued": iso(ctx.issued) + "T08:00:00Z",
        "performer": [ref(org)],
        "specimen": [ref(s) for s in spec_ids],
        "result": [ref(r) for r in results],
        "extension": [_knowledge_ext(ctx.release)],
    }))
    entries.append(entry("Provenance", ctx.i("provenance"), {
        "target": [ref(rep)],
        "recorded": iso(ctx.issued) + "T09:00:00Z",
        "agent": [{"who": ref(org)},
                  {"who": {"display": "tietai-synthea genomics pack generator (synthetic)"}}],
        "entity": [{"role": "source", "what": ref(doc)}],
    }))
    return {"resourceType": "Bundle", "type": "transaction", "entry": entries}


# --------------------------------------------------------------------------- mCODE

def _tnm_obs(ctx: CaseContext, cond: str, pat: str, kind: str, loinc: str, text: str, when: date) -> Dict[str, Any]:
    return {
        "meta": {"profile": [SD + "tietai-tnm-observation"]},
        "status": "final",
        "category": [cc(OBS_CAT, "laboratory")],
        "code": cc(LOINC, loinc),
        "subject": ref(pat),
        "focus": [ref(cond)],
        "effectiveDateTime": iso(when),
        "method": cc("https://tiet.ai/fhir/staging-system", "TNM"),
        "extension": [{"url": SD + "staging-edition", "valueString": ctx.codes["staging"]["edition"]}],
        "valueCodeableConcept": {"text": text},
    }


def tnm_values(ctx: CaseContext) -> Dict[str, Dict[str, str]]:
    """Clinical and pathological T/N/M/group as asserted for the case."""
    obs = {o["loinc"]: o["text"] for o in ctx.desc.stage_obs}
    group = obs.get("21908-9")
    t, n, m = obs.get("21905-5"), obs.get("21906-3"), obs.get("21907-1")
    if not (t and n and m and group):
        group = group or obs.get("stage") or "I"
        base = ctx.codes["tnm_by_stage_numeral"][group.rstrip("ABC")]
        t, n, m = "c" + base["t"], "c" + base["n"], "c" + base["m"]
    pt = "p" + t[1:] if t.startswith("c") else t
    pn = "p" + n[1:] if n.startswith("c") else n
    return {"clinical": {"t": t, "n": n, "m": m, "stage": group},
            "pathological": {"t": pt, "n": pn, "m": m, "stage": group}}


def condition_resource(ctx: CaseContext, pat: str) -> Dict[str, Any]:
    fam = ctx.family
    d = ctx.desc
    icdo = dict(fam["icdo3"])
    hist = fam.get("histology_by_snomed", {}).get(d.snomed)
    if hist:
        icdo.update(hist)
    return {
        "meta": {"profile": [SD + "tietai-cancer-condition"]},
        "clinicalStatus": cc("http://terminology.hl7.org/CodeSystem/condition-clinical", "active"),
        "verificationStatus": cc("http://terminology.hl7.org/CodeSystem/condition-ver-status", "confirmed"),
        "category": [cc("http://terminology.hl7.org/CodeSystem/condition-category", "problem-list-item")],
        "code": {"coding": [{"system": SNOMED, "code": d.snomed, "display": fam["snomed_display"]},
                            {"system": CIE10ES, "code": fam["cie10es"]}]},
        "bodySite": [cc(ICDO3, icdo["topography"])],
        "extension": [{"url": MORPH_EXT,
                       "valueCodeableConcept": cc(ICDO3, f"{icdo['morphology']}/{icdo['behaviour']}",
                                                  icdo.get("morphology_es"))}],
        "subject": ref(pat),
        "onsetDateTime": iso(ctx.onset),
    }


def marker_value(m: Dict[str, Any]) -> Dict[str, Any]:
    if "quantity" in m:
        q = m["quantity"]
        return {"valueQuantity": {"value": q["value"], "unit": q["unit"],
                                  "system": "http://unitsofmeasure.org", "code": q["ucum"]}}
    pos = m["value"] == "positive"
    return {"valueCodeableConcept": cc(SNOMED, "10828004" if pos else "260385009",
                                       "Positive (qualifier value)" if pos else "Negative (qualifier value)")}


def build_oncology_bundle(ctx: CaseContext) -> Dict[str, Any]:
    d = ctx.desc
    pat = _patient_id(ctx)
    entries = [patient_entry(ctx)]
    cond = ctx.i("condition")
    entries.append(entry("Condition", cond, condition_resource(ctx, pat)))
    vals = tnm_values(ctx)
    clin_date = ctx.onset + timedelta(days=7)
    path_date = ctx.collected + timedelta(days=3)
    clin_codes = [("T", "21905-5", "t"), ("N", "21906-3", "n"), ("M", "21907-1", "m"), ("stage", "21908-9", "stage")]
    path_codes = [("T", "21899-0", "t"), ("N", "21900-6", "n"), ("M", "21901-4", "m"), ("stage", "21902-2", "stage")]
    for label, codes, when in (("clinical", clin_codes, clin_date), ("pathological", path_codes, path_date)):
        for kind, loinc, key in codes:
            oid = ctx.i("tnm", label, kind)
            entries.append(entry("Observation", oid, _tnm_obs(ctx, cond, pat, kind, loinc, vals[label][key], when)))
    for mk in d.markers:
        res = {
            "status": "final",
            "category": [cc(OBS_CAT, "laboratory")],
            "code": cc(LOINC, mk["loinc"], mk.get("display")),
            "subject": ref(pat),
            "focus": [ref(cond)],
            "effectiveDateTime": iso(path_date),
        }
        res.update(marker_value(mk))
        entries.append(entry("Observation", ctx.i("marker", mk["loinc"]), res))
    atc_map = ctx.codes["rxnorm_to_atc"]
    for n, med in enumerate(d.meds):
        a = atc_map[med["rxnorm"]]
        entries.append(entry("MedicationRequest", ctx.i("med", str(n), med["rxnorm"]), {
            "status": "completed",
            "intent": "order",
            "medicationCodeableConcept": {"coding": [
                {"system": ATC, "code": a["atc"], "display": a["name"]},
                {"system": RXNORM, "code": med["rxnorm"], "display": med["display"]}]},
            "subject": ref(pat),
            "authoredOn": med["date"],
            "reasonReference": [ref(cond)],
        }))
    for n, pr in enumerate(d.procs):
        entries.append(entry("Procedure", ctx.i("proc", str(n), pr["snomed"]), {
            "status": "completed",
            "code": cc(SNOMED, pr["snomed"], pr["display"]),
            "subject": ref(pat),
            "performedDateTime": pr["date"],
            "reasonReference": [ref(cond)],
        }))
    return {"resourceType": "Bundle", "type": "transaction", "entry": entries}


def build_structural_gap_bundle(ctx: CaseContext, v: CuratedVariant) -> Dict[str, Any]:
    """The structural (fusion) form the GO-61 spec asks for: no HGVS component.

    The platform's INV-HGVS-1 rejects it today (a known gap, see known-gaps/).
    """
    pat = _patient_id(ctx)
    org = ctx.i("lab")
    spec = ctx.i("specimen", "tumour")
    fam = ctx.family
    comps = [
        _component("48018-6", cc(HGNC, v.hgnc_id, v.gene_symbol), "Gene studied [ID]"),
        {"code": cc(LOINC, "48019-4", "DNA change type"),
         "valueCodeableConcept": cc("http://www.sequenceontology.org", v.consequence, "gene_fusion")},
        _component("62374-4", cc(LOINC, "LA26806-2", GENOME_BUILD), "Human reference sequence assembly version"),
        _component("48002-0", cc(LOINC, "LA6684-0", "Somatic"), "Genomic source class"),
        _component("81258-6", {"value": ctx.vafs.get(v.label, v.vaf), "system": "http://unitsofmeasure.org",
                               "code": "1"}, "Sample VAF"),
    ]
    obs = {
        "meta": {"profile": [SD + "tietai-variant"]}, "status": "final", "category": _categories(),
        "code": cc(LOINC, "69548-6", "Genetic variant assessment"), "subject": ref(pat),
        "effectiveDateTime": iso(ctx.collected), "performer": [ref(org)], "specimen": ref(spec),
        "component": comps}
    return {"resourceType": "Bundle", "type": "transaction", "entry": [
        entry("Organization", org, {"name": ctx.lab_name}),
        patient_entry(ctx),
        entry("Specimen", spec, {"status": "available", "type": cc(SNOMED, "119376003", "Tissue specimen"),
                                 "subject": ref(pat),
                                 "collection": {"collectedDateTime": iso(ctx.collected),
                                                "bodySite": cc(SNOMED, fam["specimen"]["snomed"], fam["specimen"]["display"])}}),
        entry("Observation", ctx.i("variant", v.label), obs)]}
