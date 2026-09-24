"""Reference ranges, interpretation flags, and coherence within a lab panel.

Two problems, both reported in #113 with measurements.

**No reference range, no interpretation.** Every generated Observation carried a
value and nothing to compare it against: 0 of 2,323 had `referenceRange`, 0 had
`interpretation`. Both are standard FHIR R4 elements and near-universal on a
real report. Anything that renders a report, or scores whether a system spotted
an abnormal result, had to invent the range — and its guess would not match the
one the module author had in mind when they picked the value.

**Panel members contradicted each other.** MCV, MCH and MCHC are *definitions*,
not independent measurements:

    MCV = HCT x 10 / RBC      MCH = HGB x 10 / RBC      MCHC = HGB x 100 / HCT

The modules draw each from its own uniform range, so they disagree: 6 of 8
complete red-cell panels had an MCV more than 3 fL from the value its own HCT
and RBC imply, and 7 of 8 had an MCHC more than 1.5 g/dL out. This is inherited
from upstream Java Synthea, which shares the module JSON, rather than being a
port defect.

The fix is not to edit 256 module files. It is to pick the independent
quantities and compute the rest at the point the panel is recorded.

**Which quantities are independent** is a judgement, and worth stating. The
reporter suggested RBC, MCV and MCHC. This uses **HGB, MCV and MCHC**, because
those are the three a module author actually reaches for:

- `HGB` is how every bundled module expresses the *severity* of an anaemia.
- `MCV` is how it expresses the *classification* — microcytic, normocytic,
  macrocytic.
- `MCHC` is tightly regulated physiologically and rarely the author's point, so
  keeping an authored value costs nothing and a default is safe when absent.

RBC and HCT are then derived. Taking RBC as independent instead would preserve a
number no module chooses deliberately while overriding HGB, which is the one
carrying the clinical meaning. On the reported panel that choice matters:

    HGB 13.55, MCV 85.3, MCHC 33.0
      -> HCT 41.1 (was 46.9, implausible against that haemoglobin)
      -> RBC 4.81, MCH 28.2  (both mid-range, where before MCH implied 24.6)
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

from synthea.helpers.resources import resource_path

logger = logging.getLogger(__name__)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from synthea.world.person import Person

# ----------------------------------------------------------------------
# LOINC codes this module reasons about
# ----------------------------------------------------------------------

HGB = '718-7'
HCT = '4544-3'
RBC = '789-8'
MCV = '787-2'
MCH = '785-6'
MCHC = '786-4'

TOTAL_PROTEIN = '2885-2'
ALBUMIN = '1751-7'
GLOBULIN = '10834-0'
AG_RATIO = '1759-0'

DIFFERENTIAL = ('770-8', '736-9', '5905-5', '713-8', '706-2')

#: Used when a panel gives no MCHC. Mean corpuscular haemoglobin concentration
#: is held in a narrow band in life, so a fixed value is a better answer than
#: leaving the panel unsolvable.
DEFAULT_MCHC = 33.5

#: Used when a panel gives neither MCV nor enough to derive it.
DEFAULT_MCV = 90.0


class ReferenceRanges:
    """Reference intervals from ``reference_ranges.json``."""

    _data: Optional[Dict[str, List[Dict[str, Any]]]] = None

    @classmethod
    def load(cls) -> Dict[str, List[Dict[str, Any]]]:
        if cls._data is None:
            path = resource_path('reference_ranges.json')
            try:
                with open(path, 'r', encoding='utf-8') as handle:
                    cls._data = (json.load(handle) or {}).get('ranges', {})
            except (OSError, ValueError) as error:
                logger.warning("Could not read reference ranges at %s: %s",
                               path, error)
                cls._data = {}
        return cls._data

    @classmethod
    def for_code(cls, code: str, sex: Optional[str] = None,
                 age: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """The reference interval for a code, or None if there is not one.

        Variants are tried in order and the first whose selectors match wins,
        so a variant with no selectors must come last in the file.
        """
        variants = cls.load().get(str(code), [])
        eligible = []

        for variant in variants:
            minimum = variant.get('min_age')
            if minimum is not None and (age is None or age < minimum):
                continue
            eligible.append(variant)

        for variant in eligible:
            wanted_sex = variant.get('sex')
            if wanted_sex and str(sex or '').upper()[:1] != wanted_sex:
                continue
            return variant

        # Sex-specific code, unknown sex. Returning nothing would silently drop
        # the range for haemoglobin, haematocrit, red cell count and creatinine
        # whenever gender is not recorded. The union of the intervals is the
        # range you would use without knowing, and it cannot flag a value
        # abnormal that either sex's interval would call normal.
        if eligible and all(variant.get('sex') for variant in eligible):
            lows = [v['low'] for v in eligible if v.get('low') is not None]
            highs = [v['high'] for v in eligible if v.get('high') is not None]
            widest = dict(eligible[0])
            widest.pop('sex', None)
            if lows:
                widest['low'] = min(lows)
            if highs:
                widest['high'] = max(highs)
            return widest

        return None


def reference_range_for(code: str, person: Optional['Person'] = None,
                        time=None) -> Optional[Dict[str, Any]]:
    """The reference interval for a code, for this patient."""
    sex = None
    age = None
    if person is not None:
        sex = person.attributes.get('gender')
        if time is not None:
            try:
                age = person.age_at(time)
            except Exception:  # pragma: no cover - defensive
                age = None

    return ReferenceRanges.for_code(code, sex, age)


def interpretation_for(value: Any, low: Optional[float],
                       high: Optional[float]) -> Optional[Tuple[str, str]]:
    """`(code, display)` from HL7 v3-ObservationInterpretation, or None.

    Only the three flags a reader acts on: high, low, normal. Deliberately not
    `HH`/`LL` — a critical threshold is not the same as the top of a reference
    interval, and inventing one would put a panic flag on a result nobody
    decided was panic-worthy.
    """
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None

    if high is not None and value > high:
        return ('H', 'High')
    if low is not None and value < low:
        return ('L', 'Low')
    if low is not None or high is not None:
        return ('N', 'Normal')

    return None


def annotate(observation, person: Optional['Person'] = None) -> None:
    """Attach the reference range and interpretation to an observation."""
    if not observation.codes:
        return

    code = str(observation.codes[0].code)
    variant = reference_range_for(code, person, observation.time)
    if variant is None:
        return

    low = variant.get('low')
    high = variant.get('high')

    observation.reference_range = {
        'low': low,
        'high': high,
        'unit': variant.get('unit') or observation.unit,
    }
    observation.interpretation = interpretation_for(observation.value, low, high)


# ----------------------------------------------------------------------
# Coherence within a panel
# ----------------------------------------------------------------------

def _numeric(observations: Dict[str, Any], code: str) -> Optional[float]:
    entry = observations.get(code)
    if entry is None:
        return None
    value = getattr(entry, 'value', None)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _set(observations: Dict[str, Any], code: str, value: float,
         digits: int = 1) -> None:
    entry = observations.get(code)
    if entry is not None:
        entry.value = round(value, digits)


def red_cell_indices(observations: Dict[str, Any]) -> None:
    """Make the red-cell panel satisfy its own definitions.

    Independent: HGB, MCV, MCHC. Derived: HCT, RBC, MCH. See the module
    docstring for why that triple.
    """
    hgb = _numeric(observations, HGB)
    hct = _numeric(observations, HCT)
    mcv = _numeric(observations, MCV)
    mchc = _numeric(observations, MCHC)
    rbc = _numeric(observations, RBC)

    # Nothing to reconcile unless at least one derived member is present.
    if not any(code in observations for code in (HCT, RBC, MCH)):
        return

    if mchc is None or mchc <= 0:
        mchc = DEFAULT_MCHC

    if hgb is None:
        if hct is not None:
            hgb = hct * mchc / 100.0
        else:
            return  # No anchor for the panel; leave it alone.

    if mcv is None or mcv <= 0:
        if hct is not None and rbc:
            mcv = hct * 10.0 / rbc
        else:
            mcv = DEFAULT_MCV

    hct = hgb * 100.0 / mchc
    rbc = hct * 10.0 / mcv
    mch = hgb * 10.0 / rbc if rbc else None

    _set(observations, HCT, hct)
    _set(observations, RBC, rbc, digits=2)
    _set(observations, MCV, mcv)
    _set(observations, MCHC, mchc)
    if mch is not None:
        _set(observations, MCH, mch)


def protein_fractions(observations: Dict[str, Any]) -> None:
    """Globulin is total protein minus albumin, and A/G follows from both."""
    total = _numeric(observations, TOTAL_PROTEIN)
    albumin = _numeric(observations, ALBUMIN)

    if total is None or albumin is None:
        return

    # A total protein below its albumin is not a result, it is a contradiction.
    if albumin > total:
        albumin = total * 0.6
        _set(observations, ALBUMIN, albumin, digits=2)

    globulin = total - albumin
    _set(observations, GLOBULIN, globulin, digits=2)

    if globulin > 0:
        _set(observations, AG_RATIO, albumin / globulin, digits=2)


def differential(observations: Dict[str, Any]) -> None:
    """A white-cell differential has to add up to 100%.

    Scaled rather than clamped, so the clinical picture the module drew — a
    neutrophilia, a lymphocytosis — survives the correction.
    """
    present = [code for code in DIFFERENTIAL if code in observations]
    values = [_numeric(observations, code) for code in present]

    if len(present) < 2 or any(value is None for value in values):
        return

    total = sum(values)
    if total <= 0 or abs(total - 100.0) < 0.05:
        return

    scaled = [value * 100.0 / total for value in values]

    # Put the rounding residue on the largest fraction, where it is
    # proportionally smallest.
    rounded = [round(value, 1) for value in scaled]
    residue = round(100.0 - sum(rounded), 1)
    if residue:
        largest = max(range(len(rounded)), key=lambda i: rounded[i])
        rounded[largest] = round(rounded[largest] + residue, 1)

    for code, value in zip(present, rounded):
        _set(observations, code, value)


def make_coherent(observations: List[Any]) -> None:
    """Apply every panel rule to one encounter's observations.

    Takes the latest observation per code, because an encounter can record the
    same analyte more than once and the last is the one a reader sees.
    """
    by_code: Dict[str, Any] = {}
    for observation in observations:
        if observation.codes:
            by_code[str(observation.codes[0].code)] = observation

    red_cell_indices(by_code)
    protein_fractions(by_code)
    differential(by_code)
