"""GO-61 REQ-05 / T-GO-61-05: VCF 4.3 writer."""
import gzip
import io

from synthea.export.bgzf import BGZFWriter
from synthea.export.vcf import GRCH38_CONTIGS, VCFRecord, write_vcf


def _rec(chrom, pos, ref, alt, af=0.3, dp=100):
    alt_n = round(dp * af)
    return VCFRecord(chrom=chrom, pos=pos, id=".", ref=ref, alt=alt, qual=60.0,
                     filter="PASS", info={"SOMATIC": ""}, gt="0/1",
                     ad=(dp - alt_n, alt_n), dp=dp, af=alt_n / dp)


def test_vcf_matches_observations_and_bgzf_roundtrip():
    recs = [_rec("17", 7675088, "C", "T"), _rec("3", 179234297, "A", "G"),
            _rec("17", 43057062, "T", "TG")]
    text = write_vcf(recs, "SYNTH_OC_0001", "GRCh38", {c: GRCH38_CONTIGS[c] for c in ("3", "17")})
    lines = text.splitlines()
    assert lines[0] == "##fileformat=VCFv4.3"
    assert "##reference=GRCh38" in lines
    assert "##contig=<ID=3,length=198295559,assembly=GRCh38>" in lines
    assert "##contig=<ID=17,length=83257441,assembly=GRCh38>" in lines
    assert not any(l.startswith("##contig=<ID=chr") for l in lines)
    assert any(l.startswith("##FORMAT=<ID=AF") for l in lines)
    body = [l.split("\t") for l in lines if not l.startswith("#")]
    # sorted by contig order (3 before 17) then pos
    assert [(b[0], int(b[1])) for b in body] == [("3", 179234297), ("17", 7675088), ("17", 43057062)]
    assert body[0][8] == "GT:AD:DP:AF"
    assert body[0][9].split(":")[0] == "0/1"
    assert float(body[0][9].split(":")[3]) == 0.3
    header = [l for l in lines if l.startswith("#CHROM")][0]
    assert header.endswith("FORMAT\tSYNTH_OC_0001")

    buf = io.BytesIO()
    w = BGZFWriter(buf)
    w.write(text.encode())
    w.close()
    assert gzip.decompress(buf.getvalue()).decode() == text
    assert text == write_vcf(recs, "SYNTH_OC_0001", "GRCh38", {c: GRCH38_CONTIGS[c] for c in ("3", "17")})
