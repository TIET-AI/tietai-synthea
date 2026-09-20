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


def assign_identity(person: 'Person', pack=None) -> None:
    """Give a person a name, address, contact details and identifiers.

    Called once at birth. Everything is drawn from the person's own generator
    so the identity is reproducible from the seed.

    The shape of all of this is locale-specific — name structure, street
    format, telephone conventions, which identifiers exist and what they look
    like — so it comes from the locale pack. The order of the draws is part of
    the contract: changing it changes every generated population.
    """
    if pack is None:
        pack = getattr(person, 'locale', None) or _default_pack()

    if pack.assign_name is not None:
        pack.assign_name(person)
    if pack.assign_address is not None:
        pack.assign_address(person)
    if pack.assign_contact is not None:
        pack.assign_contact(person)

    _assign_identifiers(person, pack)
    _assign_social(person)


def _default_pack():
    from synthea.locale import get

    return get()


def _assign_identifiers(person: 'Person', pack) -> None:
    """Assign the identifiers this locale issues.

    Age limits and how common an identifier is are applied by the pack, so a
    scheme cannot forget them.
    """
    for scheme in pack.identifiers:
        value = pack.identifier_for(person, scheme)
        if value is not None:
            person.attributes[scheme.key] = value


def _assign_social(person: 'Person') -> None:
    language = LanguageCodes.get(person.attributes.get('name_language', 'english'))
    if language:
        person.attributes['language_code'] = language


def assign_marital_status(person: 'Person', age: float, pack=None) -> None:
    """Set marital status once the patient is old enough to have one."""
    if age < 18 or 'marital_status' in person.attributes:
        return

    if pack is None:
        pack = getattr(person, 'locale', None) or _default_pack()

    statuses = pack.marital_statuses or MARITAL_STATUS
    weights = [share for _, _, share in statuses]
    choice = person.random.choices(statuses, weights=weights)[0]
    person.attributes['marital_status'] = {'code': choice[0], 'display': choice[1]}


def full_name(person: 'Person') -> str:
    """The patient's display name, or a clear placeholder."""
    first = person.attributes.get('first_name')
    last = person.attributes.get('last_name')
    if first and last:
        return f"{first} {last}"
    return "Unknown Person"
