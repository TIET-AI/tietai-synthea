"""Cardiovascular risk calculators: ASCVD pooled cohort equations and Framingham.

A port of upstream Synthea's ``org.mitre.synthea.modules.calculators.ASCVD`` and
``org.mitre.synthea.modules.calculators.Framingham``
(https://github.com/synthetichealth/synthea, ``src/main/java/org/mitre/synthea/
modules/calculators/``). The generic modules for myocardial infarction, stable
ischemic heart disease, atrial fibrillation and stroke never compute risk
themselves: they read the ``mi_risk``, ``ihd_risk``, ``atrial_fibrillation_risk``
and ``stroke_risk`` attributes that upstream's Java ``CardiovascularDiseaseModule``
derives from these scores (see :mod:`synthea.modules.core.cardiovascular_disease`).

Every function returns a 10-year risk in ``[0, 1]``, or ``-1`` when the score
does not apply (outside its age range, or a required vital sign is unset), as
upstream does. Callers convert to a per-step probability with
:func:`convert_risk_to_timestep`; a ``-1`` becomes a negative probability, which
a distributed transition never selects, so "no score" means "no risk".

Point bands are computed exactly as upstream computes them, with Java's
truncating integer division (:func:`_jdiv`). That matters at the low end: a
total cholesterol of 150 lands in the "160-199" band upstream, because
``(150 - 160) / 40`` truncates to ``0``, where Python's floor division would
give ``-1``. Reproducing it keeps the population calibration identical.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import TYPE_CHECKING, Dict, List, Sequence

if TYPE_CHECKING:  # pragma: no cover - typing only
    from synthea.world.person import Person

#: Upstream ``TimeUnit.DAYS.toMillis(3650)``, expressed in days.
TEN_YEARS_DAYS = 3650.0

SYSTOLIC = 'Systolic Blood Pressure'
DIASTOLIC = 'Diastolic Blood Pressure'
TOTAL_CHOLESTEROL = 'Total Cholesterol'
HDL = 'HDL'
BMI = 'Body Mass Index'


def convert_risk_to_timestep(risk: float, original_period_days: float,
                             new_period_days: float) -> float:
    """Upstream ``Utilities.convertRiskToTimestep``: ``1 - (1 - risk)^(new/original)``."""
    return 1 - math.pow(1 - risk, new_period_days / original_period_days)


def _jdiv(numerator: int, denominator: int) -> int:
    """Java ``int / int``: truncates toward zero, unlike Python's ``//``."""
    return int(numerator / denominator)


def _bound(value: int, low: int, high: int) -> int:
    return min(max(value, low), high)


def _flag(person: 'Person', name: str) -> bool:
    """Upstream ``(Boolean) attributes.getOrDefault(name, false)``."""
    return bool(person.attributes.get(name, False))


def _male(person: 'Person') -> bool:
    return person.attributes.get('gender') == 'M'


# ----------------------------------------------------------------------------
# ASCVD: Pooled Cohort Equations, 10-year risk of hard ASCVD.
# Appendix 7, Table A of https://doi.org/10.1161/01.cir.0000437741.48606.98
# Columns: women-white, women-african-american, men-white, men-african-american.
# ----------------------------------------------------------------------------

ASCVD_COEFFICIENTS: List[List[float]] = [
    [-29.799, 17.114, 12.344, 2.469],   # Ln Age (y)
    [4.884, 0, 0, 0],                   # (Ln Age)^2
    [13.540, 0.940, 11.853, 0.302],     # Ln Total Chol
    [-3.114, 0, -2.664, 0],             # Ln Age x Ln Total Chol
    [-13.578, -18.920, -7.990, -0.307],  # Ln HDL-C
    [3.149, 4.475, 1.769, 0],           # Ln Age x Ln HDL-C
    [2.019, 29.291, 1.797, 1.916],      # Ln Treated SysBP
    [0, -6.432, 0, 0],                  # Ln Age x Ln Treated SysBP
    [1.957, 27.820, 1.764, 1.809],      # Ln Untreated SysBP
    [0, -6.087, 0, 0],                  # Ln Age x Ln Untreated SysBP
    [7.574, 0.691, 7.837, 0.549],       # Current Smoker
    [-1.665, 0, -1.795, 0],             # Ln Age x Current Smoker
    [0.661, 0.874, 0.658, 0.645],       # Diabetes
    [-29.18, 86.61, 61.18, 19.54],      # Mean (Coefficient x Value)
    [0.9665, 0.9533, 0.9144, 0.8954],   # Baseline Survival
]


def ascvd_10_year(person: 'Person', time: datetime) -> float:
    """Upstream ``ASCVD.ascvd10Year``. Applies to ages 40 to 79."""
    age = person.age_in_years(time)
    systolic = person.get_vital_sign(SYSTOLIC)
    diastolic = person.get_vital_sign(DIASTOLIC)
    total_chol = person.get_vital_sign(TOTAL_CHOLESTEROL)
    hdl = person.get_vital_sign(HDL)
    if systolic is None or diastolic is None or total_chol is None or hdl is None:
        return -1
    if age < 40 or age > 79:
        return -1

    smoker = 1 if _flag(person, 'smoker') else 0
    diabetic = 1 if _flag(person, 'diabetes') else 0
    # Upstream treats a hypertension diagnosis as "treated" blood pressure.
    hypertensive = _flag(person, 'hypertension')

    ln_age = math.log(age)
    ln_chol = math.log(total_chol)
    ln_hdl = math.log(hdl)
    ln_treated = math.log(systolic) if hypertensive else 0.0
    ln_untreated = 0.0 if hypertensive else math.log(systolic)

    values = [
        ln_age,
        ln_age * ln_age,
        ln_chol,
        ln_age * ln_chol,
        ln_hdl,
        ln_age * ln_hdl,
        ln_treated,
        ln_age * ln_treated,
        ln_untreated,
        ln_age * ln_untreated,
        smoker,
        ln_age * smoker,
        diabetic,
    ]

    column = (2 if _male(person) else 0) + (1 if person.attributes.get('race') == 'black' else 0)
    individual = sum(ASCVD_COEFFICIENTS[i][column] * values[i] for i in range(13))
    mean = ASCVD_COEFFICIENTS[13][column]
    baseline_survival = ASCVD_COEFFICIENTS[14][column]
    return 1 - math.pow(baseline_survival, math.exp(individual - mean))


# ----------------------------------------------------------------------------
# Framingham: coronary heart disease (1998 point scores).
# ----------------------------------------------------------------------------

# Age bands 20-24, 25-29, ... 75-79.
_AGE_CHD = {True: [-9, -9, -9, -4, 0, 3, 6, 8, 10, 11, 12, 13],
            False: [-7, -7, -7, -3, 0, 3, 6, 8, 10, 12, 14, 16]}

# Rows: age decades 20-29 .. 70-79. Columns: chol <160, 160-199, 200-239, 240-279, >=280.
_AGE_CHOL_CHD = {
    True: [[0, 4, 7, 9, 11], [0, 4, 7, 9, 11], [0, 3, 5, 6, 8],
           [0, 2, 3, 4, 5], [0, 1, 1, 2, 3], [0, 0, 0, 1, 1]],
    False: [[0, 4, 8, 11, 13], [0, 4, 8, 11, 13], [0, 3, 6, 8, 10],
            [0, 2, 4, 5, 7], [0, 1, 2, 3, 4], [0, 1, 1, 2, 2]],
}

_AGE_SMOKE_CHD = {True: [8, 8, 5, 3, 1, 1], False: [9, 9, 7, 4, 2, 1]}

# Rows: SBP <120, 120-129, 130-139, 140-149, 150-159, >=160.
# Columns as upstream indexes them: [0] when treated, [1] when untreated.
_SYS_BP_CHD = {
    True: [[0, 0], [1, 0], [2, 1], [2, 1], [2, 1], [3, 2]],
    False: [[0, 0], [3, 1], [4, 2], [5, 3], [5, 3], [6, 4]],
}

_HDL_CHD = [2, 1, 0, -1]  # <40, 40-49, 50-59, >=60

_RISK_CHD_M: Dict[int, float] = {
    -1: 0.005, 0: 0.01, 1: 0.01, 2: 0.01, 3: 0.01, 4: 0.01, 5: 0.02, 6: 0.02,
    7: 0.03, 8: 0.04, 9: 0.05, 10: 0.06, 11: 0.08, 12: 0.1, 13: 0.12, 14: 0.16,
    15: 0.20, 16: 0.25, 17: 0.3,
}
_RISK_CHD_F: Dict[int, float] = {
    8: 0.005, 9: 0.01, 10: 0.01, 11: 0.01, 12: 0.01, 13: 0.02, 14: 0.02,
    15: 0.03, 16: 0.04, 17: 0.05, 18: 0.06, 19: 0.08, 20: 0.11, 21: 0.14,
    22: 0.17, 23: 0.22, 24: 0.27, 25: 0.3,
}


def chd_10_year(person: 'Person', time: datetime) -> float:
    """Upstream ``Framingham.chd10Year``: angina, MI and CHD death."""
    age = person.age_in_years(time)
    systolic = person.get_vital_sign(SYSTOLIC)
    diastolic = person.get_vital_sign(DIASTOLIC)
    chol = person.get_vital_sign(TOTAL_CHOLESTEROL)
    hdl = person.get_vital_sign(HDL)
    if systolic is None or diastolic is None or chol is None or hdl is None:
        return -1

    male = _male(person)
    bp_treated = _flag(person, 'blood_pressure_controlled')

    short_age = _bound(_jdiv(age - 20, 5), 0, 11)
    long_age = _bound(_jdiv(age - 20, 10), 0, 5)
    chol_range = _bound(_jdiv(int(chol) - 160, 40) + 1, 0, 4)
    bp_range = _bound(_jdiv(int(systolic) - 120, 10) + 1, 0, 5)
    hdl_range = _bound(_jdiv(int(hdl) - 40, 10) + 1, 0, 3)

    points = _AGE_CHD[male][short_age]
    points += _AGE_CHOL_CHD[male][long_age][chol_range]
    if _flag(person, 'smoker'):
        points += _AGE_SMOKE_CHD[male][long_age]
    points += _HDL_CHD[hdl_range]
    points += _SYS_BP_CHD[male][bp_range][0 if bp_treated else 1]

    # Upstream bounds men at 0, so its "-1 means below zero" row is unreachable.
    if male:
        return _RISK_CHD_M[_bound(points, 0, 17)]
    return _RISK_CHD_F[_bound(points, 8, 25)]


# ----------------------------------------------------------------------------
# Framingham: atrial fibrillation.
# ----------------------------------------------------------------------------

# Age bands 45-49, 50-54, ... 80-84, >=85.
_AGE_AF = {True: [1, 2, 3, 4, 5, 6, 7, 7, 8], False: [-3, -2, 0, 1, 3, 4, 6, 7, 8]}

# Indexed by points, 0 (or less) to 10 (or more).
_RISK_AF = [0.01, 0.02, 0.02, 0.03, 0.04, 0.06, 0.08, 0.12, 0.16, 0.22, 0.3]


def atrial_fibrillation_10_year(person: 'Person', time: datetime) -> float:
    """Upstream ``Framingham.atrialFibrillation10Year``. Applies from age 45.

    Patients who already have atrial fibrillation (the ``atrial_fibrillation``
    attribute the module assigns at diagnosis) get no further risk.
    """
    age = person.age_in_years(time)
    systolic = person.get_vital_sign(SYSTOLIC)
    bmi = person.get_vital_sign(BMI)
    if (age < 45 or 'atrial_fibrillation' in person.attributes
            or systolic is None or bmi is None):
        return -1

    points = _AGE_AF[_male(person)][min(_jdiv(age - 45, 5), 8)]
    if bmi >= 30:
        points += 1
    if systolic >= 160:
        points += 1
    if _flag(person, 'blood_pressure_controlled'):
        points += 1
    return _RISK_AF[_bound(points, 0, 10)]


# ----------------------------------------------------------------------------
# Framingham: stroke.
# ----------------------------------------------------------------------------

# AHA prevalence of stroke by age and sex, (male, female), for ages the
# Framingham stroke points do not cover.
_STROKE_RATE_20_39 = (0.002, 0.007)
_STROKE_RATE_40_59 = (0.019, 0.022)

_TEN_YEAR_STROKE_RISK = (
    [0, 0.03, 0.03, 0.04, 0.04, 0.05, 0.05, 0.06, 0.07, 0.08, 0.1,
     0.11, 0.13, 0.15, 0.17, 0.2, 0.22, 0.26, 0.29, 0.33, 0.37, 0.42, 0.47, 0.52,
     0.57, 0.63, 0.68, 0.74, 0.79, 0.84, 0.88],
    [0, 0.01, 0.01, 0.02, 0.02, 0.02, 0.03, 0.04, 0.04, 0.05, 0.06,
     0.08, 0.09, 0.11, 0.13, 0.16, 0.19, 0.23, 0.27, 0.32, 0.37, 0.43, 0.5, 0.57,
     0.64, 0.71, 0.78, 0.84],
)

# The index of the range a value falls in is the number of points it scores.
_AGE_STROKE = ([54, 57, 60, 63, 66, 69, 73, 76, 79, 82, 85],
               [54, 57, 60, 63, 65, 68, 71, 74, 77, 79, 82])
_UNTREATED_SYS_BP_STROKE = ([0, 106, 116, 126, 136, 146, 156, 166, 176, 185, 196],
                            [0, 95, 107, 119, 131, 144, 156, 168, 181, 193, 205])
_TREATED_SYS_BP_STROKE = ([0, 106, 113, 118, 124, 130, 136, 143, 151, 162, 177],
                          [0, 95, 107, 114, 120, 126, 132, 140, 149, 161, 205])

_DIABETES_STROKE = (2, 3)
_CHD_STROKE = (4, 2)
_AF_STROKE = (4, 6)


def _range_index(value: int, bounds: Sequence[int]) -> int:
    """Upstream ``getIndexForValueInRangelist``; the last range is open-ended."""
    for i in range(len(bounds) - 1):
        if bounds[i] <= value <= bounds[i + 1]:
            return i
    if value >= bounds[-1]:
        return len(bounds) - 1
    raise ValueError(f'unexpected value {value} for ranges {list(bounds)}')


def stroke_10_year(person: 'Person', time: datetime) -> float:
    """Upstream ``Framingham.stroke10Year``. Applies from age 20."""
    systolic = person.get_vital_sign(SYSTOLIC)
    if systolic is None:
        return -1

    sex = 0 if _male(person) else 1
    age = person.age_in_years(time)
    if age < 20:
        return -1
    if age < 40:
        return _STROKE_RATE_20_39[sex]
    if age < 55:
        return _STROKE_RATE_40_59[sex]

    points = 0
    if _flag(person, 'smoker'):
        points += 3
    if _flag(person, 'left_ventricular_hypertrophy'):
        points += 5
    points += _range_index(age, _AGE_STROKE[sex])
    bp_ranges = (_TREATED_SYS_BP_STROKE if _flag(person, 'blood_pressure_controlled')
                 else _UNTREATED_SYS_BP_STROKE)
    points += _range_index(int(systolic), bp_ranges[sex])
    if _flag(person, 'diabetes'):
        points += _DIABETES_STROKE[sex]
    if _flag(person, 'coronary_heart_disease'):
        points += _CHD_STROKE[sex]
    if 'atrial_fibrillation' in person.attributes:
        points += _AF_STROKE[sex]

    table = _TEN_YEAR_STROKE_RISK[sex]
    return table[min(points, len(table) - 1)]


def timestep_days(person: 'Person', default: float = 7.0) -> float:
    """The simulation step in days, as the generator records it on the person."""
    years = person.attributes.get('timestep_years')
    return years * 365.25 if years else default
