"""Tests for the states that end conditions, medications, care plans and devices.

A GMF end state names what to end in one of three ways, and the bundled modules
use all three: an attribute holding the entry, the name of the state that
started it, or the codes of the thing itself. Only the attribute form was
implemented, so 250 end states did nothing and chronic conditions never
resolved.
"""

from datetime import datetime, timedelta

import pytest

from synthea.engine.module import Module
from synthea.engine.state import (
    CarePlanEndState,
    CarePlanStartState,
    ConditionEndState,
    ConditionOnsetState,
    DeviceEndState,
    DeviceState,
    MedicationEndState,
    MedicationOrderState,
)
from synthea.world.person import Person

START = datetime(2020, 1, 1)
LATER = datetime(2020, 3, 1)

CONDITION_CODES = [{'system': 'SNOMED-CT', 'code': '444814009', 'display': 'Viral sinusitis'}]
MED_CODES = [{'system': 'RxNorm', 'code': 199885, 'display': 'levofloxacin 500MG'}]
PLAN_CODES = [{'system': 'SNOMED-CT', 'code': '412776001', 'display': 'Asthma care plan'}]
DEVICE_CODES = [{'system': 'SNOMED-CT', 'code': '336621006', 'display': 'Oxygen concentrator'}]


@pytest.fixture
def module():
    return Module('test')


@pytest.fixture
def person():
    person = Person(seed=5)
    person.init_health_record()
    encounter = person.record.encounter_start(START, 'ambulatory')
    person.attributes['current_encounter'] = encounter
    return person


def _start_condition(module, person, name='Sinusitis_Onset', assign_to=None):
    definition = {'type': 'ConditionOnset', 'codes': list(CONDITION_CODES)}
    if assign_to:
        definition['assign_to_attribute'] = assign_to
    ConditionOnsetState(module, name, definition).run(person, START)
    return person.record.conditions[-1]


def _start_medication(module, person, name='Levofloxacin', assign_to=None):
    definition = {'type': 'MedicationOrder', 'codes': list(MED_CODES)}
    if assign_to:
        definition['assign_to_attribute'] = assign_to
    MedicationOrderState(module, name, definition).run(person, START)
    return person.record.medications[-1]


class TestEndByStartStateName:
    """The form the modules use most: name the state that started it."""

    def test_condition_end_by_onset_state_name(self, module, person):
        """Regression: this was a `pass` stub, so nothing ever resolved."""
        condition = _start_condition(module, person)
        assert condition.is_active

        ConditionEndState(module, 'End_Sinusitis', {
            'type': 'ConditionEnd', 'condition_onset': 'Sinusitis_Onset',
        }).run(person, LATER)

        assert condition.end_time == LATER
        assert not condition.is_active

    def test_medication_end_by_order_state_name(self, module, person):
        medication = _start_medication(module, person)

        MedicationEndState(module, 'End_Levofloxacin', {
            'type': 'MedicationEnd', 'medication_order': 'Levofloxacin',
        }).run(person, LATER)

        assert medication.end_time == LATER

    def test_careplan_end_by_state_name(self, module, person):
        CarePlanStartState(module, 'ADHD_CarePlan', {
            'type': 'CarePlanStart', 'codes': list(PLAN_CODES),
        }).run(person, START)
        careplan = person.record.careplans[-1]

        CarePlanEndState(module, 'ADHD_CarePlan_Ends', {
            'type': 'CarePlanEnd', 'careplan': 'ADHD_CarePlan',
        }).run(person, LATER)

        assert careplan.end_time == LATER

    def test_device_end_by_state_name(self, module, person):
        DeviceState(module, 'Oxygen', {
            'type': 'Device', 'codes': list(DEVICE_CODES),
        }).run(person, START)
        device = person.record.devices[-1]

        DeviceEndState(module, 'End_Oxygen', {
            'type': 'DeviceEnd', 'device': 'Oxygen',
        }).run(person, LATER)

        assert device.end_time == LATER

    def test_only_the_named_state_is_ended(self, module, person):
        first = _start_condition(module, person, name='First')
        second = _start_condition(module, person, name='Second')

        ConditionEndState(module, 'End_First', {
            'type': 'ConditionEnd', 'condition_onset': 'First',
        }).run(person, LATER)

        assert first.end_time == LATER
        assert second.is_active

    def test_the_most_recent_still_active_entry_is_ended(self, module, person):
        older = _start_condition(module, person)
        ConditionEndState(module, 'End', {
            'type': 'ConditionEnd', 'condition_onset': 'Sinusitis_Onset',
        }).run(person, LATER)

        newer = _start_condition(module, person)
        ConditionEndState(module, 'End', {
            'type': 'ConditionEnd', 'condition_onset': 'Sinusitis_Onset',
        }).run(person, LATER + timedelta(days=30))

        assert older.end_time == LATER
        assert newer.end_time == LATER + timedelta(days=30)

    def test_entries_are_scoped_per_module(self, module, person):
        condition = _start_condition(module, person)

        ConditionEndState(Module('other'), 'End', {
            'type': 'ConditionEnd', 'condition_onset': 'Sinusitis_Onset',
        }).run(person, LATER)

        assert condition.is_active


class TestEndByCodes:
    def test_condition_end_by_codes(self, module, person):
        condition = _start_condition(module, person)

        ConditionEndState(module, 'End', {
            'type': 'ConditionEnd', 'codes': list(CONDITION_CODES),
        }).run(person, LATER)

        assert condition.end_time == LATER

    def test_numeric_codes_match(self, module, person):
        """RxNorm codes appear unquoted in the module JSON."""
        medication = _start_medication(module, person)

        MedicationEndState(module, 'End', {
            'type': 'MedicationEnd', 'codes': list(MED_CODES),
        }).run(person, LATER)

        assert medication.end_time == LATER

    def test_unrelated_codes_do_not_match(self, module, person):
        condition = _start_condition(module, person)

        ConditionEndState(module, 'End', {
            'type': 'ConditionEnd',
            'codes': [{'system': 'SNOMED-CT', 'code': '1', 'display': 'Something else'}],
        }).run(person, LATER)

        assert condition.is_active


class TestEndByAttribute:
    def test_still_works(self, module, person):
        condition = _start_condition(module, person, assign_to='sinusitis')

        ConditionEndState(module, 'End', {
            'type': 'ConditionEnd', 'referenced_by_attribute': 'sinusitis',
        }).run(person, LATER)

        assert condition.end_time == LATER

    def test_falls_back_to_the_other_forms(self, module, person):
        """A module may give both; an unset attribute must not stop the end."""
        condition = _start_condition(module, person)

        ConditionEndState(module, 'End', {
            'type': 'ConditionEnd',
            'referenced_by_attribute': 'never_set',
            'condition_onset': 'Sinusitis_Onset',
        }).run(person, LATER)

        assert condition.end_time == LATER


class TestNothingToEnd:
    def test_missing_entry_is_a_no_op(self, module, person):
        result = ConditionEndState(module, 'End', {
            'type': 'ConditionEnd', 'condition_onset': 'Never_Started',
        }).run(person, LATER)

        assert result is True

    def test_already_ended_entry_is_not_re_ended(self, module, person):
        condition = _start_condition(module, person)
        end_state = ConditionEndState(module, 'End', {
            'type': 'ConditionEnd', 'condition_onset': 'Sinusitis_Onset',
        })

        end_state.run(person, LATER)
        end_state.run(person, LATER + timedelta(days=60))

        assert condition.end_time == LATER

    def test_no_record_is_a_no_op(self, module):
        person = Person(seed=1)
        result = ConditionEndState(module, 'End', {
            'type': 'ConditionEnd', 'condition_onset': 'Whatever',
        }).run(person, LATER)

        assert result is True
