"""What care costs.

The cost tables have shipped with the package since 1.2.0 and nothing read
them, so every generated encounter, prescription and procedure was free. A
record with no money in it cannot exercise a claims pipeline, a payer mix, or
anything that reasons about the cost of care.

Each table gives a minimum, mode and maximum per code:

    CODE,MIN,MODE,MAX,COMMENTS
    312617,2,7,25,predniSONE 5 MG Oral Tablet

Those three numbers describe a triangular distribution, which is how the
upstream project intends them to be read: most instances cost about the mode,
with a long tail towards the maximum. Sampling from it rather than taking the
mode gives a spread of costs for the same procedure, which is what a real
claims dataset looks like.

Regional adjustment files sit beside each table. They are loaded and applied by
state where present, so the same procedure costs more in some states than
others.
"""

from __future__ import annotations

import csv
import logging
from typing import Dict, Optional, TYPE_CHECKING

from synthea.helpers.resources import resource_path

logger = logging.getLogger(__name__)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from synthea.world.health_record import Code
    from synthea.world.person import Person

#: Cost table per kind of thing, and the regional adjustment file for it.
COST_TABLES = {
    'encounter': ('encounters.csv', 'encounters_adjustments.csv'),
    'medication': ('medications.csv', 'medications_adjustments.csv'),
    'procedure': ('procedures.csv', 'procedures_adjustments.csv'),
    'immunization': ('immunizations.csv', None),
    'device': ('devices.csv', 'devices_adjustments.csv'),
    'supply': ('supplies.csv', 'supplies_adjustments.csv'),
    'lab': (None, 'labs_adjustments.csv'),
}

#: Used when a code is not in the table. Deliberately conservative: a missing
#: cost should not silently become the most expensive thing in the record.
DEFAULT_COSTS = {
    'encounter': 125.0,
    'medication': 25.0,
    'procedure': 500.0,
    'immunization': 140.0,
    'device': 250.0,
    'supply': 10.0,
    'lab': 50.0,
}


class CostTables:
    """Cost ranges by code, loaded once per process."""

    _tables: Dict[str, Dict[str, tuple]] = {}
    _adjustments: Dict[str, Dict[str, float]] = {}

    @classmethod
    def _load_table(cls, kind: str) -> Dict[str, tuple]:
        if kind in cls._tables:
            return cls._tables[kind]

        filename = COST_TABLES.get(kind, (None, None))[0]
        table: Dict[str, tuple] = {}

        if filename:
            path = resource_path('costs', filename)
            if path.exists():
                try:
                    with open(path, 'r', encoding='utf-8-sig', newline='') as handle:
                        for row in csv.DictReader(handle):
                            code = (row.get('CODE') or '').strip()
                            if not code:
                                continue
                            low = _as_float(row.get('MIN'))
                            mode = _as_float(row.get('MODE'))
                            high = _as_float(row.get('MAX'))
                            if None in (low, mode, high):
                                continue
                            table[code] = (low, mode, high)
                except Exception as error:  # pragma: no cover - defensive
                    logger.warning("Could not read costs from %s: %s", path, error)

        cls._tables[kind] = table
        return table

    @classmethod
    def _load_adjustments(cls, kind: str) -> Dict[str, float]:
        if kind in cls._adjustments:
            return cls._adjustments[kind]

        filename = COST_TABLES.get(kind, (None, None))[1]
        adjustments: Dict[str, float] = {}

        if filename:
            path = resource_path('costs', filename)
            if path.exists():
                try:
                    with open(path, 'r', encoding='utf-8-sig', newline='') as handle:
                        for row in csv.DictReader(handle):
                            state = (row.get('STATE') or row.get('State') or '').strip()
                            factor = _as_float(
                                row.get('ADJ_FACTOR') or row.get('ADJUSTMENT')
                                or row.get('FACTOR'))
                            if state and factor:
                                adjustments[state.upper()] = factor
                except Exception as error:  # pragma: no cover - defensive
                    logger.warning("Could not read adjustments from %s: %s",
                                   path, error)

        cls._adjustments[kind] = adjustments
        return adjustments

    @classmethod
    def sample(cls, kind: str, code: Optional[str], person: 'Person') -> float:
        """A cost for one instance of something, in dollars.

        Drawn from the code's triangular distribution using the person's own
        generator, so costs are reproducible and vary between instances.
        """
        table = cls._load_table(kind)
        bounds = table.get(str(code)) if code is not None else None

        if bounds is None:
            amount = DEFAULT_COSTS.get(kind, 0.0)
        else:
            low, mode, high = bounds
            amount = (
                person.random.triangular(low, high, mode) if high > low else mode
            )

        state = person.attributes.get('state')
        if state:
            factor = cls._load_adjustments(kind).get(str(state).upper())
            if factor:
                amount *= factor

        return round(max(0.0, amount), 2)


def cost_of(kind: str, codes, person: 'Person') -> float:
    """The cost of a record entry, from its first code."""
    code = None
    if codes:
        first = codes[0]
        code = getattr(first, 'code', first)
    return CostTables.sample(kind, code, person)


def _as_float(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
