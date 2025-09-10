"""
Health record model for Synthea.

This module defines the health record structure that tracks all medical events,
conditions, medications, and procedures for a person.
"""

from typing import Dict, Any, Optional, List, Union, TYPE_CHECKING
from datetime import datetime
from dataclasses import dataclass, field
from enum import Enum
import uuid

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
    """Represents a medication prescription."""
    encounter: Optional[Encounter] = None
    end_time: Optional[datetime] = None
    reason: Optional[str] = None
    dosage: Optional[Dict[str, Any]] = None
    
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
    """Represents an imaging study."""
    encounter: Optional[Encounter] = None
    modality: Optional[str] = None
    body_site: Optional[str] = None
    series: List[Dict[str, Any]] = field(default_factory=list)


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


class HealthRecord:
    """Complete health record for a person."""
    
    def __init__(self, person: 'Person'):
        """
        Initialize a health record.
        
        Args:
            person: The person this record belongs to
        """
        self.person = person
        
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
        
        # Death information
        self.death_date: Optional[datetime] = None
        self.death_cause: Optional[Code] = None
    
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
        
        self.encounters.append(encounter)
        self.current_encounter = encounter
        
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
    
    def condition_start(self, time: datetime, code: Optional[Code] = None) -> Condition:
        """
        Record a new condition.
        
        Args:
            time: Onset time
            code: Condition code
            
        Returns:
            The new condition
        """
        condition = Condition(time=time)
        if code:
            condition.codes = [code]
        
        condition.encounter = self.current_encounter
        
        self.conditions.append(condition)
        
        if self.current_encounter:
            self.current_encounter.conditions.append(condition)
        
        return condition
    
    def condition_end(self, condition: Condition, time: datetime):
        """
        End a condition.
        
        Args:
            condition: The condition to end
            time: End time
        """
        condition.end_time = time
    
    def allergy_start(self, time: datetime, code: Optional[Code] = None) -> Allergy:
        """
        Record a new allergy.
        
        Args:
            time: Onset time
            code: Allergy code
            
        Returns:
            The new allergy
        """
        allergy = Allergy(time=time)
        if code:
            allergy.codes = [code]
        
        allergy.encounter = self.current_encounter
        self.allergies.append(allergy)
        
        return allergy
    
    def allergy_end(self, allergy: Allergy, time: datetime):
        """
        End an allergy.
        
        Args:
            allergy: The allergy to end
            time: End time
        """
        allergy.end_time = time
    
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
        if code:
            medication.codes = [code]
        
        medication.encounter = encounter or self.current_encounter
        
        self.medications.append(medication)
        
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
        if code:
            observation.codes = [code]
        
        observation.encounter = encounter or self.current_encounter
        
        self.observations.append(observation)
        
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
        if code:
            careplan.codes = [code]
        
        careplan.encounter = self.current_encounter
        
        self.careplans.append(careplan)
        
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
        """
        Get the most recent observation with the given code.
        
        Args:
            code: The observation code to search for
            
        Returns:
            The most recent matching observation, or None
        """
        matching = [
            obs for obs in self.observations
            if any(c.code == code.code for c in obs.codes)
        ]
        
        if matching:
            return max(matching, key=lambda o: o.time)
        return None
    
    def has_active_condition(self, code: Code) -> bool:
        """
        Check if a condition is currently active.
        
        Args:
            code: The condition code to check
            
        Returns:
            True if the condition is active
        """
        return any(
            c.is_active and any(cc.code == code.code for cc in c.codes)
            for c in self.conditions
        )
    
    def has_active_medication(self, code: Code) -> bool:
        """
        Check if a medication is currently active.
        
        Args:
            code: The medication code to check
            
        Returns:
            True if the medication is active
        """
        return any(
            m.is_active and any(mc.code == code.code for mc in m.codes)
            for m in self.medications
        )
    
    def has_active_careplan(self, code: Code) -> bool:
        """
        Check if a care plan is currently active.
        
        Args:
            code: The care plan code to check
            
        Returns:
            True if the care plan is active
        """
        return any(
            cp.is_active and any(cpc.code == code.code for cpc in cp.codes)
            for cp in self.careplans
        )
    
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