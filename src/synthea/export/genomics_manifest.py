"""Pack writer, MANIFEST.json and the PHI scan (GO-61 REQ-09, 10, 17).

The PHI scan applies the Spanish identifier patterns of HGUGM HG-20 REQ-07 to
every text artefact before it is written and aborts naming the file and the
pattern, never the match. UUIDs, SHA-256 hex strings and object ids are
removed first: they are random-looking tokens that can contain digit runs.
"""
import gzip
import hashlib
import io
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import synthea
from synthea.export.bgzf import BGZFWriter
from synthea.export.genomics_model import GenomicsPackError, file_sha256, sha256_hex
from synthea.helpers.resources import resource_path

_B = r"(?<![A-Za-z0-9+/_=.\-])"      # token boundaries: never inside an identifier-like token
_A = r"(?![A-Za-z0-9+/_=\-])"

PHI_PATTERNS: Dict[str, "re.Pattern[str]"] = {
    "dni": re.compile(_B + r"\d{8}[A-Z]" + _A),
    "nie": re.compile(_B + r"[XYZ]\d{7}[A-Z]" + _A),
    "nhc": re.compile(r"(?i)(NHC|historia|H\.C\.|n[ºo°]\s*historia)\W{0,6}\d{5,10}"),
    "cip": re.compile(r"(CIPA|TSI)\W{0,6}[A-Z0-9]{10,16}"),
    # Bare 12-digit and 9-digit runs also occur as SNOMED/NCBI codes, so they only count
    # in context ("NASS", "teléfono"...); the grouped forms count anywhere.
    "nass": re.compile(r"(?i)(NASS|seguridad social|afiliaci[oó]n)\W{0,6}\d{12}\b|" + _B + r"\d{2}/\d{8,10}/\d{2}" + _A),
    "phone": re.compile(r"(?i)(tel[eé]fono|tel\.?|m[oó]vil|fax|contacto)\W{0,6}(\+34|0034)?[ ]?[6789]\d{2}[ ]?\d{3}[ ]?\d{3}\b|"
                        r"(?<![\d.\-])(\+34|0034)[ ]?[6789]\d{2}[ ]?\d{3}[ ]?\d{3}(?![\d\-])|"
                        r"(?<![\d.\-])[6789]\d{2}([ .-])\d{3}\1\d{3}(?![\d\-])"),
    "postal": re.compile(r"(?i)(CP|C\.P\.|código postal)\W{0,3}(0[1-9]|[1-4]\d|5[0-2])\d{3}\b"),
    "email": re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"),
}
_STRIP = [
    re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"),
    re.compile(r"\b[0-9a-f]{32,}\b"),
    re.compile(r"obj_[0-9A-Z]{26}"),
    re.compile(r"[A-Za-z0-9+/]{42,}={0,2}"),      # base64 hashes
]
#: knowledge-release strings look like dates followed by numbers; none of the patterns match them.


def phi_scan(text: str) -> List[str]:
    """Names of the PHI patterns found in ``text`` (empty means clean)."""
    for rx in _STRIP:
        text = rx.sub(" ", text)
    return [name for name, rx in PHI_PATTERNS.items() if rx.search(text)]


def dumps(obj: Any) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class PackWriter:
    def __init__(self, pack_dir: Path) -> None:
        self.dir = Path(pack_dir)
        self.hashes: Dict[str, str] = {}

    def _path(self, rel: str) -> Path:
        p = self.dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def register(self, path: Path) -> None:
        self.hashes[str(Path(path).relative_to(self.dir))] = file_sha256(path)

    def _scan(self, rel: str, text: str) -> None:
        hits = phi_scan(text)
        if hits:
            raise GenomicsPackError(f"PHI pattern {hits[0]!r} found in {rel}; pack generation aborted")

    def write_text(self, rel: str, text: str) -> None:
        self._scan(rel, text)
        p = self._path(rel)
        p.write_bytes(text.encode("utf-8"))
        self.register(p)

    def write_json(self, rel: str, obj: Any) -> None:
        self.write_text(rel, dumps(obj))

    def write_vcf_gz(self, rel: str, text: str) -> None:
        self._scan(rel, text)
        p = self._path(rel)
        with open(p, "wb") as f:
            w = BGZFWriter(f)
            w.write(text.encode("utf-8"))
            w.close()
        self.register(p)
        digest = file_sha256(p)
        side = p.with_name(p.name + ".sha256")
        side.write_text(f"{digest}  {p.name}\n", "utf-8")
        self.register(side)

    def write_known_gaps(self, bundles: Dict[str, Any], curated) -> None:
        from synthea.export.genomics_fhir import build_structural_gap_bundle
        for cid, (rb, ob, ctx) in bundles.items():
            v = next((x for x in ctx.variants if x.structural), None)
            if v is None:
                continue
            bundle = build_structural_gap_bundle(ctx, v)
            d = "known-gaps/01-INV-HGVS-1-structural-variant-without-hgvs"
            self.write_json(f"{d}/bundle.json", bundle)
            self.write_json(f"{d}/expected.json", {
                "fhirVersion": "R4", "invariant": "INV-HGVS-1", "variant": "structural-fusion", "layer": "fhir-validate",
                "note": ("KNOWN GAP (GO-10 follow-up): a gene fusion has no HGVS expression, but tietai-variant "
                         "requires at least one HGVS component, so the platform rejects the structural form "
                         "the GO-61 spec asks for. Not one of the 16 negatives; kept so the gap stays visible."),
                "expected": [{"detailCode": "INV-HGVS-1", "code": "invariant", "severity": "error"}], "seed": []})
            return

    def write_manifest(self, meta: Dict[str, Any]) -> None:
        from synthea.export.genomics_model import GENOME_BUILD  # noqa: F401
        modules_dir = resource_path("modules")
        modules = {f"{n}.json": file_sha256(modules_dir / f"{n}.json")
                   for n in ("breast_cancer", "lung_cancer", "colorectal_cancer", "prostate_cancer")}
        # Pack-format version, not the package version: a release must not change a regenerated pack.
        gen = "tietai-synthea genomics-pack/1"
        manifest = {"generator": gen, "modules": modules}
        manifest.update(meta)
        manifest["files"] = dict(sorted(self.hashes.items()))
        (self.dir / "MANIFEST.json").write_text(dumps(manifest), "utf-8")


def check_reference_guard(reference_dir: Optional[str], curated_sha: str, regenerate: bool,
                          pack_dir: Path) -> None:
    """REQ-GO-61-17: refuse a changed curated table against the committed pack."""
    ref = Path(reference_dir) if reference_dir else Path(synthea.__file__).resolve().parents[2] / "examples" / "genomics-oncology-pack"
    manifest = ref / "MANIFEST.json"
    if regenerate or not manifest.is_file():
        return
    recorded = json.loads(manifest.read_text("utf-8")).get("curated_variants_sha256")
    if recorded and recorded != curated_sha:
        raise GenomicsPackError(
            "the curated variant table differs from the one recorded in the committed reference pack "
            f"({manifest}); review it and pass --regenerate-reference to accept the change")
