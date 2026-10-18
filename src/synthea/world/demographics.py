"""
Demographics model for Synthea.

This module handles demographic data loading and random selection based on
population statistics.
"""

import json
import csv
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
import random
from dataclasses import dataclass

from synthea.helpers.resources import resource_path

logger = logging.getLogger(__name__)

#: Upper bound used for an open-ended top age band (e.g. "100 and over"), so a
#: draw from it stays within plausible human lifespans.
OPEN_BAND_SPAN = 5


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
        
        #: Population by region, sex and age band, from a locale pack. When
        #: present it replaces the national gender and age distributions for
        #: patients whose region it covers.
        self.age_sex: Optional['AgeSexTable'] = None

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
    
    def load_age_sex(self, path) -> None:
        """Use a locale pack's population table for sex and age."""
        self.age_sex = AgeSexTable.from_csv(path)

    def random_gender(self, rand: random.Random,
                      region: Optional[str] = None) -> str:
        """
        Select a random gender.
        
        Args:
            rand: Random generator
            region: The patient's region code, when a population table is
                loaded; the national distribution otherwise
            
        Returns:
            Gender code ('M' or 'F')
        """
        if self.age_sex is not None:
            return self.age_sex.random_sex(rand, region)
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
    
    def random_age(self, rand: random.Random, region: Optional[str] = None,
                   sex: Optional[str] = None) -> int:
        """
        Select a random age.
        
        Args:
            rand: Random generator
            region: The patient's region code (population table only)
            sex: The patient's sex (population table only)
            
        Returns:
            Age in years
        """
        if self.age_sex is not None:
            return self.age_sex.random_age(rand, region, sex)
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


class AgeSexTable:
    """Population counts by region, sex and age band.

    The format is documented on
    :attr:`synthea.locale.base.LocalePack.demographics_file`. Sex is drawn
    from the region's sex totals, then an age band from that sex's band
    counts, then a whole year uniformly within the band.
    """

    def __init__(self, rows: List[Tuple[str, str, int, int, float]]):
        # region -> sex -> [(low, high, count)]
        self.bands: Dict[str, Dict[str, List[Tuple[int, int, float]]]] = {}
        for region, sex, low, high, count in rows:
            self.bands.setdefault(region, {}).setdefault(sex, []).append(
                (low, high, count))
        # Everything pooled, for a patient whose region the table lacks.
        pooled: Dict[str, Dict[Tuple[int, int], float]] = {}
        for by_sex in self.bands.values():
            for sex, bands in by_sex.items():
                for low, high, count in bands:
                    key = (low, high)
                    pooled.setdefault(sex, {})[key] = (
                        pooled.setdefault(sex, {}).get(key, 0.0) + count)
        self.pooled = {sex: [(low, high, count)
                             for (low, high), count in sorted(bands.items())]
                       for sex, bands in pooled.items()}
        self._warned: set = set()

    @classmethod
    def from_csv(cls, path) -> 'AgeSexTable':
        rows = []
        with open(path, 'r', encoding='utf-8-sig', newline='') as handle:
            for row in csv.DictReader(handle):
                try:
                    low = int(row['age_low'])
                    high_text = (row.get('age_high') or '').strip()
                    high = int(high_text) if high_text else low + OPEN_BAND_SPAN - 1
                    rows.append((row['region_code'].strip(),
                                 row['sex'].strip().upper()[:1],
                                 low, high, float(row['population'])))
                except (KeyError, TypeError, ValueError) as error:
                    logger.warning("Skipping a row of %s: %s", path, error)
        if not rows:
            raise ValueError(f"No usable rows in demographics file {path}")
        return cls(rows)

    def _for(self, region: Optional[str]) -> Dict[str, List[Tuple[int, int, float]]]:
        if region is not None and str(region) in self.bands:
            return self.bands[str(region)]
        if region not in self._warned:
            self._warned.add(region)
            logger.warning(
                "No age and sex table for region %r; using every region "
                "pooled.", region)
        return self.pooled

    def random_sex(self, rand: random.Random, region: Optional[str]) -> str:
        by_sex = self._for(region)
        sexes = sorted(by_sex)
        weights = [sum(count for _, _, count in by_sex[sex]) for sex in sexes]
        return rand.choices(sexes, weights=weights)[0]

    def random_age(self, rand: random.Random, region: Optional[str],
                   sex: Optional[str]) -> int:
        by_sex = self._for(region)
        if sex in by_sex:
            bands = by_sex[sex]
        else:
            merged: Dict[Tuple[int, int], float] = {}
            for rows in by_sex.values():
                for low, high, count in rows:
                    merged[(low, high)] = merged.get((low, high), 0.0) + count
            bands = [(low, high, count)
                     for (low, high), count in sorted(merged.items())]
        low, high, _ = rand.choices(bands, weights=[c for _, _, c in bands])[0]
        return rand.randint(low, high)
