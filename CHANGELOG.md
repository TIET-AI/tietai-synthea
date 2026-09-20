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

## [1.4.0] - 2026-09-20

The generator stops being American by construction. Localisation is a pluggable
pack, export profiling is selectable, and the configuration file does what it
says.

**A seed reproduces a 1.3.0 population exactly.** This is the first release
where that is true — every earlier one changed generated output. Verified by
comparing the SHA-256 of every bundle from a seeded run against v1.3.0.

### Added

- **Pluggable locale packs** (#45). Everything country-specific — names,
  addresses, identifiers, coverage, currency, coding conventions, note
  language — now lives in a locale pack, so using the generator outside the
  United States no longer means forking it.

  ```
  synthea --list-locales
  synthea -p 100 --locale us
  ```

  Two rules keep the seam honest, and both are enforced by test: **the engine
  never branches on a locale code**, and **a pack needs no engine change to
  exist**. Packs are discovered through the `synthea.locales` entry point, so
  one can ship to PyPI independently of this project.

  The United States is the reference pack and still the only one. Identity,
  identifiers and conventions read from the pack; demographics, providers,
  payers, costs and the export profile are the next migration. Spain is #46.

  `docs/writing-a-locale-pack.md` is the developer guide.

  Two interface decisions a reader will otherwise ask about. Names come from a
  *function*, not name lists, because name structure is not universal — Spain
  uses two surnames, Iceland uses patronymics, and some cultures do not split a
  name into given and family at all; a list-based interface would have quietly
  forced every country into the American shape. And an empty `race_categories`
  means *this locale does not record race*, which is the common case worldwide;
  the exporter omits the extension rather than mapping a population onto OMB
  categories, which would be inventing data that then looks authoritative.

- **Selectable export profiles** (#47). Profiling was a single boolean,
  `exporter.fhir.use_us_core_ig`. There are now four:

  | | |
  |---|---|
  | `us-core` | the default, and what every previous release produced |
  | `ips` | International Patient Summary: one Composition-led document |
  | `ehds` | EHDS priority categories: one document per category |
  | `none` | valid R4 with no profile claims |

  ```
  synthea -p 100 --profile ips
  ```

  Selection is by specificity: `exporter.fhir.profile`, else the locale pack's
  default, else US Core. A Spanish locale should produce IPS without the
  operator having to know to ask, but an operator who does ask wins.

  **Required IPS sections are emitted even when empty**, carrying `nilknown`
  and "No known allergies". An absent allergies section means "we did not
  look", which is a different and more dangerous thing to tell a clinician
  than "none known". Optional sections are still omitted.

  An empty EHDS category produces no document at all — an empty discharge
  report is noise, not a document. Every document's references are closed over
  its own bundle, so it stands alone for whoever receives it.

- **`synthea --list-locales`** and **`--locale`**, **`--profile`**.

### Fixed

- **Nine configuration keys were recognised, accepted without error, and read
  by nothing** (#106). Setting `exporter.only_living = true` got you deceased
  patients anyway, with no warning. Silence is the worst of the three possible
  behaviours: worse than working, and worse than refusing.

  Now working: `generate.geography.state` / `.city` /
  `.use_demographics`, `generate.modules.enabled` / `.disabled`,
  `generate.reference_year`, `exporter.only_living`, and
  `exporter.fhir.server_url` (which now really posts bundles, with failures
  logged rather than fatal — a long generation should not be lost because a
  server went away).

  A city without a state is ignored with a warning, because city names are not
  unique across states. Core lifecycle modules survive a module filter, or
  patients would lose their identity, growth and vital signs. A filter that
  matches nothing warns rather than silently producing patients with no
  disease — that is a typo, not an instruction.

- **Race and ethnicity extensions no longer depend on the profile alone.** Both
  the profile and the locale must want them, so a locale that records no race
  emits none.

### Changed

- `exporter.fhir.use_us_core_ig = false` now resolves to the `none` profile.
  It means what it always meant; existing configuration files keep working.
- The shipped `synthea.properties` documents every key that works, so the file
  is the reference rather than the wiki.

### Known limitations

Unchanged from 1.3.0 except where noted.

- **The United States is still the only locale pack.** The architecture exists;
  adding a country is now writing a pack rather than forking the generator, but
  nobody has written one yet (#46).
- Demographics, providers, payers and costs still read their bundled files
  directly rather than through the pack. That is the next migration.
- `exporter.append_mode` is still inert. It only means something with a CSV
  exporter (#42).
- **`SupplyDelivery` still never appears** — no bundled module reaches a
  `SupplyList` state (#101).
- The population is still plausible rather than calibrated: mortality is a
  fitted hazard, not a life table, and obesity is under-represented (#55, #56).
- No NDJSON bulk export (#41), no CSV exporter (#42), no module coverage
  report (#44).

### Upgrade notes

- **Output does not change.** A 1.3.0 seed reproduces the same population, for
  the first time in this project's history. If you pinned 1.3.0 to keep a
  dataset reproducible, you can move to 1.4.0 without regenerating.
- No change to the `synthea` command's existing options or the `Generator` /
  `GeneratorOptions` / `Person` API. `--locale`, `--list-locales` and
  `--profile` are new.
- If you set any of the nine configuration keys above expecting them to work,
  **they now do** — which may change your output. That is the point, but it is
  a behaviour change worth knowing about before you run a large job.

---

## [1.3.0] - 2026-09-20

Records now say **where care happened, who gave it, who paid for it, and what
the clinician wrote**. 1.2.0 gave patients an identity and a body; this gives
the record around them.

A generated bundle carries 23 resource types, against 9 the 1.2.0 exporter
could emit.

Five of the eight [M2 milestone](https://github.com/TIET-AI/tietai-synthea/milestone/2)
tickets are closed (#37, #38, #39, #40, #43).

Measured on a 10-patient run, ages 0–90:

| | |
|---|---|
| resource types | 23 |
| encounters | 416 |
| clinical notes | 416, none empty |
| claims / EOBs | 416 / 416 |
| dangling references | 0 |
| FHIR validation issues | 0 |
| JSON nulls | 0 |

### Added

- **Real facilities and clinicians on every encounter** (#38, #37). Encounters
  had no provider at all: the manager looked for facility data that was never
  bundled, fell back to three hard-coded clinics, and no encounter ever
  referenced them. A record could not answer the most basic question asked of
  it — where did this happen, and who saw the patient.

  50,000 real facilities now ship (8.5 MB; the wheel goes from 2.0 MB to
  5.2 MB). A patient keeps one primary care practice and largely one clinician;
  other encounters go to the nearest facility of the type they need, because a
  random facility per encounter produces a history that looks nothing like a
  real patient's. Bundles carry `Organization`, `Location`, `Practitioner` and
  `PractitionerRole`.

  The rest — nursing, rehabilitation, home health, dialysis, hospice, surgical
  centres and 45 MB of census data — is fetched on request:

  ```
  synthea fetch-data --list
  synthea fetch-data facilities
  ```

  Loaders read the cache first and fall back to what is bundled, so a run works
  without the download and improves with it. **Nothing downloads implicitly**:
  generating patients never reaches the network, and a test asserts it by
  making `urlopen` raise during a run.

- **Insurance, costs and claims** (#39). The payer and cost tables had shipped
  since 1.2.0 and nothing read them: every patient was uninsured and every
  encounter free. Patients now hold coverage across a lifetime, care is priced
  from the bundled cost tables with a triangular draw over the published
  low/mode/high, and the cost is split between payer and patient **at the time
  of care** rather than at export. Bundles carry `Coverage`, `Claim`,
  `ExplanationOfBenefit` and an `Organization` per insurer.

  Eligibility is deliberately simplified — age and socioeconomic status, not
  means testing — and says so at the point of use. Doing it properly is #55.
  The resulting payer mix (private 75% / Medicaid 20% / Medicare 5%) is
  asserted against bounds by test so the simplification cannot drift unnoticed.

- **Clinical notes** (#43). `templates/notes/note.ftl` shipped from the Java
  port and was never used, so records had no free text at all. It is ported to
  Jinja2, and every finished encounter now has a note: chief complaint, history
  of present illness, social history, allergies, medications, vitals, and an
  assessment and plan.

  Notes export as a `DocumentReference` (base64 `text/plain`, category
  `clinical-note`, linked to its encounter) and, with `exporter.text.export`,
  as one text file per patient. `generate.clinical_notes` defaults to **true**;
  `exporter.text.export` used to raise `NotImplementedError` and now works.

  `notes.set_post_processor` is the seam for an external service to rewrite
  notes in a clinician's voice. Nothing in this package calls out to one.

- **The rest of the record** (#40). The model had held allergies, care plans,
  reports, devices and supplies since the port, and the exporter emitted none
  of them. Adds `AllergyIntolerance`, `CarePlan`, `Goal`, `CareTeam`,
  `DiagnosticReport`, `Device`, `SupplyDelivery` and a run-level `Provenance`.

  Resource ordering is now part of the contract: a transaction bundle is
  applied in order, so goals and the care team are emitted before the CarePlan
  that references them, reports after their Observations, and the Provenance
  last because it targets everything else.

  Device UDIs are derived from the record's own id — stable across a run, built
  from synthetic parts only, so they cannot collide with a registered UDI.
  `Provenance` records that the data was generated and by what version, so a
  consumer mixing synthetic and real data can tell them apart **from the record
  itself** rather than from where the file came from.

### Fixed

- **Timed deaths were wrong by orders of magnitude, and cut lives short**
  (#81). The `Death` state ignored the time unit and multiplied every quantity
  by 365, so `{"quantity": 1, "unit": "days"}` scheduled death a year out; 29
  of the 35 `Death` states carrying a delay use months, days, weeks or hours.
  A scheduled death also killed the patient immediately, so a module saying
  "expected lifespan 4 to 10 years" ended the simulation on the spot and the
  years of care in between were never generated. Death is now scheduled and
  carried out when it arrives, earliest schedule winning.

- **Record lookups were quadratic** (#71). `has_active_condition`,
  `has_active_medication`, `has_active_careplan` and `get_latest_observation`
  each scanned the whole record, and the logic engine calls them on every
  timestep for every module — so cost grew with the square of the record size,
  and 1.2.0 had made records far larger. Entries are now indexed by code as
  they start and removed as they end. 6 patients aged 40–85: **24.10 →
  14.76 s/patient**.

- **Lookup-table matching was 88% of the cost of generating a patient** (#71).
  `LookupTableTransition` re-read every cell of every candidate row on every
  lookup — stripping, splitting on `-`, calling `float` — for a few hundred
  rows, once per module per timestep. Tables are compiled once now. A profiled
  3-patient run went **221s → 29.8s**, a 7.4× speedup; the test suite dropped
  from 305s to 200s.

  Equivalence is not assumed: 30 differential tests check the compiled matcher
  against an unoptimised reference implementation of the same rules, and a
  sweep of all 70 shipped tables (2800 lookups, randomised patients) found zero
  disagreements.

- **`time` selectors threw for any patient born before 1970 on Windows.** The
  matcher called `time.timestamp()`, which raises `OSError` for pre-epoch dates
  there. The COVID-19 modules stratify by epoch-millisecond windows, so every
  timestep of every such patient was throwing and being swallowed as a module
  warning.

- **Coverage churned about 65 times per lifetime.** The annual plan-switch
  check ran on every timestep rather than once a year. Median is now 2 periods
  per patient.

- **`Claim` and `ExplanationOfBenefit` referenced a `Coverage` that was not in
  the bundle** when a patient had priced care and no coverage history. A FHIR
  server would reject the bundle, or accept it with a reference that silently
  does not resolve. A self-pay `Coverage` is emitted for that case.

- **`Provenance.recorded` used wall-clock time**, which broke export
  reproducibility: two runs of the same seed produced different bundles. It
  takes the latest time in the patient's own record.

- **Jinja's `trim_blocks` silently joined list items** that ended in a block
  tag, so every list in a note rendered as one run-on line.

- **A patient on their first birthday was written up as eleven months old.**
  `age_at` divides days by 365.25, giving 0.9993 years; the note uses calendar
  arithmetic.

### Changed

- `generate.clinical_notes` now defaults to `true` (was `false`).
- `exporter.text.export` is implemented; setting it no longer raises.
- The wheel grows from 2.0 MB to 5.2 MB with the bundled facility data.
- Bundles hold substantially more resources per patient, so exported files are
  larger.

### Known limitations

- **`SupplyDelivery` never appears in a generated run.** No bundled module
  reaches a `SupplyList` state — instrumented across 20 patients, entered zero
  times — and its predecessor states are not reached either, which means whole
  branches of eleven modules never execute. The builder is implemented and
  tested directly. Tracked as #101; it belongs with the module-coverage work in
  #44.
- **`Goal` needs a population of roughly 20 to appear**, because few modules
  attach goals to a care plan.
- Insurance eligibility is age and socioeconomic status, not means testing
  (#55). Adjudication takes a copay then coinsurance; it does not run a
  deductible down over the plan year or stop at an out-of-pocket maximum.
- **Mortality is still a fitted parametric hazard, not a published life table**
  (#55), and **obesity is still under-represented** — mean adult BMI 27.2
  against a real 29.7, 17% obese against 42% (#55, #56). Unchanged from 1.2.0.
- No NDJSON bulk export (#41), no CSV exporter (#42), no population statistics
  or module coverage report (#44).
- 45 MB of census data is still not bundled; see `RESOURCES.md` and
  `synthea fetch-data --list`.
- Generation costs roughly 3.7 s per patient across all modules for ages 0–90,
  including the expanded export (#71).

### Upgrade notes

- **Output changes again.** A seed does not reproduce a 1.2.0 population, and
  bundles carry many more resources. Pin an exact version for any dataset you
  need to regenerate.
- **Notes are on by default.** Set `generate.clinical_notes = false` if you do
  not want `DocumentReference` resources in your bundles.
- No change to the `synthea` command's existing options or the `Generator` /
  `GeneratorOptions` / `Person` API. `synthea fetch-data` is new.
  `exporter.csv.export` and `exporter.ccda.export` still raise
  `NotImplementedError` at start-up.

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

[1.4.0]: https://github.com/TIET-AI/tietai-synthea/compare/v1.3.0...v1.4.0
[1.3.0]: https://github.com/TIET-AI/tietai-synthea/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/TIET-AI/tietai-synthea/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/TIET-AI/tietai-synthea/compare/v1.0.1...v1.1.0
[1.0.1]: https://github.com/TIET-AI/tietai-synthea/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/TIET-AI/tietai-synthea/releases/tag/v1.0.0
