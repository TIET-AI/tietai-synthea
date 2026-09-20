"""
Health record model for Synthea.

This module defines the health record structure that tracks all medical events,
conditions, medications, and procedures for a person.
"""

from typing import Dict, Any, Optional, List, Union, TYPE_CHECKING
from datetime import datetime
from dataclasses import dataclass, field
from enum import Enum
import logging
import random
import uuid

from synthea.helpers.rng import derive_seed

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from synthea.world.person import Person
    from synthea.world.provider import Provider


class EncounterClass(Enum):
    """Types of healthcare encounters."""
    AMBULATORY = "ambulatory"
    EMERGENCY = "emergency"
    INPATIENT = "inpatient"
    OUTPATIENT = "outpatient"
    URGENTCARE = "urgentcare"
    WELLNESS = "wellness"
    HOSPICE = "hospice"
    HOME = "home"
    SNF = "snf"  # Skilled Nursing Facility


@dataclass
class Code:
    """Represents a medical code (SNOMED, LOINC, RxNorm, etc.)."""
    system: str
    code: str
    display: str
    
    def to_dict(self) -> Dict[str, str]:
        """Convert to dictionary."""
        return {
            'system': self.system,
            'code': self.code,
            'display': self.display
        }


@dataclass
class Entry:
    """Base class for all health record entries."""
    time: datetime
    codes: List[Code] = field(default_factory=list)
    name: Optional[str] = None
    
    def __post_init__(self):
        """Generate unique ID after initialization."""
        self.id = str(uuid.uuid4())
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'id': self.id,
            'time': self.time.isoformat(),
            'codes': [c.to_dict() for c in self.codes],
            'name': self.name,
            'type': self.__class__.__name__
        }


@dataclass
class Encounter(Entry):
    """Represents a healthcare encounter."""
    encounter_class: EncounterClass = EncounterClass.AMBULATORY
    provider: Optional['Provider'] = None
    #: The practitioner who saw the patient.
    clinician: Optional[Any] = None
    reason: Optional[str] = None
    discharge_disposition: Optional[str] = None
    end_time: Optional[datetime] = None
    
    def __post_init__(self):
        super().__post_init__()
        self.conditions: List['Condition'] = []
        self.procedures: List['Procedure'] = []
        self.medications: List['Medication'] = []
        self.observations: List['Observation'] = []
        self.careplans: List['CarePlan'] = []
        self.reports: List['Report'] = []
        self.imaging_studies: List['ImagingStudy'] = []
        self.devices: List['Device'] = []
        self.supplies: List['Supply'] = []
        self.immunizations: List['Immunization'] = []

    @property
    def is_active(self) -> bool:
        """Check if encounter is still active."""
        return self.end_time is None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        data = super().to_dict()
        data.update({
            'encounter_class': self.encounter_class.value,
            'reason': self.reason,
            'discharge_disposition': self.discharge_disposition,
            'end_time': self.end_time.isoformat() if self.end_time else None,
            'conditions': [c.to_dict() for c in self.conditions],
            'procedures': [p.to_dict() for p in self.procedures],
            'medications': [m.to_dict() for m in self.medications],
            'observations': [o.to_dict() for o in self.observations],
        })
        return data


@dataclass
class Condition(Entry):
    """Represents a medical condition/diagnosis."""
    encounter: Optional[Encounter] = None
    end_time: Optional[datetime] = None
    
    @property
    def is_active(self) -> bool:
        """Check if condition is still active."""
        return self.end_time is None


@dataclass
class Allergy(Entry):
    """Represents an allergy."""
    encounter: Optional[Encounter] = None
    end_time: Optional[datetime] = None
    reactions: List[str] = field(default_factory=list)
    severity: Optional[str] = None
    
    @property
    def is_active(self) -> bool:
        """Check if allergy is still active."""
        return self.end_time is None


@dataclass
class Medication(Entry):
    """Represents a medication prescription or administration."""
    encounter: Optional[Encounter] = None
    end_time: Optional[datetime] = None
    reason: Optional[str] = None
    dosage: Optional[Dict[str, Any]] = None
    #: The GMF ``prescription`` block: dosage, duration, refills, as-needed.
    prescription: Optional[Dict[str, Any]] = None
    #: True when the drug was given during the visit rather than prescribed,
    #: which is a MedicationAdministration, not a MedicationRequest.
    administration: bool = False
    #: True for a long-term medication with no planned stop date.
    chronic: bool = False
    #: The condition being treated, once resolved from the module's `reason`.
    reason_entry: Optional['Condition'] = None
    
    @property
    def is_active(self) -> bool:
        """Check if medication is still active."""
        return self.end_time is None


@dataclass
class Procedure(Entry):
    """Represents a medical procedure."""
    encounter: Optional[Encounter] = None
    reason: Optional[str] = None
    duration: Optional[float] = None  # in minutes


@dataclass
class Observation(Entry):
    """Represents a clinical observation."""
    encounter: Optional[Encounter] = None
    value: Any = None
    unit: Optional[str] = None
    category: str = "laboratory"
    #: Parts of a panel, as ``(Code, value, unit)``. Blood pressure is one
    #: Observation with systolic and diastolic components rather than two
    #: separate Observations, which is what US Core expects.
    components: List[Any] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        data = super().to_dict()
        data.update({
            'value': self.value,
            'unit': self.unit,
            'category': self.category
        })
        return data


@dataclass
class CarePlan(Entry):
    """Represents a care plan."""
    encounter: Optional[Encounter] = None
    end_time: Optional[datetime] = None
    activities: List[str] = field(default_factory=list)
    goals: List[str] = field(default_factory=list)
    reason: Optional[str] = None
    
    @property
    def is_active(self) -> bool:
        """Check if care plan is still active."""
        return self.end_time is None


@dataclass
class Report(Entry):
    """Represents a diagnostic report."""
    encounter: Optional[Encounter] = None
    observations: List[Observation] = field(default_factory=list)


@dataclass
class ImagingStudy(Entry):
    """Represents an imaging study.

    ``dicom_uid`` and the per-series and per-instance UIDs are real DICOM
    identifiers derived from UUIDs under the ``2.25.`` arc, so a generated study
    can be handed to imaging software without colliding with anything.
    """
    encounter: Optional[Encounter] = None
    modality: Optional[str] = None
    body_site: Optional[str] = None
    series: List[Dict[str, Any]] = field(default_factory=list)
    dicom_uid: Optional[str] = None
    procedure_code: Optional[Code] = None


@dataclass
class Device(Entry):
    """Represents a medical device."""
    encounter: Optional[Encounter] = None
    end_time: Optional[datetime] = None
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    
    @property
    def is_active(self) -> bool:
        """Check if device is still active."""
        return self.end_time is None


@dataclass
class Supply(Entry):
    """Represents medical supplies."""
    encounter: Optional[Encounter] = None
    quantity: int = 1


@dataclass
class Immunization(Entry):
    """Represents an administered vaccine."""
    encounter: Optional[Encounter] = None
    series_doses: Optional[int] = None
    dose_number: Optional[int] = None


class HealthRecord:
    """Complete health record for a person."""
    
    def __init__(self, person: 'Person'):
        """
        Initialize a health record.
        
        Args:
            person: The person this record belongs to
        """
        self.person = person

        # Record entry identifiers are drawn from a dedicated stream seeded from
        # the person's seed, so a run is reproducible down to the resource ids.
        # ``uuid.uuid4()`` reads system entropy and would break that.
        self._id_random = random.Random(
            derive_seed(getattr(person, 'seed', 0) or 0, 0, 'entry-id')
        )

        # Entries indexed by code, so the logic engine's "is this condition
        # active?" questions do not scan the whole record. They are asked on
        # every timestep for every module, so a linear scan makes simulation
        # cost grow with the square of the record size.
        self._active_conditions: Dict[str, List[Condition]] = {}
        self._active_medications: Dict[str, List[Medication]] = {}
        self._active_careplans: Dict[str, List[CarePlan]] = {}
        self._active_allergies: Dict[str, List[Allergy]] = {}
        self._latest_observation: Dict[str, Observation] = {}

        # Entries indexed by the module state that created them, so an end
        # state can find what its matching start state produced
        # (``"module.State_Name" -> [entries]``).
        self._by_state: Dict[str, List[Entry]] = {}

        # All encounters
        self.encounters: List[Encounter] = []
        
        # Current active encounter
        self.current_encounter: Optional[Encounter] = None
        
        # All entries by type
        self.conditions: List[Condition] = []
        self.allergies: List[Allergy] = []
        self.medications: List[Medication] = []
        self.procedures: List[Procedure] = []
        self.observations: List[Observation] = []
        self.careplans: List[CarePlan] = []
        self.reports: List[Report] = []
        self.imaging_studies: List[ImagingStudy] = []
        self.devices: List[Device] = []
        self.supplies: List[Supply] = []
        self.immunizations: List[Immunization] = []
        
        # Death information
        self.death_date: Optional[datetime] = None
        self.death_cause: Optional[Code] = None

    # ------------------------------------------------------------------
    # Code indexes
    #
    # Every entry that can be "active" is indexed by each of its codes when it
    # starts and removed when it ends, so the logic engine answers in constant
    # time instead of scanning.
    # ------------------------------------------------------------------

    #: Entry class -> the index holding its active entries.
    def _index_for(self, entry: Entry) -> Optional[Dict[str, List[Entry]]]:
        return {
            'Condition': self._active_conditions,
            'Medication': self._active_medications,
            'CarePlan': self._active_careplans,
            'Allergy': self._active_allergies,
        }.get(type(entry).__name__)

    def _index_active(self, entry: Entry) -> None:
        """Add an entry to its code index."""
        index = self._index_for(entry)
        if index is None:
            return
        for code in entry.codes:
            index.setdefault(str(code.code), []).append(entry)

    def _unindex_active(self, entry: Entry) -> None:
        """Remove an ended entry from its code index."""
        index = self._index_for(entry)
        if index is None:
            return
        for code in entry.codes:
            bucket = index.get(str(code.code))
            if not bucket:
                continue
            try:
                bucket.remove(entry)
            except ValueError:
                pass
            if not bucket:
                index.pop(str(code.code), None)

    def reindex(self, entry: Entry) -> None:
        """Re-index an entry whose codes were replaced after it was created.

        States create an entry with one code and then assign the full list, so
        the index has to be refreshed once that has happened.
        """
        index = self._index_for(entry)
        if index is None or getattr(entry, 'end_time', None) is not None:
            return
        for bucket in list(index.values()):
            while entry in bucket:
                bucket.remove(entry)
        self._index_active(entry)

    def new_id(self) -> str:
        """Return a fresh, reproducible UUID for a record entry."""
        return str(uuid.UUID(int=self._id_random.getrandbits(128), version=4))

    def adopt(self, entry: 'Entry') -> 'Entry':
        """Give an entry created outside this record a reproducible id."""
        entry.id = self.new_id()
        return entry

    # ------------------------------------------------------------------
    # Finding entries again
    #
    # A GMF end state usually refers back to the state that started the thing
    # ("condition_onset": "Febrile_Neutropenia") or to its codes, rather than
    # holding a reference. These let it find the entry either way.
    # ------------------------------------------------------------------

    def register_state_entry(self, module_name: str, state_name: str,
                             entry: Entry) -> Entry:
        """Remember which module state produced an entry."""
        self._by_state.setdefault(f'{module_name}.{state_name}', []).append(entry)
        return entry

    def find_by_state(self, module_name: str, state_name: str,
                      kind: Optional[type] = None) -> Optional[Entry]:
        """Most recent still-active entry produced by a module state."""
        entries = self._by_state.get(f'{module_name}.{state_name}', [])
        return self._most_recent_active(entries, kind)

    def find_by_codes(self, codes: List[Code], pool: List[Entry],
                      kind: Optional[type] = None) -> Optional[Entry]:
        """Most recent still-active entry in ``pool`` carrying one of ``codes``."""
        wanted = {str(getattr(code, 'code', code)) for code in codes}
        matching = [
            entry for entry in pool
            if any(str(code.code) in wanted for code in entry.codes)
        ]
        return self._most_recent_active(matching, kind)

    @staticmethod
    def _most_recent_active(entries: List[Entry],
                            kind: Optional[type] = None) -> Optional[Entry]:
        """The latest entry that has not ended yet."""
        candidates = [
            entry for entry in entries
            if (kind is None or isinstance(entry, kind))
            and getattr(entry, 'end_time', None) is None
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda entry: entry.time)

    def encounter_start(self, time: datetime, encounter_class: Union[str, EncounterClass],
                       provider: Optional['Provider'] = None) -> Encounter:
        """
        Start a new encounter.
        
        Args:
            time: Start time of the encounter
            encounter_class: Type of encounter
            provider: Healthcare provider
            
        Returns:
            The new encounter
        """
        if isinstance(encounter_class, str):
            encounter_class = EncounterClass(encounter_class)
        
        encounter = Encounter(
            time=time,
            encounter_class=encounter_class,
            provider=provider
        )
        encounter.id = self.new_id()
        
        self.encounters.append(encounter)
        self.current_encounter = encounter

        # Every encounter gets a facility and a clinician, with routine
        # care going to the patient's usual practice. Done here because
        # encounters are created from several different places.
        if provider is None:
            manager = getattr(self.person, 'providers', None)
            if manager is not None:
                try:
                    manager.assign_to_encounter(self.person, encounter)
                except Exception:  # pragma: no cover - never fail a run
                    logger.warning('Could not assign a provider', exc_info=True)

        return encounter

    def encounter_end(self, encounter: Encounter, time: datetime,
                     discharge_disposition: Optional[str] = None):
        """
        End an encounter.
        
        Args:
            encounter: The encounter to end
            time: End time
            discharge_disposition: Discharge disposition code
        """
        encounter.end_time = time
        encounter.discharge_disposition = discharge_disposition
        
        if self.current_encounter == encounter:
            self.current_encounter = None
    
    #: Which list on an Encounter an entry type belongs to, for `attach`.
    _ENCOUNTER_BUCKETS = {
        'Condition': 'conditions',
        'Procedure': 'procedures',
        'Medication': 'medications',
        'Observation': 'observations',
        'CarePlan': 'careplans',
        'Report': 'reports',
        'ImagingStudy': 'imaging_studies',
        'Device': 'devices',
        'Supply': 'supplies',
        'Immunization': 'immunizations',
    }

    def attach(self, entry: Entry, encounter: Optional[Encounter]) -> Entry:
        """Link an already-recorded entry to the encounter that handled it.

        Used when a condition has its onset before the visit that diagnoses it:
        the entry exists from onset, and this attaches it once that visit
        happens.
        """
        if encounter is None:
            return entry

        entry.encounter = encounter
        bucket = self._ENCOUNTER_BUCKETS.get(type(entry).__name__)
        if bucket is not None:
            items = getattr(encounter, bucket, None)
            if items is not None and entry not in items:
                items.append(entry)
        return entry

    def condition_start(self, time: datetime, code: Optional[Code] = None,
                        attach: bool = True) -> Condition:
        """
        Record a new condition.

        Args:
            time: Onset time
            code: Condition code
            attach: Whether to link the condition to the encounter in progress.
                Pass ``False`` when the condition has its onset now but is
                diagnosed at a later, named encounter; call :meth:`attach` when
                that encounter happens.

        Returns:
            The new condition
        """
        condition = Condition(time=time)
        condition.id = self.new_id()
        if code:
            condition.codes = [code]

        self.conditions.append(condition)
        self._index_active(condition)

        if attach:
            self.attach(condition, self.current_encounter)

        return condition
    
    def condition_end(self, condition: Condition, time: datetime):
        """
        End a condition.
        
        Args:
            condition: The condition to end
            time: End time
        """
        condition.end_time = time
        self._unindex_active(condition)
    
    def allergy_start(self, time: datetime, code: Optional[Code] = None,
                      attach: bool = True) -> Allergy:
        """
        Record a new allergy.

        Args:
            time: Onset time
            code: Allergy code
            attach: Whether to link the allergy to the encounter in progress.
                See :meth:`condition_start`.

        Returns:
            The new allergy
        """
        allergy = Allergy(time=time)
        allergy.id = self.new_id()
        if code:
            allergy.codes = [code]

        self.allergies.append(allergy)
        self._index_active(allergy)

        if attach:
            self.attach(allergy, self.current_encounter)

        return allergy
    
    def allergy_end(self, allergy: Allergy, time: datetime):
        """
        End an allergy.
        
        Args:
            allergy: The allergy to end
            time: End time
        """
        allergy.end_time = time
        self._unindex_active(allergy)
    
    def medication_start(self, time: datetime, code: Optional[Code] = None,
                        encounter: Optional[Encounter] = None) -> Medication:
        """
        Start a medication.
        
        Args:
            time: Start time
            code: Medication code
            encounter: Associated encounter
            
        Returns:
            The new medication
        """
        medication = Medication(time=time)
        medication.id = self.new_id()
        if code:
            medication.codes = [code]
        
        medication.encounter = encounter or self.current_encounter
        
        self.medications.append(medication)
        self._index_active(medication)
        
        if medication.encounter:
            medication.encounter.medications.append(medication)
        
        return medication
    
    def medication_end(self, medication: Medication, time: datetime):
        """
        End a medication.
        
        Args:
            medication: The medication to end
            time: End time
        """
        medication.end_time = time
        self._unindex_active(medication)
    
    def procedure(self, time: datetime, code: Optional[Code] = None,
                 encounter: Optional[Encounter] = None) -> Procedure:
        """
        Record a procedure.
        
        Args:
            time: Procedure time
            code: Procedure code
            encounter: Associated encounter
            
        Returns:
            The new procedure
        """
        procedure = Procedure(time=time)
        procedure.id = self.new_id()
        if code:
            procedure.codes = [code]
        
        procedure.encounter = encounter or self.current_encounter
        
        self.procedures.append(procedure)
        
        if procedure.encounter:
            procedure.encounter.procedures.append(procedure)
        
        return procedure
    
    def observation(self, time: datetime, code: Optional[Code] = None,
                   value: Any = None, unit: Optional[str] = None,
                   encounter: Optional[Encounter] = None) -> Observation:
        """
        Record an observation.
        
        Args:
            time: Observation time
            code: Observation code
            value: Observed value
            unit: Unit of measurement
            encounter: Associated encounter
            
        Returns:
            The new observation
        """
        observation = Observation(
            time=time,
            value=value,
            unit=unit
        )
        observation.id = self.new_id()
        if code:
            observation.codes = [code]
        
        observation.encounter = encounter or self.current_encounter
        
        self.observations.append(observation)
        for entry_code in observation.codes:
            self._latest_observation[str(entry_code.code)] = observation
        
        if observation.encounter:
            observation.encounter.observations.append(observation)
        
        return observation
    
    def careplan_start(self, time: datetime, code: Optional[Code] = None) -> CarePlan:
        """
        Start a care plan.
        
        Args:
            time: Start time
            code: Care plan code
            
        Returns:
            The new care plan
        """
        careplan = CarePlan(time=time)
        careplan.id = self.new_id()
        if code:
            careplan.codes = [code]
        
        careplan.encounter = self.current_encounter
        
        self.careplans.append(careplan)
        self._index_active(careplan)
        
        if self.current_encounter:
            self.current_encounter.careplans.append(careplan)
        
        return careplan
    
    def careplan_end(self, careplan: CarePlan, time: datetime):
        """
        End a care plan.
        
        Args:
            careplan: The care plan to end
            time: End time
        """
        careplan.end_time = time
        self._unindex_active(careplan)
    
    def device_start(self, time: datetime, code: Optional[Code] = None) -> Device:
        """
        Record a new device.

        Args:
            time: Start time
            code: Device code

        Returns:
            The new device
        """
        device = Device(time=time)
        device.id = self.new_id()
        if code:
            device.codes = [code]

        device.encounter = self.current_encounter

        self.devices.append(device)

        if self.current_encounter:
            self.current_encounter.devices.append(device)

        return device

    def device_end(self, device: Device, time: datetime):
        """
        End a device.

        Args:
            device: The device to end
            time: End time
        """
        device.end_time = time

    def supply_list(self, time: datetime, supplies: List[Dict[str, Any]]) -> List[Supply]:
        """
        Record supplies.

        Args:
            time: Time of supply use
            supplies: List of supply definitions with code and quantity

        Returns:
            The new supply entries
        """
        result = []
        for supply_def in supplies:
            supply = Supply(time=time)
            supply.id = self.new_id()
            code_data = supply_def.get('code')
            if code_data and isinstance(code_data, dict):
                supply.codes = [Code(
                    system=code_data.get('system', ''),
                    code=code_data.get('code', ''),
                    display=code_data.get('display', ''),
                )]
            elif code_data and isinstance(code_data, Code):
                supply.codes = [code_data]
            supply.quantity = supply_def.get('quantity', 1)
            supply.encounter = self.current_encounter

            self.supplies.append(supply)

            if self.current_encounter:
                self.current_encounter.supplies.append(supply)

            result.append(supply)

        return result

    def immunization(self, time: datetime, code: Optional[Code] = None,
                     encounter: Optional[Encounter] = None) -> Immunization:
        """Record an administered vaccine.

        Args:
            time: Administration time
            code: CVX code for the vaccine
            encounter: The visit at which it was given

        Returns:
            The new immunization
        """
        immunization = Immunization(time=time)
        immunization.id = self.new_id()
        if code:
            immunization.codes = [code]

        self.immunizations.append(immunization)
        self.attach(immunization, encounter or self.current_encounter)

        return immunization

    def imaging_study(self, time: datetime, procedure_code: Optional[Code] = None,
                      encounter: Optional[Encounter] = None) -> ImagingStudy:
        """Record an imaging study.

        Args:
            time: When the study was performed
            procedure_code: The imaging procedure
            encounter: The visit it belongs to

        Returns:
            The new imaging study
        """
        study = ImagingStudy(time=time)
        study.id = self.new_id()
        study.procedure_code = procedure_code
        if procedure_code:
            study.codes = [procedure_code]

        self.imaging_studies.append(study)
        self.attach(study, encounter or self.current_encounter)

        return study

    def death(self, time: datetime, cause: Optional[Code] = None):
        """
        Record death.
        
        Args:
            time: Time of death
            cause: Cause of death code
        """
        self.death_date = time
        self.death_cause = cause
        self.person.alive = False
        self.person.attributes['death_date'] = time
    
    def get_latest_observation(self, code: Code) -> Optional[Observation]:
        """The most recent observation with the given code.

        Served from an index kept as observations are recorded; this used to
        scan and sort every observation the patient has ever had.
        """
        return self._latest_observation.get(str(code.code))

    def has_active_condition(self, code: Code) -> bool:
        """Whether a condition with this code is currently active."""
        return bool(self._active_conditions.get(str(code.code)))

    def has_active_medication(self, code: Code) -> bool:
        """Whether a medication with this code is currently active."""
        return bool(self._active_medications.get(str(code.code)))

    def has_active_careplan(self, code: Code) -> bool:
        """Whether a care plan with this code is currently active."""
        return bool(self._active_careplans.get(str(code.code)))

    def has_active_allergy(self, code: Code) -> bool:
        """Whether an allergy with this code is currently active."""
        return bool(self._active_allergies.get(str(code.code)))

    def finalize(self, time: datetime):
        """
        Finalize the health record.
        
        Args:
            time: The finalization time
        """
        # End any active encounters
        if self.current_encounter:
            self.encounter_end(self.current_encounter, time)
        
        # End any other active encounters
        for encounter in self.encounters:
            if encounter.is_active:
                self.encounter_end(encounter, time)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            'encounters': [e.to_dict() for e in self.encounters],
            'conditions': [c.to_dict() for c in self.conditions],
            'medications': [m.to_dict() for m in self.medications],
            'procedures': [p.to_dict() for p in self.procedures],
            'observations': [o.to_dict() for o in self.observations],
            'death_date': self.death_date.isoformat() if self.death_date else None,
        }