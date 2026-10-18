"""What a locale pack has to provide.

The generator hard-coded United States assumptions throughout: English names,
a `999` social security area, `555` telephone exchanges, ZIP codes, OMB race
categories, USD costs and US Core profiles. None of that is wrong — it is the
reference locale — but it was not *separable*, so using the generator anywhere
else meant forking it.

A locale pack is the seam. The engine asks the pack questions it cannot answer
itself ("what is this person called", "what identifiers do they carry", "what
does a postal code look like here") and never encodes an answer of its own.

Two rules keep this honest:

1. **The engine must never branch on a locale code.** No `if locale == 'es'`.
   If behaviour differs by country, it belongs in the pack, not in a
   conditional. A branch is a fork that has not admitted it yet.
2. **A pack must not need engine changes to exist.** Packs are discovered
   through the `synthea.locales` entry point, so one can ship as a separate
   package on PyPI without this repository knowing it exists.

Everything here is data or small pure functions. A pack does not get to run the
simulation; it gets to answer questions about a place.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import (TYPE_CHECKING, Any, Callable, Dict, List, Mapping,
                    Optional, Sequence, Tuple, Union)

if TYPE_CHECKING:  # pragma: no cover - typing only
    import random

    from synthea.world.person import Person

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IdentifierScheme:
    """One kind of identifier a person carries in this locale.

    `format` is given a `Person` and returns the identifier's value. It must
    produce something that **cannot collide with a real identifier** — a
    never-issued range, a reserved prefix, or an invalid check character —
    because these records will end up in test systems next to real ones.

    `minimum_age` exists because some identifiers are not issued at birth (a
    driving licence, a national ID in some countries).
    """

    key: str
    """The person attribute it is stored under, e.g. `identifier_ssn`."""

    type_code: str
    """HL7 v2-0203 identifier type code, e.g. `SS`, `MR`, `DL`, `PPN`, `NI`."""

    type_display: str

    system: str
    """The URI that namespaces this identifier in FHIR."""

    format: Callable[['Person'], Optional[str]]
    """Returns the value, or None when this person does not carry one for a
    reason only the pack knows (a national identity number for nationals, a
    foreigner's number for foreigners)."""

    minimum_age: float = 0.0

    probability: float = 1.0
    """Share of eligible people who carry one. A passport is not universal."""

    type_system: str = 'http://terminology.hl7.org/CodeSystem/v2-0203'


@dataclass(frozen=True)
class PractitionerIdentifierScheme:
    """The identifier a clinician carries in this locale (the NPI in the US).

    `format` is given the facility's staffing generator, not a patient's: a
    facility's clinicians are created once, seeded from the facility, so the
    same practice always has the same people. Like a patient identifier it
    must produce values that **cannot collide with real ones**.
    """

    system: str
    """The URI that namespaces the identifier in FHIR."""

    format: Callable[['random.Random'], str]

    type_code: Optional[str] = None
    """Optional HL7 v2-0203 type, e.g. `PRN` (provider number). Omitted from
    the export when None."""

    type_display: Optional[str] = None
    type_system: str = 'http://terminology.hl7.org/CodeSystem/v2-0203'


@dataclass(frozen=True)
class CodingPreferences:
    """Which code systems this locale expects to see in a record.

    The bundled modules speak SNOMED CT, RxNorm and LOINC. A locale may need a
    national classification alongside them — CIE-10-ES in Spain, for instance —
    which is a *translation* of the same clinical fact, not a replacement. So
    `additional_condition_systems` adds codings to a Condition rather than
    replacing the SNOMED one.
    """

    condition_system: str = 'SNOMED-CT'
    medication_system: str = 'RxNorm'
    observation_system: str = 'LOINC'

    additional_condition_systems: Sequence[str] = ()
    additional_medication_systems: Sequence[str] = ()

    translate: Optional[Callable[[str, str, str], Optional[tuple]]] = None
    """`(system, code, target_system) -> (code, display)` or None.

    Called to find a local code for a clinical code. Returning None means "no
    mapping", which is normal and must not be treated as an error: a partial
    mapping table is better than none, and a missing translation should leave
    the original coding alone rather than dropping it.
    """


@dataclass(frozen=True)
class LocalePack:
    """Everything the engine needs to know about a place.

    A pack is data plus small pure functions. Anything that needs the patient's
    random generator takes the `Person` and draws from `person.random`, so a
    seeded run stays reproducible: the pack must never use the `random` module
    directly, or `--locale` would break determinism.
    """

    code: str
    """BCP 47-ish locale code: `us`, `es`, `es-CT`."""

    name: str
    """Human-readable, for `--list-locales`."""

    country_code: str
    """ISO 3166-1 alpha-2, used for `Address.country`."""

    language: str = 'en'
    """ISO 639-1, for `Patient.communication` and the note template."""

    currency: str = 'USD'
    """ISO 4217, for Money in claims."""

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------

    assign_name: Optional[Callable[['Person'], None]] = None
    """Set the person's name attributes.

    A function rather than name lists, because name *structure* is not
    universal: Spain uses two surnames, Iceland uses patronymics, and parts of
    the world do not split a name into given and family at all.
    """

    assign_address: Optional[Callable[['Person'], None]] = None
    assign_contact: Optional[Callable[['Person'], None]] = None

    identifiers: Sequence[IdentifierScheme] = ()

    marital_statuses: Sequence[tuple] = ()
    """`(code, display, share)`, using HL7 v3-MaritalStatus codes."""

    # ------------------------------------------------------------------
    # Population
    # ------------------------------------------------------------------

    race_categories: Sequence[str] = ()
    """The race categories this locale records, if it records race at all.

    Many countries do not, and an empty sequence means exactly that: the
    exporter omits the extension rather than inventing a category.
    """

    ethnicity_categories: Sequence[str] = ()

    # ------------------------------------------------------------------
    # Data files, relative to the pack's own resource root
    # ------------------------------------------------------------------

    demographics_file: Optional[str] = None
    """Population by region, sex and age band, which shapes who is generated.

    CSV with the header `region_code,region,sex,age_low,age_high,population`:
    one row per region, sex (`M`/`F`) and age band, `population` a count of
    people. An open-ended top band leaves `age_high` empty. Each patient's sex
    and age are drawn from the row weights of the region they live in
    (matched on `region_code` from the geography file). None keeps the
    built-in national age distribution."""

    geography_file: Optional[str] = None
    """Where patients live.

    CSV with the header
    `region,region_code,city,municipality,municipality_code,postal_codes,lat,lon,population`
    (plus optional `catchment` and `radius_km` columns): one row per
    municipality. Each patient draws a home municipality weighted by
    `population`, one of its `|`-separated `postal_codes`, and a point within
    `radius_km` (default 2) of `lat,lon`. `city` names the urban area the
    municipality belongs to, which is what `generate.geography.cities`
    selects; `catchment` (default: `city`) names the area whose facilities
    serve it. None keeps the built-in US geography."""

    providers_files: Union[Sequence[str], Mapping[str, str]] = ()
    """Facility files. They **replace** the bundled US directory.

    Either a sequence of paths, or a mapping of path to the facility type
    every row in that file has (`hospital`, `primary_care`, `urgent_care`,
    `nursing`, `hospice`, `home_health`, ...). A `facility_type` column in a
    row wins over the mapping. Optional columns: `catchment` (`|`-separated
    areas the facility serves; a patient in one of them is sent there in
    preference to anywhere else) and `clinicians` (how many to staff it with,
    overriding `generate.providers.clinicians_per_facility`). Empty means the
    bundled US directory."""

    payers_file: Optional[str] = None
    """Insurers, in the format of the bundled `payers/insurance_companies.csv`."""

    plans_file: Optional[str] = None
    """Plans, in the format of the bundled `payers/insurance_plans.csv`. A
    plan's `Eligibility Policy` is what a coverage policy selects it by."""

    cost_files: Dict[str, str] = field(default_factory=dict)
    """Cost table per kind (`encounter`, `medication`, `procedure`,
    `immunization`, `device`, `supply`), in the bundled `costs/` format. A kind
    the pack does not list uses the bundled table."""

    resource_root: Optional[str] = None
    """Where this pack's data files live. None means the bundled resources.

    A pack with its own root never silently falls back to the bundled (US)
    file of the same name: a missing file is reported and that data is
    treated as absent. The one exception is the note template, which is
    looked up in `<resource_root>/templates/notes/` first and the bundled
    templates second, so a pack only ships a template if it needs one."""

    # ------------------------------------------------------------------
    # Clinical and export conventions
    # ------------------------------------------------------------------

    coding: CodingPreferences = field(default_factory=CodingPreferences)

    export_profile: str = 'us-core'
    """The export profile this locale expects: `us-core`, `ips`, `ehds`, or
    `none`. Overridden by `exporter.fhir.profile` when that is set."""

    note_template: str = 'note.md.j2'
    """Template name, resolved against the pack's templates directory and then
    the bundled one, so a pack only ships a template if it needs a different
    language."""

    temperature_unit: str = 'Cel'
    """UCUM. `Cel` almost everywhere; `[degF]` in the US."""

    identifier_export_order: Sequence[str] = ()
    """Identifier keys in the order they appear on `Patient.identifier`.

    Empty means the order of `identifiers`. Separate because the order of
    `identifiers` is also the order of the random draws, which must not move
    just to reorder an export."""

    # ------------------------------------------------------------------
    # Care: who treats patients, and who pays
    # ------------------------------------------------------------------

    clinician_names: Optional[Callable[['random.Random'], Tuple[str, str]]] = None
    """`(rand) -> (given, family)` for a generated clinician, drawing from
    the facility's staffing generator. None uses the engine's name list."""

    clinician_specialties: Sequence[tuple] = ()
    """`(specialty, share)` for generated clinicians. Empty uses the
    engine's list."""

    practitioner_identifier: Optional[PractitionerIdentifierScheme] = None
    """The clinician identifier. None uses the engine default, an NPI in the
    never-issued `9999` range."""

    coverage_policy: Optional[Any] = None
    """Who is covered by what: a :class:`synthea.world.payer.CoveragePolicy`.

    None uses the engine default, which models United States eligibility
    (Medicare from 65, Medicaid or no cover on low income, otherwise a
    private plan). A national health system with universal cover uses
    :class:`synthea.world.payer.UniversalCoverage`."""

    produces_claims: bool = True
    """Whether care generates claims. A tax-funded national health system
    does not bill its patients' insurer per visit, so its records carry
    Coverage but no Claim or ExplanationOfBenefit."""

    # ------------------------------------------------------------------
    # Population rates
    # ------------------------------------------------------------------

    calibration: Mapping[str, Any] = field(default_factory=dict)
    """`calibration.*` settings that suit this locale's population.

    Applied over the bundled `synthea.properties` and under anything the user
    sets themselves (a `-c` file, or `Config.set`), so precedence is
    bundled < pack < user. Every value should cite its source in the pack."""

    # ------------------------------------------------------------------

    def identifier_for(self, person: 'Person', scheme: IdentifierScheme
                       ) -> Optional[str]:
        """The value of one identifier for this person, or None if they lack it.

        Age and probability are applied here rather than in each pack's format
        function, so a pack cannot forget them.
        """
        age = person.attributes.get('age_at_creation')
        if scheme.minimum_age and (age is None or age < scheme.minimum_age):
            return None

        if scheme.probability < 1.0 and person.random.random() >= scheme.probability:
            return None

        return scheme.format(person)

    def data_path(self, relative: Optional[str]) -> Optional[Path]:
        """Where one of this pack's data files is, or None if it is absent.

        Relative to `resource_root`; with no root, the bundled resources (and
        the `synthea fetch-data` cache, which takes precedence there). A pack
        that declares a file it does not ship gets a warning rather than the
        bundled file of the same name, because quietly substituting American
        data is the failure this interface exists to prevent.
        """
        if not relative:
            return None

        if self.resource_root:
            path = Path(self.resource_root) / relative
            if path.exists():
                return path
            logger.warning(
                "Locale pack %r declares %s, which is not in %s; that data is "
                "treated as absent.", self.code, relative, self.resource_root)
            return None

        from synthea.helpers.optional_data import cached_path
        from synthea.helpers.resources import resource_path

        cached = cached_path(relative)
        if cached is not None:
            return cached
        path = resource_path(relative)
        return path if path.exists() else None

    def templates_dirs(self, kind: str = 'notes') -> List[Path]:
        """Template directories to search, the pack's own first."""
        from synthea.helpers.resources import resource_path

        directories: List[Path] = []
        if self.resource_root:
            own = Path(self.resource_root) / 'templates' / kind
            if own.is_dir():
                directories.append(own)
        directories.append(resource_path('templates', kind))
        return directories

    def ordered_identifiers(self) -> List[IdentifierScheme]:
        """`identifiers` in export order (see `identifier_export_order`)."""
        if not self.identifier_export_order:
            return list(self.identifiers)
        by_key = {scheme.key: scheme for scheme in self.identifiers}
        ordered = [by_key[key] for key in self.identifier_export_order
                   if key in by_key]
        ordered += [scheme for scheme in self.identifiers
                    if scheme.key not in self.identifier_export_order]
        return ordered

    def describe(self) -> Dict[str, Any]:
        """A summary for `--list-locales`."""
        return {
            'code': self.code,
            'name': self.name,
            'country': self.country_code,
            'language': self.language,
            'currency': self.currency,
            'identifiers': [scheme.key for scheme in self.identifiers],
            'profile': self.export_profile,
        }
