"""Paediatric growth from the CDC growth charts.

The bundled ``cdc_growth_charts.json`` holds, for height, weight, BMI and head
circumference, one entry per sex per age in months from 0 to 240. Each entry
carries the published percentile values plus the three LMS parameters (``l``,
``m``, ``s``) that generated them.

LMS lets us read the chart at *any* percentile rather than only the nine that
are tabulated, which is what a simulated child needs: each patient is assigned a
stable percentile at birth and then tracks it, so their height and weight are
correlated across their whole childhood instead of being redrawn each visit.

    X = M (1 + L S Z)^(1/L)     for L != 0
    X = M exp(S Z)              for L == 0

where ``Z`` is the standard normal deviate for the percentile.

Beyond 20 years the charts stop and adult weight change takes over; see
:mod:`synthea.world.vitals`.
"""

from __future__ import annotations

import json
import logging
import math
from typing import Dict, Optional

from synthea.helpers.resources import resource_path

logger = logging.getLogger(__name__)

#: Oldest age the CDC charts cover.
MAX_AGE_MONTHS = 240

#: Chart names in the bundled file.
HEIGHT = 'height'
WEIGHT = 'weight'
BMI = 'bmi'
HEAD = 'head'


class GrowthCharts:
    """Reads the CDC charts and evaluates them at an arbitrary percentile."""

    _data: Optional[Dict] = None

    @classmethod
    def load(cls) -> Dict:
        """Load and cache the chart data."""
        if cls._data is None:
            path = resource_path('cdc_growth_charts.json')
            try:
                with open(path, 'r', encoding='utf-8') as handle:
                    cls._data = json.load(handle)
            except (OSError, ValueError) as error:
                logger.warning("Could not read the CDC growth charts at %s: %s", path, error)
                cls._data = {}
        return cls._data

    @classmethod
    def available(cls) -> bool:
        """Whether the charts were found and parsed."""
        return bool(cls.load())

    @classmethod
    def value_at(cls, chart: str, gender: str, age_months: float,
                 percentile: float) -> Optional[float]:
        """Read a chart at a given age and percentile.

        Args:
            chart: One of ``height``, ``weight``, ``bmi``, ``head``.
            gender: ``'M'`` or ``'F'``.
            age_months: Age in months; clamped to the chart's range.
            percentile: A value in (0, 1).

        Returns:
            The measurement (centimetres for height, kilograms for weight), or
            ``None`` when the chart is unavailable.
        """
        data = cls.load()
        series = data.get(chart, {}).get(gender.upper() if gender else 'M')
        if not series:
            return None

        months = int(max(0, min(MAX_AGE_MONTHS, round(age_months))))
        entry = series.get(str(months))
        if entry is None:
            return None

        try:
            l = float(entry['l'])
            m = float(entry['m'])
            s = float(entry['s'])
        except (KeyError, TypeError, ValueError):
            return None

        z = z_score(percentile)
        if abs(l) < 1e-9:
            return m * math.exp(s * z)
        inner = 1.0 + l * s * z
        if inner <= 0:
            # Extreme percentile outside the chart's valid domain; fall back to
            # the median rather than producing a complex or negative result.
            return m
        return m * math.pow(inner, 1.0 / l)


def z_score(percentile: float) -> float:
    """Standard normal deviate for a percentile in (0, 1).

    Acklam's rational approximation; accurate to about 1.15e-9 across the range,
    which is far finer than the charts themselves.
    """
    p = min(max(float(percentile), 1e-6), 1 - 1e-6)

    a = (-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00)
    b = (-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01)
    c = (-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00)
    d = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00)

    low, high = 0.02425, 1 - 0.02425

    if p < low:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
               ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    if p > high:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
                ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)

    q = p - 0.5
    r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
           (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)


def bmi(weight_kg: float, height_cm: float) -> Optional[float]:
    """Body mass index, or None when height is unusable."""
    if not height_cm or height_cm <= 0:
        return None
    metres = height_cm / 100.0
    return weight_kg / (metres * metres)
