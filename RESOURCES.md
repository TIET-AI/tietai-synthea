# Bundled Resources

Everything listed here ships **inside the installed package**, under
`synthea/resources/`, and is found through `synthea.helpers.resources`. Nothing
needs a repository checkout or a working directory.

`resources/PROVENANCE.json` records the upstream commit, path, byte count and
SHA-256 of every file imported from the original Synthea project, so the
bundled data can be traced and re-verified (SOUP identification, IEC 62304
clause 8).

> **This file previously described resources that were not shipped** — 15
> provider CSVs, 4 payer CSVs, 14 cost tables, 7 geography files and the
> lookup tables were all documented and none were present. Most are now
> bundled; the rest are listed under [Not bundled](#not-bundled) with the
> reason. If you find a gap between this page and the package, that is a bug
> worth reporting.

---

## Summary

| Directory | Files | Size | Purpose |
|---|---|---|---|
| `modules/` | 256 JSON | ~9 MB | Disease pathways as state machines |
| `lookup_tables/` | 70 CSV | 656 KB | Stratified transition probabilities |
| `costs/` | 14 CSV | 236 KB | Encounter, medication, procedure, device costs |
| `payers/` | 4 CSV | 9 KB | Insurance carriers, plans, eligibility |
| `geography/` | 4 | 3.5 MB | ZIP codes, time zones, social determinants |
| `templates/` | 32 | ~200 KB | Clinical note and C-CDA templates |
| `physiology/` | 7 | ~100 KB | SBML circulation models |
| `keep_modules/` | 9 | small | Priority module sets |
| Root files | 12 | ~600 KB | Growth charts, biometrics, names, schedules |

---

## Disease modules — `modules/`

**256 JSON files**, of which **99 are top-level modules**; the rest are
submodules invoked through `CallSubmodule` and are not run directly.

Grouped by directory: `allergies/`, `anemia/`, `breast_cancer/`,
`contraceptives/`, `covid19/`, `dermatitis/`, `dme/`, `encounter/`, `eye/`,
`heart/` (with `avrr/`, `cabg/`, `savrepair/`, `savreplace/`, `tavr/`), `hiv/`,
`injuries/`, `lung_cancer/`, `medications/`, `metabolic_syndrome/`, `snf/`,
`surgery/`, `total_joint_replacement/`, `uti/`, `veterans/`, `weight_loss/`.

See [Module Value Forms](https://github.com/TIET-AI/tietai-synthea/wiki/Module-Value-Forms)
for how a module expresses values and durations.

## Lookup tables — `lookup_tables/`

**70 CSV files.** Every one of the 69 tables referenced by the bundled modules
is present; there are 289 references in total.

A table stratifies transition probabilities by patient and by date. Rows are
selected on `age` (an inclusive range in years), `gender`, `state`, `time` (an
inclusive range of epoch milliseconds) or any other column naming a patient
attribute. The remaining columns give that row's probability per transition
target.

## Costs — `costs/`

**14 CSV files**: base costs for encounters, medications, procedures,
immunizations, labs, devices and supplies, each with a regional adjustment
table.

> Costs are bundled but **not yet applied**. Cost and claim modelling is
> tracked in [#39](https://github.com/TIET-AI/tietai-synthea/issues/39).

## Payers — `payers/`

**4 CSV files**: carriers, insurance companies, insurance plans and eligibility
rules.

> Bundled but **not yet applied**. Coverage assignment is tracked in
> [#39](https://github.com/TIET-AI/tietai-synthea/issues/39).

## Geography — `geography/`

- `zipcodes.csv` — ZIP codes with city, state and coordinates
- `timezones.csv` — state to time zone
- `sdoh.csv` — social determinants by area
- `foreign_birthplace.json` — birthplaces for foreign-born patients

## Clinical reference data — root

| File | Purpose | Used by |
|---|---|---|
| `cdc_growth_charts.json` | Height, weight, BMI and head circumference by age and sex, with LMS parameters | lifecycle |
| `biometrics.yml` | Reference ranges for vitals and panels; adult weight change | lifecycle, disease modules |
| `names.yml` | Given and family names (English, Spanish) and street types | identity |
| `immunization_schedule.json` | CVX codes, ages due, first availability | immunizations |
| `language_lookup.json` | BCP-47 language codes | identity |
| `race_ethnicity_codes.json` | OMB race and ethnicity codes | FHIR export |
| `bmi_correlations.json` | Paediatric BMI correlations | reserved |
| `growth_data_error_rates.json` | Measurement error rates | reserved |
| `telemedicine_config.json` | Telemedicine likelihood by encounter type | reserved |
| `synthea.properties` | Default configuration | config |

## Templates — `templates/`

Clinical note (`notes/note.ftl`) and C-CDA templates.

> Templates are bundled but **not yet rendered**. Note generation is tracked in
> [#43](https://github.com/TIET-AI/tietai-synthea/issues/43); the C-CDA
> exporter does not exist.

## Physiology — `physiology/`

SBML circulation models and generator configuration.

> Bundled but **not yet executed**. The `Physiology` state is a no-op; see
> [#33](https://github.com/TIET-AI/tietai-synthea/issues/33).

---

## Not bundled

Four upstream datasets are deliberately left out. Together they are **68 MB**,
which would make the wheel roughly eighty times larger for data that nothing in
this version reads.

| Dataset | Size | Why not, and what it blocks |
|---|---|---|
| `geography/demographics.csv` | 25.9 MB | Per-city census breakdowns. Ages currently come from a built-in national distribution instead. Needed for locale-accurate demographics ([#55](https://github.com/TIET-AI/tietai-synthea/issues/55)) |
| `geography/veteran_demographics.csv` | 19.5 MB | Only the veterans modules use it |
| `providers/` (15 CSV) | 19.4 MB | Real facility directory. Encounters are not yet linked to a provider ([#38](https://github.com/TIET-AI/tietai-synthea/issues/38)) |
| `geography/fipscodes.csv` | 3.0 MB | County FIPS codes; nothing reads them |

Bundling these properly means an on-demand download rather than a bigger wheel.
That is tracked in [#37](https://github.com/TIET-AI/tietai-synthea/issues/37).

---

## Licensing and provenance

All imported data comes from
[synthetichealth/synthea](https://github.com/synthetichealth/synthea), licensed
under **Apache-2.0**. See [`NOTICE`](NOTICE).

`resources/PROVENANCE.json` pins the exact upstream commit and records a
SHA-256 per file. To re-verify:

```python
import hashlib, json, pathlib
from synthea.helpers.resources import resources_root

root = resources_root()
manifest = json.loads((root / "PROVENANCE.json").read_text())
for entry in manifest["files"]:
    digest = hashlib.sha256((root / entry["path"]).read_bytes()).hexdigest()
    assert digest == entry["sha256"], entry["path"]
print(f"{len(manifest['files'])} files verified against {manifest['source_commit'][:9]}")
```

`tests/test_packaged_resources.py` runs this check, so a corrupted or
accidentally edited resource fails the build.

---

## Checking what you have

```python
from synthea.engine.module import Module
from synthea.helpers.resources import resources_root

Module.load_modules()
print(f"{len(Module.get_all_modules())} top-level modules")
print(f"resources at {resources_root()}")
```

```bash
synthea --list-modules
```
