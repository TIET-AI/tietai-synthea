"""Single-sample VCF 4.3 writer for the genomics pack (GO-61 REQ-05).

Contigs carry no ``chr`` prefix and the GRCh38 lengths are declared, so the
header alone proves the build (the platform VCF reader infers it from them).
Output is deterministic: no file date, no wall-clock value.
"""
from dataclasses import dataclass
from typing import Dict, Iterable, List

#: GRCh38 primary-assembly chromosome lengths (GRCh38.p14).
GRCH38_CONTIGS: Dict[str, int] = {
    "1": 248956422, "2": 242193529, "3": 198295559, "4": 190214555,
    "5": 181538259, "6": 170805979, "7": 159345973, "8": 145138636,
    "9": 138394717, "10": 133797422, "11": 135086622, "12": 133275309,
    "13": 114364328, "14": 107043718, "15": 101991189, "16": 90338345,
    "17": 83257441, "18": 80373285, "19": 58617616, "20": 64444167,
    "21": 46709983, "22": 50818468, "X": 156040895, "Y": 57227415,
}
_ORDER = {c: i for i, c in enumerate(GRCH38_CONTIGS)}


@dataclass(frozen=True)
class VCFRecord:
    chrom: str
    pos: int
    id: str
    ref: str
    alt: str
    qual: float
    filter: str
    info: Dict[str, str]
    gt: str
    ad: tuple
    dp: int
    af: float


def _info(info: Dict[str, str]) -> str:
    if not info:
        return "."
    return ";".join(k if v == "" else f"{k}={v}" for k, v in sorted(info.items()))


def write_vcf(records: Iterable[VCFRecord], sample: str, build: str,
              contigs: Dict[str, int]) -> str:
    out: List[str] = [
        "##fileformat=VCFv4.3",
        f"##reference={build}",
        "##source=tietai-synthea genomics pack (synthetic)",
    ]
    for c in sorted(contigs, key=lambda c: _ORDER.get(c, 999)):
        out.append(f"##contig=<ID={c},length={contigs[c]},assembly={build}>")
    out += [
        '##INFO=<ID=SOMATIC,Number=0,Type=Flag,Description="Somatic variant">',
        '##INFO=<ID=GERMLINE,Number=0,Type=Flag,Description="Germline variant">',
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">',
        '##FORMAT=<ID=AD,Number=R,Type=Integer,Description="Allelic depths (ref,alt)">',
        '##FORMAT=<ID=DP,Number=1,Type=Integer,Description="Read depth">',
        '##FORMAT=<ID=AF,Number=A,Type=Float,Description="Allele fraction">',
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\t" + sample,
    ]
    for r in sorted(records, key=lambda r: (_ORDER.get(r.chrom, 999), r.pos)):
        smp = f"{r.gt}:{r.ad[0]},{r.ad[1]}:{r.dp}:{round(r.af, 4)}"
        out.append("\t".join([r.chrom, str(r.pos), r.id, r.ref, r.alt, f"{r.qual:g}",
                              r.filter, _info(r.info), "GT:AD:DP:AF", smp]))
    return "\n".join(out) + "\n"
