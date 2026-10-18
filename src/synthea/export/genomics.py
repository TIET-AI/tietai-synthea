"""Genomics / oncology synthetic pack exporter (GO-61 REQ-01, 02, 04 to 09).

Two phases, so the output is identical for any thread or process count:

1. ``GenomicsExporter.export`` runs for every person (possibly in a worker
   process) and only *stages* a small JSON descriptor for each person whose
   record holds a cancer condition of the code set.
2. ``GenomicsPackFinalizer.export`` runs once after the population is complete,
   sorts the descriptors by person uuid, assigns variants and writes the pack.

All values are synthetic. Nothing derives from the wall clock.
"""
import base64
import hashlib
import json
import random
import re
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from synthea.export.bgzf import BGZFWriter
from synthea.export.exporter import PatientExporter, PostCompletionExporter
from synthea.export.genomics_fhir import (
    CaseContext, build_oncology_bundle, build_report_bundle, pdf_object_id, tnm_values)
from synthea.export.genomics_manifest import PackWriter, check_reference_guard
from synthea.export.genomics_model import (
    GENOME_BUILD, KNOWLEDGE_RELEASE, SEED, CaseDescriptor, CuratedVariant, GenomicsPackError,
    family_of_code, genomics_resource, load_codes, load_curated, sha256_hex)
from synthea.export.genomics_negatives import build_negatives, dumps as neg_dumps
from synthea.export.genomics_oru import render_oru
from synthea.export.genomics_reports import (
    GENOMIC_SCHEMA, PATHOLOGY_SCHEMA, entities_json, render_genetic_report, render_pathology_report)
from synthea.export.pdfmini import text_twin, write_pdf
from synthea.export.vcf import GRCH38_CONTIGS, VCFRecord, write_vcf

PACK_DIRNAME = "genomics-oncology-pack"
STAGING_DIRNAME = "genomics-oncology-pack.staging"
LINES_PER_PAGE = 60


def _d(value: Any) -> str:
    if hasattr(value, "date"):
        value = value.date()
    return value.isoformat()


def _text(code_value: Any) -> str:
    return str(getattr(code_value, "display", None) or (code_value.get("display") if isinstance(code_value, dict) else "") or "")


#: The pack stages with TNM 8th edition (in force from 2018-01-01) and cites a ClinVar release of
#: 2026-09: case dates are moved forward by whole years until the diagnosis is in the TNM 8 era,
#: and the genetic report is issued after the cited release.
ERA_START = date(2018, 1, 1)


def _add_years(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:      # 29 February
        return d.replace(year=d.year + years, day=28)


def era_shift_years(onset: date) -> int:
    if onset >= ERA_START:
        return 0
    k = ERA_START.year - onset.year
    return k if _add_years(onset, k) >= ERA_START else k + 1


def _shift_descriptor(d: CaseDescriptor) -> None:
    k = era_shift_years(date.fromisoformat(d.onset))
    if not k:
        return
    d.onset = _add_years(date.fromisoformat(d.onset), k).isoformat()
    for item in d.meds + d.procs:
        item["date"] = _add_years(date.fromisoformat(item["date"]), k).isoformat()


def _thin(items: List[Dict[str, str]], key: str, gap_days: int = 21, cap: int = 6) -> List[Dict[str, str]]:
    """Keep at most ``cap`` entries per code, at least ``gap_days`` apart.

    The modules record every chemotherapy day and every radiotherapy fraction;
    the pack keeps the treatment course, not each session, so bundles stay small.
    """
    kept: List[Dict[str, str]] = []
    last: Dict[str, date] = {}
    count: Dict[str, int] = {}
    for it in items:
        d0 = date.fromisoformat(it["date"])
        k = it[key]
        if count.get(k, 0) >= cap:
            continue
        if k in last and (d0 - last[k]).days < gap_days:
            continue
        last[k] = d0
        count[k] = count.get(k, 0) + 1
        kept.append(it)
    return kept


class GenomicsExporter(PatientExporter):
    """Stage one descriptor per cancer case of a person (REQ-GO-61-01)."""

    def __init__(self, config, base_dir: Path, locale=None, fhir_exporter=None) -> None:
        self.config = config
        self.base_dir = Path(base_dir)
        self.pack_dir = self.base_dir / PACK_DIRNAME
        self.staging_dir = self.base_dir / STAGING_DIRNAME
        self.codes, _ = load_codes()
        fams = str(config.get("exporter.genomics.families", "breast,lung,colorectal,prostate"))
        self.families = [f.strip() for f in fams.replace(" ", ",").split(",") if f.strip()]
        self.rng_seed = int(config.get("exporter.genomics.seed", SEED))
        self.fhir_exporter = fhir_exporter
        # fail early (REQ-GO-61-17): the tables must load before any person is simulated
        load_curated()

    # -- orchestration ----------------------------------------------------
    def begin(self) -> None:
        """Called once by the parent process before generation starts."""
        if self.staging_dir.exists():
            shutil.rmtree(self.staging_dir)
        self.staging_dir.mkdir(parents=True)

    def rng(self, person) -> random.Random:
        return random.Random(f"{self.rng_seed}:{person.uuid}")

    # -- detection --------------------------------------------------------
    def cases_for(self, person) -> List[CaseDescriptor]:
        record = getattr(person, "record", None)
        if record is None:
            return []
        by_family: Dict[str, List[Any]] = {}
        for cond in record.conditions:
            for c in cond.codes:
                code = str(c.code)
                fam = family_of_code(self.codes, code)
                if fam and fam in self.families:
                    by_family.setdefault(fam, []).append((cond, code))
                    break
        out: List[CaseDescriptor] = []
        for n, fam in enumerate(sorted(by_family)):
            conds = sorted(by_family[fam], key=lambda cc: cc[0].time)
            first, code = conds[0]
            spec = self.codes["families"][fam]
            hist = spec.get("histology_by_snomed", {}).get(code)
            primary = hist["primary"] if hist else code
            stage = None
            for _, c in conds:
                stage = spec.get("stage_by_snomed", {}).get(c, stage)
            attrs = person.attributes
            desc = CaseDescriptor(
                person_uuid=person.uuid,
                first_name=str(attrs.get("first_name", "Sin")),
                last_name=str(attrs.get("last_name", "Nombre")),
                gender=str(attrs.get("gender", "U")),
                birth_date=_d(attrs["birth_date"]),
                family=fam, snomed=primary, onset=_d(first.time), index=n)
            self._attach_record_data(desc, record, first.time, stage)
            out.append(desc)
        return out

    def _attach_record_data(self, desc: CaseDescriptor, record, onset: datetime, stage: Optional[str]) -> None:
        codes = self.codes
        stage_codes = {"21905-5", "21906-3", "21907-1", "21908-9"}
        seen: Dict[str, Tuple[datetime, str]] = {}
        for ob in record.observations:
            if ob.time < onset:
                continue
            for c in ob.codes:
                code = str(c.code)
                if code in stage_codes:
                    disp = _text(ob.value)
                    if code == "21908-9":
                        m = re.search(r"stage (0|IV|I{1,3})([ABC]?)\b", disp)
                    else:
                        m = re.search(r"\b([cp]?(?:T|N|M)(?:is|X|[0-4])[a-d]?)\b", disp)
                    if m:
                        seen[code] = (ob.time, m.group(0).replace("stage ", "") if code == "21908-9" else m.group(1))
                elif code in codes["marker_loinc_map"] or code in ("2857-1", "2039-6"):
                    desc.markers.append(self._marker(code, ob))
        for loinc, (_, text) in sorted(seen.items()):
            desc.stage_obs.append({"loinc": loinc, "text": text})
        if "21908-9" not in seen and stage:
            desc.stage_obs.append({"loinc": "stage", "text": stage})
        atc = codes["rxnorm_to_atc"]
        for med in record.medications:
            if med.time < onset:
                continue
            for c in med.codes:
                if str(c.code) in atc:
                    desc.meds.append({"rxnorm": str(c.code), "display": str(c.display), "date": _d(med.time)})
                    break
        kinds = set(codes["surgery_snomed"]) | set(codes["radiotherapy_snomed"])
        for pr in record.procedures:
            if pr.time < onset:
                continue
            for c in pr.codes:
                if str(c.code) in kinds:
                    desc.procs.append({"snomed": str(c.code), "display": str(c.display), "date": _d(pr.time)})
                    break
        desc.meds = _thin(sorted(desc.meds, key=lambda m: (m["date"], m["rxnorm"])), "rxnorm")
        desc.procs = _thin(sorted(desc.procs, key=lambda p: (p["date"], p["snomed"])), "snomed")
        desc.markers = [m for m in desc.markers if m]
        # one marker per LOINC, first occurrence
        uniq, seen_m = [], set()
        for m in desc.markers:
            if m["loinc"] not in seen_m:
                seen_m.add(m["loinc"])
                uniq.append(m)
        desc.markers = sorted(uniq, key=lambda m: m["loinc"])

    def _marker(self, code: str, ob) -> Optional[Dict[str, Any]]:
        mapped = self.codes["marker_loinc_map"].get(code, code)
        if isinstance(ob.value, (int, float)) and not isinstance(ob.value, bool):
            fam_markers = {m["loinc"]: m for f in self.codes["families"].values() for m in f["markers"]}
            q = fam_markers.get(mapped, {}).get("quantity", {"unit": "ng/mL", "ucum": "ng/mL"})
            return {"loinc": mapped, "display": mapped, "quantity": {"value": round(float(ob.value), 2),
                                                                    "unit": q["unit"], "ucum": q["ucum"]}}
        disp = _text(ob.value).lower()
        if "positive" in disp:
            return {"loinc": mapped, "display": mapped, "value": "positive"}
        if "negative" in disp:
            return {"loinc": mapped, "display": mapped, "value": "negative"}
        return None

    # -- export -----------------------------------------------------------
    def export(self, person, time: int) -> Optional[str]:
        cases = self.cases_for(person)
        if not cases:
            return None
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        for c in cases:
            (self.staging_dir / f"{c.person_uuid}.{c.family}.json").write_text(c.to_json(), "utf-8")
        return str(self.pack_dir / "patients" / person.uuid)


class GenomicsPackFinalizer(PostCompletionExporter):
    """Write the pack once the whole population is known."""

    def __init__(self, config, base_dir: Path) -> None:
        self.config = config
        self.base_dir = Path(base_dir)

    def export(self, generator, stats: Dict[str, Any]):
        write_pack(
            self.base_dir / STAGING_DIRNAME, self.base_dir / PACK_DIRNAME,
            seed=int(self.config.get("exporter.genomics.seed", SEED)),
            knowledge_release=str(self.config.get("exporter.genomics.knowledge_release", KNOWLEDGE_RELEASE)),
            pdf=self.config.get_bool("exporter.genomics.pdf", True),
            regenerate_reference=self.config.get_bool("exporter.genomics.regenerate_reference", False),
            cohort_patches=str(self.config.get("generate.module_patches", "") or ""),
            population=int(getattr(getattr(generator, "options", None), "population_size", 0) or 0),
            reference_dir=self.config.get("exporter.genomics.reference_dir", None))


# ---------------------------------------------------------------------------
# pack writer

def _assign_variants(cases: List[CaseDescriptor], curated: List[CuratedVariant], seed: int
                     ) -> Dict[Tuple[str, str], List[CuratedVariant]]:
    """Per (person, family) variant lists (spec 4.4 step 2), deterministic."""
    out: Dict[Tuple[str, str], List[CuratedVariant]] = {}
    seen: Dict[str, int] = {}
    for d in cases:
        k = seen.get(d.family, 0)
        seen[d.family] = k + 1
        table = [v for v in curated if v.family == d.family]
        if k == 0:
            out[(d.person_uuid, d.family)] = list(table)
            continue
        rng = random.Random(f"{seed}:{d.person_uuid}:{d.family}:variants")
        n = rng.randint(1, min(3, len(table)))
        chosen = rng.sample(table, n)
        germ = [v for v in table if v.source_class == "germline"]
        if germ and k % 5 == 1 and not any(v.source_class == "germline" for v in chosen):
            chosen[0] = rng.choice(germ)
        if all(v.structural or v.kind != "variant" for v in chosen):
            # a report needs at least one reportable (HGVS-bearing) variant
            chosen[0] = next(v for v in table if v.kind == "variant" and not v.structural)
        order = {id(v): i for i, v in enumerate(table)}
        out[(d.person_uuid, d.family)] = sorted(chosen, key=lambda v: order[id(v)])
    return out


def _vafs(variants: List[CuratedVariant], rng: random.Random) -> Tuple[Dict[str, float], Dict[str, Tuple[int, int, int]]]:
    vafs: Dict[str, float] = {}
    depth: Dict[str, Tuple[int, int, int]] = {}
    for v in variants:
        if v.kind != "variant" or v.vaf is None:
            continue
        if v.source_class == "germline":
            target = 1.0 if v.zygosity == "homozygous" else 0.5
        else:
            target = min(0.95, max(0.05, v.vaf + rng.uniform(-0.05, 0.05)))
        dp = rng.randint(400, 1200)
        alt = max(1, round(target * dp))
        vafs[v.label] = round(alt / dp, 3)
        depth[v.label] = (dp - alt, alt, dp)
    return vafs, depth


def write_pack(staging: Path, pack_dir: Path, *, seed: int = SEED, knowledge_release: str = KNOWLEDGE_RELEASE,
               pdf: bool = True, regenerate_reference: bool = False, cohort_patches: str = "",
               population: int = 0, reference_dir: Optional[str] = None) -> Dict[str, Any]:
    curated, curated_sha = load_curated()
    codes, codes_sha = load_codes()
    check_reference_guard(reference_dir, curated_sha, regenerate_reference, pack_dir)
    files = sorted(Path(staging).glob("*.json"))
    descs = sorted((CaseDescriptor.from_json(f.read_text("utf-8")) for f in files),
                   key=lambda d: (d.person_uuid, d.family))
    # patients/<uuid>/case/ holds the C4 goldens written by Hydra's GO-20 procedure
    # (TestBuildGoldenGO61Pack with GO61_UPDATE=1). This generator neither
    # regenerates nor deletes them: they are carried over when the pack is
    # rewritten in place.
    _clear_previous_pack(pack_dir)
    pack_dir.mkdir(parents=True, exist_ok=True)
    w = PackWriter(pack_dir)
    for d in descs:
        _shift_descriptor(d)
    assignment = _assign_variants(descs, curated, seed)

    bundles: Dict[str, Tuple[Dict[str, Any], Dict[str, Any], CaseContext]] = {}
    counts = {"patients": len({d.person_uuid for d in descs}), "cases": len(descs), "reports": 0,
              "variants": 0, "vcf": 0, "pdf": 0, "negatives": 0}
    for n, d in enumerate(descs, 1):
        case_id = f"oc_{n:04d}"
        variants = assignment[(d.person_uuid, d.family)]
        rng = random.Random(f"{seed}:{d.person_uuid}:{d.family}:case")
        vafs, depth = _vafs(variants, rng)
        onset = date.fromisoformat(d.onset)
        collected = onset + timedelta(days=rng.randint(7, 21))
        issued = collected + timedelta(days=rng.randint(14, 30))
        release_day = date.fromisoformat(knowledge_release.split("@")[1])
        if issued <= release_day:                 # a report cannot cite a release that does not exist yet
            issued = release_day + timedelta(days=rng.randint(1, 20))
        ctx = CaseContext(desc=d, case_id=case_id, codes=codes, variants=variants, vafs=vafs,
                          onset=onset, collected=collected, issued=issued, release=knowledge_release)
        base = f"patients/{d.person_uuid}"
        # ---- reports (PDF first: the FHIR bundle references the PDF by hash)
        gtext, gents, _ = render_genetic_report(ctx)
        atext, aents, _ = render_pathology_report(ctx)
        for tag, text, ents, schema in (("informe-genetico", gtext, gents, GENOMIC_SCHEMA),
                                        ("informe-ap", atext, aents, PATHOLOGY_SCHEMA)):
            pages = _paginate(text)
            pdf_path = pack_dir / base / "reports" / f"{tag}-{case_id}.pdf"
            pdf_path.parent.mkdir(parents=True, exist_ok=True)
            write_pdf(pdf_path, pages, f"{tag} {case_id} (sintético)")
            pdf_bytes = pdf_path.read_bytes()
            if tag == "informe-genetico":
                ctx.pdf_sha256 = hashlib.sha256(pdf_bytes).digest()
                ctx.pdf_size = len(pdf_bytes)
                ctx.pdf_object = pdf_object_id(ctx.pdf_sha256)
            if pdf:
                w.register(pdf_path)
                counts["pdf"] += 1
            else:
                pdf_path.unlink()
            w.write_text(f"{base}/reports/{tag}-{case_id}.txt", text_twin(pages))
            doc = entities_json(schema, text_twin(pages), ents, hashlib.sha256(pdf_bytes).hexdigest())
            w.write_json(f"{base}/reports/{tag}-{case_id}.entities.json", doc)
        counts["reports"] += 1
        # ---- FHIR
        rb = build_report_bundle(ctx, f"Informe genético {case_id} (sintético)")
        ob = build_oncology_bundle(ctx)
        w.write_json(f"{base}/fhir/report-{case_id}.bundle.json", rb)
        w.write_json(f"{base}/fhir/oncology-{case_id}.bundle.json", ob)
        counts["variants"] += sum(1 for v in variants if v.kind == "variant" and not v.structural)
        bundles[case_id] = (rb, ob, ctx)
        # ---- VCF
        recs = []
        for v in variants:
            if v.kind != "variant" or v.structural:
                continue
            ref_n, alt_n, dp = depth[v.label]
            recs.append(VCFRecord(
                chrom=v.grch38["chrom"], pos=v.grch38["pos"], id=v.clinvar or ".", ref=v.grch38["ref"],
                alt=v.grch38["alt"], qual=99.0, filter="PASS",
                info={"GERMLINE" if v.source_class == "germline" else "SOMATIC": ""},
                gt="1/1" if v.zygosity == "homozygous" else "0/1", ad=(ref_n, alt_n), dp=dp,
                af=alt_n / dp))
        sample = f"SYNTH_{case_id.upper()}"
        contigs = {c: GRCH38_CONTIGS[c] for c in sorted({r.chrom for r in recs}, key=lambda c: list(GRCH38_CONTIGS).index(c))}
        vcf_text = write_vcf(recs, sample, GENOME_BUILD, contigs)
        w.write_vcf_gz(f"{base}/vcf/{sample}.vcf.gz", vcf_text)
        counts["vcf"] += 1
        # ---- ORU
        w.write_text(f"oru/{case_id}.hl7", render_oru(ctx, sample))

    # ---- negatives and known gaps (derived from the first case with a germline variant)
    base_case = next((cid for cid, (rb, ob, c) in bundles.items()
                      if any(v.source_class == "germline" and v.kind == "variant" for v in c.variants)
                      and sum(1 for v in c.variants if v.kind == "variant" and not v.structural) >= 3), None)
    if base_case is None:
        raise GenomicsPackError("no case has >= 3 variants including a germline one; cannot derive the negatives "
                                "(population too small or families filtered)")
    rb, ob, _ = bundles[base_case]
    for neg in build_negatives(rb, ob):
        w.write_text(f"negatives/{neg['dir']}/bundle.json", neg_dumps(neg["bundle"]))
        w.write_text(f"negatives/{neg['dir']}/expected.json", neg_dumps(neg["expected"]))
        counts["negatives"] += 1
    w.write_known_gaps(bundles, curated)

    patches_sha = sha256_hex(Path(cohort_patches).read_bytes()) if cohort_patches else None
    w.write_manifest({
        "schema": "tietai.genomics-pack/v1", "seed": seed, "population": population,
        "curated_variants_sha256": curated_sha, "cancer_codes_sha256": codes_sha,
        "knowledge_release": knowledge_release, "genome_build": GENOME_BUILD,
        "counts": counts, "tbi_source": "ci", "cohort_patches_sha256": patches_sha,
        "negative_base_case": base_case,
        "curated_review_status": "pending-clinical-geneticist-signoff",
    })
    shutil.rmtree(staging, ignore_errors=True)
    return counts


def _clear_previous_pack(pack_dir: Path) -> None:
    """Remove the files of an earlier pack, and nothing else.

    A directory that is not a pack (no ``MANIFEST.json`` of ours) is never touched, so a
    mistyped ``--output-dir`` cannot delete someone's data. Only the files the old manifest
    lists, and their ``.tbi`` indexes, are removed; the Hydra goldens under ``case/`` and any
    other file are left alone, and empty directories are pruned.
    """
    if not pack_dir.exists():
        return
    manifest = pack_dir / "MANIFEST.json"
    try:
        listed = json.loads(manifest.read_text("utf-8"))
        ok = listed.get("schema") == "tietai.genomics-pack/v1"
    except (OSError, ValueError):
        ok = False
    if not ok:
        if any(pack_dir.iterdir()):
            raise GenomicsPackError(
                f"{pack_dir} exists and is not a genomics pack written by this generator "
                "(no valid MANIFEST.json); refusing to delete it")
        return
    for rel in listed.get("files", {}):
        f = pack_dir / rel
        if f.is_file():
            f.unlink()
        tbi = f.with_name(f.name + ".tbi")
        if tbi.is_file():
            tbi.unlink()
    manifest.unlink()
    for d in sorted((p for p in pack_dir.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
        try:
            d.rmdir()
        except OSError:
            pass


def _paginate(text: str) -> List[List[str]]:
    lines = text.splitlines()
    return [lines[i:i + LINES_PER_PAGE] for i in range(0, len(lines), LINES_PER_PAGE)] or [[""]]
