"""
Tests for the state machine system.
"""

import pytest
from datetime import datetime, timedelta
from synthea.engine.state import (
    State, StateType, InitialState, SimpleState, DelayState,
    GuardState, SetAttributeState, CounterState, ConditionOnsetState
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