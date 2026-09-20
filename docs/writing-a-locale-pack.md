# Writing a locale pack

The generator ships with one locale: the United States. Everything that is
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
have to remember them.

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
demographics_file='geography/demographics.csv',
providers_files=('providers/hospitals.csv',),
payers_file='payers/insurers.csv',
resource_root='/path/inside/your/package',
```

Record where each file came from, its version and its licence, in a
`RESOURCES.md` in your pack. This is a traceability requirement, not
bureaucracy: someone will eventually need to know whether your provider list
was allowed to be redistributed.

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
