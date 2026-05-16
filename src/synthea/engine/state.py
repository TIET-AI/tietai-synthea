"""
State machine implementation for Synthea modules.

This module defines the various state types used in Synthea's Generic Module Framework.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List, TYPE_CHECKING
from datetime import datetime, timedelta
from enum import Enum
import logging
import random
import copy

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from synthea.world.person import Person
    from synthea.engine.module import Module

from synthea.world.health_record import Code


def _parse_codes(raw: list) -> list:
    """Convert raw code dicts from JSON to Code instances."""
    result = []
    for c in raw:
        if isinstance(c, Code):
            result.append(c)
        elif isinstance(c, dict):
            result.append(Code(
                system=c.get('system', ''),
                code=c.get('code', ''),
                display=c.get('display', ''),
            ))
    return result


class StateType(Enum):
    """Enumeration of all possible state types in Synthea modules."""
    
    INITIAL = "Initial"
    SIMPLE = "Simple"
    TERMINAL = "Terminal"
    DELAY = "Delay"
    GUARD = "Guard"
    SET_ATTRIBUTE = "SetAttribute"
    COUNTER = "Counter"
    ENCOUNTER = "Encounter"
    ENCOUNTER_END = "EncounterEnd"
    CONDITION_ONSET = "ConditionOnset"
    CONDITION_END = "ConditionEnd"
    ALLERGY_ONSET = "AllergyOnset"
    ALLERGY_END = "AllergyEnd"
    MEDICATION_ORDER = "MedicationOrder"
    MEDICATION_END = "MedicationEnd"
    CAREPLAN_START = "CarePlanStart"
    CAREPLAN_END = "CarePlanEnd"
    PROCEDURE = "Procedure"
    VITAL_SIGN = "VitalSign"
    OBSERVATION = "Observation"
    MULTI_OBSERVATION = "MultiObservation"
    DIAGNOSTIC_REPORT = "DiagnosticReport"
    SYMPTOM = "Symptom"
    DEATH = "Death"
    CALL_SUBMODULE = "CallSubmodule"
    DEVICE = "Device"
    DEVICE_END = "DeviceEnd"
    SUPPLY_LIST = "SupplyList"
    IMAGING_STUDY = "ImagingStudy"
    VACCINE = "Vaccine"
    PHYSIOLOGY = "Physiology"


class State(ABC):
    """Abstract base class for all state types."""
    
    def __init__(self, module: 'Module', name: str, definition: Dict[str, Any]):
        """
        Initialize a state.
        
        Args:
            module: The module this state belongs to
            name: The name of this state
            definition: The JSON definition of this state
        """
        self.module = module
        self.name = name
        # Pre-convert codes in the definition once at load time
        self.definition = dict(definition)
        if 'codes' in self.definition:
            self.definition['codes'] = _parse_codes(self.definition['codes'])
        self.remarks = definition.get('remarks', [])
        if isinstance(self.remarks, str):
            self.remarks = [self.remarks]
    
    @abstractmethod
    def run(self, person: 'Person', time: datetime) -> bool:
        """
        Execute this state.
        
        Args:
            person: The person to execute this state on
            time: The current simulation time
            
        Returns:
            True if the state completed, False if it needs to wait
        """
        pass
    
    def get_transition(self) -> Optional[str]:
        """
        Get the name of the next state to transition to.
        
        Returns:
            The name of the next state, or None if this is a terminal state
        """
        if 'transition' in self.definition:
            return self.definition['transition']
        elif 'direct_transition' in self.definition:
            return self.definition['direct_transition']
        return None
    
    def clone(self) -> 'State':
        """Create a deep copy of this state."""
        return copy.deepcopy(self)
    
    @staticmethod
    def create_state(module: 'Module', name: str, definition: Dict[str, Any]) -> 'State':
        """
        Factory method to create the appropriate state type.
        
        Args:
            module: The module this state belongs to
            name: The name of the state
            definition: The JSON definition of the state
            
        Returns:
            An instance of the appropriate State subclass
        """
        raw_type = definition.get('type')
        try:
            state_type = StateType(raw_type)
        except ValueError:
            logger.warning(
                "Unknown state type '%s' in module '%s' state '%s'; treating as Simple",
                raw_type, module.name, name,
            )
            return SimpleState(module, name, definition)
        
        state_classes = {
            StateType.INITIAL: InitialState,
            StateType.SIMPLE: SimpleState,
            StateType.TERMINAL: TerminalState,
            StateType.DELAY: DelayState,
            StateType.GUARD: GuardState,
            StateType.SET_ATTRIBUTE: SetAttributeState,
            StateType.COUNTER: CounterState,
            StateType.ENCOUNTER: EncounterState,
            StateType.ENCOUNTER_END: EncounterEndState,
            StateType.CONDITION_ONSET: ConditionOnsetState,
            StateType.CONDITION_END: ConditionEndState,
            StateType.MEDICATION_ORDER: MedicationOrderState,
            StateType.MEDICATION_END: MedicationEndState,
            StateType.PROCEDURE: ProcedureState,
            StateType.VITAL_SIGN: VitalSignState,
            StateType.OBSERVATION: ObservationState,
            StateType.SYMPTOM: SymptomState,
            StateType.DEATH: DeathState,
            StateType.VACCINE: SimpleState,
            StateType.PHYSIOLOGY: SimpleState,
        }
        
        state_class = state_classes.get(state_type, SimpleState)
        return state_class(module, name, definition)


class InitialState(State):
    """The starting state of a module."""
    
    def run(self, person: 'Person', time: datetime) -> bool:
        """Initial state always completes immediately."""
        return True


class SimpleState(State):
    """A state that performs no action and transitions immediately."""
    
    def run(self, person: 'Person', time: datetime) -> bool:
        """Simple state always completes immediately."""
        return True


class TerminalState(State):
    """The ending state of a module."""
    
    def run(self, person: 'Person', time: datetime) -> bool:
        """Terminal state always completes."""
        return True
    
    def get_transition(self) -> Optional[str]:
        """Terminal states have no transitions."""
        return None


class DelayState(State):
    """A state that waits for a specified amount of time."""
    
    def run(self, person: 'Person', time: datetime) -> bool:
        """
        Wait for the specified delay.
        
        Returns:
            True if the delay has passed, False otherwise
        """
        if self.name not in person.attributes.get(f'{self.module.name}_delays', {}):
            delay_def = self.definition.get('delay', {})
            delay = self._calculate_delay(delay_def, person)
            
            delays = person.attributes.setdefault(f'{self.module.name}_delays', {})
            delays[self.name] = time + delay
            return False
        
        delay_time = person.attributes[f'{self.module.name}_delays'][self.name]
        if time >= delay_time:
            del person.attributes[f'{self.module.name}_delays'][self.name]
            return True
        return False
    
    def _calculate_delay(self, delay_def: Dict[str, Any], person: 'Person') -> timedelta:
        """Calculate the delay duration based on the definition."""
        if 'exact' in delay_def:
            quantity = delay_def['exact']['quantity']
            unit = delay_def['exact']['unit']
        elif 'range' in delay_def:
            low = delay_def['range']['low']
            high = delay_def['range']['high']
            quantity = random.uniform(low, high)
            unit = delay_def['range']['unit']
        else:
            return timedelta(0)
        
        unit_map = {
            'years': timedelta(days=365),
            'months': timedelta(days=30),
            'weeks': timedelta(weeks=1),
            'days': timedelta(days=1),
            'hours': timedelta(hours=1),
            'minutes': timedelta(minutes=1),
            'seconds': timedelta(seconds=1),
        }
        
        return unit_map.get(unit, timedelta(0)) * quantity


class GuardState(State):
    """A state that only allows transition when a condition is met."""
    
    def run(self, person: 'Person', time: datetime) -> bool:
        """
        Check if the guard condition is met.
        
        Returns:
            True if the condition is met, False otherwise
        """
        if 'allow' in self.definition:
            from synthea.engine.logic import Logic
            return Logic.test(self.definition['allow'], person, time)
        return True


class SetAttributeState(State):
    """A state that sets an attribute on the person."""
    
    def run(self, person: 'Person', time: datetime) -> bool:
        """Set the specified attribute."""
        attribute = self.definition.get('attribute')
        if 'value' in self.definition:
            value = self.definition['value']
        elif 'value_code' in self.definition:
            value = self.definition['value_code']
        else:
            value = None
        
        if attribute:
            person.attributes[attribute] = value
        
        return True


class CounterState(State):
    """A state that increments or decrements a counter attribute."""
    
    def run(self, person: 'Person', time: datetime) -> bool:
        """Update the counter."""
        attribute = self.definition.get('attribute')
        action = self.definition.get('action', 'increment')
        
        if attribute:
            raw = person.attributes.get(attribute, 0)
            try:
                current = int(raw)
            except (TypeError, ValueError, OverflowError):
                current = 0
            if action == 'increment':
                person.attributes[attribute] = current + 1
            elif action == 'decrement':
                person.attributes[attribute] = current - 1
        
        return True


class EncounterState(State):
    """A state that starts a healthcare encounter."""
    
    def run(self, person: 'Person', time: datetime) -> bool:
        """Start an encounter."""
        encounter_class = self.definition.get('encounter_class', 'ambulatory')
        reason = self.definition.get('reason')
        codes = self.definition.get('codes', [])
        
        # Create encounter in person's health record
        if hasattr(person, 'record'):
            encounter = person.record.encounter_start(time, encounter_class)
            encounter.name = self.name
            encounter.codes.extend(codes)
            if reason:
                encounter.reason = reason
            
            # Store current encounter
            person.attributes['current_encounter'] = encounter
        
        return True


class EncounterEndState(State):
    """A state that ends a healthcare encounter."""

    def run(self, person: 'Person', time: datetime) -> bool:
        """End the current encounter and yield to the next time step.

        Returning False (yield) prevents modules that loop back to an Encounter
        state immediately after EncounterEnd from cycling indefinitely within a
        single time step — matching the Java Synthea engine's behaviour where
        ending an encounter naturally breaks the within-step loop.
        """
        end_key = f'{self.module.name}.{self.name}_ended_at'
        last_ended = person.attributes.get(end_key)

        if last_ended == time:
            # Already ended this encounter at this time step; yield again.
            return False

        if hasattr(person, 'record') and 'current_encounter' in person.attributes:
            encounter = person.attributes['current_encounter']
            person.record.encounter_end(encounter, time)
            del person.attributes['current_encounter']

        person.attributes[end_key] = time
        return False


class ConditionOnsetState(State):
    """A state that starts a medical condition."""
    
    def run(self, person: 'Person', time: datetime) -> bool:
        """Start a condition."""
        target_encounter = self.definition.get('target_encounter', 'current_encounter')
        codes = self.definition.get('codes', [])
        
        if hasattr(person, 'record'):
            encounter = person.attributes.get(target_encounter)
            if encounter:
                condition = person.record.condition_start(time, codes[0] if codes else None)
                condition.name = self.name
                condition.codes = codes
                
                # Store condition reference
                assign_to = self.definition.get('assign_to_attribute')
                if assign_to:
                    person.attributes[assign_to] = condition
        
        return True


class ConditionEndState(State):
    """A state that ends a medical condition."""
    
    def run(self, person: 'Person', time: datetime) -> bool:
        """End a condition."""
        referenced_by = self.definition.get('referenced_by_attribute')
        condition_onset = self.definition.get('condition_onset')
        
        if hasattr(person, 'record'):
            if referenced_by and referenced_by in person.attributes:
                condition = person.attributes[referenced_by]
                person.record.condition_end(condition, time)
            elif condition_onset:
                # Find condition by onset state name
                pass
        
        return True


class MedicationOrderState(State):
    """A state that prescribes a medication."""
    
    def run(self, person: 'Person', time: datetime) -> bool:
        """Prescribe a medication."""
        codes = self.definition.get('codes', [])
        reason = self.definition.get('reason')

        if hasattr(person, 'record'):
            encounter = person.attributes.get('current_encounter')
            if encounter:
                medication = person.record.medication_start(
                    time, 
                    codes[0] if codes else None,
                    encounter
                )
                medication.name = self.name
                medication.codes = codes
                if reason:
                    medication.reason = reason
                
                # Store medication reference
                assign_to = self.definition.get('assign_to_attribute')
                if assign_to:
                    person.attributes[assign_to] = medication
        
        return True


class MedicationEndState(State):
    """A state that ends a medication."""
    
    def run(self, person: 'Person', time: datetime) -> bool:
        """End a medication."""
        referenced_by = self.definition.get('referenced_by_attribute')
        medication_order = self.definition.get('medication_order')
        
        if hasattr(person, 'record'):
            if referenced_by and referenced_by in person.attributes:
                medication = person.attributes[referenced_by]
                person.record.medication_end(medication, time)
            elif medication_order:
                # Find medication by order state name
                pass
        
        return True


class ProcedureState(State):
    """A state that performs a medical procedure."""
    
    def run(self, person: 'Person', time: datetime) -> bool:
        """Perform a procedure."""
        codes = self.definition.get('codes', [])
        duration = self.definition.get('duration', {'quantity': 0, 'unit': 'minutes'})
        reason = self.definition.get('reason')
        
        if hasattr(person, 'record'):
            encounter = person.attributes.get('current_encounter')
            if encounter:
                procedure = person.record.procedure(time, codes[0] if codes else None, encounter)
                procedure.name = self.name
                procedure.codes = codes
                if reason:
                    procedure.reason = reason
        
        return True


class VitalSignState(State):
    """A state that records a vital sign."""
    
    def run(self, person: 'Person', time: datetime) -> bool:
        """Record a vital sign."""
        vital_sign = self.definition.get('vital_sign')
        unit = self.definition.get('unit')
        
        if vital_sign and hasattr(person, 'vital_signs'):
            value = self._calculate_value(person)
            person.vital_signs[vital_sign] = {
                'value': value,
                'unit': unit,
                'time': time
            }
        
        return True
    
    def _calculate_value(self, person: 'Person') -> float:
        """Calculate the vital sign value."""
        if 'exact' in self.definition:
            return self.definition['exact']['quantity']
        elif 'range' in self.definition:
            low = self.definition['range']['low']
            high = self.definition['range']['high']
            return random.uniform(low, high)
        return 0.0


class ObservationState(State):
    """A state that records an observation."""
    
    def run(self, person: 'Person', time: datetime) -> bool:
        """Record an observation."""
        codes = self.definition.get('codes', [])
        unit = self.definition.get('unit')
        category = self.definition.get('category', 'laboratory')
        
        if hasattr(person, 'record'):
            encounter = person.attributes.get('current_encounter')
            if encounter:
                value = self._calculate_value(person)
                observation = person.record.observation(
                    time,
                    codes[0] if codes else None,
                    value,
                    unit,
                    encounter
                )
                observation.name = self.name
                observation.codes = codes
                observation.category = category
        
        return True
    
    def _calculate_value(self, person: 'Person') -> Any:
        """Calculate the observation value."""
        if 'exact' in self.definition:
            return self.definition['exact']['quantity']
        elif 'range' in self.definition:
            low = self.definition['range']['low']
            high = self.definition['range']['high']
            return random.uniform(low, high)
        elif 'value_code' in self.definition:
            return self.definition['value_code']
        return None


class SymptomState(State):
    """A state that sets a symptom value."""
    
    def run(self, person: 'Person', time: datetime) -> bool:
        """Set a symptom."""
        symptom = self.definition.get('symptom')
        cause = self.definition.get('cause')
        
        if symptom:
            value = self._calculate_value(person)
            if not hasattr(person, 'symptoms'):
                person.symptoms = {}
            
            person.symptoms[symptom] = {
                'value': value,
                'cause': cause,
                'time': time
            }
        
        return True
    
    def _calculate_value(self, person: 'Person') -> float:
        """Calculate the symptom value (0-100 scale)."""
        if 'exact' in self.definition:
            return self.definition['exact']['quantity']
        elif 'range' in self.definition:
            low = self.definition['range']['low']
            high = self.definition['range']['high']
            return random.uniform(low, high)
        return 0.0


class DeathState(State):
    """A state that causes death."""
    
    def run(self, person: 'Person', time: datetime) -> bool:
        """Cause death."""
        if 'exact' in self.definition:
            death_time = time + timedelta(days=self.definition['exact']['quantity'] * 365)
        elif 'range' in self.definition:
            low = self.definition['range']['low']
            high = self.definition['range']['high']
            years = random.uniform(low, high)
            death_time = time + timedelta(days=years * 365)
        else:
            death_time = time
        
        person.alive = False
        person.attributes['death_time'] = death_time
        
        if 'codes' in self.definition and hasattr(person, 'record'):
            person.record.death(death_time, self.definition['codes'][0])
        
        return True