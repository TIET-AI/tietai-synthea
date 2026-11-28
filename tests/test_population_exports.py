"""Cross-format population acceptance checks for #41, #42 and #44."""

import csv
import json
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from synthea.cli import cli
from synthea.engine.generator import Generator, GeneratorOptions
from synthea.engine.module import Module
from synthea.export.csv_exporter import HEADERS
from synthea.export.exporter import Exporter, FHIRServerExporter, FHIRPushError
from synthea.export.fhir import FHIRExporter
from synthea.export.population import PopulationReport, TargetError
from synthea.helpers.config import Config
from synthea.world.health_record import Code
from synthea.world.person import Person
from synthea.world.provider import Provider, Clinician
from synthea.world.payer import Payer, Plan, Coverage

END = datetime(2020, 1, 1)
VISIT = datetime(2019, 1, 1)


def config(root, **changes):
    c = Config()
    c.load()
    c.set("exporter.baseDirectory", str(root))
    c.set("exporter.report.reference_date", END.isoformat())
    c.set("exporter.fhir.bulk_data", True)
    c.set("exporter.csv.export", True)
    c.set("exporter.use_uuid_filenames", True)
    for key, value in changes.items():
        c.set(key.replace("__", "."), value)
    return c


def patient(seed=1):
    p = Person(seed)
    p.init_health_record()
    p.attributes.update(
        birth_date=datetime(1980, 1, 1),
        gender="F",
        first_name="Ana, Maria",
        last_name="Test",
        latitude=40,
        longitude=-3,
    )
    e = p.record.encounter_start(VISIT, "ambulatory")
    e.provider = Provider(
        "hospital",
        "Test Hospital",
        "hospital",
        "Test address",
        "Test city",
        "Test state",
        "12345",
        (40, -3),
        "",
    )
    e.clinician = Clinician(
        "doctor", "Ada", "Test", "General Practice", e.provider, identifier="9999000001"
    )
    cover = Coverage(
        Plan("plan", Payer("payer", "Test Payer", "private"), "Test plan"), p.birth_date
    )
    p.attributes["coverage_history"] = [cover]
    e.coverage = cover
    e.cost = 100
    e.payer_cost = 80
    e.patient_cost = 20
    p.record.condition_start(VISIT, Code("SNOMED-CT", "123", "Test condition"))
    p.record.allergy_start(VISIT, Code("SNOMED-CT", "91935009", "Peanut allergy"))
    p.record.medication_start(VISIT, Code("RxNorm", "860975", "Metformin"))
    p.record.procedure(VISIT, Code("SNOMED-CT", "456", "Test procedure"))
    o = p.record.observation(VISIT, Code("LOINC", "85354-9", "Blood pressure"))
    o.components = [
        (Code("LOINC", "8480-6", "Systolic"), 120, "mm[Hg]"),
        (Code("LOINC", "8462-4", "Diastolic"), 80, "mm[Hg]"),
    ]
    p.record.immunization(VISIT, Code("CVX", "140", "Influenza"))
    p.record.careplan_start(VISIT, Code("SNOMED-CT", "789", "Care plan"))
    p.record.device_start(VISIT, Code("SNOMED-CT", "321", "Device"))
    p.record.supply_list(VISIT, [{"code": Code("SNOMED-CT", "654", "Supply"), "quantity": 2}])
    study = p.record.imaging_study(VISIT, Code("SNOMED-CT", "987", "Imaging"))
    study.dicom_uid = "2.25." + str(seed)
    study.series = [
        {
            "uid": study.dicom_uid + ".1",
            "modality": Code("DICOM-DCM", "DX", "Radiograph"),
            "body_site": Code("SNOMED-CT", "51185008", "Chest"),
            "instances": [
                {
                    "uid": study.dicom_uid + ".1.1",
                    "sop_class": Code(
                        "DICOM-SOP", "1.2.840.10008.5.1.4.1.1.7", "Secondary Capture"
                    ),
                }
            ],
        }
    ]
    p.record.encounter_end(e, VISIT + timedelta(hours=1))
    return p


def run_people(root, people, **changes):
    c = config(root, **changes)
    exporter = Exporter(c)
    exporter.begin_run()
    for p in people:
        exporter.export(p)
    exporter.run_post_completion({"rejected": 0})
    return c


def load_csv(root, name):
    with (root / "csv" / (name + ".csv")).open(newline="") as f:
        return list(csv.DictReader(f))


def test_all_csv_headers_and_resource_counts(tmp_path):
    people = [patient(1), patient(2)]
    run_people(tmp_path, people)
    expected = json.loads((Path(__file__).parent / "fixtures/csv_headers.json").read_text())
    assert set(expected) == set(HEADERS)
    for name, header in expected.items():
        with (tmp_path / "csv" / (name + ".csv")).open(newline="") as f:
            assert next(csv.reader(f)) == header
    manifest = json.loads((tmp_path / "fhir/bulk/manifest.json").read_text())
    counts = {f["type"]: f["count"] for f in manifest["output"]}
    mapping = {
        "patients": "Patient",
        "encounters": "Encounter",
        "conditions": "Condition",
        "procedures": "Procedure",
        "immunizations": "Immunization",
        "allergies": "AllergyIntolerance",
        "careplans": "CarePlan",
        "devices": "Device",
        "supplies": "SupplyDelivery",
        "providers": "Practitioner",
        "payer_transitions": "Coverage",
        "claims": "Claim",
    }
    for table, resource in mapping.items():
        assert len(load_csv(tmp_path, table)) == counts[resource]
    assert len(load_csv(tmp_path, "medications")) == counts.get(
        "MedicationRequest", 0
    ) + counts.get("MedicationAdministration", 0)
    assert len(load_csv(tmp_path, "observations")) == 2 * counts["Observation"]
    assert len(load_csv(tmp_path, "imaging_studies")) == counts["ImagingStudy"]
    assert (
        len(load_csv(tmp_path, "organizations")) + len(load_csv(tmp_path, "payers"))
        == counts["Organization"]
    )
    assert len(load_csv(tmp_path, "providers")) == 1
    assert load_csv(tmp_path, "patients")[0]["FIRST"] == "Ana, Maria"
    assert len(load_csv(tmp_path, "claims")) == 2
    payer_ids = {r["Id"] for r in load_csv(tmp_path, "payers")}
    assert all(r["PRIMARYPATIENTINSURANCEID"] in payer_ids for r in load_csv(tmp_path, "claims"))


def test_bulk_references_resolve_and_no_urns_remain(tmp_path):
    run_people(tmp_path, [patient(1), patient(2)])
    resources = [
        json.loads(line)
        for f in (tmp_path / "fhir/bulk").glob("*.ndjson")
        for line in f.read_text().splitlines()
    ]
    ids = {r["resourceType"] + "/" + r["id"] for r in resources}

    def check(value):
        if isinstance(value, dict):
            if "reference" in value:
                assert value["reference"] in ids
            for v in value.values():
                check(v)
        elif isinstance(value, list):
            for v in value:
                check(v)

    for r in resources:
        check(r)
    assert len(ids) == len(resources)


def test_conditional_creates_use_real_identifiers(tmp_path):
    bundle = FHIRExporter(config(tmp_path), tmp_path).create_bundle(patient())
    for e in bundle["entry"]:
        r = e["resource"]
        if r["resourceType"] in ("Patient", "Organization", "Practitioner"):
            identifier = r["identifier"][0]
            assert parse_qs(e["request"]["ifNoneExist"])["identifier"] == [
                identifier["system"] + "|" + identifier["value"]
            ]
        else:
            assert "ifNoneExist" not in e["request"]


def test_append_repeat_and_file_selection(tmp_path):
    run_people(tmp_path, [patient()])
    before = {p.name: p.read_bytes() for p in (tmp_path / "csv").glob("*.csv")}
    run_people(tmp_path, [patient()], exporter__csv__append_mode=True)
    assert before == {p.name: p.read_bytes() for p in (tmp_path / "csv").glob("*.csv")}
    other = tmp_path / "selected"
    run_people(
        other,
        [patient()],
        exporter__csv__included_files="patients.csv,conditions",
        exporter__csv__excluded_files="conditions.csv",
    )
    assert [p.name for p in (other / "csv").glob("*.csv")] == ["patients.csv"]
    (other / "csv/patients.csv").write_text("wrong,header\n")
    with pytest.raises(ValueError, match="incompatible CSV header"):
        run_people(other, [patient()], exporter__csv__append_mode=True)
    with pytest.raises(ValueError, match="Unknown CSV"):
        Exporter(config(tmp_path, exporter__csv__included_files="../patients"))


def test_report_counts_dead_even_when_exports_filter_them(tmp_path):
    alive, dead = patient(1), patient(2)
    dead.record.death(datetime(2019, 6, 1))
    run_people(tmp_path, [alive, dead], exporter__only_living=True)
    report = json.loads((tmp_path / "report/population.json").read_text())
    assert report["population"] == {"generated": 2, "living": 1, "dead": 1, "rejected": 0}
    assert report["conditions"]["SNOMED-CT|123"]["prevalence"] == 1
    assert report["medications"]["per_patient"] == 1
    assert len(load_csv(tmp_path, "patients")) == 1
    assert report["mortality_by_age_band"] == {"35-39": 1}


def test_state_hits_count_entries_not_waiting_polls():
    module = Module._create_from_json(
        "coverage",
        {
            "name": "coverage",
            "states": {
                "Initial": {"type": "Initial", "direct_transition": "Wait"},
                "Wait": {
                    "type": "Delay",
                    "exact": {"quantity": 2, "unit": "days"},
                    "direct_transition": "Terminal",
                },
                "Terminal": {"type": "Terminal"},
            },
        },
    )
    p = patient()
    for offset in range(4):
        module.process(p, VISIT + timedelta(days=offset))
    assert p._report_state_hits["coverage"] == {"Initial": 1, "Wait": 1, "Terminal": 1}


def test_targets_fail_cli_and_no_report_disables_output(tmp_path):
    target = tmp_path / "targets.yml"
    target.write_text("targets:\n  - metric: /population/generated\n    min: 1\n")
    args = ["-p", "0", "-s", "42", "-r", "20200101", "-o", str(tmp_path / "failed")]
    result = CliRunner().invoke(cli, args + ["--targets", str(target)])
    assert result.exit_code == 1, result.output
    report = json.loads((tmp_path / "failed/report/population.json").read_text())
    assert report["targets_passed"] is False
    assert "Population targets missed" in result.output
    result = CliRunner().invoke(cli, ["-p", "0", "-o", str(tmp_path / "disabled"), "--no-report"])
    assert result.exit_code == 0, result.output
    assert not (tmp_path / "disabled/report").exists()
    result = CliRunner().invoke(cli, args + ["--targets", str(target), "--no-report"])
    assert result.exit_code == 1


@pytest.mark.parametrize(
    "body",
    [
        "targets: nope",
        "targets: [{metric: /x, min: .nan}]",
        "targets: [{metric: /x, min: 2, max: 1}]",
    ],
)
def test_invalid_targets_are_rejected_before_generation(tmp_path, body):
    p = tmp_path / "targets.yml"
    p.write_text(body)
    with pytest.raises(TargetError):
        PopulationReport(config(tmp_path, exporter__report__targets=str(p)))


def test_sequential_and_parallel_outputs_are_identical(tmp_path):
    def generate(path, workers):
        c = config(path)
        options = GeneratorOptions()
        options.population_size = 4
        options.seed = 13
        options.min_age = 1
        options.max_age = 2
        options.reference_date = END
        options.threads = workers
        Generator(options, c).run()
        return {
            p.relative_to(path).as_posix(): p.read_bytes() for p in path.rglob("*") if p.is_file()
        }

    assert generate(tmp_path / "one", 1) == generate(tmp_path / "two", 2)


def test_fhir_push_retries_transients_and_retains_transaction_boundary(tmp_path):
    c = config(
        tmp_path, exporter__fhir__server_retry_delay=0, exporter__fhir__server_fail_on_error=True
    )
    exporter = FHIRServerExporter(c, "http://localhost:9999/fhir")

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self):
            return b'{"resourceType":"Bundle","type":"transaction-response"}'

    with patch("urllib.request.urlopen", side_effect=[OSError("temporary"), Response()]) as send:
        exporter.export(patient(), 0)
    assert send.call_count == 2
    bodies = [json.loads(call.args[0].data) for call in send.call_args_list]
    assert bodies[0] == bodies[1]
    assert bodies[0]["type"] == "transaction"
    assert all(
        "ifNoneExist" in e["request"] or e["request"]["method"] == "PUT" for e in bodies[0]["entry"]
    )
    with patch("urllib.request.urlopen", side_effect=OSError("down")):
        with pytest.raises(FHIRPushError):
            exporter.export(patient(), 0)


def test_append_new_patients_updates_shared_totals_without_duplicates(tmp_path):
    run_people(tmp_path, [patient(1)])
    revenue = float(load_csv(tmp_path, "organizations")[0]["REVENUE"])
    run_people(tmp_path, [patient(2)], exporter__csv__append_mode=True)
    assert len(load_csv(tmp_path, "patients")) == 2
    assert len(load_csv(tmp_path, "encounters")) == 2
    assert len(load_csv(tmp_path, "organizations")) == 1
    assert load_csv(tmp_path, "organizations")[0]["UTILIZATION"] == "2"
    assert float(load_csv(tmp_path, "organizations")[0]["REVENUE"]) > revenue
    assert load_csv(tmp_path, "payers")[0]["UNIQUE_CUSTOMERS"] == "2"


def test_empty_rerun_clears_old_bulk_resources(tmp_path):
    run_people(tmp_path, [patient()])
    # Unrelated files must survive, including files with an NDJSON extension.
    custom = tmp_path / "fhir/bulk/Custom.ndjson"
    custom.write_text("custom\n")
    run_people(tmp_path, [])
    assert sorted(p.name for p in (tmp_path / "fhir/bulk").glob("*.ndjson")) == ["Custom.ndjson"]
    assert json.loads((tmp_path / "fhir/bulk/manifest.json").read_text())["output"] == []


def test_unknown_target_is_a_failure_with_evidence(tmp_path):
    target = tmp_path / "targets.yml"
    target.write_text("targets:\n  - metric: /unknown/metric\n    max: 1\n")
    with pytest.raises(TargetError, match="targets missed"):
        run_people(tmp_path, [patient()], exporter__report__targets=str(target))
    check = json.loads((tmp_path / "report/population.json").read_text())["targets"][0]
    assert check["observed"] is None and not check["passed"]
    assert not (tmp_path / "fhir/bulk/manifest.json").exists()
    assert not list(tmp_path.glob(".synthea-run-*"))


def test_report_golden_seeded_record():
    from synthea.export.population import patient_summary

    report = PopulationReport(Config())
    report.add(patient_summary(patient(7), END))
    result = report.result({"rejected": 1}, {})
    golden = json.loads(
        (Path(__file__).parent / "fixtures/population_report_seed7.json").read_text()
    )
    assert result == golden


def test_100_patient_bulk_dataset_validates_and_reconciles(tmp_path):
    from synthea.export.validation import validate_resource

    options = GeneratorOptions()
    options.population_size = 100
    options.seed = 29
    options.min_age = 1
    options.max_age = 2
    options.reference_date = END
    Generator(options, config(tmp_path)).run()
    manifest = json.loads((tmp_path / "fhir/bulk/manifest.json").read_text())
    for item in manifest["output"]:
        rows = [
            json.loads(line)
            for line in (tmp_path / "fhir/bulk" / item["url"]).read_text().splitlines()
        ]
        assert len(rows) == item["count"]
        for resource in rows:
            assert resource["resourceType"] == item["type"]
            assert validate_resource(resource) is None
    assert next(i["count"] for i in manifest["output"] if i["type"] == "Patient") == 100
    assert len(load_csv(tmp_path, "patients")) == 100


import os


@pytest.mark.skipif(
    not os.environ.get("SYNTHEA_FHIR_URL"),
    reason="set SYNTHEA_FHIR_URL to a disposable FHIR test server",
)
def test_server_reposting_does_not_duplicate_patient(tmp_path):
    import requests

    url = os.environ["SYNTHEA_FHIR_URL"].rstrip("/")
    c = config(tmp_path, exporter__fhir__server_fail_on_error=True)
    p = patient(918273)
    exporter = FHIRServerExporter(c, url)
    exporter.export(p, 0)
    exporter.export(p, 0)
    response = requests.get(
        url + "/Patient",
        params={
            "identifier": "https://github.com/TIET-AI/tietai-synthea|" + p.id,
            "_summary": "count",
        },
        timeout=30,
    )
    response.raise_for_status()
    assert response.json()["total"] == 1


def test_conflicting_shared_resource_fails_without_success_manifest(tmp_path):
    a, b = patient(1), patient(2)
    b.record.encounters[0].provider.name = "Conflicting hospital"
    with pytest.raises(ValueError, match="Conflicting shared FHIR resource"):
        run_people(tmp_path, [a, b])
    assert not (tmp_path / "fhir/bulk/manifest.json").exists()
    assert not list(tmp_path.glob(".synthea-run-*"))


def test_finalizer_failure_removes_private_staging(tmp_path):
    from synthea.export.exporter import GenomicsPackError

    options = GeneratorOptions()
    options.population_size = 0
    generator = Generator(options, config(tmp_path))
    with patch.object(
        generator.exporter, "run_post_completion", side_effect=GenomicsPackError("failed")
    ):
        with pytest.raises(GenomicsPackError):
            generator.run()
    assert not list(tmp_path.glob(".synthea-run-*"))
    assert not (tmp_path / "fhir/bulk/manifest.json").exists()


def test_csv_retains_both_text_allergy_reactions(tmp_path):
    p = patient()
    p.record.allergies[0].reactions = ["Hives", "Wheezing"]
    p.record.allergies[0].severity = "severe"
    run_people(tmp_path, [p])
    row = load_csv(tmp_path, "allergies")[0]
    assert row["DESCRIPTION1"] == "Hives"
    assert row["DESCRIPTION2"] == "Wheezing"
    assert row["SEVERITY1"] == row["SEVERITY2"] == "SEVERE"
