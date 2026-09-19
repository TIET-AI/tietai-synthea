"""The immunizations module.

``immunization_schedule.json`` has shipped with the package since the first
release and nothing read it, so no generated patient had ever been vaccinated.
Each entry names a CVX code, the ages in months at which the vaccine is due, and
the year it first became available.

Vaccines are given at routine check-ups, not on arbitrary dates, which is both
how it happens and what ties the immunization to an encounter in the record. A
dose is given when the patient is at or past its scheduled age, has not already
had it, and the vaccine existed at the time being simulated.

That last condition matters for patients born decades ago: someone born in 1960
should not have received a vaccine licensed in 2006.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from synthea.engine.module import Module
from synthea.helpers.resources import resource_path
from synthea.world.health_record import Code

logger = logging.getLogger(__name__)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from synthea.world.person import Person

#: Annual vaccines repeat rather than being given once.
ANNUAL = {'flu'}

#: An annual vaccine is offered every year from this age in months.
ANNUAL_FROM_MONTHS = 6


class ImmunizationSchedule:
    """The bundled childhood and adult immunization schedule."""

    _data: Optional[Dict[str, Any]] = None

    @classmethod
    def load(cls) -> Dict[str, Any]:
        if cls._data is None:
            path = resource_path('immunization_schedule.json')
            try:
                with open(path, 'r', encoding='utf-8') as handle:
                    cls._data = json.load(handle)
            except (OSError, ValueError) as error:
                logger.warning("Could not read the immunization schedule at %s: %s",
                               path, error)
                cls._data = {}
        return cls._data

    @classmethod
    def code_for(cls, name: str) -> Optional[Code]:
        entry = cls.load().get(name, {}).get('code')
        if not isinstance(entry, dict):
            return None
        return Code(
            system=entry.get('system', ''),
            code=str(entry.get('code', '')),
            display=entry.get('display', ''),
        )

    @classmethod
    def due(cls, name: str, age_months: float, year: int,
            already_given: List[str]) -> bool:
        """Whether this vaccine is due now."""
        entry = cls.load().get(name, {})

        first_available = entry.get('first_available')
        if first_available and year < int(first_available):
            return False

        if name in ANNUAL:
            return age_months >= ANNUAL_FROM_MONTHS

        schedule = entry.get('at_months') or []
        doses_given = already_given.count(name)
        if doses_given >= len(schedule):
            return False

        try:
            return age_months >= float(schedule[doses_given])
        except (TypeError, ValueError):
            return False


class ImmunizationModule(Module):
    """Administers scheduled vaccines at routine check-ups."""

    def __init__(self):
        super().__init__('immunizations')

    def process(self, person: 'Person', time: datetime) -> bool:
        if not person.alive or getattr(person, 'record', None) is None:
            return True

        encounter = person.attributes.get('current_encounter')
        if encounter is None or encounter.time != time:
            return True  # only at a visit happening now

        age_months = person.age_at(time) * 12
        given: List[str] = person.attributes.setdefault('immunizations_given', [])
        annual_years = person.attributes.setdefault('immunizations_annual_years', {})

        for name in ImmunizationSchedule.load():
            if name in ANNUAL:
                if annual_years.get(name) == time.year:
                    continue
                if not ImmunizationSchedule.due(name, age_months, time.year, given):
                    continue
                annual_years[name] = time.year
            elif not ImmunizationSchedule.due(name, age_months, time.year, given):
                continue

            self._administer(person, time, encounter, name)
            given.append(name)

        return True

    def _administer(self, person: 'Person', time: datetime, encounter,
                    name: str) -> None:
        code = ImmunizationSchedule.code_for(name)
        if code is None:
            return
        immunization = person.record.immunization(time, code, encounter)
        immunization.name = name
        person.record.register_state_entry(self.name, name, immunization)
