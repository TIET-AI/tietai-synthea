"""
Person model for Synthea.

This module defines the Person class which represents an individual patient
throughout their simulated lifetime.
"""

import random
from typing import Dict, Any, Optional, List, TYPE_CHECKING
from datetime import datetime, timedelta
import hashlib

if TYPE_CHECKING:
    from synthea.world.health_record import HealthRecord


class Person:
    """Represents a simulated person/patient."""
    
    def __init__(self, seed: Optional[int] = None):
        """
        Initialize a new person.
        
        Args:
            seed: Random seed for reproducible randomness
        """
        # Set up random generator
        if seed is not None:
            self.seed = seed
            self.random = random.Random(seed)
        else:
            self.seed = random.randint(0, 2**32 - 1)
            self.random = random.Random(self.seed)
        
        # Core attributes
        self.attributes: Dict[str, Any] = {}
        self.alive: bool = True
        
        # Health-related
        self.symptoms: Dict[str, Dict[str, Any]] = {}
        self.vital_signs: Dict[str, Dict[str, Any]] = {}
        
        # Health record
        self.record: Optional['HealthRecord'] = None
        
        # Unique identifier
        self.id = self._generate_id()
    
    def _generate_id(self) -> str:
        """Generate a unique identifier for this person."""
        # Use seed to generate consistent ID
        hash_input = f"person_{self.seed}"
        return hashlib.sha256(hash_input.encode()).hexdigest()[:16]
    
    def init_health_record(self):
        """Initialize the person's health record."""
        from synthea.world.health_record import HealthRecord
        self.record = HealthRecord(self)
    
    def finalize_health_record(self, time: datetime):
        """Finalize the health record at the given time."""
        if self.record:
            self.record.finalize(time)
    
    def age_at(self, time: datetime) -> float:
        """
        Calculate the person's age at a given time.
        
        Args:
            time: The time to calculate age at
            
        Returns:
            Age in years
        """
        birth_date = self.attributes.get('birth_date')
        if not birth_date:
            return 0.0
        
        if isinstance(birth_date, str):
            birth_date = datetime.fromisoformat(birth_date)
        
        age_delta = time - birth_date
        return age_delta.days / 365.25
    
    @property
    def age(self) -> float:
        """Get the person's current age."""
        return self.age_at(datetime.now())
    
    @property
    def gender(self) -> str:
        """Get the person's gender."""
        return self.attributes.get('gender', 'U')
    
    @property
    def race(self) -> str:
        """Get the person's race."""
        return self.attributes.get('race', 'other')
    
    @property
    def ethnicity(self) -> str:
        """Get the person's ethnicity."""
        return self.attributes.get('ethnicity', 'non_hispanic')
    
    @property
    def birth_date(self) -> Optional[datetime]:
        """Get the person's birth date."""
        birth = self.attributes.get('birth_date')
        if isinstance(birth, str):
            return datetime.fromisoformat(birth)
        return birth
    
    @property
    def death_date(self) -> Optional[datetime]:
        """Get the person's death date."""
        death = self.attributes.get('death_date')
        if isinstance(death, str):
            return datetime.fromisoformat(death)
        return death
    
    def get_vital_sign(self, vital_sign: str) -> Optional[float]:
        """
        Get the current value of a vital sign.
        
        Args:
            vital_sign: The name of the vital sign
            
        Returns:
            The value of the vital sign, or None if not set
        """
        if vital_sign in self.vital_signs:
            return self.vital_signs[vital_sign].get('value')
        return None
    
    def set_vital_sign(self, vital_sign: str, value: float, unit: str, time: datetime):
        """
        Set a vital sign value.
        
        Args:
            vital_sign: The name of the vital sign
            value: The value to set
            unit: The unit of measurement
            time: The time of measurement
        """
        self.vital_signs[vital_sign] = {
            'value': value,
            'unit': unit,
            'time': time
        }
    
    def get_symptom(self, symptom: str) -> float:
        """
        Get the current value of a symptom.
        
        Args:
            symptom: The name of the symptom
            
        Returns:
            The symptom value (0-100), or 0 if not present
        """
        if symptom in self.symptoms:
            return self.symptoms[symptom].get('value', 0)
        return 0
    
    def set_symptom(self, symptom: str, value: float, cause: Optional[str] = None, 
                   time: Optional[datetime] = None):
        """
        Set a symptom value.
        
        Args:
            symptom: The name of the symptom
            value: The symptom value (0-100 scale)
            cause: The cause of the symptom
            time: The time the symptom started
        """
        self.symptoms[symptom] = {
            'value': max(0, min(100, value)),  # Clamp to 0-100
            'cause': cause,
            'time': time or datetime.now()
        }
    
    def rand(self, min_val: float = 0.0, max_val: float = 1.0) -> float:
        """
        Generate a random float using this person's random generator.
        
        Args:
            min_val: Minimum value
            max_val: Maximum value
            
        Returns:
            Random float between min_val and max_val
        """
        if min_val == 0.0 and max_val == 1.0:
            return self.random.random()
        return self.random.uniform(min_val, max_val)
    
    def rand_int(self, min_val: int, max_val: int) -> int:
        """
        Generate a random integer using this person's random generator.
        
        Args:
            min_val: Minimum value (inclusive)
            max_val: Maximum value (inclusive)
            
        Returns:
            Random integer between min_val and max_val
        """
        return self.random.randint(min_val, max_val)
    
    def rand_choice(self, choices: List[Any]) -> Any:
        """
        Make a random choice from a list.
        
        Args:
            choices: List of choices
            
        Returns:
            Randomly selected choice
        """
        return self.random.choice(choices)
    
    def rand_bool(self, probability: float = 0.5) -> bool:
        """
        Generate a random boolean.
        
        Args:
            probability: Probability of returning True
            
        Returns:
            Random boolean
        """
        return self.random.random() < probability
    
    def get_attribute(self, key: str, default: Any = None) -> Any:
        """
        Get an attribute value.
        
        Args:
            key: The attribute key
            default: Default value if not found
            
        Returns:
            The attribute value or default
        """
        return self.attributes.get(key, default)
    
    def set_attribute(self, key: str, value: Any):
        """
        Set an attribute value.
        
        Args:
            key: The attribute key
            value: The value to set
        """
        self.attributes[key] = value
    
    def has_attribute(self, key: str) -> bool:
        """
        Check if an attribute exists.
        
        Args:
            key: The attribute key
            
        Returns:
            True if the attribute exists
        """
        return key in self.attributes
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert person to dictionary representation.
        
        Returns:
            Dictionary representation of the person
        """
        return {
            'id': self.id,
            'seed': self.seed,
            'alive': self.alive,
            'attributes': self.attributes.copy(),
            'vital_signs': self.vital_signs.copy(),
            'symptoms': self.symptoms.copy(),
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Person':
        """
        Create a person from dictionary representation.
        
        Args:
            data: Dictionary representation
            
        Returns:
            Person instance
        """
        person = cls(data.get('seed'))
        person.id = data.get('id', person.id)
        person.alive = data.get('alive', True)
        person.attributes = data.get('attributes', {}).copy()
        person.vital_signs = data.get('vital_signs', {}).copy()
        person.symptoms = data.get('symptoms', {}).copy()
        return person