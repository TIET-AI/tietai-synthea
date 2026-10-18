"""Curated tables and the case model of the genomics pack (GO-61 REQ-03, 17).

Everything here is synthetic test data. The tables are validated against their
JSON schema when loaded, and the generator refuses to start (naming the entry)
when an HGVS string fails the local syntax check or a germline entry has no
GERMLINE mapping (REQ-GO-61-17).
"""
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import jsonschema
import yaml

from synthea.helpers.resources import resource_path

#: Local HGVS syntax check (REQ-GO-61-17).
HGVS_RE = re.compile(r"^(NM|NC|NG|NR|NP|LRG)_\d+(\.\d+)?:[gcnp]\.")

#: source class -> security label the platform applies (GO-05 reads 48002-0).
GERMLINE_LABELS: Dict[str, Optional[str]] = {"germline": "GERMLINE", "somatic": None}

SEED = 20261017
KNOWLEDGE_RELEASE = "clinvar@2026-09-01"
GENOME_BUILD = "GRCh38"


from synthea.export.exporter import GenomicsPackError  # noqa: E402  (shared type, see exporter.py)


def genomics_resource(name: str) -> Path:
    return resource_path("genomics") / name


def file_sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class Classification:
    system: str
    value: str
    source: str


@dataclass(frozen=True)
class Therapy:
    atc: str
    display: str
    evidence: str


@dataclass(frozen=True)
class CuratedVariant:
    family: str
    kind: str
    source_class: str
    gene_symbol: Optional[str] = None
    hgnc_id: Optional[str] = None
    hgvs_c: Optional[str] = None
    hgvs_p: Optional[str] = None
    hgvs_g: Optional[str] = None
    grch38: Optional[Dict[str, Any]] = None
    zygosity: str = "unknown"
    vaf: Optional[float] = None
    classification: Optional[Classification] = None
    second_classification: Optional[Classification] = None
    clinvar: Optional[str] = None
    consequence: Optional[str] = None
    structural: bool = False
    partner_gene: Optional[str] = None
    msi: Optional[str] = None
    therapies: Tuple[Therapy, ...] = ()

    @property
    def label(self) -> str:
        """Short name for messages: gene + c. (or kind)."""
        return f"{self.family}:{self.gene_symbol or self.kind}:{self.hgvs_c or self.msi or 'structural'}"

    @property
    def security_label(self) -> Optional[str]:
        return GERMLINE_LABELS.get(self.source_class)


def _cls(d: Optional[dict]) -> Optional[Classification]:
    return Classification(d["system"], d["value"], d["source"]) if d else None


def load_curated(path: Optional[Path] = None,
                 label_map: Optional[Dict[str, Optional[str]]] = None
                 ) -> Tuple[List[CuratedVariant], str]:
    """Load and validate the curated table; returns (variants, sha256 of the file)."""
    path = Path(path) if path else genomics_resource("curated_variants.yaml")
    schema = json.loads(genomics_resource("curated_variants.schema.json").read_text("utf-8"))
    raw = path.read_bytes()
    doc = yaml.safe_load(raw)
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(doc), key=lambda e: list(e.absolute_path))
    if errors:
        e = errors[0]
        loc = list(e.absolute_path)
        entry = ""
        if len(loc) >= 2 and loc[0] == "variants":
            v = doc["variants"][loc[1]]
            entry = f" (entry {loc[1]}: {v.get('family')}/{v.get('gene_symbol') or v.get('kind')})"
        raise GenomicsPackError(f"curated variant table invalid{entry}: {e.message}")
    labels = GERMLINE_LABELS if label_map is None else label_map
    out: List[CuratedVariant] = []
    for i, v in enumerate(doc["variants"]):
        name = f"entry {i} ({v['family']}/{v.get('gene_symbol') or v['kind']})"
        for k in ("hgvs_c", "hgvs_p", "hgvs_g"):
            if k in v and not HGVS_RE.match(v[k]):
                raise GenomicsPackError(f"{name}: {k} {v[k]!r} fails the HGVS syntax check")
        if v["source_class"] == "germline" and not labels.get("germline"):
            raise GenomicsPackError(f"{name}: germline entry has no GERMLINE label mapping")
        out.append(CuratedVariant(
            family=v["family"], kind=v["kind"], source_class=v["source_class"],
            gene_symbol=v.get("gene_symbol"), hgnc_id=v.get("hgnc_id"),
            hgvs_c=v.get("hgvs_c"), hgvs_p=v.get("hgvs_p"), hgvs_g=v.get("hgvs_g"),
            grch38=v.get("grch38"), zygosity=v.get("zygosity", "unknown"), vaf=v.get("vaf"),
            classification=_cls(v.get("classification")),
            second_classification=_cls(v.get("second_classification")),
            clinvar=v.get("clinvar"), consequence=v.get("consequence"),
            structural=bool(v.get("structural", False)), partner_gene=v.get("partner_gene"),
            msi=v.get("msi"),
            therapies=tuple(Therapy(**t) for t in v.get("therapies", [])),
        ))
    return out, sha256_hex(raw)


def load_codes(path: Optional[Path] = None) -> Tuple[Dict[str, Any], str]:
    path = Path(path) if path else genomics_resource("cancer_codes.yaml")
    raw = path.read_bytes()
    return yaml.safe_load(raw), sha256_hex(raw)


def family_of_code(codes: Dict[str, Any], snomed: str) -> Optional[str]:
    for fam, spec in codes["families"].items():
        if snomed in spec["snomed_codes"]:
            return fam
    return None


@dataclass
class CaseDescriptor:
    """What the per-person export stages for the post-completion writer.

    Plain JSON-able data: workers are separate processes and the pack is only
    written once the whole population is known (deterministic variant
    assignment independent of thread count).
    """
    person_uuid: str
    first_name: str
    last_name: str
    gender: str
    birth_date: str
    family: str
    snomed: str
    onset: str                                   # ISO date
    stage_obs: List[Dict[str, str]] = field(default_factory=list)
    markers: List[Dict[str, Any]] = field(default_factory=list)
    meds: List[Dict[str, str]] = field(default_factory=list)
    procs: List[Dict[str, str]] = field(default_factory=list)
    index: int = 0                               # ordinal of the case within the person

    def to_json(self) -> str:
        return json.dumps(self.__dict__, sort_keys=True, ensure_ascii=False, indent=1)

    @staticmethod
    def from_json(text: str) -> "CaseDescriptor":
        return CaseDescriptor(**json.loads(text))
