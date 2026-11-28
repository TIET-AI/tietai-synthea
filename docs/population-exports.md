# Population exports

Generate ordinary FHIR bundles plus population-wide files with a properties file:

```properties
exporter.fhir.bulk_data = true
exporter.csv.export = true
exporter.csv.append_mode = false
exporter.csv.included_files =
exporter.csv.excluded_files =
```

```bash
synthea -p 100 -s 42 -r 20200101 -c population.properties -o output
```

Use a separate output directory for concurrently running generators. Workers
within one run share a private staging directory; only the parent writes the
final aggregate files. Staging is removed on completion or a generation error.
Disk staging and SQLite keep aggregate resource data out of process memory.

## Bulk FHIR (#41)

`fhir/bulk/<ResourceType>.ndjson` contains one resource per line, ordered by id.
Shared providers and payers appear once. Conflicting content for the same
resource type/id fails the run. Bundle-local `urn:uuid:` references become
`ResourceType/id`, including nested references. An unresolved URN fails export.
`manifest.json` lists each file's type, relative filename and resource count.
Its timestamp is the simulation end date, so seeded runs stay reproducible.
This is a local dataset manifest; serve its files and resolve the relative URLs
before passing it to a remote loader. It is not a hosted Bulk Data Access API.

The manifest is published after successful finalization. A subsequent run
replaces it and removes obsolete files listed in the previous manifest, while
preserving unrelated files. Bundle JSON output remains available separately.

Transaction bundles use `ifNoneExist=identifier=...` for Patient, Organization
and Practitioner. The identifier token is URL-encoded. Set
`exporter.fhir.conditional_create=false` only when reproducing old bundle bytes.

```bash
synthea -p 100 -s 42 --fhir-url http://localhost:8080/fhir -o output
```

Server push sends one transaction per patient; splitting that transaction would
break its local references. Other resource types use PUT by stable resource id
on this path. Transient transport errors, HTTP 429 and HTTP 5xx are retried
(`exporter.fhir.server_retries`, default 2; exponential delay starting at
`exporter.fhir.server_retry_delay`, default 0.1 seconds, capped at 10 seconds).
The CLI flag makes errors fatal; library users setting only `server_url` keep
the existing best-effort behavior unless they enable `server_fail_on_error`.
IPS/EHDS documents are wrapped as transactions for server push without changing
the clinical resources or locale conventions.

Verification includes a 100-patient generated dataset, FHIR model validation,
reference closure, shared-resource deduplication and sequential/parallel equality.
An opt-in repost test uses `SYNTHEA_FHIR_URL` against a disposable test server.
The test writes synthetic records and leaves them in that server.

**Remaining acceptance:** real FHIR-server bulk import and the opt-in repost
check must pass in the target environment before #41 can close. The checked-out
TietAI FHIR service's bulk-data routes currently expose export operations, so
this PR does not claim its native bulk-import acceptance or add that API.

## CSV (#42)

Headers follow upstream
[`CSVConstants.java` at 0857400](https://github.com/synthetichealth/synthea/blob/0857400eacbbecc5a67c7d05740efa227d22db39/src/main/java/org/mitre/synthea/export/CSVConstants.java)
and the [CSV data dictionary](https://github.com/synthetichealth/synthea/wiki/CSV-File-Data-Dictionary).
The supported tables are patients, encounters, conditions, medications,
observations, procedures, immunizations, allergies, careplans, imaging_studies,
devices, supplies, organizations, providers, payers, payer_transitions and claims.
`claims_transactions` and `patient_expenses` are outside this change's scope;
requesting them in `included_files` fails explicitly.

`included_files` is a comma-separated selection (with optional `.csv` suffixes).
An empty selection means all supported tables. `excluded_files` then removes
names. Excluding `patient_expenses`/`claims_transactions` is accepted for
compatibility with upstream defaults. Excluded files from older runs are left
untouched. `folder_per_run=true` is refused; choose a new `--output-dir` instead.

Rows use the same resource identifiers as FHIR. Facilities and insurers both
use FHIR Organization, but are separated into organizations/payers in CSV.
Medication rows cover both MedicationRequest and MedicationAdministration.
A multi-component Observation becomes one CSV row per component, and an
ImagingStudy becomes one row per DICOM instance. Count reconciliation tests use
these explicit mappings rather than comparing incompatible raw totals.

Unknown source values remain empty. The exporter does not invent billing
transactions, refill history, payer headquarters or clinician demographics.
Each recorded medication represents one recorded dispense; pharmacy refill
simulation is outside this exporter. Prices retain the engine's existing
cost-model and locale limitations. No additional clinical or coding validity
is implied by matching the upstream columns.

Append mode merges by source-resource key, preserving distinct observations
with equal values and updating shared utilization totals. Retain the generated
`csv/.synthea-rows.ndjson` index alongside the CSV files; it stores rows for all
supported tables to reconcile future append runs. Append requires this index
and compatible CSV headers, so editing CSV files directly is not supported.
The index is an internal export cache, not a public dataset manifest.

## Population report (#44)

Every run writes `report/population.json` and `report/population.md`, even if
individual FHIR/JSON exporters are disabled. `--no-report` disables both.
The population is all generated, accepted patients, including deceased patients
when `exporter.only_living=true` suppresses their individual exports. Rejected
patients are counted separately and excluded from metric denominators.

- Prevalence means each patient's condition was recorded at least once during
  their simulated lifetime. It is not a calibrated point-prevalence estimate.
- The age/sex pyramid uses completed age at death or simulation end. Deaths are
  grouped by age at death. Person-years run from birth to death or simulation end.
- Encounter rates use those lifetime person-years. Medication counts include
  prescriptions and administrations represented by the record.
- GMF state coverage counts entries, not each waiting poll. Loaded states with
  no hits remain visible as zero. Python core modules are excluded because
  they do not have GMF state machines.

Target files contain numeric bounds on JSON Pointer paths in the report:

```yaml
targets:
  - metric: /population/generated
    min: 100
    max: 100
  - metric: /medications/per_patient
    min: 0
```

```bash
synthea -p 100 -s 42 -r 20200101 --targets targets.yml -o output
```

`~1` escapes a slash and `~0` a tilde inside a path segment. Unknown metrics,
non-numeric observations or missed bounds fail the CLI after the report records
the result. Malformed target files fail before generation. Targets and
`--no-report` cannot be combined. These are explicit user-defined bounds, not
the sourced locale target system or automated calibration proposed in #55/#56.
