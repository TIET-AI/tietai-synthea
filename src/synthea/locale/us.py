"""The United States reference pack.

This is the behaviour the generator had before locale packs existed, moved
behind the interface rather than rewritten. The draw order from
`person.random` is preserved exactly — name, address, contact, then
identifiers in the order SSN, MRN, driving licence, passport — because a
seeded run must produce the same population it did before, and a test asserts
that byte for byte.

If you are writing a pack for somewhere else, read this one: it is the worked
example the interface was designed against.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from synthea.locale import register
from synthea.locale.base import CodingPreferences, IdentifierScheme, LocalePack

if TYPE_CHECKING:  # pragma: no cover - typing only
    from synthea.world.person import Person


# ----------------------------------------------------------------------
# Identity
# ----------------------------------------------------------------------

def assign_name(person: 'Person') -> None:
    """Given name, family name, and sometimes a maiden name."""
    from synthea.world.identity import NameData

    gender = person.attributes.get('gender', 'F')
    ethnicity = person.attributes.get('ethnicity', '')
    language = NameData.language_for(ethnicity)

    given = NameData.given_names(language, gender)
    family = NameData.family_names(language)

    if given:
        person.attributes['first_name'] = person.random.choice(given)
    if family:
        person.attributes['last_name'] = person.random.choice(family)

    # A minority of adults have a maiden name recorded.
    if gender == 'F' and family and person.random.random() < 0.35:
        person.attributes['maiden_name'] = person.random.choice(family)

    person.attributes['name_language'] = language

    prefix = {'M': 'Mr.', 'F': 'Ms.'}.get(gender)
    if prefix:
        person.attributes['name_prefix'] = prefix


def assign_address(person: 'Person') -> None:
    """A street address in the American form: number, street, optional unit."""
    from synthea.world.identity import NameData

    types = NameData.street_types()
    families = NameData.family_names(
        person.attributes.get('name_language', 'english'))
    if not types or not families:
        return

    number = person.random.randint(1, 9999)
    street = f"{person.random.choice(families)} {person.random.choice(types)}"
    line = f"{number} {street}"

    # A minority of addresses carry a unit.
    secondary = NameData.secondary_types()
    if secondary and person.random.random() < 0.25:
        line += f" {person.random.choice(secondary)} {person.random.randint(1, 999)}"

    person.attributes['address'] = line


def assign_contact(person: 'Person') -> None:
    """Telephone and email, both in ranges that cannot reach a real person."""
    # 555 exchange numbers are reserved for fiction and cannot ring a real line.
    person.attributes['telephone'] = (
        f"555-{person.random.randint(100, 999)}-{person.random.randint(1000, 9999)}"
    )

    first = person.attributes.get('first_name', 'patient')
    last = person.attributes.get('last_name', 'unknown')
    # example.com is reserved by RFC 2606 and can never be registered.
    person.attributes['email'] = (
        f"{first}.{last}{person.random.randint(1, 999)}@example.com".lower()
    )


# ----------------------------------------------------------------------
# Identifiers, all in ranges that were never issued
# ----------------------------------------------------------------------

def _ssn(person: 'Person') -> str:
    # The SSA has never issued an area number of 999.
    return (f"999-{person.random.randint(10, 99)}"
            f"-{person.random.randint(1000, 9999)}")


def _mrn(person: 'Person') -> str:
    return str(person.random.randint(10 ** 6, 10 ** 7 - 1))


def _drivers(person: 'Person') -> str:
    return f"S{person.random.randint(10 ** 8, 10 ** 9 - 1)}"


def _passport(person: 'Person') -> str:
    return f"X{person.random.randint(10 ** 7, 10 ** 8 - 1)}X"


IDENTIFIERS = (
    IdentifierScheme(
        key='identifier_ssn',
        type_code='SS',
        type_display='Social Security Number',
        system='http://hl7.org/fhir/sid/us-ssn',
        format=_ssn,
    ),
    IdentifierScheme(
        key='identifier_mrn',
        type_code='MR',
        type_display='Medical Record Number',
        system='http://hospital.smarthealthit.org',
        format=_mrn,
    ),
    IdentifierScheme(
        key='identifier_drivers',
        type_code='DL',
        type_display="Driver's License",
        system='urn:oid:2.16.840.1.113883.4.3.25',
        format=_drivers,
        minimum_age=16,
    ),
    IdentifierScheme(
        key='identifier_passport',
        type_code='PPN',
        type_display='Passport Number',
        # What the exporter has always written. (Before the exporter read the
        # pack, this field said `http://hl7.org/fhir/sid/passport-USA` and
        # was never used.)
        system='http://standardhealthrecord.org/fhir/StructureDefinition/passportNumber',
        format=_passport,
        probability=0.42,
    ),
)


#: The bundled (and `synthea fetch-data facilities`) US facility directory,
#: and the facility type of each file. Order matters: it is the order the
#: facilities are indexed in, which a seeded run depends on.
US_FACILITY_FILES = {
    'providers/hospitals.csv': 'hospital',
    'providers/primary_care_facilities.csv': 'primary_care',
    'providers/primary_care_facilities_children.csv': 'primary_care',
    'providers/primary_care_facilities_women.csv': 'primary_care',
    'providers/urgent_care_facilities.csv': 'urgent_care',
    'providers/va_facilities.csv': 'hospital',
    'providers/ihs_facilities.csv': 'primary_care',
    'providers/ihs_centers.csv': 'primary_care',
    'providers/longterm.csv': 'longterm',
    'providers/nursing.csv': 'nursing',
    'providers/rehab.csv': 'rehab',
    'providers/hospice.csv': 'hospice',
    'providers/dialysis.csv': 'dialysis',
    'providers/home_health_agencies.csv': 'home_health',
    'providers/ambulatory_surgical_center.csv': 'surgical',
}

#: Rough adult shares, HL7 v3 MaritalStatus codes.
MARITAL_STATUS = (
    ('M', 'Married', 0.48),
    ('S', 'Never Married', 0.35),
    ('D', 'Divorced', 0.11),
    ('W', 'Widowed', 0.06),
)

#: The OMB categories the United States records, and US Core expects.
RACE_CATEGORIES = ('white', 'black', 'asian', 'native', 'other')
ETHNICITY_CATEGORIES = ('hispanic', 'non_hispanic')


PACK = LocalePack(
    code='us',
    name='United States',
    country_code='US',
    language='en',
    currency='USD',

    assign_name=assign_name,
    assign_address=assign_address,
    assign_contact=assign_contact,
    identifiers=IDENTIFIERS,
    # Drawn SSN first, but exported with the record number first, as every
    # earlier release did.
    identifier_export_order=('identifier_mrn', 'identifier_ssn',
                             'identifier_drivers', 'identifier_passport'),
    marital_statuses=MARITAL_STATUS,

    race_categories=RACE_CATEGORIES,
    ethnicity_categories=ETHNICITY_CATEGORIES,

    # The United States keeps the engine's built-in geography and national
    # age distribution. The bundled `geography/zipcodes.csv` and the
    # fetchable census `geography/demographics.csv` are in upstream Synthea's
    # formats, not the pack formats, and switching to them would change every
    # seeded US population; that is a deliberate future change, not a side
    # effect of wiring the interface.
    demographics_file=None,
    geography_file=None,
    providers_files=US_FACILITY_FILES,
    payers_file='payers/insurance_companies.csv',
    plans_file='payers/insurance_plans.csv',
    cost_files={
        'encounter': 'costs/encounters.csv',
        'procedure': 'costs/procedures.csv',
        'medication': 'costs/medications.csv',
        'immunization': 'costs/immunizations.csv',
        'device': 'costs/devices.csv',
        'supply': 'costs/supplies.csv',
    },

    coding=CodingPreferences(
        condition_system='SNOMED-CT',
        medication_system='RxNorm',
        observation_system='LOINC',
    ),

    export_profile='us-core',
    note_template='note.md.j2',
    # The only place in the world where a clinical note reports Fahrenheit.
    temperature_unit='[degF]',
)

register(PACK)
