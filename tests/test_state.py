"""
Tests for the state machine system.
"""

import pytest
from datetime import datetime, timedelta
from synthea.engine.state import (
    State, StateType, InitialState, SimpleState, DelayState,
    GuardState, SetAttributeState, CounterState, ConditionOnsetState,
    AllergyOnsetState, AllergyEndState, CarePlanStartState,
    CarePlanEndState, CallSubmoduleState, DeviceState, DeviceEndState,
    SupplyListState, MultiObservationState, DiagnosticReportState,
)
from synthea.engine.module import Module
from synthea.world.person import Person


class TestStates:
    """Test state implementations."""
    
    def test_initial_state(self):
        """Test Initial state."""
        module = Module('test')
        state = InitialState(module, 'start', {'type': 'Initial'})
        person = Person()
        
        result = state.run(person, datetime.now())
        assert result is True  # Initial state always completes
    
    def test_simple_state(self):
        """Test Simple state."""
        module = Module('test')
        state = SimpleState(module, 'simple', {'type': 'Simple'})
        person = Person()
        
        result = state.run(person, datetime.now())
        assert result is True  # Simple state always completes
    
    def test_delay_state(self):
        """Test Delay state."""
        module = Module('test')
        definition = {
            'type': 'Delay',
            'delay': {
                'exact': {
                    'quantity': 7,
                    'unit': 'days'
                }
            }
        }
        state = DelayState(module, 'wait', definition)
        person = Person()
        
        # First run - should set delay and return False
        time1 = datetime.now()
        result1 = state.run(person, time1)
        assert result1 is False
        
        # Check delay was set
        delay_key = f'{module.name}_delays'
        assert delay_key in person.attributes
        assert 'wait' in person.attributes[delay_key]
        
        # Run again before delay expires - should return False
        time2 = time1 + timedelta(days=3)
        result2 = state.run(person, time2)
        assert result2 is False
        
        # Run after delay expires - should return True
        time3 = time1 + timedelta(days=8)
        result3 = state.run(person, time3)
        assert result3 is True
        
        # Delay should be cleared
        assert 'wait' not in person.attributes.get(delay_key, {})
    
    def test_set_attribute_state(self):
        """Test SetAttribute state."""
        module = Module('test')
        definition = {
            'type': 'SetAttribute',
            'attribute': 'test_attr',
            'value': 'test_value'
        }
        state = SetAttributeState(module, 'set', definition)
        person = Person()
        
        result = state.run(person, datetime.now())
        assert result is True
        assert person.attributes['test_attr'] == 'test_value'
    
    def test_counter_state(self):
        """Test Counter state."""
        module = Module('test')
        
        # Test increment
        inc_def = {
            'type': 'Counter',
            'attribute': 'counter',
            'action': 'increment'
        }
        inc_state = CounterState(module, 'inc', inc_def)
        person = Person()
        
        # First increment (from 0)
        inc_state.run(person, datetime.now())
        assert person.attributes['counter'] == 1
        
        # Second increment
        inc_state.run(person, datetime.now())
        assert person.attributes['counter'] == 2
        
        # Test decrement
        dec_def = {
            'type': 'Counter',
            'attribute': 'counter',
            'action': 'decrement'
        }
        dec_state = CounterState(module, 'dec', dec_def)
        
        dec_state.run(person, datetime.now())
        assert person.attributes['counter'] == 1
    
    def test_counter_state_none_attribute(self):
        """Counter state must not crash when the attribute is None or non-numeric."""
        module = Module('test')
        inc_def = {'type': 'Counter', 'attribute': 'counter', 'action': 'increment'}
        dec_def = {'type': 'Counter', 'attribute': 'counter', 'action': 'decrement'}
        person = Person()

        # Attribute explicitly set to None
        person.attributes['counter'] = None
        CounterState(module, 'inc', inc_def).run(person, datetime.now())
        assert person.attributes['counter'] == 1

        # Attribute set to a string
        person.attributes['counter'] = 'not_a_number'
        CounterState(module, 'inc', inc_def).run(person, datetime.now())
        assert person.attributes['counter'] == 1

        # Attribute set to float('inf') — int() raises OverflowError
        person.attributes['counter'] = float('inf')
        CounterState(module, 'dec', dec_def).run(person, datetime.now())
        assert person.attributes['counter'] == -1

    def test_guard_state(self):
        """Test Guard state."""
        module = Module('test')
        definition = {
            'type': 'Guard',
            'allow': {
                'condition_type': 'Attribute',
                'attribute': 'allowed',
                'value': True
            }
        }
        state = GuardState(module, 'guard', definition)
        person = Person()
        
        # Should not pass without attribute
        result1 = state.run(person, datetime.now())
        assert result1 is False
        
        # Set attribute to false - should not pass
        person.attributes['allowed'] = False
        result2 = state.run(person, datetime.now())
        assert result2 is False
        
        # Set attribute to true - should pass
        person.attributes['allowed'] = True
        result3 = state.run(person, datetime.now())
        assert result3 is True
    
    def test_state_factory(self):
        """Test state factory method."""
        module = Module('test')
        
        # Test creating different state types
        initial_def = {'type': 'Initial'}
        initial = State.create_state(module, 'init', initial_def)
        assert isinstance(initial, InitialState)
        
        simple_def = {'type': 'Simple'}
        simple = State.create_state(module, 'simple', simple_def)
        assert isinstance(simple, SimpleState)
        
        delay_def = {'type': 'Delay', 'delay': {'exact': {'quantity': 1, 'unit': 'days'}}}
        delay = State.create_state(module, 'delay', delay_def)
        assert isinstance(delay, DelayState)

    def _make_person_with_encounter(self):
        """Helper: create a Person with an initialised record and active encounter."""
        person = Person()
        person.init_health_record()
        encounter = person.record.encounter_start(datetime.now(), 'ambulatory')
        person.attributes['current_encounter'] = encounter
        return person

    def test_allergy_onset_state(self):
        """Test AllergyOnset state creates an allergy on the record."""
        module = Module('test')
        definition = {
            'type': 'AllergyOnset',
            'codes': [{'system': 'SNOMED-CT', 'code': '419474003', 'display': 'Allergy to mold'}],
            'assign_to_attribute': 'mold_allergy',
        }
        state = AllergyOnsetState(module, 'allergy_start', definition)
        person = self._make_person_with_encounter()

        result = state.run(person, datetime.now())
        assert result is True
        assert len(person.record.allergies) == 1
        assert person.record.allergies[0].name == 'allergy_start'
        assert 'mold_allergy' in person.attributes
        assert person.attributes['mold_allergy'] is person.record.allergies[0]

    def test_allergy_onset_no_encounter(self):
        """AllergyOnset does nothing without an active encounter."""
        module = Module('test')
        definition = {
            'type': 'AllergyOnset',
            'codes': [{'system': 'SNOMED-CT', 'code': '419474003', 'display': 'Allergy to mold'}],
        }
        state = AllergyOnsetState(module, 'allergy_start', definition)
        person = Person()
        person.init_health_record()

        result = state.run(person, datetime.now())
        assert result is True
        assert len(person.record.allergies) == 0

    def test_allergy_end_state(self):
        """Test AllergyEnd state ends an allergy via referenced_by_attribute."""
        module = Module('test')

        # First create an allergy
        onset_def = {
            'type': 'AllergyOnset',
            'codes': [{'system': 'SNOMED-CT', 'code': '419474003', 'display': 'Allergy to mold'}],
            'assign_to_attribute': 'mold_allergy',
        }
        person = self._make_person_with_encounter()
        AllergyOnsetState(module, 'onset', onset_def).run(person, datetime.now())

        # Now end it
        end_def = {
            'type': 'AllergyEnd',
            'referenced_by_attribute': 'mold_allergy',
        }
        end_state = AllergyEndState(module, 'end', end_def)
        now = datetime.now()
        result = end_state.run(person, now)
        assert result is True
        assert person.record.allergies[0].end_time == now

    def test_careplan_start_state(self):
        """Test CarePlanStart state creates a care plan."""
        module = Module('test')
        definition = {
            'type': 'CarePlanStart',
            'codes': [{'system': 'SNOMED-CT', 'code': '698360004', 'display': 'Diabetes self management plan'}],
            'activities': [
                {'system': 'SNOMED-CT', 'code': '160670007', 'display': 'Diabetic diet'},
            ],
            'goals': [
                {'text': 'Maintain blood sugar'},
            ],
            'reason': 'diabetes',
            'assign_to_attribute': 'diabetes_careplan',
        }
        state = CarePlanStartState(module, 'cp_start', definition)
        person = self._make_person_with_encounter()

        result = state.run(person, datetime.now())
        assert result is True
        assert len(person.record.careplans) == 1
        cp = person.record.careplans[0]
        assert cp.name == 'cp_start'
        assert cp.reason == 'diabetes'
        assert len(cp.activities) == 1
        assert len(cp.goals) == 1
        assert person.attributes['diabetes_careplan'] is cp

    def test_careplan_start_no_encounter(self):
        """CarePlanStart does nothing without an active encounter."""
        module = Module('test')
        definition = {
            'type': 'CarePlanStart',
            'codes': [{'system': 'SNOMED-CT', 'code': '698360004', 'display': 'Care plan'}],
        }
        state = CarePlanStartState(module, 'cp_start', definition)
        person = Person()
        person.init_health_record()

        result = state.run(person, datetime.now())
        assert result is True
        assert len(person.record.careplans) == 0

    def test_careplan_end_state(self):
        """Test CarePlanEnd state ends a care plan via referenced_by_attribute."""
        module = Module('test')

        # Start a care plan
        start_def = {
            'type': 'CarePlanStart',
            'codes': [{'system': 'SNOMED-CT', 'code': '698360004', 'display': 'Care plan'}],
            'assign_to_attribute': 'my_cp',
        }
        person = self._make_person_with_encounter()
        CarePlanStartState(module, 'start', start_def).run(person, datetime.now())

        # End it
        end_def = {
            'type': 'CarePlanEnd',
            'referenced_by_attribute': 'my_cp',
        }
        now = datetime.now()
        result = CarePlanEndState(module, 'end', end_def).run(person, now)
        assert result is True
        assert person.record.careplans[0].end_time == now

    def test_call_submodule_state_missing(self):
        """CallSubmodule returns True when the submodule is not found."""
        module = Module('test')
        definition = {
            'type': 'CallSubmodule',
            'submodule': 'nonexistent_module',
        }
        state = CallSubmoduleState(module, 'call', definition)
        person = Person()

        result = state.run(person, datetime.now())
        assert result is True

    def test_call_submodule_state_no_name(self):
        """CallSubmodule returns True when no submodule name is given."""
        module = Module('test')
        definition = {'type': 'CallSubmodule'}
        state = CallSubmoduleState(module, 'call', definition)
        person = Person()

        result = state.run(person, datetime.now())
        assert result is True

    def test_device_state(self):
        """Test Device state creates a device on the record."""
        module = Module('test')
        definition = {
            'type': 'Device',
            'codes': [{'system': 'SNOMED-CT', 'code': '705415000', 'display': 'Pacemaker'}],
            'assign_to_attribute': 'my_device',
        }
        state = DeviceState(module, 'device_start', definition)
        person = self._make_person_with_encounter()

        result = state.run(person, datetime.now())
        assert result is True
        assert len(person.record.devices) == 1
        assert person.record.devices[0].name == 'device_start'
        assert person.attributes['my_device'] is person.record.devices[0]

    def test_device_end_state(self):
        """Test DeviceEnd state ends a device via referenced_by_attribute."""
        module = Module('test')

        # Start a device
        start_def = {
            'type': 'Device',
            'codes': [{'system': 'SNOMED-CT', 'code': '705415000', 'display': 'Pacemaker'}],
            'assign_to_attribute': 'my_device',
        }
        person = self._make_person_with_encounter()
        DeviceState(module, 'start', start_def).run(person, datetime.now())

        # End it
        end_def = {
            'type': 'DeviceEnd',
            'referenced_by_attribute': 'my_device',
        }
        now = datetime.now()
        result = DeviceEndState(module, 'end', end_def).run(person, now)
        assert result is True
        assert person.record.devices[0].end_time == now

    def test_supply_list_state(self):
        """Test SupplyList state records supplies."""
        module = Module('test')
        definition = {
            'type': 'SupplyList',
            'supplies': [
                {
                    'code': {'system': 'SNOMED-CT', 'code': '468159004', 'display': 'Bandage'},
                    'quantity': 5,
                },
                {
                    'code': {'system': 'SNOMED-CT', 'code': '700621003', 'display': 'Gauze pad'},
                    'quantity': 10,
                },
            ],
        }
        state = SupplyListState(module, 'supplies', definition)
        person = self._make_person_with_encounter()

        result = state.run(person, datetime.now())
        assert result is True
        assert len(person.record.supplies) == 2
        assert person.record.supplies[0].quantity == 5
        assert person.record.supplies[1].quantity == 10

    def test_multi_observation_state(self):
        """Test MultiObservation state creates a report with child observations."""
        module = Module('test')
        definition = {
            'type': 'MultiObservation',
            'codes': [{'system': 'LOINC', 'code': '57698-3', 'display': 'Lipid Panel'}],
            'observations': [
                {
                    'codes': [{'system': 'LOINC', 'code': '2093-3', 'display': 'Total Cholesterol'}],
                    'exact': {'quantity': 200},
                    'unit': 'mg/dL',
                },
                {
                    'codes': [{'system': 'LOINC', 'code': '2571-8', 'display': 'Triglycerides'}],
                    'exact': {'quantity': 150},
                    'unit': 'mg/dL',
                },
            ],
        }
        state = MultiObservationState(module, 'lipid_panel', definition)
        person = self._make_person_with_encounter()

        result = state.run(person, datetime.now())
        assert result is True
        assert len(person.record.reports) == 1
        assert len(person.record.reports[0].observations) == 2
        assert len(person.record.observations) == 2

    def test_diagnostic_report_state(self):
        """Test DiagnosticReport state creates a report with child observations."""
        module = Module('test')
        definition = {
            'type': 'DiagnosticReport',
            'codes': [{'system': 'LOINC', 'code': '24323-8', 'display': 'CBC Panel'}],
            'observations': [
                {
                    'codes': [{'system': 'LOINC', 'code': '6690-2', 'display': 'WBC'}],
                    'exact': {'quantity': 7.5},
                    'unit': '10*3/uL',
                },
            ],
        }
        state = DiagnosticReportState(module, 'cbc', definition)
        person = self._make_person_with_encounter()

        result = state.run(person, datetime.now())
        assert result is True
        assert len(person.record.reports) == 1
        assert len(person.record.reports[0].observations) == 1

    def test_state_factory_new_types(self):
        """Test state factory creates the new state types correctly."""
        module = Module('test')

        cases = [
            ('AllergyOnset', AllergyOnsetState),
            ('AllergyEnd', AllergyEndState),
            ('CarePlanStart', CarePlanStartState),
            ('CarePlanEnd', CarePlanEndState),
            ('CallSubmodule', CallSubmoduleState),
            ('Device', DeviceState),
            ('DeviceEnd', DeviceEndState),
            ('SupplyList', SupplyListState),
            ('MultiObservation', MultiObservationState),
            ('DiagnosticReport', DiagnosticReportState),
        ]
        for type_name, expected_class in cases:
            defn = {'type': type_name}
            state = State.create_state(module, f'test_{type_name}', defn)
            assert isinstance(state, expected_class), f"Expected {expected_class} for {type_name}"