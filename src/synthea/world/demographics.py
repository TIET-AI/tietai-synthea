"""
Demographics model for Synthea.

This module handles demographic data loading and random selection based on
population statistics.
"""

import json
import csv
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
import random
from dataclasses import dataclass

from synthea.helpers.resources import resource_path


@dataclass
class DemographicDistribution:
    """Represents a demographic distribution."""
    categories: List[str]
    probabilities: List[float]
    
    def random_choice(self, rand: random.Random) -> str:
        """Select a random category based on probabilities."""
        return rand.choices(self.categories, weights=self.probabilities)[0]


class Demographics:
    """Manages demographic data and distributions."""
    
    def __init__(self):
        """Initialize demographics."""
        self.data: Dict[str, Any] = {}
        self.loaded = False
        
        # Default distributions
        self.gender_distribution = DemographicDistribution(
            categories=['M', 'F'],
            probabilities=[0.49, 0.51]
        )
        
        self.race_distribution = DemographicDistribution(
            categories=['white', 'black', 'asian', 'native', 'other'],
            probabilities=[0.723, 0.127, 0.06, 0.02, 0.07]
        )
        
        self.ethnicity_distribution = DemographicDistribution(
            categories=['hispanic', 'non_hispanic'],
            probabilities=[0.18, 0.82]
        )
        
        self.ses_distribution = DemographicDistribution(
            categories=['low', 'middle', 'high'],
            probabilities=[0.3, 0.5, 0.2]
        )
        
        # Age distribution (simplified)
        self.age_distribution = self._create_age_distribution()
        
        # Name lists
        self.first_names_male: List[str] = []
        self.first_names_female: List[str] = []
        self.last_names: List[str] = []
    
    def _create_age_distribution(self) -> DemographicDistribution:
        """Create age distribution."""
        # Simplified age distribution (US census-like)
        age_ranges = []
        probabilities = []
        
        # 0-18 years: ~22%
        for age in range(0, 19):
            age_ranges.append(age)
            probabilities.append(0.22 / 19)
        
        # 19-65 years: ~60%
        for age in range(19, 66):
            age_ranges.append(age)
            probabilities.append(0.60 / 47)
        
        # 66-100 years: ~18%
        for age in range(66, 101):
            age_ranges.append(age)
            probabilities.append(0.18 / 35)
        
        return DemographicDistribution(
            categories=[str(a) for a in age_ranges],
            probabilities=probabilities
        )
    
    def load(self, location: Optional['Location'] = None):
        """
        Load demographic data.
        
        Args:
            location: Location to load demographics for
        """
        self._load_names()
        
        if location:
            self._load_location_demographics(location)
        
        self.loaded = True
    
    def _load_names(self):
        """Load name lists."""
        # Default name lists
        self.first_names_male = [
            "James", "John", "Robert", "Michael", "William", "David", "Richard",
            "Joseph", "Thomas", "Christopher", "Charles", "Daniel", "Matthew",
            "Anthony", "Mark", "Donald", "Steven", "Kenneth", "Paul", "Joshua"
        ]
        
        self.first_names_female = [
            "Mary", "Patricia", "Jennifer", "Linda", "Elizabeth", "Barbara",
            "Susan", "Jessica", "Sarah", "Karen", "Lisa", "Nancy", "Betty",
            "Margaret", "Sandra", "Ashley", "Kimberly", "Emily", "Donna", "Michelle"
        ]
        
        self.last_names = [
            "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
            "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez",
            "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin"
        ]
        
        # Try to load from files
        self._load_names_from_file('first_names_male.txt', self.first_names_male)
        self._load_names_from_file('first_names_female.txt', self.first_names_female)
        self._load_names_from_file('last_names.txt', self.last_names)
    
    def _load_names_from_file(self, filename: str, target_list: List[str]):
        """Load names from a file."""
        paths = [
            resource_path('names') / filename,
            Path('resources/names') / filename,
            Path('src/main/resources/names') / filename,
            Path('../resources/names') / filename,
        ]
        
        for path in paths:
            if path.exists():
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        names = [line.strip() for line in f if line.strip()]
                        if names:
                            target_list.clear()
                            target_list.extend(names)
                        break
                except Exception:
                    pass
    
    def _load_location_demographics(self, location: 'Location'):
        """Load location-specific demographics."""
        # Try to load state-specific demographics
        state = location.state
        if not state:
            return
        
        paths = [
            resource_path('geography') / f'{state.lower()}_demographics.json',
            Path('resources/geography') / f'{state.lower()}_demographics.json',
            Path('src/main/resources/geography') / f'{state.lower()}_demographics.json',
        ]
        
        for path in paths:
            if path.exists():
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        self._update_distributions(data)
                        break
                except Exception:
                    pass
    
    def _update_distributions(self, data: Dict[str, Any]):
        """Update distributions from loaded data."""
        if 'gender' in data:
            self.gender_distribution = DemographicDistribution(
                categories=list(data['gender'].keys()),
                probabilities=list(data['gender'].values())
            )
        
        if 'race' in data:
            self.race_distribution = DemographicDistribution(
                categories=list(data['race'].keys()),
                probabilities=list(data['race'].values())
            )
        
        if 'ethnicity' in data:
            self.ethnicity_distribution = DemographicDistribution(
                categories=list(data['ethnicity'].keys()),
                probabilities=list(data['ethnicity'].values())
            )
        
        if 'socioeconomic' in data:
            self.ses_distribution = DemographicDistribution(
                categories=list(data['socioeconomic'].keys()),
                probabilities=list(data['socioeconomic'].values())
            )
    
    def random_gender(self, rand: random.Random) -> str:
        """
        Select a random gender.
        
        Args:
            rand: Random generator
            
        Returns:
            Gender code ('M' or 'F')
        """
        return self.gender_distribution.random_choice(rand)
    
    def random_race(self, rand: random.Random) -> str:
        """
        Select a random race.
        
        Args:
            rand: Random generator
            
        Returns:
            Race category
        """
        return self.race_distribution.random_choice(rand)
    
    def random_ethnicity(self, race: str, rand: random.Random) -> str:
        """
        Select a random ethnicity.
        
        Args:
            race: The person's race
            rand: Random generator
            
        Returns:
            Ethnicity category
        """
        # Could be more sophisticated based on race
        return self.ethnicity_distribution.random_choice(rand)
    
    def random_ses(self, rand: random.Random) -> str:
        """
        Select a random socioeconomic status.
        
        Args:
            rand: Random generator
            
        Returns:
            Socioeconomic status category
        """
        return self.ses_distribution.random_choice(rand)
    
    def random_age(self, rand: random.Random) -> int:
        """
        Select a random age.
        
        Args:
            rand: Random generator
            
        Returns:
            Age in years
        """
        age_str = self.age_distribution.random_choice(rand)
        return int(age_str)
    
    def random_first_name(self, gender: str, rand: random.Random) -> str:
        """
        Select a random first name.
        
        Args:
            gender: Gender ('M' or 'F')
            rand: Random generator
            
        Returns:
            First name
        """
        if gender == 'M':
            return rand.choice(self.first_names_male)
        else:
            return rand.choice(self.first_names_female)
    
    def random_last_name(self, rand: random.Random) -> str:
        """
        Select a random last name.
        
        Args:
            rand: Random generator
            
        Returns:
            Last name
        """
        return rand.choice(self.last_names)
    
    def random_name(self, gender: str, rand: random.Random) -> Tuple[str, str]:
        """
        Generate a random full name.
        
        Args:
            gender: Gender ('M' or 'F')
            rand: Random generator
            
        Returns:
            Tuple of (first_name, last_name)
        """
        first = self.random_first_name(gender, rand)
        last = self.random_last_name(rand)
        return first, last