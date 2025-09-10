"""
Tests for the Person model.
"""

import pytest
from datetime import datetime, timedelta
from synthea.world.person import Person


class TestPerson:
    """Test Person class."""
    
    def test_person_creation(self):
        """Test creating a person."""
        person = Person(seed=12345)
        
        assert person.seed == 12345
        assert person.alive is True
        assert person.id is not None
        assert len(person.id) == 16  # SHA256 truncated to 16 chars
    
    def test_person_reproducibility(self):
        """Test that same seed produces same person."""
        person1 = Person(seed=42)
        person2 = Person(seed=42)
        
        assert person1.id == person2.id
        assert person1.seed == person2.seed
    
    def test_person_age_calculation(self):
        """Test age calculation."""
        person = Person()
        birth_date = datetime.now() - timedelta(days=365 * 25)  # 25 years ago
        person.attributes['birth_date'] = birth_date
        
        age = person.age_at(datetime.now())
        assert 24.9 < age < 25.1  # Account for leap years
    
    def test_person_attributes(self):
        """Test attribute management."""
        person = Person()
        
        # Test setting and getting attributes
        person.set_attribute('test_key', 'test_value')
        assert person.get_attribute('test_key') == 'test_value'
        assert person.has_attribute('test_key') is True
        assert person.has_attribute('nonexistent') is False
        
        # Test default values
        assert person.get_attribute('nonexistent', 'default') == 'default'
    
    def test_person_vital_signs(self):
        """Test vital sign management."""
        person = Person()
        
        # Set vital sign
        person.set_vital_sign('blood_pressure', 120, 'mmHg', datetime.now())
        
        # Get vital sign
        bp = person.get_vital_sign('blood_pressure')
        assert bp == 120
        
        # Non-existent vital sign
        assert person.get_vital_sign('nonexistent') is None
    
    def test_person_symptoms(self):
        """Test symptom management."""
        person = Person()
        
        # Set symptom
        person.set_symptom('headache', 75, 'stress', datetime.now())
        
        # Get symptom
        headache = person.get_symptom('headache')
        assert headache == 75
        
        # Non-existent symptom
        assert person.get_symptom('nonexistent') == 0
        
        # Test clamping
        person.set_symptom('pain', 150)  # Over 100
        assert person.get_symptom('pain') == 100
        
        person.set_symptom('mild', -10)  # Below 0
        assert person.get_symptom('mild') == 0
    
    def test_person_random_generators(self):
        """Test random number generation."""
        person = Person(seed=100)
        
        # Test float generation
        val1 = person.rand()
        assert 0 <= val1 <= 1
        
        val2 = person.rand(10, 20)
        assert 10 <= val2 <= 20
        
        # Test integer generation
        int_val = person.rand_int(1, 10)
        assert 1 <= int_val <= 10
        
        # Test choice
        choices = ['a', 'b', 'c']
        choice = person.rand_choice(choices)
        assert choice in choices
        
        # Test boolean
        bool_val = person.rand_bool(0.5)
        assert isinstance(bool_val, bool)
        
        # Test reproducibility
        person2 = Person(seed=100)
        assert person2.rand() == val1
    
    def test_person_serialization(self):
        """Test serialization to/from dict."""
        person = Person(seed=999)
        person.attributes['name'] = 'Test Person'
        person.set_vital_sign('temperature', 98.6, 'F', datetime.now())
        person.set_symptom('fever', 20)
        
        # Convert to dict
        data = person.to_dict()
        
        assert data['seed'] == 999
        assert data['id'] == person.id
        assert data['alive'] is True
        assert data['attributes']['name'] == 'Test Person'
        assert 'temperature' in data['vital_signs']
        assert 'fever' in data['symptoms']
        
        # Create from dict
        person2 = Person.from_dict(data)
        
        assert person2.seed == person.seed
        assert person2.id == person.id
        assert person2.attributes['name'] == 'Test Person'
        assert person2.get_vital_sign('temperature') == 98.6
        assert person2.get_symptom('fever') == 20