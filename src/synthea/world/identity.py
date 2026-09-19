"""Patient identity: names, addresses, contact details and identifiers.

Before this existed every generated patient exported as "Unknown Person" with no
address and no identifier, which made the output useless for anything that keys
on a patient — record linkage, master patient index testing, de-duplication, or
simply looking realistic in a demo.

Names and street types come from the bundled ``names.yml``; language codes from
``language_lookup.json``.

**Identifiers are deliberately non-issuable.** Social security numbers use the
``999`` area, which has never been issued to a real person, and the other
identifier formats are synthetic by construction. Nothing here can collide with
a real person's identifier.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, TYPE_CHECKING

import yaml

from synthea.helpers.resources import resource_path

logger = logging.getLogger(__name__)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from synthea.world.person import Person

#: Marital status codes (HL7 v3 MaritalStatus), with rough adult shares.
MARITAL_STATUS = [
    ('M', 'Married', 0.48),
    ('S', 'Never Married', 0.35),
    ('D', 'Divorced', 0.11),
    ('W', 'Widowed', 0.06),
]


class NameData:
    """Name and street vocabulary from ``names.yml``."""

    _data: Optional[Dict] = None

    @classmethod
    def load(cls) -> Dict:
        if cls._data is None:
            path = resource_path('names.yml')
            try:
                with open(path, 'r', encoding='utf-8') as handle:
                    cls._data = yaml.safe_load(handle) or {}
            except (OSError, ValueError) as error:
                logger.warning("Could not read names at %s: %s", path, error)
                cls._data = {}
        return cls._data

    @classmethod
    def language_for(cls, ethnicity: str) -> str:
        """Which name vocabulary suits this patient."""
        data = cls.load()
        if ethnicity and ethnicity.lower().startswith('hispanic') and 'spanish' in data:
            return 'spanish'
        return 'english'

    @classmethod
    def given_names(cls, language: str, gender: str) -> List[str]:
        return cls.load().get(language, {}).get('M' if gender == 'M' else 'F', [])

    @classmethod
    def family_names(cls, language: str) -> List[str]:
        return cls.load().get(language, {}).get('family', [])

    @classmethod
    def street_types(cls) -> List[str]:
        return cls.load().get('street', {}).get('type', [])

    @classmethod
    def secondary_types(cls) -> List[str]:
        return cls.load().get('street', {}).get('secondary', [])


class LanguageCodes:
    """BCP-47 codes from ``language_lookup.json``."""

    _data: Optional[Dict] = None

    @classmethod
    def load(cls) -> Dict:
        if cls._data is None:
            path = resource_path('language_lookup.json')
            try:
                with open(path, 'r', encoding='utf-8') as handle:
                    cls._data = json.load(handle)
            except (OSError, ValueError) as error:
                logger.warning("Could not read languages at %s: %s", path, error)
                cls._data = {}
        return cls._data

    @classmethod
    def get(cls, language: str) -> Optional[Dict[str, str]]:
        return cls.load().get(language)


def assign_identity(person: 'Person') -> None:
    """Give a person a name, address, contact details and identifiers.

    Called once at birth. Everything is drawn from the person's own generator so
    the identity is reproducible from the seed.
    """
    _assign_name(person)
    _assign_address(person)
    _assign_contact(person)
    _assign_identifiers(person)
    _assign_social(person)


def _assign_name(person: 'Person') -> None:
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


def _assign_address(person: 'Person') -> None:
    types = NameData.street_types()
    families = NameData.family_names(person.attributes.get('name_language', 'english'))
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


def _assign_contact(person: 'Person') -> None:
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


def _assign_identifiers(person: 'Person') -> None:
    """Assign identifiers that cannot collide with real ones."""
    # SSA has never issued an area number of 999.
    person.attributes['identifier_ssn'] = (
        f"999-{person.random.randint(10, 99)}-{person.random.randint(1000, 9999)}"
    )

    person.attributes['identifier_mrn'] = str(person.random.randint(10 ** 6, 10 ** 7 - 1))

    age = person.attributes.get('age_at_creation')
    if age is None or age >= 16:
        person.attributes['identifier_drivers'] = f"S{person.random.randint(10 ** 8, 10 ** 9 - 1)}"

    if person.random.random() < 0.42:
        person.attributes['identifier_passport'] = (
            f"X{person.random.randint(10 ** 7, 10 ** 8 - 1)}X"
        )


def _assign_social(person: 'Person') -> None:
    language = LanguageCodes.get(person.attributes.get('name_language', 'english'))
    if language:
        person.attributes['language_code'] = language


def assign_marital_status(person: 'Person', age: float) -> None:
    """Set marital status once the patient is old enough to have one."""
    if age < 18 or 'marital_status' in person.attributes:
        return
    weights = [share for _, _, share in MARITAL_STATUS]
    choice = person.random.choices(MARITAL_STATUS, weights=weights)[0]
    person.attributes['marital_status'] = {'code': choice[0], 'display': choice[1]}


def full_name(person: 'Person') -> str:
    """The patient's display name, or a clear placeholder."""
    first = person.attributes.get('first_name')
    last = person.attributes.get('last_name')
    if first and last:
        return f"{first} {last}"
    return "Unknown Person"
