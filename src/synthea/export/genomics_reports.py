"""Spanish synthetic reports and their C5 expected-entity files (GO-61 REQ-06).

Reports are rendered from Jinja2 templates. Entity spans are recorded with
sentinel characters while rendering and converted to code-point offsets over
the final NFC text, so an offset can never refer to bytes or to pre-NFC text.
The expected-entity JSON conforms to the C5 schemas
``tietai.genomic-extraction/v1`` and ``tietai.synoptic-pathology/v1`` (copied
from the Hydra repository, see resources/genomics/c5).
"""
import hashlib
import json
import random
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

import jinja2
import jsonschema
from referencing import Registry, Resource

from synthea.export.genomics_fhir import CaseContext, tnm_values
from synthea.export.genomics_staging import EDITION
from synthea.export.genomics_model import CuratedVariant, genomics_resource

_S, _M, _E = "", "", ""   # sentinels (private use, never in text)
EXTRACTOR_VERSION = "go-61-gold/1"
GENOMIC_SCHEMA = "tietai.genomic-extraction/v1"
PATHOLOGY_SCHEMA = "tietai.synoptic-pathology/v1"


def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def sha256_text(s: str) -> str:
    return hashlib.sha256(nfc(s).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Entity:
    kind: str
    value: Dict[str, Any]
    char_start: int
    char_end: int
    quote: str
    assertion: str = "present"
    needs_review: bool = False   # root-level in C5; kept here for callers


class _Recorder:
    def __init__(self) -> None:
        self.pending: Dict[int, Tuple[str, Dict[str, Any], str, Optional[str], List[str]]] = {}

    def ent(self, kind: str, text: str, key: Optional[str] = None, fields: Optional[dict] = None,
            links: Optional[List[str]] = None, **kw) -> str:
        text = nfc(text)
        if any(c in text for c in (_S, _M, _E)):
            raise ValueError("sentinel in text")
        n = len(self.pending)
        f = dict(fields or {})
        f.update(kw)
        self.pending[n] = (kind, f, text, key, list(links or []))
        return f"{_S}{n}{_M}{text}{_E}"


@lru_cache(maxsize=None)
def _env() -> jinja2.Environment:
    return jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(genomics_resource("templates"))),
        autoescape=False, keep_trailing_newline=True, trim_blocks=True, lstrip_blocks=True,
        undefined=jinja2.StrictUndefined)


def render_with_entities(template: str, params: Dict[str, Any]) -> Tuple[str, List[Entity], List[Tuple[Optional[str], List[str]]]]:
    rec = _Recorder()
    raw = _env().get_template(template).render(ent=rec.ent, **params)
    out: List[str] = []
    spans: Dict[int, List[int]] = {}
    i, pos = 0, 0
    while i < len(raw):
        c = raw[i]
        if c == _S:
            j = raw.index(_M, i)
            idx = int(raw[i + 1:j])
            spans[idx] = [pos, pos]
            i = j + 1
        elif c == _E:
            i += 1
        else:
            out.append(c)
            pos += 1
            i += 1
    # second pass for spans (simple, quote lengths are known)
    text = "".join(out)
    ents: List[Entity] = []
    meta: List[Tuple[Optional[str], List[str]]] = []
    for idx in sorted(spans, key=lambda k: spans[k][0]):
        kind, fields, quote, key, links = rec.pending[idx]
        start = spans[idx][0]
        end = start + len(quote)
        if text[start:end] != quote:
            raise ValueError(f"offset error for {kind}: {quote!r}")
        ents.append(Entity(kind, fields, start, end, quote))
        meta.append((key, links))
    if text != nfc(text):
        raise ValueError("report text is not NFC")
    return text, ents, meta


# --------------------------------------------------------------------------- helpers

_SEX_ES = {"F": "mujer", "M": "varón"}
_ZYG_ES = {"heterozygous": "Heterocigosis", "homozygous": "Homocigosis", "hemizygous": "Hemicigosis"}
_CLASS_ES = {"pathogenic": "Patogénica", "likely-pathogenic": "Probablemente patogénica",
             "uncertain-significance": "Significado incierto", "likely-benign": "Probablemente benigna",
             "benign": "Benigna", "tier-i": "Tier I", "tier-ii": "Tier II", "tier-iii": "Tier III",
             "tier-iv": "Tier IV", "oncogenic": "Oncogénica", "likely-oncogenic": "Probablemente oncogénica"}
_DX_ES = {"breast": "carcinoma de mama", "lung": "carcinoma de pulmón", "colorectal": "adenocarcinoma de colon",
          "prostate": "adenocarcinoma de próstata"}


def vaf_text(v: float) -> str:
    return f"{v * 100:.1f}".replace(".", ",") + "%"


def _class_text(c) -> str:
    return f"{_CLASS_ES[c.value]} ({c.system})"


def _p_short(hgvs_p: str) -> str:
    return hgvs_p.split(":", 1)[1]


def case_number(case_id: str) -> int:
    return int(case_id.split("_")[1])


def specimen_identifier(case_id: str) -> str:
    return f"SYN-{case_number(case_id):04d}"


def _common(ctx: CaseContext) -> Dict[str, Any]:
    d = ctx.desc
    return {
        "name": nfc(f"{d.first_name} {d.last_name}"),
        "sex_es": _SEX_ES.get(d.gender, "no consta"),
        "dob": d.birth_date,
        "case_id": ctx.case_id,
        "dx_es": _DX_ES[d.family],
    }


# --------------------------------------------------------------------------- genetic report

def render_genetic_report(ctx: CaseContext) -> Tuple[str, List[Entity], Dict[str, Any]]:
    fam = ctx.family
    lab_title = "LABORATORIO DE GENÉTICA MOLECULAR (sintético)"
    sid = specimen_identifier(ctx.case_id)
    stype = "tejido tumoral FFPE"
    spec_line = f"Muestra: {fam['specimen']['type_es']}   ID de muestra {sid}"
    params: Dict[str, Any] = _common(ctx)
    params.update(
        lab_title=lab_title,
        panel_line=f"Panel NGS de tumor sólido {fam['panel']['name']} {fam['panel']['version']}",
        panel_name=fam["panel"]["name"], panel_version=fam["panel"]["version"],
        specimen_line=spec_line, sid=sid, stype=stype, collected=ctx.collected.isoformat(),
        build_line="Genoma de referencia GRCh38", issued=ctx.issued.isoformat())

    variants, biomarkers, implications = [], [], []
    for n, v in enumerate(x for x in ctx.variants if x.kind == "variant"):
        key = f"v{n + 1}"
        parts: List[str]
        fields: Dict[str, Any] = {"gene": v.gene_symbol, "vaf": vaf_text(ctx.vafs[v.label]),
                                  "source_class": v.source_class}
        if v.structural:
            line = (f"Reordenamiento {v.gene_symbol}::{v.partner_gene} detectado por RNA. "
                    f"VAF {fields['vaf']}. Variante {'germinal' if v.source_class == 'germline' else 'somática'}. "
                    f"{_class_text(v.classification)}.")
        else:
            fields.update(hgvs_c=v.hgvs_c, hgvs_p=_p_short(v.hgvs_p), zygosity=v.zygosity)
            line = (f"{v.gene_symbol} {v.hgvs_c} ({_p_short(v.hgvs_p)}) VAF {fields['vaf']}. "
                    f"{_ZYG_ES[v.zygosity]}. Variante {'germinal' if v.source_class == 'germline' else 'somática'}. "
                    f"{_class_text(v.classification)}.")
        if v.classification:
            fields.update(classification=v.classification.value.replace("-", "_"),
                          classification_system=v.classification.system)
        variants.append({"line": line, "key": key, "fields": fields})
        if v.second_classification:
            c = v.second_classification
            implications.append({
                "line": (f"Clasificación alternativa de {v.gene_symbol} {v.hgvs_c or '(reordenamiento)'} (laboratorio): "
                         f"{_class_text(c)}."),
                "links": [key], "fields": {"implication_kind": "diagnostic"}})
        for t in v.therapies:
            implications.append({
                "line": (f"Implicación terapéutica: {t.display}. Evidencia: {t.evidence}. "
                         f"Enfermedad: {_DX_ES[ctx.desc.family]}."),
                "links": [key],
                "fields": {"implication_kind": "therapeutic", "therapy": t.display,
                           "evidence_level": t.evidence, "phenotype": _DX_ES[ctx.desc.family]}})
    for v in ctx.variants:
        if v.kind == "msi":
            biomarkers.append({"kind": "msi", "line": f"Estado de inestabilidad de microsatélites: {v.msi}.",
                               "fields": {"value": v.msi}})
    params.update(variants=variants, biomarkers=biomarkers, implications=implications)
    rel_src, rel_ver = ctx.release.split("@")
    params.update(
        release_line=f"Fuente de conocimiento: ClinVar versión {rel_ver}",
        release_fields={"name": rel_src, "version": rel_ver})
    has_germline = any(v.source_class == "germline" for v in ctx.variants)
    reco = ("Se recomienda valorar consejo genético y estudio familiar."
            if has_germline else "Se recomienda discutir el resultado en comité multidisciplinar de tumores.")
    params.update(reco_line=f"Recomendación: {reco}", reco_fields={"text": reco})

    text, ents, meta = render_with_entities("informe_genetico.es.j2", params)
    # resolve local keys -> entity ids
    ids = {key: f"ent_{i + 1:04d}" for i, (key, _) in enumerate(meta) if key}
    resolved: List[Entity] = []
    for i, (e, (key, links)) in enumerate(zip(ents, meta)):
        val = {k: v for k, v in e.value.items() if v is not None}
        if links:
            val["linked_variant_ids"] = [ids[k] for k in links]
        resolved.append(Entity(e.kind, val, e.char_start, e.char_end, e.quote))
    return text, resolved, {"specimen_identifier": sid}


# --------------------------------------------------------------------------- pathology report

_SPECIMEN_ES = {"breast": ("Tumorectomía de mama izquierda", "Tumorectomía con biopsia selectiva de ganglio centinela", "left"),
                "lung": ("Lobectomía pulmonar derecha", "Lobectomía pulmonar con linfadenectomía", "right"),
                "colorectal": ("Hemicolectomía derecha", "Hemicolectomía derecha con linfadenectomía", "unknown"),
                "prostate": ("Prostatectomía radical", "Prostatectomía radical con linfadenectomía pélvica", "unknown")}
_MARKER_ES = {"16112-5": ("Receptor de estrógenos (RE)", "estrógenos"),
              "16113-3": ("Receptor de progesterona (RP)", "progesterona"),
              "48676-1": ("HER2", "HER2")}
_POS_ES = {"positive": "positivo", "negative": "negativo"}


def _accession(ctx: CaseContext) -> str:
    return f"AP-{ctx.collected.year}-{case_number(ctx.case_id) * 37 + 100:06d}"


def render_pathology_report(ctx: CaseContext) -> Tuple[str, List[Entity], Dict[str, Any]]:
    rng = random.Random(f"{ctx.desc.person_uuid}:{ctx.case_id}:ap")
    fam, d = ctx.family, ctx.desc
    icdo = dict(fam["icdo3"])
    hist = fam.get("histology_by_snomed", {}).get(d.snomed)
    if hist:
        icdo.update(hist)
    sp_type, proc_text, lat = _SPECIMEN_ES[d.family]
    acc = _accession(ctx)
    tnm = tnm_values(ctx)["pathological"]
    lines: List[Dict[str, Any]] = []

    def add(kind: str, line: str, **fields: Any) -> None:
        lines.append({"kind": kind, "line": line, "fields": fields})

    spec_f: Dict[str, Any] = {"accession": acc, "type_text": sp_type.lower(),
                              "collection_date": ctx.collected.isoformat()}
    if lat != "unknown":
        spec_f["laterality"] = lat
    add("specimen", f"Muestra {acc}: {sp_type}, recibida el {ctx.collected.isoformat()}", **spec_f)
    add("procedure", f"Procedimiento: {proc_text}", text=proc_text)
    add("tumour_site", f"Localización del tumor: {fam['label_es'].capitalize()} ({icdo['topography']})",
        code=icdo["topography"])
    add("histology", f"Tipo histológico: {icdo['morphology_es']} ({icdo['morphology']}/{icdo['behaviour']})",
        code=icdo["morphology"], behaviour=icdo["behaviour"])
    if d.family == "prostate":
        gl = ctx.staging.gleason
        add("grade", f"Grado histológico: Gleason {gl} (grupo de grado {ctx.staging.grade_group})",
            system="gleason", value_text=f"Gleason {gl}")
    elif d.family == "breast":
        add("grade", "Grado histológico: Grado 2 de Nottingham (puntuación 3+2+1)", system="nottingham",
            value_text="Grado 2")
    else:
        add("grade", "Grado histológico: Grado 2 (moderadamente diferenciado)", system="who", value_text="Grado 2")
    st = ctx.staging
    size = st.size_mm
    add("size_mm", f"Tamaño tumoral: {size} mm en su mayor dimensión", value=size, dimension="greatest",
        unit="mm", source_value=str(size), source_unit="mm")
    dist = rng.choice([2, 4, 6])
    add("margins", f"Márgenes quirúrgicos: negativos, margen más próximo a {dist} mm", status="negative",
        distance_mm=dist)
    lvi_absent = rng.random() < 0.6
    add("lymphovascular_invasion", "Invasión linfovascular: " + ("ausente" if lvi_absent else "presente"),
        status="absent" if lvi_absent else "present")
    add("perineural_invasion", "Invasión perineural: ausente", status="absent")
    examined, positive = st.nodes_examined, st.nodes_positive
    add("nodes", f"Ganglios linfáticos: {positive} de {examined} ganglios con metástasis",
        examined=examined, positive=positive)
    if d.family == "prostate":
        psa = f"{ctx.staging.psa:.1f}"
        add("biomarker", f"PSA preoperatorio: {psa.replace('.', ',')} ng/mL", code="2857-1", name_text="PSA",
            method_text="suero", value={"value": float(psa), "unit": "ng/mL"})
    add("ptnm", f"Estadificación pTNM (TNM {EDITION}.ª edición): {tnm['t']} {tnm['n']} {tnm['m']}, estadio {tnm['stage']}",
        prefix="p", t=tnm["t"], n=tnm["n"], m=tnm["m"], stage_group=tnm["stage"], edition=EDITION)
    for m in d.markers:
        if m["loinc"] in _MARKER_ES:
            label, nm = _MARKER_ES[m["loinc"]]
            add("biomarker", f"{label}: {_POS_ES[m['value']]}, inmunohistoquímica", code=m["loinc"], name_text=nm,
                method_text="inmunohistoquímica", value=m["value"])
    comment = "Sin hallazgos adicionales de interés."
    add("comment", f"Comentario: {comment}", text=comment)

    params = _common(ctx)
    params["lines"] = lines
    text, ents, _ = render_with_entities("informe_anatomia_patologica.es.j2", params)
    resolved = [Entity(e.kind, {k: v for k, v in e.value.items() if v is not None},
                       e.char_start, e.char_end, e.quote) for e in ents]
    return text, resolved, {"accession": acc}


# --------------------------------------------------------------------------- C5 documents

@lru_cache(maxsize=None)
def _c5_registry() -> Registry:
    d = genomics_resource("c5")
    res = []
    for f in ("clinical-extraction.v1.schema.json", "genomic-extraction.v1.schema.json",
              "synoptic-pathology.v1.schema.json"):
        s = json.loads((d / f).read_text("utf-8"))
        res.append((s["$id"], Resource.from_contents(s)))
    return Registry().with_resources(res)


def validate_c5(doc: Dict[str, Any]) -> None:
    f = {GENOMIC_SCHEMA: "genomic-extraction.v1.schema.json",
         PATHOLOGY_SCHEMA: "synoptic-pathology.v1.schema.json"}[doc["schema"]]
    schema = json.loads((genomics_resource("c5") / f).read_text("utf-8"))
    errs = sorted(jsonschema.Draft202012Validator(schema, registry=_c5_registry()).iter_errors(doc),
                  key=lambda e: list(e.absolute_path))
    if errs:
        raise ValueError(f"C5 validation failed at {list(errs[0].absolute_path)}: {errs[0].message}")


def entities_json(schema: str, text: str, entities: List[Entity], pdf_sha256: str) -> Dict[str, Any]:
    out_ents = []
    for i, e in enumerate(entities):
        row: Dict[str, Any] = {"entity_id": f"ent_{i + 1:04d}", "kind": e.kind, "quote": e.quote,
                               "char_start": e.char_start, "char_end": e.char_end,
                               "quote_sha256": sha256_text(e.quote), "assertion": e.assertion}
        row.update(e.value)
        out_ents.append(row)
    doc = {"schema": schema, "document_sha256": pdf_sha256, "source_text": text,
           "source_text_sha256": sha256_text(text), "entities": out_ents,
           "needs_review": True, "extractor_version": EXTRACTOR_VERSION}
    validate_c5(doc)
    return doc
