"""HL7 v2 ORU^R01 genomics message per case (GO-61 Q2), in the GO-12 fixture format.

Mirrors ``tests/fixtures/messages/oru/genomics_lri.hl7`` of the connect repository:
one OBR 51969-4, one SPM, a knowledge-source row, and per variant the LRI
sub-ID rows (``n``, ``na``..``nh``) with implication rows under ``n.k``.
Synthetic; derived from the same case as the FHIR bundles.
"""
from typing import List

from synthea.export.genomics_fhir import CaseContext, classification_coding

_LA = {"germline": ("LA6683-2", "Germline"), "somatic": ("LA6684-0", "Somatic")}
_ALLELIC = {"heterozygous": ("LA6706-1", "Heterozygous"), "homozygous": ("LA6705-3", "Homozygous"),
            "hemizygous": ("LA6707-9", "Hemizygous")}


def _ts(d, hhmmss="080000") -> str:
    return d.strftime("%Y%m%d") + hhmmss + "+0000"


def render_oru(ctx: CaseContext, sample: str) -> str:
    from synthea.export.genomics_reports import case_number
    n = case_number(ctx.case_id)
    d = ctx.desc
    seg: List[str] = [
        f"MSH|^~\\&|LIS|LABFAC|HIS|HOSPFAC|{_ts(ctx.issued, '101500')}||ORU^R01^ORU_R01|MSG{n:04d}|P|2.5.1",
        f"PID|1||SYN{n:04d}^^^SYNTH^MR||{d.last_name}^{d.first_name}||{d.birth_date.replace('-', '')}|{d.gender}",
        f"ORC|RE|PL-{n:03d}^LIS|FL-{n:03d}^LIS",
        f"OBR|1|PL-{n:03d}^LIS|FL-{n:03d}^LIS|51969-4^Genetic analysis report^LN|||{_ts(ctx.collected)}"
        f"|||||||||^ORDERPROV^TEST||||||{_ts(ctx.issued, '100000')}||GE|F",
        f"SPM|1|SYN-{n:04d}^LIS||119376003^Tissue specimen^SCT|||||||||||||"
        f"{ctx.collected.strftime('%Y%m%d')}080000|{ctx.collected.strftime('%Y%m%d')}090000",
    ]
    k = 0

    def obx(vt: str, code: str, name: str, sub: str, value: str, system: str = "LN") -> None:
        nonlocal k
        k += 1
        seg.append(f"OBX|{k}|{vt}|{code}^{name}^{system}|{sub}|{value}||||||F")

    k += 1
    seg.append(f"OBX|{k}|ST|KNOWSRC^Knowledge source^L||{ctx.release}||||||F")
    g = 0
    for v in ctx.variants:
        if v.kind != "variant" or v.structural:
            continue
        g += 1
        s = str(g)
        obx("CWE", "69548-6", "Genetic variant assessment", s, "LA9633-4^Present^LN")
        obx("CWE", "48018-6", "Gene studied [ID]", f"{s}a", f"{v.hgnc_id}^{v.gene_symbol}^HGNC")
        obx("ST", "48004-6", "DNA change (c.HGVS)", f"{s}b", v.hgvs_c)
        obx("ST", "48005-3", "Amino acid change (p.HGVS)", f"{s}c", v.hgvs_p)
        obx("ST", "81290-9", "Genomic DNA change (g.HGVS)", f"{s}d", v.hgvs_g)
        obx("CWE", "62374-4", "Human reference sequence assembly version", f"{s}e", "LA26806-2^GRCh38^LN")
        la, name = _LA[v.source_class]
        obx("CWE", "48002-0", "Genomic source class", f"{s}f", f"{la}^{name}^LN")
        if v.zygosity in _ALLELIC:
            code, disp = _ALLELIC[v.zygosity]
            obx("CWE", "53034-5", "Allelic state", f"{s}g", f"{code}^{disp}^LN")
        obx("NM", "81258-6", "Allele frequency", f"{s}h", str(ctx.vafs[v.label]))
        j = 0
        for c in [x for x in (v.classification, v.second_classification) if x]:
            j += 1
            cod = classification_coding(c)["coding"][0]
            sysname = "LN" if cod["system"] == "http://loinc.org" else "TIETAI"
            obx("CWE", "53037-8", "Genetic variation clinical significance", f"{s}.{j}",
                f"{cod['code']}^{cod['display']}^{sysname}")
        for t in v.therapies:
            j += 1
            obx("CWE", "51963-7", "Medication assessed", f"{s}.{j}", f"{t.atc}^{t.display}^ATC")
            obx("CWE", "93044-6", "Level of evidence", f"{s}.{j}", f"^{t.evidence}^")
    return "\r".join(seg) + "\r"
