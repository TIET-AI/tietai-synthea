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

    @classmethod
    def values(cls, *path: str) -> Optional[List[float]]:
        """Fetch every number of a list by its path, e.g. a severity ladder."""
        node: Any = cls.load()
        for key in path:
            if not isinstance(node, dict) or key not in node:
                return None
            node = node[key]
        if not isinstance(node, list) or len(node) < 2:
            return None
        try:
            return [float(value) for value in node]
        except (TypeError, ValueError):
            return None


#: Units for the laboratory values the lifecycle keeps current. Modules read
#: these by name (``"vital_sign": "Glucose"``) on their Observation states and
#: Vital Sign conditions; they are not recorded at every visit.
LAB_UNITS: Dict[str, str] = {
    'Blood Glucose': '%',  # HbA1c, under the name upstream modules use
    'Glucose': 'mg/dL',
    'Urea Nitrogen': 'mg/dL',
    'Creatinine': 'mg/dL',
    'Calcium': 'mg/dL',
    'Sodium': 'mmol/L',
    'Potassium': 'mmol/L',
    'Chloride': 'mmol/L',
    'Carbon Dioxide': 'mmol/L',
    'Total Cholesterol': 'mg/dL',
    'Triglycerides': 'mg/dL',
    'LDL': 'mg/dL',
    'HDL': 'mg/dL',
    'EGFR': 'mL/min/{1.73_m2}',
    'Microalbumin Creatinine Ratio': 'mg/g',
}

#: RxNorm code -> expected HbA1c change, from upstream LifecycleModule.
DIABETES_DRUG_HBA1C_IMPACTS: Dict[str, float] = {
    '860975': -1.5,   # metformin
    '897122': -0.5,   # liraglutide
    '1373463': -0.5,  # canagliflozin
    '106892': -3.0,   # basal insulin
    '865098': -6.0,   # prandial insulin
}

#: Lowest HbA1c (%) treatment can bring a patient to; see calculate_vitals.
HBA1C_TREATED_FLOOR_DIABETES = 6.0
HBA1C_TREATED_FLOOR_PREDIABETES = 5.0

#: ``ckd`` attribute stage -> (creatinine clearance, microalbumin/creatinine).
_KIDNEY_RANGES = {
    1: ('mild_kidney_damage', 'normal'),
    2: ('moderate_kidney_damage', 'microalbuminuria_controlled'),
    3: ('severe_kidney_damage', 'microalbuminuria_uncontrolled'),
    4: ('esrd', 'proteinuria'),
}


def calculate_vitals(person: 'Person', time: datetime) -> Dict[str, float]:
    """The vitals and laboratory values implied by the patient's state now.

    A port of upstream ``LifecycleModule.calculateVitalSigns``. The disease
    modules diagnose from these values - HbA1c for diabetes, eGFR for kidney
    disease, the lipid panel and blood pressure for metabolic syndrome - so a
    patient's values must follow their ``diabetes_severity``, ``prediabetes``,
    ``hypertension``, ``ckd`` and ``chf`` attributes. Only a healthy baseline
    for five vitals used to be drawn, and every lab was unset: HbA1c was
    recorded with no value and every patient with prediabetes was diagnosed
    with diabetes.

    Values come from the person's own generator, so they are reproducible.
    """
    attributes = person.attributes
    random = person.random
    female = attributes.get('gender') == 'F'
    values: Dict[str, float] = {}

    severity = attributes.get('diabetes_severity')
    index = int(severity) if isinstance(severity, (int, float)) else 0
    index = max(0, min(index, 4))

    values.update(_lipids(person, index))

    hba1c = _hba1c(person)
    if attributes.get('prediabetes') or attributes.get('diabetes'):
        # Only patients with (pre)diabetes are prescribed these.
        for code, impact in DIABETES_DRUG_HBA1C_IMPACTS.items():
            if _medication_active(person, code):
                hba1c += impact
        # Deliberate deviation from upstream, which subtracts the impacts with
        # no floor: a lean diabetic on basal insulin read 6.6 - 3.0 = 3.6% at
        # every visit for life, below any healthy adult. Treatment brings a
        # diabetic towards goal, not under it; 6.0 keeps a treated diabetic in
        # the band metabolic_syndrome_care already handles as "controlled"
        # (Set_Severity_0 -> PriorState Diagnose_Diabetes -> Check_CarePlan).
        floor = HBA1C_TREATED_FLOOR_DIABETES if attributes.get('diabetes') \
            else HBA1C_TREATED_FLOOR_PREDIABETES
        hba1c = max(hba1c, floor)
    values['Blood Glucose'] = round(hba1c, 1)

    saturation = Biometrics.range(
        'cardiovascular', 'oxygen_saturation',
        'hypoxemia' if attributes.get('chf') else 'normal')
    if saturation:
        values['Oxygen Saturation'] = float(int(random.uniform(*saturation)))

    values.update(_kidney(person, time, female))

    for name, key in (('Urea Nitrogen', 'urea_nitrogen'), ('Calcium', 'calcium'),
                      ('Chloride', 'chloride'), ('Potassium', 'potassium'),
                      ('Carbon Dioxide', 'carbon_dioxide'), ('Sodium', 'sodium')):
        bounds = Biometrics.range('metabolic', 'basic_panel', 'normal', key)
        if bounds:
            values[name] = round(random.uniform(*bounds), 1)

    glucose = Biometrics.values('metabolic', 'basic_panel', 'glucose')
    if glucose:
        step = min(index, 2)
        values['Glucose'] = round(random.uniform(glucose[step], glucose[step + 1]), 1)

    heart_rate = Biometrics.range('cardiovascular', 'heart_rate', 'normal')
    if heart_rate:
        values['Heart Rate'] = round(random.uniform(*heart_rate), 1)
    respiration = Biometrics.range('respiratory', 'respiration_rate', 'normal')
    if respiration:
        values['Respiration Rate'] = round(random.uniform(*respiration), 1)

    values.update(_blood_pressure(person))
    return values


def _lipids(person: 'Person', index: int) -> Dict[str, float]:
    """Lipid panel: NCHS population rates without diabetes, the ladder with it."""
    attributes = person.attributes
    random = person.random
    cholesterol = Biometrics.values('metabolic', 'lipid_panel', 'cholesterol')
    triglyceride = Biometrics.values('metabolic', 'lipid_panel', 'triglycerides')
    hdl_ladder = Biometrics.values('metabolic', 'lipid_panel', 'hdl')
    if not (cholesterol and triglyceride and hdl_ladder):
        return {}

    triglycerides = random.uniform(triglyceride[index], triglyceride[index + 1])

    if index == 0:
        # NCHS Data Brief 363 (2020): low HDL in 26.6% of men and 8.5% of
        # women; high total cholesterol in 11.4% of adults. Decided once so a
        # patient keeps their status.
        if 'low_hdl' not in attributes:
            chance = 0.085 if attributes.get('gender') == 'F' else 0.266
            attributes['low_hdl'] = random.random() < chance
            attributes['high_total_chol'] = random.random() < 0.114
        hdl = (3 * random.gauss(0, 1) + 30 if attributes['low_hdl']
               else 5 * random.gauss(0, 1) + 55)
        total = (20 * random.gauss(0, 1) + 280 if attributes['high_total_chol']
                 else 30 * random.gauss(0, 1) + 170)
    else:
        total = random.uniform(cholesterol[index], cholesterol[index + 1])
        hdl = random.uniform(hdl_ladder[index + 1], hdl_ladder[index])

    return {
        'Total Cholesterol': round(total, 1),
        'Triglycerides': round(triglycerides, 1),
        'HDL': round(hdl, 1),
        'LDL': round(total - hdl - 0.2 * triglycerides, 1),
    }


def _hba1c(person: 'Person') -> float:
    """Upstream ``estimateHbA1c``: BMI-driven with diabetes, banded without."""
    if person.attributes.get('diabetes'):
        bmi = person.get_vital_sign('Body Mass Index') or 0.0
        if bmi > 48.0:
            return 12.0
        if bmi <= 27.0:
            return 6.6
        return bmi / 4.0
    if person.attributes.get('prediabetes'):
        return person.random.uniform(5.8, 6.4)
    return person.random.uniform(5.0, 5.7)


def _kidney(person: 'Person', time: datetime, female: bool) -> Dict[str, float]:
    """eGFR, microalbumin/creatinine ratio and creatinine for the CKD stage."""
    stage = person.attributes.get('ckd')
    stage = int(stage) if isinstance(stage, (int, float)) else 0
    clearance_key, ratio_key = _KIDNEY_RANGES.get(stage, (None, 'normal'))

    if clearance_key:
        clearance_range = Biometrics.range(
            'metabolic', 'basic_panel', 'creatinine_clearance', clearance_key)
    else:
        clearance_range = Biometrics.range(
            'metabolic', 'basic_panel', 'creatinine_clearance', 'normal',
            'female' if female else 'male')
    ratio_range = Biometrics.range(
        'metabolic', 'basic_panel', 'microalbumin_creatinine_ratio', ratio_key)
    if not (clearance_range and ratio_range):
        return {}

    clearance = person.random.uniform(*clearance_range)
    values = {
        'EGFR': round(clearance, 1),
        'Microalbumin Creatinine Ratio': round(person.random.uniform(*ratio_range), 1),
        'Creatinine': 1.0,
    }

    # Cockcroft-Gault solved for creatinine, as upstream does.
    weight = person.get_vital_sign('Weight')
    if weight:
        age = person.age_in_years(time)
        bounded = max(1.0, min(clearance, 100.0))
        creatinine = ((140.0 - age) * weight) / (72.0 * bounded)
        if female:
            creatinine *= 0.85
        values['Creatinine'] = round(creatinine, 2)
    return values


def _blood_pressure(person: 'Person') -> Dict[str, float]:
    """Upstream ``BloodPressureValueGenerator``, without the drug table.

    A baseline is drawn once per hypertension status - from the hypertensive
    range (its upper half when ``hypertension_severe``) once the patient has
    hypertension - and a visit adds a normal variation (SD 8 systolic, 5
    diastolic) with the same sign for both. Upstream also subtracts the effect
    of active antihypertensives from ``htn_drugs.csv``; that table is not
    bundled, so treated patients keep their untreated baseline.
    """
    attributes = person.attributes
    hypertension = bool(attributes.get('hypertension'))
    severe = bool(attributes.get('hypertension_severe'))
    sign = 1 if person.random.random() < 0.5 else -1
    values: Dict[str, float] = {}

    for name, key, sd in (('Systolic Blood Pressure', 'systolic', 8.0),
                          ('Diastolic Blood Pressure', 'diastolic', 5.0)):
        cache = f'bp_baseline_{hypertension}_{key}'
        baseline = attributes.get(cache)
        if baseline is None:
            baseline = _bp_baseline(person, key, hypertension, severe)
            if baseline is None:
                continue
            attributes[cache] = baseline
        variation = abs(person.random.gauss(0, 1)) * sd * sign
        values[name] = round(baseline + variation, 1)

    return values


def _bp_baseline(person: 'Person', key: str, hypertension: bool,
                 severe: bool) -> Optional[float]:
    if hypertension:
        ladder = Biometrics.values('metabolic', 'blood_pressure', 'hypertensive', key)
        if not ladder:
            return None
        if key == 'systolic' and len(ladder) >= 3 and severe:
            low, high = ladder[1], ladder[2]
        else:
            low, high = ladder[0], ladder[1]
    else:
        bounds = Biometrics.range('metabolic', 'blood_pressure', 'normal', key)
        if not bounds:
            return None
        low, high = bounds
    baseline = person.random.uniform(low, high)
    return baseline + (1 if person.attributes.get('gender') == 'M' else -1)


def _medication_active(person: 'Person', rxnorm: str) -> bool:
    record = getattr(person, 'record', None)
    if record is None:
        return False
    return record.has_active_medication(Code(system='RxNorm', code=rxnorm, display=''))


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
