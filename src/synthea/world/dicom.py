"""DICOM unique identifiers for generated imaging studies.

An imaging study is only useful to imaging software if its identifiers are real
DICOM UIDs. A UID is a dotted numeric string under a registered root; anyone may
mint one under the ``2.25.`` arc by taking a UUID and writing its 128 bits as a
decimal integer, which is what this does.

The UUIDs come from the person's own generator rather than ``uuid.uuid4()``, so
a seeded run produces the same study identifiers every time.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from synthea.world.person import Person

#: The arc reserved for UUID-derived identifiers, so no registration is needed
#: and no collision with an issuing organisation is possible.
UUID_ROOT = '2.25'

#: DICOM caps a UID at 64 characters. ``2.25.`` plus a 39-digit integer fits.
MAX_UID_LENGTH = 64


def uid(person: 'Person') -> str:
    """Mint a DICOM UID from the person's random stream."""
    value = person.random.getrandbits(128)
    result = f"{UUID_ROOT}.{value}"
    return result[:MAX_UID_LENGTH]


def study_uid(person: 'Person') -> str:
    """Study Instance UID."""
    return uid(person)


def series_uid(person: 'Person') -> str:
    """Series Instance UID."""
    return uid(person)


def sop_instance_uid(person: 'Person') -> str:
    """SOP Instance UID, identifying one image."""
    return uid(person)
