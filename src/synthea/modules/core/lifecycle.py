"""The lifecycle module: who a patient is, and how their body changes.

This runs before every disease module on each timestep. It owns everything that
is true of a patient regardless of what they suffer from:

- **Identity** at birth: name, address, contact details, identifiers.
- **Growth**: height and weight tracked against a stable CDC percentile through
  childhood, then adult weight change with age.
- **Vital signs**: a healthy baseline refreshed each timestep, which disease
  modules are free to override.
- **Death**: background mortality from :mod:`synthea.world.mortality`, plus
  honouring a death scheduled by a module.

Disease modules read the attributes this sets (``age``, ``bmi``, blood pressure)
in their logic conditions, so it has to run first. The generator orders it ahead
of everything else.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from synthea.engine.module import Module
from synthea.world import identity, mortality, vitals
from synthea.world.growth import BMI, GrowthCharts, HEIGHT, WEIGHT, bmi as compute_bmi
from synthea.world.vitals import Biometrics

logger = logging.getLogger(__name__)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from synthea.world.person import Person

#: Age at which the CDC charts stop and adult weight change takes over.
ADULT_AGE = 20

#: Beyond this the charts are extrapolated rather than read.
MAX_CHART_AGE_MONTHS = 240

#: ``biometrics.yml`` gives adult weight change as a bare number with no unit.
#: Read as kilograms per year it produces a population with a mean BMI near 32
#: and two thirds obese, well above the real distribution. Read as **pounds**
#: per year the population lands close to published United States figures, which
#: is the reading taken here.
#:
#: tests/test_lifecycle.py asserts the resulting distribution, so if this
#: assumption is wrong the test says so rather than the error hiding in the data.
POUNDS_TO_KG = 0.45359237


class LifecycleModule(Module):
    """Identity, growth, vital signs and background mortality."""

    def __init__(self):
        super().__init__('lifecycle')

    def process(self, person: 'Person', time: datetime) -> bool:
        if not person.alive:
            return True

        age = person.age_at(time)

        if not person.attributes.get('lifecycle_initialised'):
            self._at_birth(person, time)
            person.attributes['lifecycle_initialised'] = True

        person.attributes['age'] = age
        person.attributes['age_years'] = int(age)
        person.attributes['age_months'] = int(age * 12)

        identity.assign_marital_status(person, age)

        self._grow(person, age, time)
        self._vitals(person, time)
        self._mortality(person, age, time)

        return True

    # ------------------------------------------------------------------
    # Birth
    # ------------------------------------------------------------------

    def _at_birth(self, person: 'Person', time: datetime) -> None:
        identity.assign_identity(person)

        # A stable percentile per measure, held for life. Height and weight
        # percentiles are correlated: tall children tend to be heavier.
        height_percentile = person.random.uniform(0.02, 0.98)
        weight_percentile = min(0.98, max(0.02, person.random.gauss(height_percentile, 0.18)))
        person.attributes['growth_percentile_height'] = height_percentile
        person.attributes['growth_percentile_weight'] = weight_percentile

        if 'birth_weight' not in person.attributes:
            birth_weight = GrowthCharts.value_at(
                WEIGHT, person.attributes.get('gender', 'F'), 0, weight_percentile,
            )
            if birth_weight is not None:
                person.attributes['birth_weight'] = round(birth_weight, 3)

    # ------------------------------------------------------------------
    # Growth
    # ------------------------------------------------------------------

    def _grow(self, person: 'Person', age: float, time: datetime) -> None:
        gender = person.attributes.get('gender', 'F')
        height_pct = person.attributes.get('growth_percentile_height')
        weight_pct = person.attributes.get('growth_percentile_weight')
        if height_pct is None or weight_pct is None:
            return

        if age < ADULT_AGE:
            height = GrowthCharts.value_at(HEIGHT, gender, age * 12, height_pct)
            weight = GrowthCharts.value_at(WEIGHT, gender, age * 12, weight_pct)
        else:
            height = person.attributes.get('adult_height')
            if height is None:
                height = GrowthCharts.value_at(
                    HEIGHT, gender, MAX_CHART_AGE_MONTHS, height_pct,
                )
                if height is not None:
                    person.attributes['adult_height'] = height
            weight = self._adult_weight(person, age, gender, weight_pct)

        if height is not None:
            person.set_vital_sign('Height', round(height, 1), 'cm', time)
        if weight is not None:
            person.set_vital_sign('Weight', round(weight, 1), 'kg', time)

        if height and weight:
            index = compute_bmi(weight, height)
            if index is not None:
                person.set_vital_sign('Body Mass Index', round(index, 1), 'kg/m2', time)
                person.attributes['bmi'] = round(index, 1)

    def _adult_weight(self, person: 'Person', age: float, gender: str,
                      weight_pct: float) -> float:
        """Adult weight: the 20-year value, then gain, plateau and later loss.

        Rates come from ``biometrics.yml`` (``lifecycle.adult_weight_gain`` and
        ``geriatric_weight_loss``), the same file the disease modules use.
        """
        baseline = person.attributes.get('adult_weight_baseline')
        if baseline is None:
            baseline = GrowthCharts.value_at(
                WEIGHT, gender, MAX_CHART_AGE_MONTHS, weight_pct,
            ) or 70.0
            person.attributes['adult_weight_baseline'] = baseline

        data = Biometrics.load().get('lifecycle', {})
        gain_range = Biometrics.range('lifecycle', 'adult_weight_gain') or [1.0, 2.0]
        loss_range = Biometrics.range('lifecycle', 'geriatric_weight_loss') or [1.0, 2.0]
        max_gain_age = float(data.get('adult_max_weight_age', 49))
        loss_age = float(data.get('geriatric_weight_loss_age', 60))

        # One rate per person, not per timestep, so the trajectory is smooth.
        gain_rate = person.attributes.get('adult_weight_gain_rate')
        if gain_rate is None:
            gain_rate = person.random.uniform(*gain_range)
            person.attributes['adult_weight_gain_rate'] = gain_rate
        loss_rate = person.attributes.get('geriatric_weight_loss_rate')
        if loss_rate is None:
            loss_rate = person.random.uniform(*loss_range)
            person.attributes['geriatric_weight_loss_rate'] = loss_rate

        gaining_years = max(0.0, min(age, max_gain_age) - ADULT_AGE)
        losing_years = max(0.0, age - loss_age)

        gained = gain_rate * POUNDS_TO_KG * gaining_years
        lost = loss_rate * POUNDS_TO_KG * losing_years
        return max(35.0, baseline + gained - lost)

    # ------------------------------------------------------------------
    # Vital signs
    # ------------------------------------------------------------------

    def _vitals(self, person: 'Person', time: datetime) -> None:
        """Refresh the healthy baseline, without overwriting module values.

        A disease module that has raised a patient's blood pressure must keep
        it; this only fills in what nothing else has set during this step.
        """
        for name, value in vitals.baseline_vitals(person).items():
            existing = person.vital_signs.get(name)
            if existing and existing.get('time') == time:
                continue  # a module already set it this step
            unit = vitals.VITAL_CODES.get(name, {}).get('unit')
            person.set_vital_sign(name, value, unit, time)

    # ------------------------------------------------------------------
    # Death
    # ------------------------------------------------------------------

    def _mortality(self, person: 'Person', age: float, time: datetime) -> None:
        scheduled = person.attributes.get('death_time')
        if scheduled is not None and time >= scheduled:
            self._die(person, scheduled)
            return

        years = person.attributes.get('timestep_years', 7.0 / 365.0)
        if mortality.dies_this_step(person, age, years):
            self._die(person, time)

    def _die(self, person: 'Person', time: datetime) -> None:
        person.alive = False
        person.attributes['death_date'] = time
        if getattr(person, 'record', None) is not None and person.record.death_date is None:
            person.record.death(time, person.attributes.get('cause_of_death'))
