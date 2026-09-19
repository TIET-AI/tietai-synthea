# Changelog

All notable changes to PySynthea are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html) over its **public API**
(the `synthea` package, the `synthea` command and `synthea.properties`).

> **Generated data is not covered by the version contract.** Fixing an engine
> defect changes what the modules produce, so the patients generated from a
> given seed can differ between any two releases. Pin an exact version when you
> need a dataset to be reproducible, and record it (see the `manifest` work
> tracked in issue #74).

---

## [1.2.0] - 2026-09-19

Patients now have an identity, a body that grows and ages, routine care, and a
FHIR export that validates. 1.1.0 made the engine faithful to the modules; this
makes the records it produces usable.

Eleven of the thirteen [M1 milestone](https://github.com/TIET-AI/tietai-synthea/milestone/1)
tickets are closed.

### Added

- **Core lifecycle** (#30). The engine tried to import five core modules and
  swallowed the failure; none existed. Patients now get a name, street address,
  telephone, email and four typed identifiers at birth, from the bundled
  `names.yml`. Exported files are no longer called `Unknown_Person_*`.

  Identifiers cannot collide with real ones by construction: social security
  numbers use the never-issued `999` area, telephones the reserved `555`
  exchange, emails the reserved `example.com` domain.

- **Growth from the CDC charts** (#30). Each patient holds one height and one
  weight percentile for life, evaluated through the charts' LMS parameters, so a
  child's measurements are correlated across their whole childhood instead of
  being redrawn at every visit. Adult height fixes at 20; adult weight gains,
  plateaus at 49 and declines from 60.

- **Vital signs** (#30). Blood pressure, heart rate, respiration rate and oxygen
  saturation each timestep, from the reference ranges in `biometrics.yml`, and
  never overwriting a value a disease module has already set.

- **Background mortality** (#30). Previously a patient died only if a module
  killed them, so populations contained implausible numbers of centenarians.

- **Routine check-ups** (#29) at age-appropriate intervals, with vitals recorded
  at each. This is what a `wellness` Encounter state attaches to.

- **Immunizations** (#31). The bundled schedule, which nothing had ever read,
  administered at check-ups. A vaccine licensed after a patient's birth is not
  backdated. The `Vaccine` state, previously a no-op, now records module-driven
  vaccinations.

- **Imaging studies** (#33). The `ImagingStudy` state was a no-op, so 39 states
  across 19 modules produced nothing. Studies, series and instances now carry
  real DICOM UIDs under the `2.25.` arc.

- **Reference data** (#37). 70 lookup tables, 14 cost tables, 4 payer tables and
  geography, with `PROVENANCE.json` pinning the upstream commit and recording a
  SHA-256 per file.

- **FHIR validation gate** (#35). `synthea.export.validation` checks a bundle
  against the R4B models in `fhir.resources`, and the suite fails on any invalid
  resource, any null, or any reference that does not resolve.

### Fixed

- **The FHIR export was never valid** (#35). Every bundle this project has
  written was invalid R4:

  | | Was | Now |
  |---|---|---|
  | `Encounter.class` | `AMBULATORY`, the enum name upper-cased | An ActCode: `AMB`, `EMER`, `IMP`, `HH`, `VR` |
  | `Coding.system` | `SNOMED-CT`, `RxNorm`, `CVX` | A URI |
  | Open periods | `"end": null` | Absent |
  | dateTimes | No timezone | UTC offset |
  | `Quantity.code` | Display unit | UCUM symbol |
  | `Observation.category` | Any string | One of nine valid codes |
  | `Condition.category` | Absent | Present |
  | Coded observation values | A bare `Coding` | A `CodeableConcept` |
  | `fullUrl` | `urn:uuid:` plus a 16-character hash | A real UUID |

  The coding system was the worst of these: every code was correct and
  simultaneously unresolvable by any server.

- **The bundled reference data never shipped** (#37). A blanket `*.csv` in
  `.gitignore`, presumably added to keep generated output out of the repository,
  silently excluded every provider, payer, cost and lookup table. They were
  documented for a year while never being committed, so all 289 lookup-table
  references fell back to a default probability and the age, sex, state and date
  stratification did nothing.

  `LookupTableTransition` could not have read them anyway: it looked for
  `age_min` and `age_max` columns, and the real tables stratify on an age
  *range*, a state name, an epoch-millisecond window or a patient attribute.

- **Module-set vital signs never reached the record** (#32). They lived only on
  the person object, invisible to every exporter. This is why observations
  reading a vital sign exported with no value.

- **Medication detail was ignored** (#28). `prescription` (400 uses),
  `administration` (145) and `chronic` (336) were dropped, so prescriptions had
  no dosage or refills. A drug given during a visit is now a
  `MedicationAdministration`, not a request for a drug, and `reason` resolves to
  the condition being treated instead of free text no consumer could resolve.

- **Three condition types always returned false** (#32), so modules silently
  took the wrong branch: `Active Allergy` (24 uses), `At Least` and `At Most`
  (13 uses). `PriorState` now honours its `within` window.

- **The configuration promised output it could not produce** (#36). Enabling the
  CSV exporter raised an `ImportError` from deep inside start-up; C-CDA was
  accepted and silently did nothing. Both now fail immediately with a message
  naming the tracking issue.

- **The package would not install on Python 3.14** (#85) despite the whole suite
  passing there. The version ceiling was an untested assumption; it is gone, and
  3.14 is in the CI matrix.

- Ages came from a uniform draw between the requested bounds; they now follow
  the demographic distribution, and birthdays are spread across the year.

- `Patient.gender` reported `female` for any non-male patient, including unknown.

### Changed

- Core modules run first, in a defined order, because disease-module logic reads
  the attributes they set. `generate.core_modules = false` turns them off.
- An `ImportError` in a core module is now logged rather than swallowed. That
  silence is how a missing lifecycle went unnoticed for a year.
- Unknown distribution kinds, time units, code systems and condition types log
  once per process instead of failing silently.
- `Person` carries a `uuid` alongside its `id`, derived from the seed.
- The wheel grows from 863 KB to 2.0 MB with the bundled reference data.

### Known limitations

- **Mortality is a fitted parametric hazard, not a published life table.** It
  gives life expectancies of 75.3 and 80.5 years and a test asserts that, but
  survival curves from this generator are plausible, not authoritative. Real
  life tables are #55.
- **Obesity is under-represented**: mean adult BMI 27.2 against a real 29.7, and
  17% obese against 42%. `biometrics.yml` gives adult weight change without a
  unit; read as kilograms per year it produced a mean BMI of 32 with two thirds
  obese, so it is read as pounds. Calibrating properly is #55 and #56.
- 68 MB of upstream data is deliberately **not** bundled: per-city census
  demographics, veteran demographics, the provider directory and county FIPS
  codes. Nothing in this version reads them. See `RESOURCES.md` and #37.
- Encounters are not linked to a provider or clinician (#38); there is no
  insurance, cost or claim modelling (#39); there are no clinical notes (#43).
- `Death` states still ignore the time unit and read every quantity as years
  (#81).
- Generation costs roughly 3.6 s per patient across all modules (#71).

### Upgrade notes

- **Output changes completely again.** A seed does not reproduce a 1.1.0
  population. Pin an exact version for any dataset you need to regenerate.
- No change to the `synthea` command, its options, or the `Generator` /
  `GeneratorOptions` / `Person` API. Enabling `exporter.csv.export` or
  `exporter.ccda.export` now raises `NotImplementedError` at start-up instead of
  an `ImportError` or silence.

---

## [1.1.0] - 2026-09-19

The first release of the engine-correctness work. Four defects in the Generic
Module Framework (GMF) engine meant large parts of every bundled module were
silently doing nothing. Records generated by 1.0.1 were far sparser and far less
coherent than the modules describe.

### Fixed

- **All randomness now comes from the patient's own generator.**
  States, transitions and delays drew from the global `random` module, so a seed
  did not reproduce a patient and `--threads 4` produced a different population
  on every run. Record identifiers came from `uuid.uuid4()`, which reads system
  entropy, so even two sequential runs with the same seed differed byte for byte.
  Each patient's seed is now derived from `(population seed, index)`, making
  patient *N* identical however many patients ran before it.
  (#34, PR #79)

- **Delays did not delay.** `DelayState` read its duration from a nested `delay`
  key. Not one of the 534 Delay states in the bundled modules has one — they all
  put `exact` / `range` / `distribution` on the state itself. Every delay
  therefore resolved to zero, so a "wait five years before the next screening"
  step advanced a single timestep and disease progression ran at the speed of the
  simulation clock.
  (#27, PR #80)

- **Value distributions were ignored.** `Observation`, `VitalSign`, `Symptom`,
  `SetAttribute` and `Delay` understood only the `exact` and `range` forms.
  The `distribution` block (about 420 uses), `value_attribute`, the observation
  `attribute` and `vital_sign` sources and the `Symptom` probability gate were
  all dropped, so observations exported with no value. Observations carrying a
  value rose from 31% to 67% of those produced.
  (#27, PR #80)

- **Condition onsets were discarded.** `ConditionOnset` read `target_encounter`
  as the name of a person attribute; in GMF it names an Encounter *state*. The
  lookup always missed, so all 263 ConditionOnset states carrying a
  `target_encounter` recorded nothing, as did the 22 AllergyOnset states. Onsets
  occurring with no visit in progress were dropped too. Conditions recorded rose
  from 57 to 344 over 20 seeded patients.
  (#25, PR #82)

- **Nothing ever ended.** `ConditionEnd`, `MedicationEnd`, `CarePlanEnd`,
  `AllergyEnd` and `DeviceEnd` only resolved the `referenced_by_attribute` form;
  referring to the start state by name, or to the entry's codes, hit a `pass`
  stub. 250 end states did nothing, so chronic conditions never resolved,
  antibiotics never stopped and care plans ran forever.
  (#26, PR #83)

- **Parallel generation reported nothing and was needlessly slow.** Worker
  results were discarded, so `--threads N` always reported zero patients
  generated, and a whole `Generator` was pickled for every patient rather than
  built once per worker.
  (#34, PR #79)

### Added

- **Onset and diagnosis are now distinct events.** A condition is recorded when
  it starts and linked to the encounter that diagnoses it when that visit
  happens, so the record carries a true onset date that can precede the
  diagnosis date. Conditions whose diagnosing visit never occurs stay
  undiagnosed, as they would in life.
  (#25, PR #82)

- `synthea.engine.values` — one resolver for every GMF value form, with the
  distribution kinds the modules use (EXACT, UNIFORM, GAUSSIAN with optional
  `min`/`max` clamping, EXPONENTIAL) and the `round` flag.
- `synthea.helpers.rng` — `derive_seed`, `resolve_seed` and `random_seed` for
  reproducible seed derivation.
- `HealthRecord.attach`, `register_state_entry`, `find_by_state` and
  `find_by_codes` — finding record entries again by the state that created them
  or by their codes.
- 72 new tests (`test_determinism`, `test_values`, `test_diagnosis_timing`,
  `test_end_states`), bringing the suite to 126.

### Changed

- **Unsupported input now reports itself.** Unknown distribution kinds and time
  units log a warning once per process and fall back, instead of silently
  producing zero.
- `GeneratorOptions.end_date` defaults to `None` and resolves to
  `reference_date`. Previously both defaulted independently to "now", so setting
  only `reference_date` (as `GeneratorOptions.from_args` does) silently simulated
  to the present instead. Code that set `end_date` explicitly is unaffected.
- `ProviderManager` accepts a `seed` so clinician generation is reproducible and
  separate from the patient stream.
- `HealthRecord.condition_start` and `allergy_start` accept `attach`, controlling
  whether the entry links to the encounter in progress.

### Known limitations

Carried forward and tracked; none is a regression. See the
[M1 milestone](https://github.com/TIET-AI/tietai-synthea/milestone/1).

- No core lifecycle module. Patients have no names, addresses or identifiers,
  ages are drawn uniformly rather than from census data, and there is no growth,
  no vital signs and no natural mortality. (#30)
- `wellness: true` on an Encounter is ignored, so chronic-disease modules open
  their diagnosing encounter at the start of life rather than at a check-up. (#29)
- `VitalSign` states set a value on the patient but do not record an Observation,
  which is why observations sourced from vital signs still export without a
  value. (#32)
- Medication `prescription`, `administration` and `chronic` details are ignored,
  so MedicationRequests carry no dosage or refills. (#28)
- `ImagingStudy`, `Vaccine` and `Physiology` states are no-ops. (#33, #31)
- FHIR output is not yet valid R4 or US Core: encounter class codes, null
  fields, missing timezones, non-UCUM units, and only six resource types. (#35)
- The bundled provider, payer, cost, lookup-table and geography data described
  in `RESOURCES.md` is not all present, and enabling the CSV exporter raises an
  import error. (#36, #37)
- `Death` states ignore the time unit and read every quantity as years. (#81)
- Generation is roughly 3.6 s per patient across all modules now that delays
  hold patients for the modelled duration. The record lookup helpers scan the
  whole record on each call, which is quadratic in record size. (#71)

### Upgrade notes

- **Output changes completely.** Do not expect a seed to reproduce a 1.0.1
  population. Both the seed derivation and the resource identifiers changed, and
  the modules now produce substantially more of the record they describe.
- No change to the `synthea` command, its options, `synthea.properties`, or the
  `Generator` / `GeneratorOptions` / `Person` API beyond the `end_date` default
  noted above.

---

## [1.0.1] - 2026-07-06

### Fixed

- `-o` / `--output-dir` was ignored and output always went to `./output/`. (#21)
- The generator logged "Loaded 0 modules" despite 99 modules being available. (#22)

## [1.0.0]

Initial packaged release: Python-native Synthea engine, 99 bundled modules,
FHIR R4 and JSON export, published to PyPI as `tietai-synthea`.

[1.2.0]: https://github.com/TIET-AI/tietai-synthea/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/TIET-AI/tietai-synthea/compare/v1.0.1...v1.1.0
[1.0.1]: https://github.com/TIET-AI/tietai-synthea/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/TIET-AI/tietai-synthea/releases/tag/v1.0.0
