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

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Sequence

if TYPE_CHECKING:  # pragma: no cover - typing only
    from synthea.world.person import Person


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

    format: Callable[['Person'], str]

    minimum_age: float = 0.0

    probability: float = 1.0
    """Share of eligible people who carry one. A passport is not universal."""

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
    geography_file: Optional[str] = None
    providers_files: Sequence[str] = ()
    payers_file: Optional[str] = None
    plans_file: Optional[str] = None
    cost_files: Dict[str, str] = field(default_factory=dict)

    resource_root: Optional[str] = None
    """Where this pack's data files live. None means the bundled resources."""

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
