"""Insurance coverage over a patient's life.

Coverage is decided once a year rather than once, because it changes: a patient
turning 65 moves to Medicare, and someone whose circumstances change moves
between Medicaid, private cover and none. A record with a single lifelong payer
cannot exercise anything that reasons about coverage transitions, which is a
large part of why payer data is interesting.

The history is kept in full, so the export can emit a Coverage resource per
period rather than only the current one.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

from synthea.engine.module import Module

logger = logging.getLogger(__name__)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from synthea.world.person import Person

#: Chance per year that a patient switches plan while their kind of cover is
#: unchanged — a new employer, or shopping the marketplace.
ANNUAL_SWITCH_CHANCE = 0.08

#: Person attribute holding the coverage in force.
CURRENT_COVERAGE = 'current_coverage'

#: Person attribute holding the year coverage was last reviewed.
LAST_REVIEW = 'coverage_reviewed_year'

#: Person attribute holding every coverage period the patient has had.
COVERAGE_HISTORY = 'coverage_history'


class HealthInsuranceModule(Module):
    """Assigns and maintains insurance coverage."""

    def __init__(self):
        super().__init__('health_insurance')

    def process(self, person: 'Person', time: datetime) -> bool:
        if not person.alive:
            return True

        manager = getattr(person, 'payers', None)
        if manager is None:
            return True

        # Coverage is reviewed once a year, at most. The module runs every
        # timestep, so without this gate the annual switch chance fired weekly
        # and a lifetime produced sixty-odd coverage periods.
        current = person.attributes.get(CURRENT_COVERAGE)
        last_review = person.attributes.get(LAST_REVIEW)
        if current is not None and last_review == time.year:
            return True
        person.attributes[LAST_REVIEW] = time.year

        age = person.age_at(time)
        kind = manager.kind_for(person, age)

        # People do not change insurer every year. While the kind of cover is
        # unchanged the patient keeps the same plan, apart from an occasional
        # switch; without this a lifetime produced sixty-odd coverage periods,
        # which is nothing like a real coverage history.
        if current is not None and current.kind == kind:
            if person.random.random() >= ANNUAL_SWITCH_CHANCE:
                return True

        coverage = manager.coverage_for(person, age, time, kind=kind)

        if current is not None and _same_cover(current, coverage):
            return True

        if current is not None:
            current.end = time

        person.attributes[CURRENT_COVERAGE] = coverage
        person.attributes.setdefault(COVERAGE_HISTORY, []).append(coverage)

        return True


def _same_cover(a, b) -> bool:
    """Whether two coverages are the same cover, so the period continues."""
    if a.kind != b.kind:
        return False
    if a.plan is None or b.plan is None:
        return a.plan is b.plan
    return a.plan.id == b.plan.id
