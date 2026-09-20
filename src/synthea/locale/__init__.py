"""Locale packs: everything country-specific, in one pluggable place.

    from synthea.locale import get, available

    pack = get('us')
    print([code for code, _ in available()])

Packs ship either in this package or as separate distributions declaring a
`synthea.locales` entry point:

    [project.entry-points."synthea.locales"]
    es = "synthea_locale_es:PACK"

The entry point resolves to a :class:`~synthea.locale.base.LocalePack`, or to a
callable returning one. That means a pack can be published to PyPI and used
without this repository knowing it exists — which is the point: localisation
must not require a fork.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

from synthea.locale.base import CodingPreferences, IdentifierScheme, LocalePack

logger = logging.getLogger(__name__)

__all__ = [
    'CodingPreferences',
    'IdentifierScheme',
    'LocalePack',
    'available',
    'get',
    'register',
    'DEFAULT_LOCALE',
]

#: The locale used when nothing asks for another. The United States is the
#: reference pack: it is the one the bundled modules and reference data were
#: built around, not a statement about who the generator is for.
DEFAULT_LOCALE = 'us'

#: Entry point group third-party packs advertise themselves under.
ENTRY_POINT_GROUP = 'synthea.locales'

_registry: Dict[str, LocalePack] = {}
_discovered = False


def register(pack: LocalePack) -> LocalePack:
    """Add a pack to the registry, replacing any pack with the same code."""
    _registry[pack.code.lower()] = pack
    return pack


def _discover() -> None:
    """Load built-in packs, then anything advertising the entry point."""
    global _discovered
    if _discovered:
        return
    _discovered = True

    from synthea.locale import us  # noqa: F401  (registers on import)

    try:
        from importlib.metadata import entry_points
    except ImportError:  # pragma: no cover - Python < 3.8
        return

    try:
        points = entry_points(group=ENTRY_POINT_GROUP)
    except TypeError:  # pragma: no cover - older importlib.metadata
        points = entry_points().get(ENTRY_POINT_GROUP, [])

    for point in points:
        try:
            loaded = point.load()
        except Exception as error:
            # A broken third-party pack must not stop the generator starting.
            logger.warning("Could not load locale pack %r: %s", point.name, error)
            continue

        pack = loaded() if callable(loaded) else loaded

        if not isinstance(pack, LocalePack):
            logger.warning(
                "Locale entry point %r did not provide a LocalePack (got %s)",
                point.name, type(pack).__name__,
            )
            continue

        register(pack)


def available() -> List[Tuple[str, LocalePack]]:
    """Every known pack, as `(code, pack)`, sorted by code."""
    _discover()
    return sorted(_registry.items())


def get(code: Optional[str] = None) -> LocalePack:
    """The pack for a locale code.

    An unknown code is an error rather than a silent fall back to the United
    States: quietly generating American patients for someone who asked for
    Spain is the kind of wrong that is only noticed much later.
    """
    _discover()

    wanted = (code or DEFAULT_LOCALE).strip().lower()

    pack = _registry.get(wanted)
    if pack is not None:
        return pack

    # `es-ES` should find `es` when no regional pack is installed.
    if '-' in wanted:
        pack = _registry.get(wanted.split('-', 1)[0])
        if pack is not None:
            return pack

    known = ', '.join(sorted(_registry)) or '(none)'
    raise LookupError(
        f"Unknown locale {code!r}. Available: {known}. "
        f"Packs are discovered through the '{ENTRY_POINT_GROUP}' entry point; "
        f"install one, or run --list-locales to see what is present."
    )
