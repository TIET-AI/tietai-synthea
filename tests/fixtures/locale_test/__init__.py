"""A minimal locale pack, used to prove the interface is really pluggable.

Deliberately unlike the United States in every dimension the interface
exposes — name structure, address shape, identifier schemes, currency,
temperature unit, export profile — so a test can tell whether the engine is
reading the pack or falling back to its old hard-coded behaviour.

It is also the smallest worked example of what a real pack has to provide.
"""

from synthea.locale.base import CodingPreferences, IdentifierScheme, LocalePack

GIVEN = ['Ada', 'Grace', 'Alan', 'Edsger']
FIRST_SURNAME = ['Testonia', 'Fixtura']
SECOND_SURNAME = ['Verifica', 'Probata']


def assign_name(person):
    """Two surnames, to prove name structure is not assumed."""
    person.attributes['first_name'] = person.random.choice(GIVEN)
    person.attributes['last_name'] = (
        f"{person.random.choice(FIRST_SURNAME)} "
        f"{person.random.choice(SECOND_SURNAME)}"
    )
    person.attributes['name_language'] = 'testish'


def assign_address(person):
    """Street before number, and a four-digit postal code."""
    person.attributes['address'] = (
        f"Via Fixtura {person.random.randint(1, 99)}")
    person.attributes['postal_code'] = f"{person.random.randint(1000, 9999)}"


def assign_contact(person):
    person.attributes['telephone'] = f"+99 000 {person.random.randint(1000, 9999)}"
    person.attributes['email'] = (
        f"{person.attributes.get('first_name', 'x')}@example.org".lower())


def _national_id(person):
    """Always invalid by construction: a real one never ends in ZZ."""
    return f"TST{person.random.randint(10 ** 5, 10 ** 6 - 1)}ZZ"


PACK = LocalePack(
    code='test',
    name='Test Locale',
    country_code='TS',
    language='tt',
    currency='EUR',
    assign_name=assign_name,
    assign_address=assign_address,
    assign_contact=assign_contact,
    identifiers=(
        IdentifierScheme(
            key='identifier_national',
            type_code='NI',
            type_display='National unique individual identifier',
            system='urn:test:national-id',
            format=_national_id,
        ),
    ),
    marital_statuses=(('M', 'Married', 0.5), ('S', 'Never Married', 0.5)),
    # This locale does not record race, which is the common case worldwide.
    race_categories=(),
    ethnicity_categories=(),
    coding=CodingPreferences(additional_condition_systems=('ICD10',)),
    export_profile='ips',
    temperature_unit='Cel',
)
