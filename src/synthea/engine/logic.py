"""
Logic evaluation for conditions in Synthea modules.

This module provides the logic engine for evaluating conditions used in
conditional transitions, guard states, and other conditional elements.
"""

import logging
from typing import Dict, Any, Optional, Union, List, TYPE_CHECKING
from datetime import datetime, timedelta
import operator
import re

from synthea.world.health_record import Code

logger = logging.getLogger(__name__)

#: Condition types already reported as unsupported, so each is logged once.
_WARNED_CONDITIONS = set()

if TYPE_CHECKING:
    from synthea.world.person import Person


def _to_code(raw: Any) -> Code:
    """Convert a raw code dict (from JSON) to a Code instance, or pass through if already a Code."""
    if isinstance(raw, Code):
        return raw
    return Code(
        system=raw.get('system', ''),
        code=raw.get('code', ''),
        display=raw.get('display', ''),
    )


class Logic:
    """Static class for evaluating logical conditions."""
    
    @staticmethod
    def test(condition: Dict[str, Any], person: 'Person', time: datetime) -> bool:
        """
        Evaluate a logical condition.
        
        Args:
            condition: The condition definition
            person: The person being simulated
            time: The current simulation time
            
        Returns:
            True if the condition is met, False otherwise
        """
        if not condition:
            return True
        
        condition_type = condition.get('condition_type')
        
        if condition_type == 'And':
            return Logic._test_and(condition, person, time)
        elif condition_type == 'Or':
            return Logic._test_or(condition, person, time)
        elif condition_type == 'Not':
            return Logic._test_not(condition, person, time)
        elif condition_type == 'Gender':
            return Logic._test_gender(condition, person)
        elif condition_type == 'Age':
            return Logic._test_age(condition, person, time)
        elif condition_type == 'Date':
            return Logic._test_date(condition, time)
        elif condition_type == 'Socioeconomic Status':
            return Logic._test_socioeconomic(condition, person)
        elif condition_type == 'Race':
            return Logic._test_race(condition, person)
        elif condition_type == 'Symptom':
            return Logic._test_symptom(condition, person)
        elif condition_type == 'Observation':
            return Logic._test_observation(condition, person)
        elif condition_type == 'Vital Sign':
            return Logic._test_vital_sign(condition, person)
        elif condition_type == 'Active Condition':
            return Logic._test_active_condition(condition, person)
        elif condition_type == 'Active Medication':
            return Logic._test_active_medication(condition, person)
        elif condition_type == 'Active CarePlan':
            return Logic._test_active_careplan(condition, person)
        elif condition_type == 'Active Allergy':
            return Logic._test_active_allergy(condition, person)
        elif condition_type == 'At Least':
            return Logic._test_at_least(condition, person, time)
        elif condition_type == 'At Most':
            return Logic._test_at_most(condition, person, time)
        elif condition_type == 'PriorState':
            return Logic._test_prior_state(condition, person, time)
        elif condition_type == 'Attribute':
            return Logic._test_attribute(condition, person)
        elif condition_type == 'True':
            return True
        elif condition_type == 'False':
            return False
        else:
            # An unrecognised condition used to return False silently, which
            # meant the module took the wrong branch and nothing said so.
            if condition_type not in _WARNED_CONDITIONS:
                _WARNED_CONDITIONS.add(condition_type)
                logger.warning(
                    "Unsupported condition type %r; treating it as false. "
                    "The module will take the wrong branch.", condition_type,
                )
            return False
    
    @staticmethod
    def _test_and(condition: Dict[str, Any], person: 'Person', time: datetime) -> bool:
        """Test an AND condition - all subconditions must be true."""
        conditions = condition.get('conditions', [])
        return all(Logic.test(c, person, time) for c in conditions)
    
    @staticmethod
    def _test_or(condition: Dict[str, Any], person: 'Person', time: datetime) -> bool:
        """Test an OR condition - at least one subcondition must be true."""
        conditions = condition.get('conditions', [])
        return any(Logic.test(c, person, time) for c in conditions)
    
    @staticmethod
    def _test_not(condition: Dict[str, Any], person: 'Person', time: datetime) -> bool:
        """Test a NOT condition - inverts the subcondition."""
        subcondition = condition.get('condition')
        if subcondition:
            return not Logic.test(subcondition, person, time)
        return True
    
    @staticmethod
    def _test_gender(condition: Dict[str, Any], person: 'Person') -> bool:
        """Test a gender condition."""
        required_gender = condition.get('gender', '').upper()
        person_gender = person.attributes.get('gender', '').upper()
        return person_gender == required_gender
    
    @staticmethod
    def _test_age(condition: Dict[str, Any], person: 'Person', time: datetime) -> bool:
        """Test an age condition."""
        age = person.age_at(time)
        operator_str = condition.get('operator', '==')
        quantity = condition.get('quantity', 0)
        unit = condition.get('unit', 'years')
        
        # Convert quantity to years if needed
        if unit == 'months':
            quantity = quantity / 12
        elif unit == 'weeks':
            quantity = quantity / 52
        elif unit == 'days':
            quantity = quantity / 365.25
        
        return Logic._compare(age, operator_str, quantity)
    
    @staticmethod
    def _test_date(condition: Dict[str, Any], time: datetime) -> bool:
        """Test a date condition."""
        operator_str = condition.get('operator', '==')
        
        # Parse the date — 'date' may be an ISO string, a dict of {year,month,day},
        # or absent (year/month/day as top-level keys).
        date_val = condition.get('date')
        if isinstance(date_val, dict):
            year = date_val.get('year', condition.get('year'))
            month = date_val.get('month', condition.get('month', 1))
            day = date_val.get('day', condition.get('day', 1))
            if not year:
                return False
            target_date = datetime(int(year), int(month), int(day))
        elif isinstance(date_val, str):
            target_date = datetime.fromisoformat(date_val.replace('Z', '+00:00'))
        else:
            year = condition.get('year')
            month = condition.get('month', 1)
            day = condition.get('day', 1)
            if not year:
                return False
            target_date = datetime(int(year), int(month), int(day))
        
        return Logic._compare_dates(time, operator_str, target_date)
    
    @staticmethod
    def _test_socioeconomic(condition: Dict[str, Any], person: 'Person') -> bool:
        """Test a socioeconomic status condition."""
        category = condition.get('category', '').lower()
        person_ses = person.attributes.get('socioeconomic_status', '').lower()
        return person_ses == category
    
    @staticmethod
    def _test_race(condition: Dict[str, Any], person: 'Person') -> bool:
        """Test a race condition."""
        race = condition.get('race', '').lower()
        person_race = person.attributes.get('race', '').lower()
        return person_race == race
    
    @staticmethod
    def _test_symptom(condition: Dict[str, Any], person: 'Person') -> bool:
        """Test a symptom condition."""
        symptom = condition.get('symptom')
        operator_str = condition.get('operator', '>=')
        value = condition.get('value', 0)
        
        if not hasattr(person, 'symptoms') or symptom not in person.symptoms:
            return Logic._compare(0, operator_str, value)
        
        symptom_value = person.symptoms[symptom].get('value', 0)
        return Logic._compare(symptom_value, operator_str, value)
    
    @staticmethod
    def _test_observation(condition: Dict[str, Any], person: 'Person') -> bool:
        """Test an observation condition."""
        if not hasattr(person, 'record'):
            return False
        
        # Find the most recent observation matching the codes
        codes = condition.get('codes', [])
        if not codes:
            return False
        
        observation = person.record.get_latest_observation(_to_code(codes[0]))
        if not observation:
            return False
        
        operator_str = condition.get('operator', '==')
        
        # Check if we're comparing values or codes
        if 'value' in condition:
            target_value = condition['value']
            return Logic._compare(observation.value, operator_str, target_value)
        elif 'value_code' in condition:
            target_code = condition['value_code']
            return observation.value == target_code
        
        return False
    
    @staticmethod
    def _test_vital_sign(condition: Dict[str, Any], person: 'Person') -> bool:
        """Test a vital sign condition."""
        vital_sign = condition.get('vital_sign')
        operator_str = condition.get('operator', '>=')
        value = condition.get('value', 0)
        
        if not hasattr(person, 'vital_signs') or vital_sign not in person.vital_signs:
            return False
        
        vital_value = person.vital_signs[vital_sign].get('value', 0)
        return Logic._compare(vital_value, operator_str, value)
    
    @staticmethod
    def _test_active_condition(condition: Dict[str, Any], person: 'Person') -> bool:
        """Test if a condition is currently active."""
        if not hasattr(person, 'record'):
            return False
        
        codes = condition.get('codes', [])
        if not codes:
            return False
        
        return person.record.has_active_condition(_to_code(codes[0]))
    
    @staticmethod
    def _test_active_medication(condition: Dict[str, Any], person: 'Person') -> bool:
        """Test if a medication is currently active."""
        if not hasattr(person, 'record'):
            return False
        
        codes = condition.get('codes', [])
        if not codes:
            return False
        
        return person.record.has_active_medication(_to_code(codes[0]))
    
    @staticmethod
    def _test_active_careplan(condition: Dict[str, Any], person: 'Person') -> bool:
        """Test if a care plan is currently active."""
        if not hasattr(person, 'record'):
            return False
        
        codes = condition.get('codes', [])
        if not codes:
            return False
        
        return person.record.has_active_careplan(_to_code(codes[0]))
    
    @staticmethod
    def _test_active_allergy(condition: Dict[str, Any], person: 'Person') -> bool:
        """Whether an allergy is currently active.

        Used 24 times in the bundled modules and previously unsupported, so
        every allergy check silently took the 'no allergy' branch.
        """
        if getattr(person, 'record', None) is None:
            return False

        codes = condition.get('codes', [])
        if not codes:
            return False

        return person.record.has_active_allergy(_to_code(codes[0]))

    @staticmethod
    def _count_true(condition: Dict[str, Any], person: 'Person',
                    time: datetime) -> int:
        return sum(
            1 for sub in condition.get('conditions', [])
            if Logic.test(sub, person, time)
        )

    @staticmethod
    def _test_at_least(condition: Dict[str, Any], person: 'Person',
                       time: datetime) -> bool:
        """True when at least N of the sub-conditions hold."""
        try:
            minimum = int(condition.get('minimum', 1))
        except (TypeError, ValueError):
            minimum = 1
        return Logic._count_true(condition, person, time) >= minimum

    @staticmethod
    def _test_at_most(condition: Dict[str, Any], person: 'Person',
                      time: datetime) -> bool:
        """True when at most N of the sub-conditions hold."""
        try:
            maximum = int(condition.get('maximum', 0))
        except (TypeError, ValueError):
            maximum = 0
        return Logic._count_true(condition, person, time) <= maximum

    @staticmethod
    def _test_prior_state(condition: Dict[str, Any], person: 'Person',
                          time: Optional[datetime] = None) -> bool:
        """Test if a specific state has been processed."""
        state_name = condition.get('name')
        module_name = condition.get('module')

        if not state_name:
            return False

        if module_name:
            key = f'{module_name}.{state_name}_visited'
            time_key = f'{module_name}.{state_name}_visited_at'
        else:
            key = f'{state_name}_visited'
            time_key = f'{state_name}_visited_at'

        if not person.attributes.get(key, False):
            return False

        window = condition.get('within')
        if not window or time is None:
            return True

        # `within` narrows the question from "ever" to "recently". Ignoring it
        # made a visit five years ago count the same as one last week.
        visited_at = person.attributes.get(time_key)
        if visited_at is None:
            return True

        from synthea.engine.values import to_timedelta
        span = to_timedelta(window.get('quantity'), window.get('unit', 'years'))
        return (time - visited_at) <= span

    @staticmethod
    def _test_attribute(condition: Dict[str, Any], person: 'Person') -> bool:
        """Test an attribute condition."""
        attribute = condition.get('attribute')
        if not attribute:
            return False
        
        person_value = person.attributes.get(attribute)
        
        # Check if we're just testing for existence
        if 'value' not in condition and 'operator' not in condition:
            return person_value is not None
        
        operator_str = condition.get('operator', '==')
        
        # Handle different value types
        if 'value' in condition:
            target_value = condition['value']
        elif 'value_code' in condition:
            target_value = condition['value_code']
        else:
            target_value = None
        
        # Special handling for None/null
        if target_value is None:
            if operator_str == '==':
                return person_value is None
            elif operator_str == '!=':
                return person_value is not None
            return False
        
        if person_value is None:
            return operator_str == '!='
        
        # Type conversion for comparison
        if isinstance(target_value, (int, float)) and isinstance(person_value, str):
            try:
                person_value = float(person_value)
            except ValueError:
                return operator_str == '!='
        elif isinstance(target_value, str) and isinstance(person_value, (int, float)):
            person_value = str(person_value)
        
        return Logic._compare(person_value, operator_str, target_value)
    
    @staticmethod
    def _compare(left: Any, operator_str: str, right: Any) -> bool:
        """Perform a comparison operation."""
        ops = {
            '<': operator.lt,
            '<=': operator.le,
            '>': operator.gt,
            '>=': operator.ge,
            '==': operator.eq,
            '!=': operator.ne,
            'is': operator.is_,
            'is not': operator.is_not,
        }
        
        op = ops.get(operator_str)
        if op:
            try:
                return op(left, right)
            except TypeError:
                # Type mismatch - try string comparison
                return op(str(left), str(right))
        
        return False
    
    @staticmethod
    def _compare_dates(date1: datetime, operator_str: str, date2: datetime) -> bool:
        """Compare two dates."""
        if operator_str == '<':
            return date1 < date2
        elif operator_str == '<=':
            return date1 <= date2
        elif operator_str == '>':
            return date1 > date2
        elif operator_str == '>=':
            return date1 >= date2
        elif operator_str == '==':
            return date1.date() == date2.date()
        elif operator_str == '!=':
            return date1.date() != date2.date()
        
        return False