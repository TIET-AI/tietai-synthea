"""Hand-built persons with cancer records for the GO-61 tests (synthetic)."""
from datetime import datetime

from synthea.world.health_record import Code, HealthRecord
from synthea.world.person import Person

SN = "SNOMED-CT"
FAMILY_CODE = {"breast": ("254837009", "Malignant neoplasm of breast (disorder)"),
               "lung": ("254637007", "Non-small cell lung cancer (disorder)"),
               "colorectal": ("363406005", "Malignant neoplasm of colon (disorder)"),
               "prostate": ("399068003", "Malignant tumor of prostate (disorder)")}


def make_person(seed, fam=None, onset=datetime(2020, 3, 2, 9, 0), first="Íñigo", last="Núñez", treat=True):
    p = Person(seed)
    p.attributes.update(first_name=first, last_name=last, gender="F" if fam == "breast" else "M",
                        birth_date=datetime(1955, 5, 4))
    p.record = HealthRecord(p)
    if fam is None:
        return p
    code, disp = FAMILY_CODE[fam]
    r = p.record
    r.condition_start(onset, Code(SN, code, disp), attach=False)
    if fam == "lung":
        r.condition_start(onset, Code(SN, "422968005", "NSCLC stage 3"), attach=False)
    if fam == "breast":
        for loinc, val in (("21905-5", "American Joint Committee on Cancer cT2 (qualifier value)"),
                           ("21906-3", "American Joint Committee on Cancer cN1 (qualifier value)"),
                           ("21907-1", "American Joint Committee on Cancer cM0 (qualifier value)"),
                           ("21908-9", "American Joint Committee on Cancer stage IIB (qualifier value)")):
            r.observation(datetime(2020, 3, 9), Code("LOINC", loinc, "x"), Code(SN, "1", val))
        r.observation(datetime(2020, 3, 9), Code("LOINC", "85337-4", "ER"), Code(SN, "10828004", "Positive (qualifier value)"))
        r.observation(datetime(2020, 3, 9), Code("LOINC", "85339-0", "PR"), Code(SN, "260385009", "Negative (qualifier value)"))
        r.observation(datetime(2020, 3, 9), Code("LOINC", "85319-2", "HER2"), Code(SN, "260385009", "Negative (qualifier value)"))
    if fam == "prostate":
        r.observation(datetime(2020, 3, 5), Code("LOINC", "2857-1", "PSA"), 9.8, "ng/mL")
    if treat:
        meds = {"breast": ("198240", "Tamoxifen 10 MG Oral Tablet"), "lung": ("1736854", "Cisplatin 50 MG Injection"),
                "colorectal": ("1736776", "oxaliplatin 5 MG/ML"), "prostate": ("199123", "bicalutamide 50 MG Oral Tablet")}[fam]
        r.medication_start(datetime(2020, 4, 1), Code("RxNorm", *meds))
        r.medication_start(datetime(2019, 1, 1), Code("RxNorm", *meds))   # before onset: must be ignored
        proc = {"breast": ("392021009", "Lumpectomy of breast (procedure)"), "lung": ("703423002", "Combined chemoradiation"),
                "colorectal": ("43075005", "Partial resection of colon (procedure)"), "prostate": None}[fam]
        if proc:
            r.procedure(datetime(2020, 3, 25), Code(SN, *proc))
    return p


FAMS = ["breast", "lung", "colorectal", "prostate", "breast", "breast", "lung", "prostate", "colorectal", "breast"]


def family_of(i):
    return FAMS[i % len(FAMS)] if i % 6 != 5 else None


def population(n=12):
    return [make_person(100 + i, family_of(i), first=f"Nombre{i}", last="Prueba") for i in range(n)]


def build_pack(tmp_path, persons=None, **cfg):
    from pathlib import Path
    from synthea.export.exporter import Exporter
    from synthea.helpers.config import Config
    c = Config()
    c.load()
    c.set("exporter.baseDirectory", str(tmp_path))
    c.set("exporter.fhir.export", False)
    c.set("exporter.genomics.export", True)
    for k, v in cfg.items():
        c.set(k.replace("__", "."), v)
    ex = Exporter(c)
    ex.begin_run()
    for p in (persons if persons is not None else population()):
        ex.export(p)
    ex.run_post_completion({})
    return Path(tmp_path) / "genomics-oncology-pack"
