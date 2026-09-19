"""
State machine implementation for Synthea modules.

This module defines the various state types used in Synthea's Generic Module Framework.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List, TYPE_CHECKING
from datetime import datetime, timedelta
from enum import Enum
import logging
import copy

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from synthea.world.person import Person
    from synthea.engine.module import Module

from synthea.engine.values import (
    duration_for,
    passes_probability,
    to_timedelta,
    value_for,
)
from synthea.world.dicom import series_uid, sop_instance_uid, study_uid
from synthea.world.health_record import (
    Allergy,
    CarePlan,
    Code,
    Condition,
    Device,
    Medication,
    Report,
)


#: LOINC codes for the vital signs modules set by name. A VitalSign state
#: usually gives no `codes`, so without this the value could not be exported.
VITAL_SIGN_LOINC = {
    'Height': ('8302-2', 'Body Height'),
    'Weight': ('29463-7', 'Body Weight'),
    'Body Mass Index': ('39156-5', 'Body mass index (BMI) [Ratio]'),
    'Systolic Blood Pressure': ('8480-6', 'Systolic blood pressure'),
    'Diastolic Blood Pressure': ('8462-4', 'Diastolic blood pressure'),
    'Heart Rate': ('8867-4', 'Heart rate'),
    'Respiration Rate': ('9279-1', 'Respiratory rate'),
    'Oxygen Saturation': ('2708-6', 'Oxygen saturation in Arterial blood'),
}


def vital_sign_codes(vital_sign: str) -> list:
    """The LOINC code for a named vital sign, if one is known."""
    entry = VITAL_SIGN_LOINC.get(vital_sign)
    if entry is None:
        return []
    return [Code(system='http://loinc.org', code=entry[0], display=entry[1])]


def _pending_key(module_name: str) -> str:
    """Person-attribute key holding this module's undiagnosed entries."""
    return f'{module_name}_pending_diagnoses'


def _defer_diagnosis(person: 'Person', module_name: str,
                     target_state: str, entry) -> None:
    """Hold an entry until the named Encounter state runs.

    In GMF, ``target_encounter`` means the condition starts now but is only
    diagnosed at that later visit. The entry is already on the record; this
    just remembers which visit should claim it.
    """
    pending = person.attributes.setdefault(_pending_key(module_name), {})
    pending.setdefault(target_state, []).append(entry)


def _claim_pending(person: 'Person', module_name: str, state_name: str) -> list:
    """Take the entries waiting for this Encounter state to happen."""
    pending = person.attributes.get(_pending_key(module_name))
    if not pending:
        return []
    return pending.pop(state_name, [])


def _current_encounter_is(person: 'Person', state_name: str) -> bool:
    """Whether the encounter in progress was opened by the named state."""
    encounter = person.attributes.get('current_encounter')
    return encounter is not None and getattr(encounter, 'name', None) == state_name


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
            StateType.ALLERGY_ONSET: AllergyOnsetState,
            StateType.ALLERGY_END: AllergyEndState,
            StateType.MEDICATION_ORDER: MedicationOrderState,
            StateType.MEDICATION_END: MedicationEndState,
            StateType.CAREPLAN_START: CarePlanStartState,
            StateType.CAREPLAN_END: CarePlanEndState,
            StateType.PROCEDURE: ProcedureState,
            StateType.VITAL_SIGN: VitalSignState,
            StateType.OBSERVATION: ObservationState,
            StateType.MULTI_OBSERVATION: MultiObservationState,
            StateType.DIAGNOSTIC_REPORT: DiagnosticReportState,
            StateType.SYMPTOM: SymptomState,
            StateType.DEATH: DeathState,
            StateType.CALL_SUBMODULE: CallSubmoduleState,
            StateType.DEVICE: DeviceState,
            StateType.DEVICE_END: DeviceEndState,
            StateType.SUPPLY_LIST: SupplyListState,
            StateType.IMAGING_STUDY: ImagingStudyState,
            StateType.VACCINE: VaccineState,
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
        delays = person.attributes.setdefault(f'{self.module.name}_delays', {})

        if self.name not in delays:
            delays[self.name] = time + self._calculate_delay(person)

        if time >= delays[self.name]:
            del delays[self.name]
            return True
        return False

    def _calculate_delay(self, person: 'Person') -> timedelta:
        """Calculate the delay duration from this state's definition.

        The duration is written directly on the state (``exact``, ``range`` or
        ``distribution``), not under a nested ``delay`` key: none of the
        bundled modules uses one.
        """
        return duration_for(self.definition, person)


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
        """Set the specified attribute.

        ``attribute`` names the target of the assignment, so the value can only
        be sourced from another attribute through ``value_attribute``.
        """
        attribute = self.definition.get('attribute')
        if attribute:
            person.attributes[attribute] = value_for(
                self.definition, person, attribute_key='value_attribute',
            )

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
    """A state that starts a healthcare encounter.

    ``"wellness": true`` means the module is not booking an appointment of its
    own: it is attaching to the patient's next routine check-up, scheduled by
    the core encounter module. Such a state **waits** until that visit happens.

    Until this was implemented the flag was ignored and the state opened an
    ambulatory encounter immediately, so every chronic-disease module diagnosed
    its condition in the patient's first week of life.
    """

    def run(self, person: 'Person', time: datetime) -> bool:
        """Start an encounter, or wait for the routine visit to attach to."""
        if self.definition.get('wellness'):
            return self._attach_to_wellness(person, time)

        encounter_class = self.definition.get('encounter_class', 'ambulatory')
        reason = self.definition.get('reason')
        codes = self.definition.get('codes', [])

        # Create encounter in person's health record
        if getattr(person, 'record', None) is not None:
            encounter = person.record.encounter_start(time, encounter_class)
            encounter.name = self.name
            encounter.codes.extend(codes)
            if reason:
                encounter.reason = reason

            # Store current encounter
            person.attributes['current_encounter'] = encounter

            # Claim anything that has been waiting for this visit to diagnose it.
            for entry in _claim_pending(person, self.module.name, self.name):
                person.record.attach(entry, encounter)

        return True


    def _attach_to_wellness(self, person: 'Person', time: datetime) -> bool:
        """Adopt the routine check-up in progress, or wait for the next one.

        Returns False (yield to the next timestep) while no check-up is open,
        which is how the module ends up sitting here until the patient attends.
        """
        if getattr(person, 'record', None) is None:
            return True

        encounter = person.attributes.get('current_wellness_encounter')
        if encounter is None or encounter.time != time:
            return False  # no visit today; come back next step

        # The module joins the existing visit rather than opening its own, so
        # its codes and reason describe what the visit found.
        for code in self.definition.get('codes', []):
            if code not in encounter.codes:
                encounter.codes.append(code)
        if self.definition.get('reason') and not encounter.reason:
            encounter.reason = self.definition['reason']

        person.attributes['current_encounter'] = encounter

        for entry in _claim_pending(person, self.module.name, self.name):
            person.record.attach(entry, encounter)

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
        """Start a condition.

        The onset is recorded now whether or not a visit is in progress: people
        fall ill before they see a clinician. ``target_encounter`` names the
        Encounter state that diagnoses it, and the condition is linked to that
        encounter when it happens (or immediately, if that encounter is already
        the one in progress).
        """
        if getattr(person, 'record', None) is None:
            return True

        codes = self.definition.get('codes', [])
        target_encounter = self.definition.get('target_encounter')
        diagnose_now = target_encounter is None or _current_encounter_is(
            person, target_encounter
        )

        condition = person.record.condition_start(
            time, codes[0] if codes else None, attach=diagnose_now,
        )
        condition.name = self.name
        condition.codes = codes
        person.record.register_state_entry(self.module.name, self.name, condition)

        if not diagnose_now:
            _defer_diagnosis(person, self.module.name, target_encounter, condition)

        # Store condition reference
        assign_to = self.definition.get('assign_to_attribute')
        if assign_to:
            person.attributes[assign_to] = condition

        return True


class _EndState(State):
    """Shared resolution for the states that end something.

    A GMF end state names what to end in one of three ways, and modules use all
    of them: an attribute holding the entry (``referenced_by_attribute``), the
    name of the state that started it (``condition_onset``, ``medication_order``,
    ``careplan``, ``allergy_onset``, ``device``), or the ``codes`` of the thing
    itself. Only the first was implemented, so 250 end states did nothing:
    chronic conditions never resolved and medications never stopped.

    All three are tried in turn, because a module may give more than one.
    """

    #: Record entry class this state ends.
    ENTRY_TYPE: type = None
    #: Definition key naming the state that started it.
    START_STATE_KEY: str = ''
    #: Attribute on the record holding every entry of this type.
    POOL: str = ''
    #: Record method that ends the entry.
    END_METHOD: str = ''

    def run(self, person: 'Person', time: datetime) -> bool:
        record = getattr(person, 'record', None)
        if record is None:
            return True

        entry = self._resolve(person, record)
        if entry is not None:
            getattr(record, self.END_METHOD)(entry, time)

        return True

    def _resolve(self, person: 'Person', record) -> Optional[Any]:
        """Find the entry this state should end, or None if there is none."""
        referenced_by = self.definition.get('referenced_by_attribute')
        if referenced_by:
            entry = person.attributes.get(referenced_by)
            if isinstance(entry, self.ENTRY_TYPE) and getattr(entry, 'end_time', None) is None:
                return entry

        start_state = self.definition.get(self.START_STATE_KEY)
        if start_state:
            entry = record.find_by_state(self.module.name, start_state, self.ENTRY_TYPE)
            if entry is not None:
                return entry

        codes = self.definition.get('codes')
        if codes:
            return record.find_by_codes(codes, getattr(record, self.POOL, []),
                                        self.ENTRY_TYPE)

        return None


class ConditionEndState(_EndState):
    """A state that ends a medical condition."""

    ENTRY_TYPE = Condition
    START_STATE_KEY = 'condition_onset'
    POOL = 'conditions'
    END_METHOD = 'condition_end'


class MedicationOrderState(State):
    """A state that prescribes or administers a medication."""

    def run(self, person: 'Person', time: datetime) -> bool:
        """Prescribe a medication, or record one given during the visit."""
        codes = self.definition.get('codes', [])
        reason = self.definition.get('reason')

        if getattr(person, 'record', None) is None:
            return True

        encounter = person.attributes.get('current_encounter')
        if encounter is None:
            return True

        medication = person.record.medication_start(
            time, codes[0] if codes else None, encounter,
        )
        medication.name = self.name
        medication.codes = codes
        person.record.register_state_entry(self.module.name, self.name, medication)

        # How the drug is taken, and for how long.
        medication.prescription = self.definition.get('prescription')
        medication.chronic = bool(self.definition.get('chronic'))
        medication.administration = bool(self.definition.get('administration'))

        if reason:
            medication.reason = reason
            medication.reason_entry = self._resolve_reason(person, reason)

        # A drug given during the visit is finished when the visit is. A
        # prescription with a stated duration ends when it runs out; a chronic
        # one has no planned end at all.
        if medication.administration:
            medication.end_time = time
        else:
            duration = (medication.prescription or {}).get('duration')
            if duration and not medication.chronic:
                medication.end_time = time + to_timedelta(
                    duration.get('quantity'), duration.get('unit', 'days'),
                )

        # Store medication reference
        assign_to = self.definition.get('assign_to_attribute')
        if assign_to:
            person.attributes[assign_to] = medication

        return True

    def _resolve_reason(self, person: 'Person', reason: str):
        """Find the condition this drug treats, so the export can reference it.

        ``reason`` names either the state that started a condition or an
        attribute holding one.
        """
        found = person.record.find_by_state(self.module.name, reason, Condition)
        if found is not None:
            return found

        candidate = person.attributes.get(reason)
        return candidate if isinstance(candidate, Condition) else None


class MedicationEndState(_EndState):
    """A state that ends a medication."""

    ENTRY_TYPE = Medication
    START_STATE_KEY = 'medication_order'
    POOL = 'medications'
    END_METHOD = 'medication_end'


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
        
        if not vital_sign or not hasattr(person, 'vital_signs'):
            return True

        value = self._calculate_value(person)
        person.vital_signs[vital_sign] = {
            'value': value,
            'unit': unit,
            'time': time,
        }

        # A vital set by a module must also reach the record, or it is invisible
        # to every exporter. Previously it lived only on the person, which is
        # why observations reading a vital sign exported with no value.
        self._record_observation(person, time, vital_sign, value, unit)

        return True

    def _record_observation(self, person: 'Person', time: datetime,
                            vital_sign: str, value: Any, unit: Any) -> None:
        """Record the vital as an Observation on the visit in progress."""
        if getattr(person, 'record', None) is None or value is None:
            return

        encounter = person.attributes.get('current_encounter')
        if encounter is None:
            # Nothing to hang it on; the value still lives on the person and a
            # later Observation state can read it.
            return

        codes = self.definition.get('codes') or vital_sign_codes(vital_sign)
        if not codes:
            return

        observation = person.record.observation(
            time, codes[0], value, unit, encounter,
        )
        observation.codes = list(codes)
        observation.category = 'vital-signs'
        observation.name = vital_sign

    def _calculate_value(self, person: 'Person') -> Any:
        """Calculate the vital sign value."""
        return value_for(self.definition, person, default=0.0,
                         attribute_key='attribute')


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
        """Calculate the observation value.

        On an Observation, ``attribute`` and ``vital_sign`` name where to read
        the value from rather than describing the observation itself.
        """
        return value_for(self.definition, person, attribute_key='attribute')


class SymptomState(State):
    """A state that sets a symptom value."""
    
    def run(self, person: 'Person', time: datetime) -> bool:
        """Set a symptom.

        A ``probability`` on the state means only that fraction of patients
        reaching it express the symptom at all; the rest leave it unchanged.
        """
        symptom = self.definition.get('symptom')
        cause = self.definition.get('cause')

        if symptom and passes_probability(self.definition, person):
            value = self._calculate_value(person)
            if not hasattr(person, 'symptoms'):
                person.symptoms = {}

            person.symptoms[symptom] = {
                'value': value,
                'cause': cause,
                'time': time
            }

        return True

    def _calculate_value(self, person: 'Person') -> Any:
        """Calculate the symptom value (0-100 scale)."""
        return value_for(self.definition, person, default=0.0,
                         attribute_key='attribute')


class DeathState(State):
    """A state that causes death."""
    
    def run(self, person: 'Person', time: datetime) -> bool:
        """Cause death."""
        if 'exact' in self.definition:
            death_time = time + timedelta(days=self.definition['exact']['quantity'] * 365)
        elif 'range' in self.definition:
            low = self.definition['range']['low']
            high = self.definition['range']['high']
            years = person.random.uniform(low, high)
            death_time = time + timedelta(days=years * 365)
        else:
            death_time = time
        
        person.alive = False
        person.attributes['death_time'] = death_time
        
        if 'codes' in self.definition and hasattr(person, 'record'):
            person.record.death(death_time, self.definition['codes'][0])

        return True


class AllergyOnsetState(State):
    """A state that starts an allergy."""

    def run(self, person: 'Person', time: datetime) -> bool:
        """Start an allergy.

        Recorded at onset like a condition, and linked to the encounter named
        by ``target_encounter`` when that visit happens.
        """
        if getattr(person, 'record', None) is None:
            return True

        codes = self.definition.get('codes', [])
        target_encounter = self.definition.get('target_encounter')
        diagnose_now = target_encounter is None or _current_encounter_is(
            person, target_encounter
        )

        allergy = person.record.allergy_start(
            time, codes[0] if codes else None, attach=diagnose_now,
        )
        allergy.name = self.name
        allergy.codes = codes
        person.record.register_state_entry(self.module.name, self.name, allergy)

        if not diagnose_now:
            _defer_diagnosis(person, self.module.name, target_encounter, allergy)

        # Store allergy reference
        assign_to = self.definition.get('assign_to_attribute')
        if assign_to:
            person.attributes[assign_to] = allergy

        return True


class AllergyEndState(_EndState):
    """A state that ends an allergy."""

    ENTRY_TYPE = Allergy
    START_STATE_KEY = 'allergy_onset'
    POOL = 'allergies'
    END_METHOD = 'allergy_end'


class CarePlanStartState(State):
    """A state that starts a care plan."""

    def run(self, person: 'Person', time: datetime) -> bool:
        """Start a care plan."""
        codes = self.definition.get('codes', [])
        reason = self.definition.get('reason')
        activities = self.definition.get('activities', [])
        goals = self.definition.get('goals', [])

        if hasattr(person, 'record'):
            encounter = person.attributes.get('current_encounter')
            if encounter:
                careplan = person.record.careplan_start(time, codes[0] if codes else None)
                careplan.name = self.name
                careplan.codes = codes
                person.record.register_state_entry(
                    self.module.name, self.name, careplan)
                if reason:
                    careplan.reason = reason
                careplan.activities = [
                    _parse_codes([a])[0] if isinstance(a, dict) else a
                    for a in activities
                ]
                careplan.goals = goals

                # Store careplan reference
                assign_to = self.definition.get('assign_to_attribute')
                if assign_to:
                    person.attributes[assign_to] = careplan

        return True


class CarePlanEndState(_EndState):
    """A state that ends a care plan."""

    ENTRY_TYPE = CarePlan
    START_STATE_KEY = 'careplan'
    POOL = 'careplans'
    END_METHOD = 'careplan_end'


class _ReportStateBase(State):
    """Shared logic for MultiObservation and DiagnosticReport states."""

    def run(self, person: 'Person', time: datetime) -> bool:
        codes = self.definition.get('codes', [])
        obs_defs = self.definition.get('observations', [])

        if hasattr(person, 'record'):
            encounter = person.attributes.get('current_encounter')
            if encounter:
                report = Report(time=time)
                person.record.adopt(report)
                report.codes = codes
                report.name = self.name
                report.encounter = encounter

                for obs_def in obs_defs:
                    obs_codes = _parse_codes(obs_def.get('codes', []))
                    unit = obs_def.get('unit')
                    if isinstance(obs_def.get('exact'), dict):
                        unit = obs_def['exact'].get('unit', unit)
                    elif isinstance(obs_def.get('range'), dict):
                        unit = obs_def['range'].get('unit', unit)

                    value = value_for(obs_def, person, attribute_key='attribute')

                    observation = person.record.observation(
                        time,
                        obs_codes[0] if obs_codes else None,
                        value,
                        unit,
                        encounter
                    )
                    observation.codes = obs_codes
                    report.observations.append(observation)

                person.record.reports.append(report)
                if encounter:
                    encounter.reports.append(report)

        return True


class MultiObservationState(_ReportStateBase):
    """A state that creates a multi-observation report (e.g. vital sign panels)."""
    pass


class DiagnosticReportState(_ReportStateBase):
    """A state that creates a diagnostic report with child observations."""
    pass


class CallSubmoduleState(State):
    """A state that calls a submodule."""

    def run(self, person: 'Person', time: datetime) -> bool:
        """Load and process a submodule."""
        from synthea.engine.module import Module

        submodule_name = self.definition.get('submodule')
        if not submodule_name:
            return True

        submodule = Module.get_module(submodule_name)
        if not submodule:
            logger.warning("Submodule '%s' not found", submodule_name)
            return True

        submodule.process(person, time)
        return True


class DeviceState(State):
    """A state that records a device."""

    def run(self, person: 'Person', time: datetime) -> bool:
        """Record a device."""
        codes = self.definition.get('codes', [])

        if hasattr(person, 'record'):
            encounter = person.attributes.get('current_encounter')
            if encounter:
                device = person.record.device_start(time, codes[0] if codes else None)
                device.name = self.name
                device.codes = codes
                person.record.register_state_entry(
                    self.module.name, self.name, device)

                # Store device reference
                assign_to = self.definition.get('assign_to_attribute')
                if assign_to:
                    person.attributes[assign_to] = device

        return True


class DeviceEndState(_EndState):
    """A state that ends a device."""

    ENTRY_TYPE = Device
    START_STATE_KEY = 'device'
    POOL = 'devices'
    END_METHOD = 'device_end'


class SupplyListState(State):
    """A state that records supplies."""

    def run(self, person: 'Person', time: datetime) -> bool:
        """Record supplies."""
        supplies = self.definition.get('supplies', [])

        if hasattr(person, 'record'):
            encounter = person.attributes.get('current_encounter')
            if encounter:
                person.record.supply_list(time, supplies)

        return True


class VaccineState(State):
    """A state that administers a vaccine.

    Mapped to a no-op before this, so the five module-driven vaccinations in the
    bundled modules recorded nothing. The routine childhood and adult schedule
    is handled separately by the immunizations core module; this covers vaccines
    a disease pathway gives for its own reasons, such as the COVID-19 and HIV
    care modules.
    """

    def run(self, person: 'Person', time: datetime) -> bool:
        if getattr(person, 'record', None) is None:
            return True

        encounter = person.attributes.get('current_encounter')
        if encounter is None:
            return True

        codes = self.definition.get('codes', [])
        if not codes:
            return True

        immunization = person.record.immunization(time, codes[0], encounter)
        immunization.name = self.name
        immunization.codes = list(codes)

        series = self.definition.get('series')
        if series is not None:
            try:
                immunization.dose_number = int(series)
            except (TypeError, ValueError):
                pass

        person.record.register_state_entry(self.module.name, self.name, immunization)

        assign_to = self.definition.get('assign_to_attribute')
        if assign_to:
            person.attributes[assign_to] = immunization

        return True


class ImagingStudyState(State):
    """A state that performs an imaging study.

    Mapped to a no-op before this: 39 ImagingStudy states across 19 modules did
    nothing, so a patient could have a chest X-ray procedure recorded with no
    study attached to it.

    The study, each series and each instance get real DICOM UIDs, so the output
    can be handed to imaging software or used to name files that a PACS will
    accept.
    """

    def run(self, person: 'Person', time: datetime) -> bool:
        if getattr(person, 'record', None) is None:
            return True

        encounter = person.attributes.get('current_encounter')
        if encounter is None:
            return True

        procedure_code = _first_code(self.definition.get('procedure_code'))
        study = person.record.imaging_study(time, procedure_code, encounter)
        study.name = self.name
        study.dicom_uid = study_uid(person)
        study.series = [
            self._build_series(person, definition)
            for definition in self.definition.get('series', [])
        ]

        if study.series:
            study.modality = study.series[0].get('modality')
            study.body_site = study.series[0].get('body_site')

        # An imaging study is also a procedure that happened at this visit.
        if procedure_code is not None:
            procedure = person.record.procedure(time, procedure_code, encounter)
            procedure.name = self.name
            procedure.codes = [procedure_code]

        person.record.register_state_entry(self.module.name, self.name, study)

        assign_to = self.definition.get('assign_to_attribute')
        if assign_to:
            person.attributes[assign_to] = study

        return True

    def _build_series(self, person: 'Person', definition: Dict[str, Any]) -> Dict[str, Any]:
        instances = [
            {
                'uid': sop_instance_uid(person),
                'title': instance.get('title'),
                'sop_class': _first_code(instance.get('sop_class')),
            }
            for instance in definition.get('instances', [])
        ]
        return {
            'uid': series_uid(person),
            'modality': _first_code(definition.get('modality')),
            'body_site': _first_code(definition.get('body_site')),
            'instances': instances,
        }


def _first_code(raw: Any) -> Optional[Code]:
    """Coerce a single code definition to a Code."""
    if raw is None:
        return None
    if isinstance(raw, Code):
        return raw
    if isinstance(raw, dict):
        return _parse_codes([raw])[0] if _parse_codes([raw]) else None
    if isinstance(raw, list) and raw:
        return _first_code(raw[0])
    return None
