"""Background mortality.

Until this existed, a generated patient only ever died if a disease module's
``Death`` state fired. Everyone else lived to the end of the simulation, so a
population contained implausible numbers of centenarians and no one died of
anything ordinary.

## What this is, and what it is not

This is a **parametric approximation**, not a published life table. Mortality is
modelled as a Gompertz-Makeham hazard with an added infant term:

    mu(x) = infant(x) + A + B exp(C x)

- ``A`` is the age-independent (Makeham) background: accidents and the like.
- ``B exp(C x)`` is the Gompertz term: senescent mortality, which doubles roughly
  every 8 years.
- The infant term captures the first year of life, which Gompertz does not fit.

The parameters below were chosen so the resulting life expectancy at birth lands
near published United States values, and :mod:`tests.test_mortality` asserts
that numerically rather than taking it on trust. They are *not* a substitute for
real data.

**Replace this with real life tables.** Doing so is part of the target-data work
in issue #55, where each locale pack ships the mortality of its own population.
Until then, treat survival curves from this generator as plausible, not
authoritative, and do not use them for actuarial or epidemiological conclusions.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from synthea.world.person import Person

# Parameters fitted by least squares against published United States anchors:
# life expectancy at birth (76 male, 81 female) and annual death probability for
# males at ages 25, 45, 65 and 85. The fit gives 75.3 and 80.5 years, with each
# anchor within about a fifth of its value. tests/test_mortality.py re-checks
# this, so the numbers cannot drift unnoticed.

#: Makeham background hazard, per year: the age-independent component.
BACKGROUND_HAZARD = 0.0004

#: Gompertz scale and rate. The rate gives a mortality doubling time of about
#: eight years, which is the classic human value.
GOMPERTZ_SCALE = 0.000045
GOMPERTZ_RATE = 0.085

#: Sex multiplier applied to both the background and senescent terms. Male
#: mortality runs higher at every age, from accidents in youth through to
#: senescence, and this is what separates the two life expectancies.
SEX_MULTIPLIER = {'M': 1.5, 'F': 1.0}

#: First-year hazard, decaying quickly through infancy. Gompertz does not fit
#: the first year of life, which has its own elevated risk.
INFANT_HAZARD = 0.0060
INFANT_DECAY = 3.0


def hazard(age: float, gender: str) -> float:
    """Instantaneous mortality hazard at an age, per year."""
    age = max(0.0, float(age))
    multiplier = SEX_MULTIPLIER.get((gender or 'F').upper(), 1.0)

    infant = INFANT_HAZARD * math.exp(-INFANT_DECAY * age)
    background = BACKGROUND_HAZARD * multiplier
    senescent = GOMPERTZ_SCALE * multiplier * math.exp(GOMPERTZ_RATE * age)
    return infant + background + senescent


def probability_of_death(age: float, gender: str, years: float) -> float:
    """Probability of dying within ``years`` of the given age.

    Uses the hazard at the start of the interval, which is accurate for the
    short intervals a timestep represents.
    """
    if years <= 0:
        return 0.0
    return 1.0 - math.exp(-hazard(age, gender) * years)


def dies_this_step(person: 'Person', age: float, years: float) -> bool:
    """Whether background mortality takes this person during this timestep."""
    gender = person.attributes.get('gender', 'F')
    return person.random.random() < probability_of_death(age, gender, years)


def life_expectancy(gender: str, step_years: float = 1.0 / 12,
                    max_age: float = 130.0) -> float:
    """Life expectancy at birth implied by the hazard, by numeric integration.

    Exposed so tests can assert the parameters produce a plausible population
    rather than trusting the constants above.
    """
    survival = 1.0
    expectancy = 0.0
    age = 0.0
    while age < max_age and survival > 1e-9:
        expectancy += survival * step_years
        survival *= math.exp(-hazard(age, gender) * step_years)
        age += step_years
    return expectancy
