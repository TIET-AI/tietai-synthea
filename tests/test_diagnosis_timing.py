"""Tests for onset recording and deferred diagnosis.

In GMF a condition's onset and its diagnosis are separate events:
``target_encounter`` names the Encounter state at which the condition is
diagnosed, while the onset happens when the ConditionOnset state runs. The
engine previously read ``target_encounter`` as a person-attribute name, so the
lookup failed and 263 ConditionOnset states (plus 22 AllergyOnset states)
recorded nothing at all.
"""

from datetime import datetime, timedelta

import pytest

from synthea.engine.module import Module
from synthea.engine.state import (
    AllergyOnsetState,
    ConditionOnsetState,
    EncounterEndState,
    EncounterState,
)
from synthea.world.person import Person

CODES = [{'system': 'SNOMED-CT', 'code': '59621000', 'display': 'Hypertension'}]
ALLERGY_CODES = [{'system': 'SNOMED-CT', 'code': '419474003', 'display': 'Allergy to mold'}]

ONSET = datetime(2020, 1, 1)
VISIT = datetime(2021, 6, 1)


@pytest.fixture
def person():
    person = Person(seed=99)
    person.init_health_record()
    return person


@pytest.fixture
def module():
    return Module('test')


def _onset_state(module, target=None, name='Onset'):
    definition = {'type': 'ConditionOnset', 'codes': list(CODES)}
    if target:
        definition['target_encounter'] = target
    return ConditionOnsetState(module, name, definition)


def _encounter_state(module, name='Diagnosis_Visit'):
    return EncounterState(module, name, {
        'type': 'Encounter', 'encounter_class': 'ambulatory',
    })


class TestOnsetIsAlwaysRecorded:
    def test_onset_without_any_encounter(self, person, module):
        _onset_state(module).run(person, ONSET)

        assert len(person.record.conditions) == 1
        condition = person.record.conditions[0]
        assert condition.time == ONSET
        assert condition.encounter is None

    def test_onset_inside_an_open_encounter_attaches_to_it(self, person, module):
        _encounter_state(module, 'Visit').run(person, ONSET)
        _onset_state(module).run(person, ONSET)

        condition = person.record.conditions[0]
        assert condition.encounter is person.attributes['current_encounter']
        assert condition in condition.encounter.conditions

    def test_codes_and_attribute_are_set(self, person, module):
        state = _onset_state(module)
        state.definition['assign_to_attribute'] = 'htn'
        state.run(person, ONSET)

        condition = person.record.conditions[0]
        assert person.attributes['htn'] is condition
        assert condition.codes[0].code == '59621000'
        assert condition.name == 'Onset'


class TestDeferredDiagnosis:
    def test_condition_waits_for_its_target_encounter(self, person, module):
        """Regression: this recorded nothing at all."""
        _onset_state(module, target='Diagnosis_Visit').run(person, ONSET)

        condition = person.record.conditions[0]
        assert condition.time == ONSET
        assert condition.encounter is None, "not diagnosed until the visit happens"

        _encounter_state(module).run(person, VISIT)

        assert condition.encounter is not None
        assert condition.encounter.time == VISIT
        assert condition in condition.encounter.conditions

    def test_onset_date_is_kept_when_the_diagnosis_arrives(self, person, module):
        _onset_state(module, target='Diagnosis_Visit').run(person, ONSET)
        _encounter_state(module).run(person, VISIT)

        condition = person.record.conditions[0]
        assert condition.time == ONSET
        assert condition.encounter.time == VISIT

    def test_a_different_encounter_does_not_claim_it(self, person, module):
        _onset_state(module, target='Diagnosis_Visit').run(person, ONSET)
        _encounter_state(module, 'Unrelated_Visit').run(person, VISIT)

        assert person.record.conditions[0].encounter is None

    def test_target_encounter_already_in_progress_diagnoses_immediately(self, person, module):
        _encounter_state(module, 'Diagnosis_Visit').run(person, VISIT)
        _onset_state(module, target='Diagnosis_Visit').run(person, VISIT)

        condition = person.record.conditions[0]
        assert condition.encounter is person.attributes['current_encounter']

    def test_an_undiagnosed_condition_stays_undiagnosed(self, person, module):
        """A module that ends before the visit leaves the condition unseen."""
        _onset_state(module, target='Never_Happens').run(person, ONSET)

        assert person.record.conditions[0].encounter is None

    def test_several_conditions_wait_for_the_same_visit(self, person, module):
        _onset_state(module, target='Diagnosis_Visit', name='A').run(person, ONSET)
        _onset_state(module, target='Diagnosis_Visit', name='B').run(
            person, ONSET + timedelta(days=30)
        )
        _encounter_state(module).run(person, VISIT)

        assert all(c.encounter is not None for c in person.record.conditions)
        assert len(person.record.conditions[0].encounter.conditions) == 2

    def test_a_claimed_diagnosis_is_not_claimed_twice(self, person, module):
        _onset_state(module, target='Diagnosis_Visit').run(person, ONSET)
        _encounter_state(module).run(person, VISIT)
        first_encounter = person.record.conditions[0].encounter

        EncounterEndState(module, 'End', {'type': 'EncounterEnd'}).run(person, VISIT)
        _encounter_state(module).run(person, VISIT + timedelta(days=200))

        assert person.record.conditions[0].encounter is first_encounter

    def test_pending_entries_are_scoped_per_module(self, person, module):
        other = Module('other')
        _onset_state(module, target='Diagnosis_Visit').run(person, ONSET)
        _encounter_state(other).run(person, VISIT)

        assert person.record.conditions[0].encounter is None


class TestAllergyOnset:
    def test_allergy_waits_for_its_target_encounter(self, person, module):
        state = AllergyOnsetState(module, 'Allergy', {
            'type': 'AllergyOnset',
            'codes': list(ALLERGY_CODES),
            'target_encounter': 'Diagnosis_Visit',
        })
        state.run(person, ONSET)

        allergy = person.record.allergies[0]
        assert allergy.time == ONSET
        assert allergy.encounter is None

        _encounter_state(module).run(person, VISIT)

        assert allergy.encounter is not None
        assert allergy.encounter.time == VISIT
