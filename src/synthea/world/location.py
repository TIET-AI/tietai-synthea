"""
Location model for Synthea.

This module handles geographic location data including states, cities,
zip codes, and coordinates.
"""

import json
import csv
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
import random
from dataclasses import dataclass


@dataclass
class City:
    """Represents a city."""
    name: str
    population: int
    coordinates: Tuple[float, float]  # (latitude, longitude)
    zip_codes: List[str]


@dataclass
class State:
    """Represents a state."""
    name: str
    abbreviation: str
    population: int
    cities: List[City]


class Location:
    """Manages location data."""
    
    def __init__(self):
        """Initialize location."""
        self.states: Dict[str, State] = {}
        self.current_state: Optional[State] = None
        self.current_city: Optional[City] = None
        
        # Default to Massachusetts if no state specified
        self.state = "Massachusetts"
        self.state_abbreviation = "MA"
        self.city = "Boston"
        
        self._load_default_data()
    
    def _load_default_data(self):
        """Load default location data."""
        # Default Massachusetts data
        boston = City(
            name="Boston",
            population=675647,
            coordinates=(42.3601, -71.0589),
            zip_codes=["02108", "02109", "02110", "02111", "02112", "02113", "02114", "02115"]
        )
        
        cambridge = City(
            name="Cambridge",
            population=118977,
            coordinates=(42.3736, -71.1097),
            zip_codes=["02138", "02139", "02140", "02141", "02142"]
        )
        
        worcester = City(
            name="Worcester",
            population=185428,
            coordinates=(42.2626, -71.8023),
            zip_codes=["01601", "01602", "01603", "01604", "01605"]
        )
        
        springfield = City(
            name="Springfield",
            population=153060,
            coordinates=(42.1015, -72.5898),
            zip_codes=["01101", "01102", "01103", "01104", "01105"]
        )
        
        ma = State(
            name="Massachusetts",
            abbreviation="MA",
            population=6892503,
            cities=[boston, cambridge, worcester, springfield]
        )
        
        self.states["Massachusetts"] = ma
        self.states["MA"] = ma
        
        # Add more default states
        self._add_default_states()
    
    def _add_default_states(self):
        """Add more default states."""
        # California
        los_angeles = City(
            name="Los Angeles",
            population=3979576,
            coordinates=(34.0522, -118.2437),
            zip_codes=["90001", "90002", "90003", "90004", "90005"]
        )
        
        san_francisco = City(
            name="San Francisco",
            population=881549,
            coordinates=(37.7749, -122.4194),
            zip_codes=["94102", "94103", "94104", "94105", "94107"]
        )
        
        ca = State(
            name="California",
            abbreviation="CA",
            population=39512223,
            cities=[los_angeles, san_francisco]
        )
        
        self.states["California"] = ca
        self.states["CA"] = ca
        
        # New York
        new_york_city = City(
            name="New York",
            population=8336817,
            coordinates=(40.7128, -74.0060),
            zip_codes=["10001", "10002", "10003", "10004", "10005"]
        )
        
        buffalo = City(
            name="Buffalo",
            population=261310,
            coordinates=(42.8864, -78.8784),
            zip_codes=["14201", "14202", "14203", "14204", "14205"]
        )
        
        ny = State(
            name="New York",
            abbreviation="NY",
            population=19453561,
            cities=[new_york_city, buffalo]
        )
        
        self.states["New York"] = ny
        self.states["NY"] = ny
        
        # Texas
        houston = City(
            name="Houston",
            population=2320268,
            coordinates=(29.7604, -95.3698),
            zip_codes=["77001", "77002", "77003", "77004", "77005"]
        )
        
        dallas = City(
            name="Dallas",
            population=1343573,
            coordinates=(32.7767, -96.7970),
            zip_codes=["75201", "75202", "75203", "75204", "75205"]
        )
        
        tx = State(
            name="Texas",
            abbreviation="TX",
            population=28995881,
            cities=[houston, dallas]
        )
        
        self.states["Texas"] = tx
        self.states["TX"] = tx
    
    def load(self, state: Optional[str] = None):
        """
        Load location data.
        
        Args:
            state: State to load data for
        """
        if state:
            self.set_state(state)
        
        # Try to load from files
        self._load_from_files()
    
    def _load_from_files(self):
        """Load location data from files."""
        paths = [
            Path('resources/geography'),
            Path('src/main/resources/geography'),
            Path('../resources/geography'),
        ]
        
        for base_path in paths:
            if base_path.exists():
                self._load_states_from_path(base_path)
                break
    
    def _load_states_from_path(self, base_path: Path):
        """Load state data from a directory."""
        # Look for state JSON files
        for state_file in base_path.glob('*.json'):
            try:
                with open(state_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self._load_state_data(data)
            except Exception:
                pass
    
    def _load_state_data(self, data: Dict[str, Any]):
        """Load state data from JSON."""
        if 'name' not in data or 'abbreviation' not in data:
            return
        
        cities = []
        for city_data in data.get('cities', []):
            city = City(
                name=city_data['name'],
                population=city_data.get('population', 0),
                coordinates=tuple(city_data.get('coordinates', [0, 0])),
                zip_codes=city_data.get('zip_codes', [])
            )
            cities.append(city)
        
        state = State(
            name=data['name'],
            abbreviation=data['abbreviation'],
            population=data.get('population', 0),
            cities=cities
        )
        
        self.states[state.name] = state
        self.states[state.abbreviation] = state
    
    def set_state(self, state: str):
        """
        Set the current state.
        
        Args:
            state: State name or abbreviation
        """
        if state in self.states:
            self.current_state = self.states[state]
            self.state = self.current_state.name
            self.state_abbreviation = self.current_state.abbreviation
            
            # Set default city to first city in state
            if self.current_state.cities:
                self.set_city(self.current_state.cities[0].name)
    
    def set_city(self, city: str):
        """
        Set the current city.
        
        Args:
            city: City name
        """
        if self.current_state:
            for c in self.current_state.cities:
                if c.name.lower() == city.lower():
                    self.current_city = c
                    self.city = c.name
                    break
    
    def random_city(self, rand: random.Random) -> City:
        """
        Select a random city.
        
        Args:
            rand: Random generator
            
        Returns:
            Random city
        """
        if self.current_state and self.current_state.cities:
            # Weight by population
            cities = self.current_state.cities
            weights = [c.population for c in cities]
            return rand.choices(cities, weights=weights)[0]
        
        # Fallback to current city
        return self.current_city or City("Unknown", 0, (0, 0), [])
    
    def random_zip_code(self, rand: random.Random) -> str:
        """
        Select a random zip code.
        
        Args:
            rand: Random generator
            
        Returns:
            Zip code
        """
        city = self.current_city or self.random_city(rand)
        
        if city.zip_codes:
            return rand.choice(city.zip_codes)
        
        # Generate a default zip code
        return "00000"
    
    def random_coordinates(self, rand: random.Random) -> Tuple[float, float]:
        """
        Generate random coordinates near the current location.
        
        Args:
            rand: Random generator
            
        Returns:
            Tuple of (latitude, longitude)
        """
        city = self.current_city or self.random_city(rand)
        
        base_lat, base_lon = city.coordinates
        
        # Add some random variation (about 0.1 degrees ~ 7 miles)
        lat_offset = rand.uniform(-0.1, 0.1)
        lon_offset = rand.uniform(-0.1, 0.1)
        
        return (base_lat + lat_offset, base_lon + lon_offset)
    
    def distance_between(self, coord1: Tuple[float, float], 
                        coord2: Tuple[float, float]) -> float:
        """
        Calculate distance between two coordinates.
        
        Args:
            coord1: First coordinate (lat, lon)
            coord2: Second coordinate (lat, lon)
            
        Returns:
            Distance in kilometers
        """
        import math
        
        lat1, lon1 = coord1
        lat2, lon2 = coord2
        
        # Haversine formula
        R = 6371  # Earth's radius in kilometers
        
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        
        a = (math.sin(dlat / 2) ** 2 + 
             math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * 
             math.sin(dlon / 2) ** 2)
        
        c = 2 * math.asin(math.sqrt(a))
        
        return R * c