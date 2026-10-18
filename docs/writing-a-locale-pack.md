# Writing a locale pack

The generator ships with two locales: the United States (`us`, the reference
pack) and Spain (`es`, `src/synthea/locale/es.py`). Everything that is
specific to a country — names, addresses, identifiers, coverage, currency,
coding conventions, the language a note is written in — lives in a **locale
pack**, so using the generator somewhere else does not mean forking it.

This guide is for someone adding a country. It assumes you can read Python and
know roughly how records look where you are.

## The two rules

**The engine never branches on a locale code.** There is no `if locale == 'es'`
anywhere, and there must never be. If behaviour differs by country, it belongs
in a pack. A branch is a fork that has not admitted it yet.

**A pack must not need engine changes to exist.** Packs are discovered through
the `synthea.locales` entry point, so yours can live in its own repository and
ship to PyPI without this project knowing about it.

If you find yourself wanting to change the engine to make your pack work, that
is a gap in the interface — please open an issue rather than working around it,
because the next pack will hit the same wall.

## The smallest possible pack

```python
from synthea.locale.base import IdentifierScheme, LocalePack


def assign_name(person):
    person.attributes['first_name'] = person.random.choice(GIVEN_NAMES)
    person.attributes['last_name'] = person.random.choice(SURNAMES)


PACK = LocalePack(
    code='xx',
    name='Examplia',
    country_code='XX',
    language='xx',
    currency='EUR',
    assign_name=assign_name,
)
```

Register it in your `pyproject.toml`:

```toml
[project.entry-points."synthea.locales"]
xx = "synthea_locale_xx:PACK"
```

Then `synthea --list-locales` will show it, and `synthea --locale xx` will use
it. The entry point may point at a `LocalePack` or at a callable returning one.

## Draws must come from the patient

Every random choice must come from `person.random`, never from the `random`
module:

```python
# Right: reproducible from the seed
person.random.choice(SURNAMES)

# Wrong: breaks --seed, silently
random.choice(SURNAMES)
```

A seeded run is a promise the project makes. Using the global module means two
runs of the same seed produce different people, and nothing will tell you — the
output still looks fine.

## What to fill in, roughly in order of impact

### Names

`assign_name` is a function, not a list of names, because **name structure is
not universal**. Spain uses two surnames. Iceland uses patronymics. Some
cultures do not split a name into given and family at all. A pack that only
needed name *lists* would quietly force every country into the American shape.

Set `first_name` and `last_name` at minimum; add `maiden_name`, `name_prefix`
or anything else your locale records.

### Identifiers

```python
IdentifierScheme(
    key='identifier_national',
    type_code='NI',                    # HL7 v2-0203
    type_display='National unique individual identifier',
    system='urn:oid:1.2.3.4',          # namespaces it in FHIR
    format=lambda person: ...,
    minimum_age=16,                    # not issued at birth
    probability=0.42,                  # not everyone has one
)
```

**Your `format` must produce identifiers that cannot collide with real ones.**
This matters more than it sounds: generated records end up in test systems next
to real ones, and an identifier that could belong to a real person is a hazard,
not a detail.

Use whatever your country's equivalent of "never issued" is:

- a number range the authority has never allocated (the US pack uses social
  security area `999`)
- a reserved prefix
- a deliberately **invalid check character** — the cleanest option where the
  identifier has a checksum, because validation will reject it everywhere

Age and probability are applied by the interface, so your `format` does not
have to remember them. `format` may return `None` when a person does not carry
the identifier for a reason only your pack knows - the Spanish pack issues a
DNI to nationals and an NIE to foreign nationals, deciding nationality in
`assign_name`.

Every scheme is exported on `Patient.identifier` with its `type_code`,
`type_display`, `type_system` and `system`. The order of `identifiers` is the
order of the random draws; if you want a different order on the Patient, set
`identifier_export_order` to the keys in that order rather than reordering the
schemes (which would change every seeded population).

Use an official identifier system URI only where one exists. Where none does,
use a URN that is plainly synthetic (the Spanish pack uses
`urn:tietai:synthea:es:<name>`) - never invent an official-looking OID.

### Race and ethnicity

```python
race_categories=(),        # this locale does not record race
```

Most countries do not record race, and the exporter omits the extension when
the list is empty. Leave it empty rather than mapping your population onto
American categories — that would be inventing data, and it is the kind of
invention that looks authoritative in an export.

### Coding

Modules speak SNOMED CT, RxNorm and LOINC. If your locale needs a national
classification too:

```python
coding=CodingPreferences(
    additional_condition_systems=('CIE10-ES',),
    translate=my_lookup,   # (system, code, target) -> (code, display) | None
)
```

A local code is a *translation* of the same clinical fact, so it is added
alongside the SNOMED coding rather than replacing it. Returning `None` from
`translate` is normal and must not be treated as an error: a partial mapping
table is better than none, and a missing translation leaves the original coding
alone rather than dropping it.

### Data files

```python
geography_file='geography.csv',
demographics_file='population_by_age_sex.csv',
providers_files={'providers/hospitals.csv': 'hospital'},
payers_file='payers/insurers.csv',
plans_file='payers/plans.csv',
cost_files={'encounter': 'costs/encounters.csv'},
resource_root=str(Path(__file__).parent / 'data'),
```

Paths are relative to `resource_root`. With no root the bundled resources are
used. **A pack with a root never silently falls back to the bundled (US) file
of the same name**: a declared file that is missing is a warning, and that
data is treated as absent. `LocalePack.data_path(relative)` is the resolver
the engine uses; use it in your own code too.

Record where each file came from, its version and its licence, in a
`RESOURCES.md` in your pack. This is a traceability requirement, not
bureaucracy: someone will eventually need to know whether your provider list
was allowed to be redistributed.

#### Geography - where patients live

A CSV, one row per municipality:

```
region,region_code,city,municipality,municipality_code,postal_codes,lat,lon,population
Madrid,28,Madrid,Getafe,28065,28901|28902|28903|28904|28905|28906|28907,40.30,-3.73,189063
```

Each patient draws a municipality weighted by `population`, one of its
`|`-separated `postal_codes`, and a home uniformly within `radius_km` (optional
column, default 2) of `lat,lon`. The patient's attributes become `state`
(= `region`), `region_code`, `city` (= `municipality`), `municipality_code`,
`urban_area` (= `city`), `catchment_area` (optional `catchment` column, default
`city`), `zip_code`, `latitude` and `longitude`.

Users narrow it, for any pack, with:

```properties
generate.geography.cities = Madrid, Barcelona   # urban areas or municipalities
generate.geography.regions = 28                 # region names or codes
```

`--state`/`--city` (and `generate.geography.state`/`.city`) select a region and
a city the same way. Matching ignores case and accents. An unknown name is a
warning that lists what is known; it never silently means "everywhere".

Without a geography file the built-in US geography is used (the US pack does
this, to keep its seeded output stable).

#### Demographics - who lives there

A CSV of population counts by region, sex and age band:

```
region_code,region,sex,age_low,age_high,population
28,Madrid,F,0,4,123456
28,Madrid,F,100,,1234
```

`region_code` matches the geography file. Leave `age_high` empty for an
open-ended top band (it is read as five years wide). Sex is drawn from the
region's totals, the band from that sex's counts, and the year uniformly
within the band; because of that, a pack geography draws the home first and
the age and sex second.

#### Race and ethnicity

With `race_categories=()` no race or ethnicity is drawn at all: the attributes
are absent, modules' `Race` conditions are false, the cardiovascular risk
model uses its non-Black column, and neither notes nor exports mention race.

#### Facilities and clinicians

`providers_files` **replaces** the bundled US directory. Give it a mapping of
file to facility type, or a list of files whose rows carry a `facility_type`
column (a row's column wins over the mapping). Types are those encounters ask
for: `hospital`, `primary_care`, `urgent_care`, `nursing`, `longterm`,
`hospice`, `home_health`, ... An encounter whose preferred types are absent
falls back along `ENCOUNTER_PROVIDER_TYPES` and finally to any facility, so a
pack with only hospitals sends every encounter class to a hospital.

Columns the loader reads: `id`, `name`, `address`, `city`, `state`, `zip`,
`lat`, `lon`, `phone`, `bed_count`, and two optional ones:

- `catchment` - `|`-separated areas the facility serves. A patient whose
  `catchment_area` is listed is sent there in preference to any other
  facility of the type, which is how a public health system's assigned
  hospital works;
- `clinicians` - how many clinicians to staff it with. Otherwise
  `generate.providers.clinicians_per_facility` (default 4).

Clinicians come from the pack too: `clinician_names` (`rand -> (given,
family)`, drawing from the facility's staffing generator),
`clinician_specialties` (`(name, share)`), and `practitioner_identifier`, a
`PractitionerIdentifierScheme(system, format, type_code, type_display)` that
replaces the US NPI. Its values must be unissuable, like a patient's.

#### Coverage and claims

`coverage_policy` decides who is covered by what. It is a
`synthea.world.payer.CoveragePolicy` with two methods: `kind_for(manager,
person, age)` and `coverage_for(manager, person, age, time, kind)`. The
default, `UnitedStatesCoverage`, is Medicare from 65, Medicaid or no cover on
low income, otherwise a private plan. A national health system uses
`UniversalCoverage(eligibility='SNS', kind='public')`, which covers everyone
from birth with the plans whose `Eligibility Policy` is `SNS`.

`produces_claims=False` says the health system does not bill per visit: the
export carries Coverage (in IPS/EHDS, under the Payers section) but no Claim or
ExplanationOfBenefit. Where claims are produced, Money is in `currency`.

#### Population rates

```python
calibration={'calibration.reproduction.exposure': 0.2},
```

`calibration.*` defaults that suit your population. They apply over the
bundled `synthea.properties` and under anything the user sets (their `-c`
file or `Config.set`): bundled < pack < user. Cite the source of every value
and record how it was measured.

#### Notes

`note_template` is looked up in `<resource_root>/templates/notes/` first and
the bundled templates second. The template receives the bundled English
sentences and also `patient`, the facts behind them (`first_name`, `sex`,
`age_years`, `age_months`, `race`, `ethnicity` - None where the locale does not
record race - `active_conditions`, `marital_status`, `smoker`,
`quit_smoking_age`, `alcoholic`, `socioeconomic_status`, `education`,
`insurer`), so a template in another language can phrase them itself. Clinical
displays come from the codes and stay in the terminology's language.

#### Export conventions

`country_code` is `Address.country` for patients and facilities; a pack that
sets the `postal_code` attribute in `assign_address` overrides the geography's
postal code. `language` is `Patient.communication` when the name language has
no entry in `language_lookup.json`. The US Core DocumentReference category is
only written when the export profile is US Core.

## Testing your pack

`tests/fixtures/locale_test` is a deliberately un-American pack — two
surnames, a different identifier scheme, EUR, Celsius, IPS export — used to
prove the engine reads the pack rather than falling back to hard-coded
behaviour. Copy it as a starting point.

The test worth stealing is the determinism one: generate a population twice
with the same seed and assert the exports are identical. If your pack uses the
global `random` anywhere, that test fails immediately; without it, you may not
notice for months.

## Checking your work

```bash
synthea --list-locales
synthea -p 10 --locale xx -o ./out
synthea -p 10 --locale es -o ./out-es
```

Then read a generated note and a bundle. The things most often wrong on a first
pass:

- names that are plausible individually but never co-occur in reality
- identifiers that would pass real validation
- an address format borrowed from the US pack
- a currency that does not match the cost tables

## Getting it merged, if you want it in-tree

Packs for countries the project supports directly live in
`src/synthea/locale/`. Branch from `dev`, and include the provenance of every
data file. If the pack is large, or its data has licence terms that do not suit
this repository, keeping it as a separate distribution is a perfectly good
outcome — the entry point exists precisely so that works.
