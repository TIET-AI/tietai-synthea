"""
Healthcare provider model for Synthea.

This module manages healthcare providers including hospitals, clinics,
and individual practitioners.
"""

from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass
from pathlib import Path
import csv
import json
import random

from synthea.helpers.resources import resource_path


@dataclass
class Provider:
    """Represents a healthcare provider/facility."""
    id: str
    name: str
    organization_type: str  # hospital, clinic, urgentcare, etc.
    address: str
    city: str
    state: str
    zip_code: str
    coordinates: Tuple[float, float]
    phone: str
    capacity: int = 100
    utilization: float = 0.0
    
    def has_capacity(self) -> bool:
        """Check if provider has capacity for new patients."""
        return self.utilization < 0.95  # 95% utilization threshold


@dataclass
class Clinician:
    """Represents an individual healthcare practitioner."""
    id: str
    first_name: str
    last_name: str
    specialty: str
    provider: Optional[Provider] = None
    
    @property
    def full_name(self) -> str:
        """Get full name."""
        return f"{self.first_name} {self.last_name}"


class ProviderManager:
    """Manages healthcare providers and clinicians."""
    
    def __init__(self):
        """Initialize provider manager."""
        self.providers: Dict[str, Provider] = {}
        self.clinicians: Dict[str, Clinician] = {}
        self.providers_by_type: Dict[str, List[Provider]] = {}
        self.providers_by_location: Dict[str, List[Provider]] = {}
    
    def load(self, location: Optional['Location'] = None):
        """
        Load provider data.
        
        Args:
            location: Location to filter providers
        """
        # Try to load from CSV file
        self._load_from_csv()
        
        # If no providers loaded, create defaults
        if not self.providers:
            self._create_default_providers(location)
        
        # Create clinicians
        self._create_clinicians()
        
        # Index providers
        self._index_providers()
    
    def _load_from_csv(self):
        """Load providers from CSV file."""
        paths = [
            resource_path('providers', 'providers.csv'),
            Path('resources/providers/providers.csv'),
            Path('src/main/resources/providers/providers.csv'),
            Path('../resources/providers/providers.csv'),
        ]
        
        for path in paths:
            if path.exists():
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        reader = csv.DictReader(f)
                        for row in reader:
                            provider = self._parse_provider_row(row)
                            if provider:
                                self.providers[provider.id] = provider
                    break
                except Exception:
                    pass
    
    def _parse_provider_row(self, row: Dict[str, str]) -> Optional[Provider]:
        """Parse a provider from CSV row."""
        try:
            return Provider(
                id=row.get('id', ''),
                name=row.get('name', ''),
                organization_type=row.get('type', 'hospital'),
                address=row.get('address', ''),
                city=row.get('city', ''),
                state=row.get('state', ''),
                zip_code=row.get('zip', ''),
                coordinates=(
                    float(row.get('latitude', 0)),
                    float(row.get('longitude', 0))
                ),
                phone=row.get('phone', ''),
                capacity=int(row.get('capacity', 100))
            )
        except (ValueError, KeyError):
            return None
    
    def _create_default_providers(self, location: Optional['Location'] = None):
        """Create default providers."""
        state = location.state if location else "Massachusetts"
        city = location.city if location else "Boston"
        
        # Create default hospital
        hospital = Provider(
            id="hospital-1",
            name=f"{city} General Hospital",
            organization_type="hospital",
            address="123 Main St",
            city=city,
            state=state,
            zip_code="00000",
            coordinates=(0, 0),
            phone="555-0100",
            capacity=500
        )
        self.providers[hospital.id] = hospital
        
        # Create default clinic
        clinic = Provider(
            id="clinic-1",
            name=f"{city} Family Practice",
            organization_type="clinic",
            address="456 Oak Ave",
            city=city,
            state=state,
            zip_code="00000",
            coordinates=(0, 0),
            phone="555-0200",
            capacity=50
        )
        self.providers[clinic.id] = clinic
        
        # Create urgent care
        urgent = Provider(
            id="urgent-1",
            name=f"{city} Urgent Care",
            organization_type="urgentcare",
            address="789 Elm St",
            city=city,
            state=state,
            zip_code="00000",
            coordinates=(0, 0),
            phone="555-0300",
            capacity=25
        )
        self.providers[urgent.id] = urgent
    
    def _create_clinicians(self):
        """Create clinicians for providers."""
        clinician_id = 1
        
        specialties = [
            "General Practice",
            "Internal Medicine",
            "Pediatrics",
            "Emergency Medicine",
            "Cardiology",
            "Orthopedics",
            "Obstetrics/Gynecology",
            "Psychiatry"
        ]
        
        first_names = ["John", "Jane", "Michael", "Sarah", "David", "Emily", "Robert", "Lisa"]
        last_names = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Davis", "Miller", "Wilson"]
        
        for provider in self.providers.values():
            # Create clinicians based on provider capacity
            num_clinicians = max(1, provider.capacity // 20)
            
            for _ in range(num_clinicians):
                clinician = Clinician(
                    id=f"clinician-{clinician_id}",
                    first_name=random.choice(first_names),
                    last_name=random.choice(last_names),
                    specialty=random.choice(specialties),
                    provider=provider
                )
                self.clinicians[clinician.id] = clinician
                clinician_id += 1
    
    def _index_providers(self):
        """Index providers by type and location."""
        self.providers_by_type.clear()
        self.providers_by_location.clear()
        
        for provider in self.providers.values():
            # Index by type
            if provider.organization_type not in self.providers_by_type:
                self.providers_by_type[provider.organization_type] = []
            self.providers_by_type[provider.organization_type].append(provider)
            
            # Index by location (state)
            if provider.state not in self.providers_by_location:
                self.providers_by_location[provider.state] = []
            self.providers_by_location[provider.state].append(provider)
    
    def find_provider(self, encounter_class: str, location: Tuple[float, float],
                     rand: random.Random) -> Optional[Provider]:
        """
        Find a suitable provider for an encounter.
        
        Args:
            encounter_class: Type of encounter (emergency, ambulatory, etc.)
            location: Patient location (lat, lon)
            rand: Random generator
            
        Returns:
            Selected provider or None
        """
        # Map encounter class to provider type
        provider_type_map = {
            'emergency': 'hospital',
            'urgentcare': 'urgentcare',
            'ambulatory': 'clinic',
            'outpatient': 'clinic',
            'inpatient': 'hospital',
            'wellness': 'clinic',
        }
        
        provider_type = provider_type_map.get(encounter_class, 'hospital')
        
        # Get providers of the right type
        candidates = self.providers_by_type.get(provider_type, [])
        
        if not candidates:
            # Fallback to any provider
            candidates = list(self.providers.values())
        
        # Filter by capacity
        available = [p for p in candidates if p.has_capacity()]
        
        if not available:
            # If none available, use any provider
            available = candidates
        
        if available:
            # For now, randomly select
            # Could implement distance-based selection
            return rand.choice(available)
        
        return None
    
    def find_clinician(self, specialty: Optional[str], provider: Optional[Provider],
                      rand: random.Random) -> Optional[Clinician]:
        """
        Find a clinician.
        
        Args:
            specialty: Desired specialty
            provider: Provider to find clinician at
            rand: Random generator
            
        Returns:
            Selected clinician or None
        """
        candidates = []
        
        for clinician in self.clinicians.values():
            if provider and clinician.provider != provider:
                continue
            if specialty and clinician.specialty != specialty:
                continue
            candidates.append(clinician)
        
        if candidates:
            return rand.choice(candidates)
        
        # Fallback to any clinician
        if self.clinicians:
            return rand.choice(list(self.clinicians.values()))
        
        return None