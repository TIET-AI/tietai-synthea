"""The encounter module: routine visits that the rest of the record hangs off.

Most chronic-disease modules do not open their own appointment. They declare
``"wellness": true`` on an Encounter state, meaning "attach this to the patient's
next routine check-up". Without something scheduling those check-ups the engine
had nowhere to attach them, so it opened an ambulatory encounter immediately
instead, and every chronic condition was diagnosed in the first week of life.

This module schedules check-ups at the intervals people actually attend them:
frequently in infancy, rarely in early adulthood, more often again with age. A
wellness encounter stays open for the timestep in which it occurs, which is the
window a ``wellness`` Encounter state has to claim it.

Vital signs are recorded at every check-up, which is what makes the visit a
useful clinical record rather than an empty container.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from synthea.engine.module import Module
from synthea.world import vitals

logger = logging.getLogger(__name__)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from synthea.world.person import Person

#: Months between routine check-ups, by age band. Infants are seen often, young
#: adults rarely, older adults annually.
WELLNESS_INTERVAL_MONTHS = [
    (1.0, 2),     # under 1: roughly every other month
    (3.0, 6),     # 1-3: twice a year
    (19.0, 12),   # childhood and adolescence: annual
    (40.0, 36),   # young adults: every three years
    (65.0, 24),   # middle age: every two years
    (999.0, 12),  # 65 and over: annual
]

#: Person attribute holding the wellness encounter currently in progress.
CURRENT_WELLNESS = 'current_wellness_encounter'

#: SNOMED code for a general check-up, used as the encounter's type.
WELLNESS_CODE = {
    'system': 'SNOMED-CT',
    'code': '162673000',
    'display': 'General examination of patient (procedure)',
}


def interval_months(age: float) -> int:
    """How many months between check-ups at this age."""
    for upper, months in WELLNESS_INTERVAL_MONTHS:
        if age < upper:
            return months
    return 12


class EncounterModule(Module):
    """Schedules routine check-ups and records vitals at each."""

    def __init__(self):
        super().__init__('encounter')

    def process(self, person: 'Person', time: datetime) -> bool:
        if not person.alive or getattr(person, 'record', None) is None:
            return True

        # Any wellness encounter from an earlier timestep is over. Closing it
        # here, rather than when the next one opens, keeps the window during
        # which a `wellness` Encounter state can attach to exactly one step.
        self._close_stale(person, time)

        if self._is_due(person, time):
            self._open_wellness(person, time)

        return True

    def _is_due(self, person: 'Person', time: datetime) -> bool:
        next_due = person.attributes.get('next_wellness_encounter')
        if next_due is None:
            # First visit shortly after birth, not exactly at it.
            person.attributes['next_wellness_encounter'] = (
                time + timedelta(days=person.random.randint(7, 45))
            )
            return False
        return time >= next_due

    def _open_wellness(self, person: 'Person', time: datetime) -> None:
        encounter = person.record.encounter_start(time, 'wellness')
        encounter.name = 'Wellness Encounter'
        encounter.codes = [_wellness_code()]

        person.attributes[CURRENT_WELLNESS] = encounter
        # Disease modules look here for the encounter in progress.
        person.attributes['current_encounter'] = encounter
        person.attributes['wellness_encounter_open'] = True

        vitals.record_vitals(person, time, encounter)

        age = person.age_at(time)
        months = interval_months(age)
        # Spread visits so a cohort does not attend in lockstep.
        jitter = person.random.uniform(0.85, 1.15)
        person.attributes['next_wellness_encounter'] = (
            time + timedelta(days=months * 30.4 * jitter)
        )
        person.attributes['last_wellness_encounter'] = time

    def _close_stale(self, person: 'Person', time: datetime) -> None:
        encounter = person.attributes.get(CURRENT_WELLNESS)
        if encounter is None:
            return
        if encounter.time == time:
            return  # opened this step, still claimable

        if encounter.end_time is None:
            person.record.encounter_end(encounter, encounter.time)
        person.attributes.pop(CURRENT_WELLNESS, None)
        person.attributes['wellness_encounter_open'] = False
        if person.attributes.get('current_encounter') is encounter:
            person.attributes.pop('current_encounter', None)


def _wellness_code():
    from synthea.world.health_record import Code
    return Code(**WELLNESS_CODE)
