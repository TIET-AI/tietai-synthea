"""GO-61 REQ-08 / T-GO-61-08."""
import json

from synthea.export.genomics_negatives import SPECS, build_negatives, diff_paths


def _load(pack, rel):
    return json.loads((pack / rel).read_text("utf-8"))


def test_sixteen_negatives_each_differ_in_one_path(genomics_pack):
    pack = genomics_pack
    dirs = sorted(d for d in (pack / "negatives").iterdir())
    assert len(dirs) == 16
    case = json.loads((pack / "MANIFEST.json").read_text())["negative_base_case"]
    reports = list((pack / "patients").glob(f"*/fhir/report-{case}.bundle.json"))
    onc = list((pack / "patients").glob(f"*/fhir/oncology-{case}.bundle.json"))
    rb, ob = json.loads(reports[0].read_text()), json.loads(onc[0].read_text())
    seen = set()
    for d in dirs:
        exp = json.loads((d / "expected.json").read_text())
        neg = json.loads((d / "bundle.json").read_text())
        key = (exp["invariant"], exp["variant"])
        assert key not in seen
        seen.add(key)
        assert set(exp) >= {"fhirVersion", "note", "expected", "seed", "invariant", "variant", "layer"}
        base = rb if exp["layer"] != "hydra-tool" and "INV-ICDO" not in exp["invariant"] and "STAGING" not in exp["invariant"] else ob
        paths = diff_paths(base, neg)
        if exp["variant"] == "group-only":      # removes the six T/N/M observations: one mutation, six entries
            assert len(paths) == 6 and all(p.endswith("removed") for p in paths)
        else:
            assert len(paths) == 1, (d.name, paths)
        if exp["layer"] == "fhir-validate":
            assert exp["expected"], d.name
            assert all(e["severity"] == "error" for e in exp["expected"])
    names = {d.name.split("-", 1)[1] for d in dirs}
    assert any(n.startswith("INV-HGVS-1") for n in names)
    assert sum(1 for s in SPECS if s[1] == "INV-HGVS-1") == 2
    assert sum(1 for s in SPECS if s[1] == "INV-BUILD-1") == 2
    assert (pack / "known-gaps").is_dir()
