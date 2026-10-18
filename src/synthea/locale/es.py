"""Spain (`es`).

Patients live in seven urban areas - Madrid, Barcelona, Valencia, Bilbao,
Sevilla, Málaga and Santiago de Compostela - in proportion to the official
municipal population, with each province's own age and sex structure, and
receive all of their care at one fictional public hospital per city, covered
by the Sistema Nacional de Salud.

Everything here is data from the pack's own resource directory
(`synthea/resources/locale/es/`, provenance in its `RESOURCES.md`) plus small
functions that draw from `person.random`. Nothing in the engine knows this
pack exists.

**Identifiers cannot belong to a real person.** DNI and NIE numbers carry a
deliberately wrong check letter, the health card code a prefix no health
service issues, the Social Security number wrong control digits, and the
practitioner number a province code that does not exist. See
:func:`dni_letter` for the algorithm the check letters are made to fail.
"""

from __future__ import annotations

import csv
import unicodedata
from functools import lru_cache
from typing import TYPE_CHECKING, Dict, List, Optional, Sequence, Tuple

from synthea.helpers.resources import resource_path
from synthea.locale import register
from synthea.locale.base import (CodingPreferences, IdentifierScheme,
                                 LocalePack, PractitionerIdentifierScheme)
from synthea.world.payer import UniversalCoverage

if TYPE_CHECKING:  # pragma: no cover - typing only
    import random

    from synthea.world.person import Person

#: Where this pack's data lives, inside the installed package.
RESOURCE_ROOT = resource_path('locale', 'es')

#: Namespace for identifier systems that have no official FHIR URI. These
#: identifiers are synthetic by construction, so they are deliberately not
#: given an official-looking OID.
SYSTEM_PREFIX = 'urn:tietai:synthea:es:'


# ----------------------------------------------------------------------
# Data
# ----------------------------------------------------------------------

def _rows(name: str) -> List[Dict[str, str]]:
    with open(RESOURCE_ROOT / name, 'r', encoding='utf-8-sig', newline='') as handle:
        return list(csv.DictReader(handle))


@lru_cache(maxsize=None)
def _given_names(sex: str) -> Tuple[Tuple[str, ...], Tuple[float, ...]]:
    rows = _rows('names/given_names_male.csv' if sex == 'M'
                 else 'names/given_names_female.csv')
    return (tuple(row['name'] for row in rows),
            tuple(float(row['frequency']) for row in rows))


@lru_cache(maxsize=None)
def _surnames() -> Tuple[Tuple[str, ...], Tuple[float, ...], Tuple[float, ...]]:
    rows = _rows('names/surnames.csv')
    return (tuple(row['surname'] for row in rows),
            tuple(float(row['first_frequency']) for row in rows),
            tuple(float(row['second_frequency']) for row in rows))


@lru_cache(maxsize=None)
def _foreign_share() -> Dict[str, float]:
    """Share of residents with a foreign nationality, by province code."""
    shares = {}
    for row in _rows('nationality.csv'):
        total = float(row['total'])
        if total > 0:
            shares[row['region_code'].strip()] = float(row['foreign']) / total
    return shares


def _marital_statuses() -> Tuple[tuple, ...]:
    return tuple((row['code'], row['display'], float(row['share']))
                 for row in _rows('marital_status.csv'))


# ----------------------------------------------------------------------
# Identity
# ----------------------------------------------------------------------

def _weighted(rand: 'random.Random', items: Sequence[str],
              weights: Sequence[float]) -> str:
    return rand.choices(items, weights=weights)[0]


def _two_surnames(rand: 'random.Random') -> str:
    """First and second surname, each drawn from its own INE frequency."""
    names, first, second = _surnames()
    return f"{_weighted(rand, names, first)} {_weighted(rand, names, second)}"


def assign_name(person: 'Person') -> None:
    """Nationality, a given name and two surnames.

    Nationality is drawn here, first, because it decides which identity
    document the person carries (DNI or NIE). Draws: nationality, given
    name, first surname, second surname.
    """
    share = _foreign_share()
    region = str(person.attributes.get('region_code', ''))
    foreign_share = share.get(region, share.get('00', 0.0))
    person.attributes['foreign_national'] = person.random.random() < foreign_share

    sex = 'M' if person.attributes.get('gender') == 'M' else 'F'
    names, weights = _given_names(sex)
    person.attributes['first_name'] = _weighted(person.random, names, weights)
    person.attributes['last_name'] = _two_surnames(person.random)
    person.attributes['name_language'] = 'spanish'


#: Street types and how often each is used here. Illustrative weights for
#: formatting variety, not a statistic.
STREET_TYPES = (('Calle', 0.70), ('Avenida', 0.15), ('Plaza', 0.08),
                ('Paseo', 0.05), ('Camino', 0.02))

#: Door designations in a block of flats. Formatting variety, not a statistic.
DOORS = ('A', 'B', 'C', 'D', 'Izda.', 'Dcha.')


def assign_address(person: 'Person') -> None:
    """A Spanish street address: `Calle de Gómez, 23, 4.º B`.

    The street is named after a surname, so it reads like a Spanish street
    without being any particular real one. Most urban homes are flats, so a
    floor and door usually follow the number.
    """
    kinds = [kind for kind, _ in STREET_TYPES]
    weights = [share for _, share in STREET_TYPES]
    kind = person.random.choices(kinds, weights=weights)[0]
    names, first, _ = _surnames()
    street = _weighted(person.random, names, first)
    number = person.random.randint(1, 199)
    line = f"{kind} de {street}, {number}"
    if person.random.random() < 0.75:
        floor = person.random.randint(1, 10)
        door = person.random.choice(DOORS)
        line += f", {floor}.º {door}"
    person.attributes['address'] = line


def _ascii(text: str) -> str:
    decomposed = unicodedata.normalize('NFKD', text)
    return ''.join(ch for ch in decomposed
                   if not unicodedata.combining(ch)).replace(' ', '')


def fictional_phone(rand: 'random.Random') -> str:
    """A telephone number no subscriber can have: `+34 30X XXX XXX`.

    Spain has no range reserved for fiction (unlike the US 555-01xx or UK
    drama numbers). National numbers are nine digits whose first digit names
    the service; N=3 is "pendiente de atribución" in the numbering plan (Real
    Decreto 2296/2004, annex, section 4.4) and the CNMC numbering register of
    16 October 2026 assigns no nine-digit number beginning with 3 (and no
    code at all beginning 30). Numbers starting 0 or 1 are deliberately
    avoided: those are short codes and prefixes, including emergency
    services. See RESOURCES.md; re-check the register before a release, since
    a pending segment can be attributed later.
    """
    return (f"+34 30{rand.randint(0, 9)} {rand.randint(0, 999):03d} "
            f"{rand.randint(0, 999):03d}")


def assign_contact(person: 'Person') -> None:
    """Telephone and email, both in ranges that cannot reach a real person."""
    person.attributes['telephone'] = fictional_phone(person.random)
    first = _ascii(person.attributes.get('first_name', 'paciente'))
    last = _ascii(str(person.attributes.get('last_name', 'desconocido')).split(' ')[0])
    # example.com is reserved by RFC 2606 and can never be registered.
    person.attributes['email'] = (
        f"{first}.{last}{person.random.randint(1, 999)}@example.com".lower())


# ----------------------------------------------------------------------
# Identifiers, all invalid or unissuable by construction
# ----------------------------------------------------------------------

#: The official DNI/NIE check-letter table: letter = TABLE[number % 23].
DNI_LETTERS = 'TRWAGMYFPDXBNJZSQVHLCKE'

#: NIE prefixes and the digit each stands for in the check computation.
NIE_PREFIXES = {'X': 0, 'Y': 1, 'Z': 2}


def dni_letter(number: int) -> str:
    """The valid check letter for a DNI number (or an NIE's numeric form)."""
    return DNI_LETTERS[number % 23]


def _wrong_letter(number: int, rand: 'random.Random') -> str:
    """A check letter from the official alphabet that is never the right one.

    Shifting the valid letter's position by 1-22 always lands on a different
    letter of the same table, so the identifier looks well-formed and fails
    every validator.
    """
    valid = number % 23
    return DNI_LETTERS[(valid + rand.randint(1, 22)) % 23]


def _dni(person: 'Person') -> Optional[str]:
    """8 digits and a wrong check letter. Spanish nationals only."""
    if person.attributes.get('foreign_national'):
        return None
    number = person.random.randint(0, 99_999_999)
    return f"{number:08d}{_wrong_letter(number, person.random)}"


def _nie(person: 'Person') -> Optional[str]:
    """X, Y or Z, 7 digits and a wrong check letter. Foreign nationals only."""
    if not person.attributes.get('foreign_national'):
        return None
    prefix = person.random.choice(sorted(NIE_PREFIXES))
    digits = person.random.randint(0, 9_999_999)
    number = NIE_PREFIXES[prefix] * 10_000_000 + digits
    return f"{prefix}{digits:07d}{_wrong_letter(number, person.random)}"


#: Health card codes start with this. No health service issues codes
#: beginning `ZZSYN`, so a generated code can never be a real card.
CIP_PREFIX = 'ZZSYN'


def _cip(person: 'Person') -> str:
    """A health card code (CIP/TSI-like): the synthetic prefix and 11 digits."""
    return f"{CIP_PREFIX}{person.random.randint(0, 10 ** 11 - 1):011d}"


def nuss_control(province: int, number: int) -> int:
    """The valid NUSS control digits for a province and serial number."""
    if number < 10_000_000:
        base = province * 10_000_000 + number
    else:
        base = int(f"{province}{number}")
    return base % 97


def _nuss(person: 'Person') -> str:
    """Social Security number: province, 8 digits, wrong control digits."""
    try:
        province = int(person.attributes.get('region_code') or 28)
    except (TypeError, ValueError):
        province = 28
    number = person.random.randint(10_000_000, 99_999_999)
    control = (nuss_control(province, number) + person.random.randint(1, 96)) % 97
    return f"{province:02d}{number:08d}{control:02d}"


def _nhc(person: 'Person') -> str:
    """The hospital's medical record number (número de historia clínica)."""
    return str(person.random.randint(10 ** 6, 10 ** 7 - 1))


IDENTIFIERS = (
    IdentifierScheme(
        key='identifier_dni',
        type_code='NNESP',
        type_display='National Person Identifier (Spain)',
        system=SYSTEM_PREFIX + 'dni',
        format=_dni,
        # Compulsory from 14 (Ley Orgánica 4/2015, art. 9); many children
        # have one earlier, which is not modelled.
        minimum_age=14,
    ),
    IdentifierScheme(
        key='identifier_nie',
        type_code='NI',
        type_display='National unique individual identifier',
        system=SYSTEM_PREFIX + 'nie',
        format=_nie,
    ),
    IdentifierScheme(
        key='identifier_cip',
        type_code='JHN',
        type_display='Jurisdictional health number',
        system=SYSTEM_PREFIX + 'cip',
        format=_cip,
    ),
    IdentifierScheme(
        key='identifier_nuss',
        type_code='SS',
        type_display='Social Security number',
        system=SYSTEM_PREFIX + 'nuss',
        format=_nuss,
        # Assumption, not a statistic: affiliation begins with first
        # employment, legally possible from 16.
        minimum_age=16,
    ),
    IdentifierScheme(
        key='identifier_mrn',
        type_code='MR',
        type_display='Medical record number',
        system=SYSTEM_PREFIX + 'nhc',
        format=_nhc,
    ),
)


# ----------------------------------------------------------------------
# Clinicians
# ----------------------------------------------------------------------

def clinician_names(rand: 'random.Random') -> Tuple[str, str]:
    """A clinician's given name and two surnames, from the INE lists."""
    sex = rand.choice(('F', 'M'))
    names, weights = _given_names(sex)
    return _weighted(rand, names, weights), _two_surnames(rand)


#: The engine's specialty mix, named as Spanish specialties. The shares are
#: the engine defaults, not Spanish workforce statistics.
SPECIALTIES = (
    ('Medicina Familiar y Comunitaria', 0.30),
    ('Medicina Interna', 0.20),
    ('Pediatría', 0.10),
    ('Medicina de Urgencias', 0.10),
    ('Cardiología', 0.07),
    ('Cirugía Ortopédica y Traumatología', 0.07),
    ('Obstetricia y Ginecología', 0.06),
    ('Psiquiatría', 0.05),
    ('Dermatología', 0.03),
    ('Oncología Médica', 0.02),
)


def _colegiado(rand: 'random.Random') -> str:
    """A medical college membership number in a province that does not exist.

    Collegiate numbers begin with the two-digit province code (01-52); 99 is
    not a province, so the number cannot belong to a real doctor.
    """
    return f"99{rand.randint(0, 9_999_999):07d}"


PRACTITIONER_IDENTIFIER = PractitionerIdentifierScheme(
    system=SYSTEM_PREFIX + 'colegiado',
    format=_colegiado,
    type_code='PRN',
    type_display='Provider number',
)


# ----------------------------------------------------------------------
# The pack
# ----------------------------------------------------------------------

#: Calibration for Spain. Each value is measured, and the measurement is
#: recorded in RESOURCES.md next to its source.
CALIBRATION = {
    # Completed cohort fertility of women born 1966-1980 is 1.36-1.58
    # children (derived from INE IDB table 1406; see RESOURCES.md). The US
    # value, 0.3, gave 1.77 births per woman aged 46-60 here; 0.22 gives 1.46.
    'calibration.reproduction.exposure': 0.22,
}


PACK = LocalePack(
    code='es',
    name='Spain',
    country_code='ES',
    language='es',
    currency='EUR',

    assign_name=assign_name,
    assign_address=assign_address,
    assign_contact=assign_contact,
    identifiers=IDENTIFIERS,
    marital_statuses=_marital_statuses(),

    # Spain does not record race or ethnicity.
    race_categories=(),
    ethnicity_categories=(),

    demographics_file='population_by_age_sex.csv',
    geography_file='geography.csv',
    providers_files={'providers/hospitals.csv': 'hospital'},
    payers_file='payers/insurers.csv',
    plans_file='payers/plans.csv',
    resource_root=str(RESOURCE_ROOT),

    coding=CodingPreferences(),
    export_profile='ehds',
    note_template='note_es.md.j2',
    temperature_unit='Cel',

    clinician_names=clinician_names,
    clinician_specialties=SPECIALTIES,
    practitioner_identifier=PRACTITIONER_IDENTIFIER,

    # Universal public cover from birth; the SNS does not bill per visit.
    coverage_policy=UniversalCoverage(eligibility='SNS', kind='public'),
    produces_claims=False,

    calibration=CALIBRATION,
)

register(PACK)
