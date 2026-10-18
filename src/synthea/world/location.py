"""
Location model for Synthea.

This module handles geographic location data including states, cities,
zip codes, and coordinates.
"""

import json
import csv
import logging
import math
from pathlib import Path
from typing import Dict, Any, Iterable, Optional, List, Sequence, Tuple
import random
from dataclasses import dataclass, field

from synthea.helpers.resources import resource_path

logger = logging.getLogger(__name__)


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
            resource_path('geography'),
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
        else:
            # Not silently: an unrecognised state used to leave every patient
            # in the default, which looks like a successful run.
            logger.warning(
                "Unknown state %r: the built-in geography knows %s. Patients "
                "keep the default location (%s).", state,
                ', '.join(sorted({s.name for s in self.states.values()})),
                self.state,
            )
    
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
            else:
                logger.warning(
                    "Unknown city %r in %s: known cities are %s. Patients keep "
                    "%s.", city, self.current_state.name,
                    ', '.join(c.name for c in self.current_state.cities),
                    self.city,
                )
    
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


# ----------------------------------------------------------------------
# Locale-pack geography
# ----------------------------------------------------------------------

#: Default radius, in kilometres, around a municipality's reference point
#: within which a home is placed when the file gives none.
DEFAULT_RADIUS_KM = 2.0


@dataclass
class Municipality:
    """One row of a locale pack's geography file."""
    region: str
    region_code: str
    city: str
    name: str
    code: str
    postal_codes: List[str]
    coordinates: Tuple[float, float]
    population: int
    catchment: str = ''
    radius_km: float = DEFAULT_RADIUS_KM


class PackGeography:
    """Where patients live, from a locale pack's geography file.

    The built-in :class:`Location` knows a handful of US cities and, unless a
    state is chosen, places everyone at latitude 0, longitude 0 with ZIP code
    `00000`. A pack geography instead gives every patient a real municipality,
    drawn in proportion to its population, with one of its postal codes and a
    home near it.

    The file format is documented on
    :attr:`synthea.locale.base.LocalePack.geography_file`. Selection works for
    any pack: `restrict(regions=..., cities=...)` keeps the matching rows, and
    an unknown name is a warning naming what is known rather than a silent
    fall back to everywhere.
    """

    def __init__(self, municipalities: Sequence[Municipality]):
        self.municipalities: List[Municipality] = list(municipalities)
        self.selected: List[Municipality] = list(self.municipalities)
        self._weights = [m.population for m in self.selected]
        #: Kept for interfaces written against :class:`Location`. A pack
        #: geography has no single state or city, so both are None and
        #: nothing downstream narrows by them.
        self.state: Optional[str] = None
        self.city: Optional[str] = None

    # ------------------------------------------------------------------

    @classmethod
    def from_csv(cls, path) -> 'PackGeography':
        rows: List[Municipality] = []
        with open(path, 'r', encoding='utf-8-sig', newline='') as handle:
            for number, row in enumerate(csv.DictReader(handle), start=2):
                try:
                    rows.append(_municipality(row))
                except (KeyError, TypeError, ValueError) as error:
                    logger.warning("Skipping %s line %d: %s", path, number, error)
        if not rows:
            raise ValueError(f"No usable rows in geography file {path}")
        return cls(rows)

    # ------------------------------------------------------------------

    def regions(self) -> List[str]:
        return sorted({m.region for m in self.municipalities})

    def cities(self) -> List[str]:
        return sorted({m.city for m in self.municipalities})

    def restrict(self, regions: Iterable[str] = (), cities: Iterable[str] = ()
                 ) -> List[str]:
        """Keep only the named regions and/or cities. Returns unknown names.

        A region matches its name or code; a city matches the urban area
        (`city` column) or a single municipality. Matching ignores case and
        accents. When nothing requested is known the selection is left as it
        was, with a warning, rather than emptied.
        """
        regions = [r for r in (str(r).strip() for r in regions) if r]
        cities = [c for c in (str(c).strip() for c in cities) if c]
        if not regions and not cities:
            return []

        unknown: List[str] = []
        selected = self.municipalities

        if regions:
            wanted = {_fold(r) for r in regions}
            known = {_fold(m.region) for m in selected} | {
                _fold(m.region_code) for m in selected}
            unknown += [r for r in regions if _fold(r) not in known]
            selected = [m for m in selected
                        if _fold(m.region) in wanted
                        or _fold(m.region_code) in wanted]

        if cities:
            wanted = {_fold(c) for c in cities}
            known = {_fold(m.city) for m in selected} | {
                _fold(m.name) for m in selected}
            unknown += [c for c in cities if _fold(c) not in known]
            selected = [m for m in selected
                        if _fold(m.city) in wanted or _fold(m.name) in wanted]

        if unknown:
            logger.warning(
                "Unknown geography %s. Known regions: %s. Known cities: %s.",
                ', '.join(repr(u) for u in unknown),
                ', '.join(self.regions()), ', '.join(self.cities()),
            )

        if not selected:
            logger.warning(
                "The geography selection matched nothing, so patients are "
                "drawn from every place in the file.")
            return unknown

        self.selected = selected
        self._weights = [m.population for m in selected]
        return unknown

    # ------------------------------------------------------------------

    def random_place(self, rand: random.Random) -> Dict[str, Any]:
        """A home for one patient: municipality, postal code and coordinates.

        Three draws, always in this order: the municipality (weighted by
        population), the postal code, then the point (two draws).
        """
        place = rand.choices(self.selected, weights=self._weights)[0]
        postal = rand.choice(place.postal_codes) if place.postal_codes else None
        latitude, longitude = _point_near(place.coordinates, place.radius_km,
                                          rand)
        return {
            'state': place.region,
            'region_code': place.region_code,
            'city': place.name,
            'municipality_code': place.code,
            'urban_area': place.city,
            'catchment_area': place.catchment or place.city,
            'zip_code': postal,
            'latitude': latitude,
            'longitude': longitude,
        }


def _municipality(row: Dict[str, str]) -> Municipality:
    radius = (row.get('radius_km') or '').strip()
    return Municipality(
        region=row['region'].strip(),
        region_code=row['region_code'].strip(),
        city=row['city'].strip(),
        name=row['municipality'].strip(),
        code=(row.get('municipality_code') or '').strip(),
        postal_codes=[code.strip() for code in
                      (row.get('postal_codes') or '').split('|')
                      if code.strip()],
        coordinates=(float(row['lat']), float(row['lon'])),
        population=int(float(row['population'])),
        catchment=(row.get('catchment') or '').strip(),
        radius_km=float(radius) if radius else DEFAULT_RADIUS_KM,
    )


def _point_near(centre: Tuple[float, float], radius_km: float,
                rand: random.Random) -> Tuple[float, float]:
    """A point uniformly distributed within a disc around `centre`."""
    distance = radius_km * math.sqrt(rand.random())
    bearing = rand.uniform(0.0, 2.0 * math.pi)
    latitude = centre[0] + (distance / 111.32) * math.cos(bearing)
    scale = 111.32 * max(0.01, math.cos(math.radians(centre[0])))
    longitude = centre[1] + (distance / scale) * math.sin(bearing)
    return round(latitude, 6), round(longitude, 6)


def _fold(text: str) -> str:
    """Lower case without accents, so `Malaga` finds `Málaga`."""
    import unicodedata

    decomposed = unicodedata.normalize('NFKD', str(text).strip().lower())
    return ''.join(ch for ch in decomposed if not unicodedata.combining(ch))
