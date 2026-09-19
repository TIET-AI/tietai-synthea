"""Value generation for Generic Module Framework states.

Several GMF states carry a value: the quantity an Observation records, how long
a Delay waits, how severe a Symptom is, what a SetAttribute stores. The value
can be written in several ways, and a state definition uses exactly one of them:

``exact``
    ``{"quantity": 5}`` - a literal.
``range``
    ``{"low": 250, "high": 500}`` - uniform between the bounds.
``distribution``
    ``{"kind": "GAUSSIAN", "parameters": {"mean": 90, "standardDeviation": 30}}``
    - a named distribution. Kinds in the bundled modules are EXACT, UNIFORM,
    GAUSSIAN (optionally clamped by ``min``/``max``) and EXPONENTIAL. A sibling
    ``round`` flag rounds the sample to a whole number.
``attribute`` / ``value_attribute``
    Read the value from one of the person's attributes.
``vital_sign``
    Read the person's current value for a vital sign.
``value`` / ``value_code``
    A literal value or a coded value.

Every draw comes from ``person.random`` so that a population seed reproduces
the values exactly.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any, Dict, Optional, Set, TYPE_CHECKING

logger = logging.getLogger(__name__)

#: How long one of each GMF time unit lasts. Months and years are the nominal
#: lengths upstream uses; simulation timesteps are far coarser than the error.
UNIT_TO_TIMEDELTA = {
    'years': timedelta(days=365),
    'year': timedelta(days=365),
    'months': timedelta(days=30),
    'month': timedelta(days=30),
    'weeks': timedelta(weeks=1),
    'week': timedelta(weeks=1),
    'days': timedelta(days=1),
    'day': timedelta(days=1),
    'hours': timedelta(hours=1),
    'hour': timedelta(hours=1),
    'minutes': timedelta(minutes=1),
    'minute': timedelta(minutes=1),
    'seconds': timedelta(seconds=1),
    'second': timedelta(seconds=1),
}

#: Units already reported as unknown, so each is logged once per process.
_WARNED_UNITS: Set[str] = set()

if TYPE_CHECKING:  # pragma: no cover - typing only
    from synthea.world.person import Person

#: Distribution kinds this engine understands.
KNOWN_KINDS = frozenset({'EXACT', 'UNIFORM', 'GAUSSIAN', 'EXPONENTIAL'})

#: Kinds already reported as unsupported, so each is logged once per process
#: rather than once per patient per timestep.
_WARNED_KINDS: Set[str] = set()


def sample_distribution(spec: Dict[str, Any], person: 'Person') -> float:
    """Draw one sample from a GMF ``distribution`` block.

    Args:
        spec: The distribution definition (``kind``, ``parameters``, ``round``).
        person: The person being simulated; supplies the random stream.

    Returns:
        The sampled value, rounded to an integer when ``round`` is true.
    """
    kind = str(spec.get('kind', 'EXACT')).upper()
    params = spec.get('parameters') or {}
    rand = person.random

    if kind == 'EXACT':
        value = _as_float(params.get('value'), 0.0)
    elif kind == 'UNIFORM':
        value = rand.uniform(_as_float(params.get('low'), 0.0),
                             _as_float(params.get('high'), 0.0))
    elif kind == 'GAUSSIAN':
        value = rand.gauss(_as_float(params.get('mean'), 0.0),
                           _as_float(params.get('standardDeviation'), 0.0))
        if 'min' in params:
            value = max(value, _as_float(params.get('min'), value))
        if 'max' in params:
            value = min(value, _as_float(params.get('max'), value))
    elif kind == 'EXPONENTIAL':
        mean = _as_float(params.get('mean'), 0.0)
        value = rand.expovariate(1.0 / mean) if mean > 0 else 0.0
    else:
        if kind not in _WARNED_KINDS:
            _WARNED_KINDS.add(kind)
            logger.warning(
                "Unsupported distribution kind '%s'; treating it as EXACT. "
                "Supported kinds: %s", kind, ', '.join(sorted(KNOWN_KINDS)),
            )
        value = _as_float(params.get('value'), 0.0)

    if spec.get('round'):
        value = float(round(value))
    return value


def value_for(definition: Dict[str, Any], person: 'Person',
              default: Any = None, attribute_key: Optional[str] = None) -> Any:
    """Resolve the value a state definition describes.

    Args:
        definition: The state (or child observation) definition.
        person: The person being simulated.
        default: Returned when the definition names no value at all.
        attribute_key: Which key, if any, names an attribute to read the value
            from. This differs by state: on ``Observation`` it is ``attribute``,
            while on ``SetAttribute`` the key ``attribute`` names the *target*
            of the assignment and the source is ``value_attribute``. Passing it
            explicitly keeps the two from being confused.

    Returns:
        The resolved value, or ``default``.
    """
    if 'exact' in definition:
        exact = definition['exact']
        if isinstance(exact, dict):
            return exact.get('quantity', default)
        return exact

    if 'range' in definition:
        bounds = definition['range']
        low = _as_float(bounds.get('low'), 0.0)
        high = _as_float(bounds.get('high'), 0.0)
        value = person.random.uniform(low, high)
        decimals = bounds.get('decimals')
        if decimals is not None:
            value = round(value, int(decimals))
        return value

    if 'distribution' in definition:
        return sample_distribution(definition['distribution'], person)

    if 'value_attribute' in definition:
        return person.attributes.get(definition['value_attribute'], default)

    if attribute_key and attribute_key in definition:
        return person.attributes.get(definition[attribute_key], default)

    if 'vital_sign' in definition:
        vital = person.get_vital_sign(definition['vital_sign'])
        return default if vital is None else vital

    if 'value_code' in definition:
        return definition['value_code']

    if 'value' in definition:
        return definition['value']

    return default


def passes_probability(definition: Dict[str, Any], person: 'Person') -> bool:
    """Whether an optional ``probability`` gate on a state lets it act.

    A ``Symptom`` state may carry ``"probability": 0.83``, meaning only 83% of
    patients reaching it express the symptom. Absent the key the state always
    acts.
    """
    probability = definition.get('probability')
    if probability is None:
        return True
    try:
        threshold = float(probability)
    except (TypeError, ValueError):
        return True
    return person.random.random() < threshold


def unit_for(definition: Dict[str, Any], default: str = 'days') -> str:
    """Find the time unit a definition uses.

    ``exact`` and ``range`` blocks carry their own ``unit``; a ``distribution``
    block does not, and the unit sits on the state instead.
    """
    for key in ('exact', 'range'):
        block = definition.get(key)
        if isinstance(block, dict) and block.get('unit'):
            return str(block['unit'])
    if definition.get('unit'):
        return str(definition['unit'])
    return default


def to_timedelta(quantity: Any, unit: str) -> timedelta:
    """Convert a quantity and a GMF time unit to a duration."""
    amount = _as_float(quantity, 0.0)
    span = UNIT_TO_TIMEDELTA.get(str(unit).lower())
    if span is None:
        if unit not in _WARNED_UNITS:
            _WARNED_UNITS.add(unit)
            logger.warning(
                "Unknown time unit '%s'; treating the quantity as days.", unit,
            )
        span = UNIT_TO_TIMEDELTA['days']
    return span * amount


def duration_for(definition: Dict[str, Any], person: 'Person') -> timedelta:
    """Resolve the duration a state describes, in any of the value forms."""
    quantity = value_for(definition, person, default=None)
    if quantity is None:
        return timedelta(0)
    return to_timedelta(quantity, unit_for(definition))


def _as_float(value: Any, default: float) -> float:
    """Coerce a JSON value to float, falling back to ``default``."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
