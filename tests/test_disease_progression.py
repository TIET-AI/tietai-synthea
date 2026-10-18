"""Engine semantics that decide whether disease modules ever reach a diagnosis.

Each of these was broken at the same time, and together they kept almost every
chronic condition out of the generated population: no patient was ever
diagnosed with diabetes, kidney disease, coronary disease or cancer, while
92% were given pulmonic valve stenosis. The unit tests pin each rule; the
population test at the end guards the combined effect.
"""

import logging
import re
from datetime import datetime, timedelta

import pytest

from synthea.engine.generator import Generator, GeneratorOptions
from synthea.engine.logic import Logic
from synthea.engine.module import Module
from synthea.engine.state import CounterState
from synthea.engine.transition import LookupTableTransition
from synthea.helpers.config import Config
from synthea.world import vitals
from synthea.world.health_record import EncounterClass
from synthea.world.person import Person

NOW = datetime(2020, 6, 1)


def _person(**attributes):
    person = Person(seed=7)
    person.attributes.update(attributes)
    person.init_health_record()
    return person


class TestEncounterEndResumes:
    """A module must carry on after an EncounterEnd, one step later."""

    MODULE = {
        'name': 'visit_then_more',
        'states': {
            'Initial': {'type': 'Initial', 'direct_transition': 'Visit'},
            'Visit': {'type': 'Encounter', 'encounter_class': 'ambulatory',
                      'direct_transition': 'End_Visit'},
            'End_Visit': {'type': 'EncounterEnd', 'direct_transition': 'After'},
            'After': {'type': 'SetAttribute', 'attribute': 'after_visit',
                      'value': True, 'direct_transition': 'Terminal'},
            'Terminal': {'type': 'Terminal'},
        },
    }

    def test_the_state_after_encounter_end_runs(self):
        module = Module._create_from_json('visit_then_more', self.MODULE)
        person = _person(birth_date=datetime(1980, 1, 1))

        module.process(person, NOW)
        assert 'after_visit' not in person.attributes, \
            "EncounterEnd yields for the rest of the step"

        module.process(person, NOW + timedelta(days=7))
        assert person.attributes.get('after_visit') is True

    def test_the_encounter_is_ended_once(self):
        module = Module._create_from_json('visit_then_more', self.MODULE)
        person = _person(birth_date=datetime(1980, 1, 1))

        module.process(person, NOW)
        module.process(person, NOW + timedelta(days=7))

        assert len(person.record.encounters) == 1
        assert person.record.encounters[0].end_time == NOW


class TestNilOperators:
    @pytest.mark.parametrize('value, is_nil', [
        (None, True), (True, False), (False, False), (0, False), ('', False),
    ])
    def test_existence_of_an_attribute(self, value, is_nil):
        person = _person()
        if value is not None:
            person.attributes['flag'] = value

        def test(operator):
            return Logic.test({'condition_type': 'Attribute', 'attribute': 'flag',
                               'operator': operator}, person, NOW)

        assert test('is nil') is is_nil
        assert test('is not nil') is (not is_nil)


class TestCounterAmount:
    @pytest.mark.parametrize('action, amount, expected', [
        ('decrement', 18, 37), ('increment', 3, 58), ('decrement', None, 54),
    ])
    def test_amount_is_applied(self, action, amount, expected):
        person = _person(countdown=55)
        definition = {'type': 'Counter', 'attribute': 'countdown', 'action': action}
        if amount is not None:
            definition['amount'] = amount

        CounterState(Module('m'), 'Count', definition).run(person, NOW)

        assert person.attributes['countdown'] == expected


class TestWholeYearAge:
    def test_age_in_years_counts_birthdays(self):
        person = _person(birth_date=datetime(2000, 6, 2))

        assert person.age_in_years(datetime(2020, 6, 1)) == 19
        assert person.age_in_years(datetime(2020, 6, 2)) == 20

    def test_a_fractional_age_matches_its_band(self):
        """4.5 years old is in the 0-4 band, not between 0-4 and 5-9."""
        rows = [{'age': '0-4', 'yes': '0.01', 'no': '0.99'},
                {'age': '5-9', 'yes': '0.02', 'no': '0.98'}]
        transition = LookupTableTransition({'lookup_table_transition': []})
        person = _person(birth_date=NOW - timedelta(days=int(4.5 * 365.25)))

        row = transition._matching_row('bands.csv', rows, person, NOW, {'yes', 'no'})

        assert row is rows[0]


class TestCalculatedVitals:
    def test_hba1c_follows_glycaemic_status(self):
        normal = vitals.calculate_vitals(_person(gender='F'), NOW)['Blood Glucose']
        pre = vitals.calculate_vitals(
            _person(gender='F', prediabetes=True), NOW)['Blood Glucose']

        diabetic = _person(gender='F', diabetes=True)
        diabetic.set_vital_sign('Body Mass Index', 40.0, 'kg/m2', NOW)
        diabetes = vitals.calculate_vitals(diabetic, NOW)['Blood Glucose']

        assert 5.0 <= normal <= 5.7
        assert 5.8 <= pre <= 6.4
        assert diabetes == pytest.approx(10.0)

    def test_treatment_does_not_push_hba1c_below_physiology(self):
        """Basal insulin takes 3 points off; a lean diabetic must not read 3.6%."""
        from synthea.world.health_record import Code

        person = _person(gender='F', diabetes=True)
        person.set_vital_sign('Body Mass Index', 24.0, 'kg/m2', NOW)
        person.record.medication_start(
            NOW, Code(system='RxNorm', code='106892', display='basal insulin'))

        assert vitals.calculate_vitals(person, NOW)['Blood Glucose'] == 6.0

    def test_egfr_follows_kidney_stage(self):
        values = vitals.calculate_vitals(
            _person(gender='M', ckd=4, birth_date=datetime(1950, 1, 1)), NOW)

        assert 1 <= values['EGFR'] <= 15

    def test_hypertension_raises_the_baseline(self):
        person = _person(gender='M', hypertension=True)
        vitals.calculate_vitals(person, NOW)

        assert 140 <= person.attributes['bp_baseline_True_systolic'] <= 161

    def test_modules_can_read_bmi_by_its_upstream_name(self):
        person = _person()
        person.set_vital_sign('Body Mass Index', 31.0, 'kg/m2', NOW)

        assert person.get_vital_sign('BMI') == 31.0
        assert Logic.test({'condition_type': 'Vital Sign', 'vital_sign': 'BMI',
                           'operator': '>=', 'value': 30}, person, NOW)


def test_virtual_encounters_are_a_class():
    assert EncounterClass('virtual') is EncounterClass.VIRTUAL


class TestPopulation:
    """The combined effect: chronic disease appears, valve stenosis does not
    swamp the population. Bounds are deliberately loose - this guards against
    a module silently never firing, not against a rate drifting."""

    @pytest.fixture(scope='class')
    def conditions(self):
        logging.disable(logging.WARNING)
        try:
            config = Config()
            config.load()
            config.set('exporter.fhir.export', False)
            options = GeneratorOptions()
            options.population_size = 60
            options.seed = 20261018
            options.min_age = 45
            options.max_age = 85
            options.reference_date = datetime(2020, 1, 1)
            generator = Generator(options, config=config)
            people = [generator.generate_person(i) for i in range(60)]
        finally:
            logging.disable(logging.NOTSET)
        return [
            {str(code.display if hasattr(code, 'display') else code.get('display'))
             for condition in person.record.conditions
             for code in (condition.codes or [])[:1]}
            for person in people if person is not None
        ]

    @staticmethod
    def _share(conditions, pattern):
        regex = re.compile(pattern, re.IGNORECASE)
        return sum(any(regex.search(d) for d in displays)
                   for displays in conditions) / len(conditions)

    def test_hypertension_is_diagnosed(self, conditions):
        assert self._share(conditions, r'hypertension') >= 0.10

    def test_disordered_glucose_is_diagnosed(self, conditions):
        assert self._share(conditions, r'prediabetes|diabetes mellitus') >= 0.10

    def test_valve_stenosis_is_rare(self, conditions):
        assert self._share(conditions, r'valve stenosis') <= 0.10
