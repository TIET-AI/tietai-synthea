"""Vital signs and their LOINC codes.

Reference ranges come from the bundled ``biometrics.yml``, the same file the
disease modules draw on, so a patient's baseline vitals and the values a module
sets are on the same scale.

Two things this module deliberately does *not* do:

- It does not overwrite a vital a disease module has already set for this visit.
  A hypertension module raising blood pressure must win over the healthy
  baseline.
- It does not invent a value when the reference data is missing; the caller
  simply records nothing.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, TYPE_CHECKING

import yaml

from synthea.helpers.resources import resource_path
from synthea.world.health_record import Code

logger = logging.getLogger(__name__)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from synthea.world.person import Person

LOINC = 'http://loinc.org'


def _code(code: str, display: str) -> Code:
    return Code(system=LOINC, code=code, display=display)


#: LOINC codes and units for the vitals the lifecycle records at each visit.
VITAL_CODES: Dict[str, Dict[str, Any]] = {
    'Height': {'code': _code('8302-2', 'Body Height'), 'unit': 'cm'},
    'Weight': {'code': _code('29463-7', 'Body Weight'), 'unit': 'kg'},
    'Body Mass Index': {'code': _code('39156-5', 'Body mass index (BMI) [Ratio]'),
                        'unit': 'kg/m2'},
    'Systolic Blood Pressure': {'code': _code('8480-6', 'Systolic blood pressure'),
                                'unit': 'mm[Hg]'},
    'Diastolic Blood Pressure': {'code': _code('8462-4', 'Diastolic blood pressure'),
                                 'unit': 'mm[Hg]'},
    'Heart Rate': {'code': _code('8867-4', 'Heart rate'), 'unit': '/min'},
    'Respiration Rate': {'code': _code('9279-1', 'Respiratory rate'), 'unit': '/min'},
    'Oxygen Saturation': {
        'code': _code('2708-6', 'Oxygen saturation in Arterial blood'), 'unit': '%'},
}

#: The blood pressure panel, recorded as one Observation with two components.
BLOOD_PRESSURE_PANEL = _code('85354-9', 'Blood pressure panel with all children optional')


class Biometrics:
    """Reference ranges from ``biometrics.yml``."""

    _data: Optional[Dict] = None

    @classmethod
    def load(cls) -> Dict:
        if cls._data is None:
            path = resource_path('biometrics.yml')
            try:
                with open(path, 'r', encoding='utf-8') as handle:
                    cls._data = yaml.safe_load(handle) or {}
            except (OSError, ValueError) as error:
                logger.warning("Could not read biometrics at %s: %s", path, error)
                cls._data = {}
        return cls._data

    @classmethod
    def range(cls, *path: str) -> Optional[List[float]]:
        """Fetch a ``[low, high]`` range by its path in the file."""
        node: Any = cls.load()
        for key in path:
            if not isinstance(node, dict) or key not in node:
                return None
            node = node[key]
        if isinstance(node, list) and len(node) >= 2:
            try:
                return [float(node[0]), float(node[1])]
            except (TypeError, ValueError):
                return None
        return None


def baseline_vitals(person: 'Person') -> Dict[str, float]:
    """Draw a healthy baseline for the vitals that are not height or weight.

    Values are drawn from the person's own generator, so they are reproducible,
    and are re-drawn per visit rather than held constant: a patient's heart rate
    is not the same number at every appointment.
    """
    values: Dict[str, float] = {}

    systolic = Biometrics.range('metabolic', 'blood_pressure', 'normal', 'systolic')
    diastolic = Biometrics.range('metabolic', 'blood_pressure', 'normal', 'diastolic')
    heart_rate = Biometrics.range('cardiovascular', 'heart_rate', 'normal')
    respiration = Biometrics.range('respiratory', 'respiration_rate', 'normal')
    saturation = Biometrics.range('cardiovascular', 'oxygen_saturation', 'normal')

    if systolic:
        values['Systolic Blood Pressure'] = round(person.random.uniform(*systolic), 1)
    if diastolic:
        values['Diastolic Blood Pressure'] = round(person.random.uniform(*diastolic), 1)
    if heart_rate:
        values['Heart Rate'] = round(person.random.uniform(*heart_rate), 1)
    if respiration:
        values['Respiration Rate'] = round(person.random.uniform(*respiration), 1)
    if saturation:
        values['Oxygen Saturation'] = round(person.random.uniform(*saturation), 1)

    return values


def record_vitals(person: 'Person', time: datetime, encounter) -> List[Any]:
    """Record the person's current vitals as Observations on an encounter.

    Blood pressure is recorded as a single panel Observation with systolic and
    diastolic components, which is how US Core expects it; the rest are simple
    quantities. All carry the ``vital-signs`` category.

    Returns the Observations created.
    """
    if getattr(person, 'record', None) is None or encounter is None:
        return []

    created = []

    systolic = person.get_vital_sign('Systolic Blood Pressure')
    diastolic = person.get_vital_sign('Diastolic Blood Pressure')
    if systolic is not None and diastolic is not None:
        panel = person.record.observation(time, BLOOD_PRESSURE_PANEL, None, None, encounter)
        panel.category = 'vital-signs'
        panel.name = 'Blood Pressure'
        panel.components = [
            (VITAL_CODES['Systolic Blood Pressure']['code'], systolic, 'mm[Hg]'),
            (VITAL_CODES['Diastolic Blood Pressure']['code'], diastolic, 'mm[Hg]'),
        ]
        created.append(panel)

    for name, spec in VITAL_CODES.items():
        if name in ('Systolic Blood Pressure', 'Diastolic Blood Pressure'):
            continue  # recorded above as a panel
        value = person.get_vital_sign(name)
        if value is None:
            continue
        observation = person.record.observation(
            time, spec['code'], value, spec['unit'], encounter,
        )
        observation.category = 'vital-signs'
        observation.name = name
        created.append(observation)

    return created
