"""Healthcare providers: where care happens, and who gives it.

Encounters used to have no provider at all. The manager loaded nothing — the
facility data it looked for was never bundled — and fell back to three
hard-coded clinics that no encounter ever referenced. So a generated record
could not answer the most basic question asked of it: where did this happen,
and who saw the patient.

Two things matter for realism beyond simply attaching a name.

**Continuity of care.** A patient keeps the same primary care practice and, for
routine visits, largely the same clinician. Drawing a random facility per
encounter produces records that look nothing like a real patient's history and
defeat anything that reasons about a care relationship.

**Proximity.** People attend facilities near them. Selection is by distance
from the patient, among facilities of the type the encounter needs.
"""

from __future__ import annotations

import csv
import logging
import math
import random
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple, TYPE_CHECKING

from synthea.helpers.optional_data import cached_path
from synthea.helpers.resources import resource_path
from synthea.helpers.rng import derive_seed, random_seed

logger = logging.getLogger(__name__)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from synthea.world.location import Location
    from synthea.world.person import Person

#: Facility files, mapped to the provider type they supply. Files that are not
#: bundled are fetched with `synthea fetch-data facilities`; a missing file is
#: skipped rather than being an error.
FACILITY_FILES = {
    'hospitals.csv': 'hospital',
    'primary_care_facilities.csv': 'primary_care',
    'primary_care_facilities_children.csv': 'primary_care',
    'primary_care_facilities_women.csv': 'primary_care',
    'urgent_care_facilities.csv': 'urgent_care',
    'va_facilities.csv': 'hospital',
    'ihs_facilities.csv': 'primary_care',
    'ihs_centers.csv': 'primary_care',
    'longterm.csv': 'longterm',
    'nursing.csv': 'nursing',
    'rehab.csv': 'rehab',
    'hospice.csv': 'hospice',
    'dialysis.csv': 'dialysis',
    'home_health_agencies.csv': 'home_health',
    'ambulatory_surgical_center.csv': 'surgical',
}

#: Which provider type an encounter class is looking for, in order of
#: preference. A wellness visit is primary care; an emergency needs a hospital.
ENCOUNTER_PROVIDER_TYPES = {
    'wellness': ('primary_care', 'hospital'),
    'ambulatory': ('primary_care', 'hospital'),
    'outpatient': ('primary_care', 'hospital'),
    'emergency': ('hospital',),
    'inpatient': ('hospital',),
    'urgentcare': ('urgent_care', 'primary_care', 'hospital'),
    'snf': ('nursing', 'longterm', 'hospital'),
    'hospice': ('hospice', 'home_health', 'hospital'),
    'home': ('home_health', 'primary_care'),
    'virtual': ('primary_care', 'hospital'),
}

#: Clinician specialties, and the share of clinicians in each.
SPECIALTIES = [
    ('General Practice', 0.30),
    ('Internal Medicine', 0.20),
    ('Pediatrics', 0.10),
    ('Emergency Medicine', 0.10),
    ('Cardiology', 0.07),
    ('Orthopedics', 0.07),
    ('Obstetrics and Gynecology', 0.06),
    ('Psychiatry', 0.05),
    ('Dermatology', 0.03),
    ('Oncology', 0.02),
]

#: Names used for generated clinicians.
FIRST_NAMES = ["John", "Jane", "Michael", "Sarah", "David", "Emily",
               "Robert", "Lisa", "Carlos", "Priya", "Ahmed", "Grace"]
LAST_NAMES = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Davis",
              "Miller", "Wilson", "Garcia", "Okafor", "Nguyen", "Rossi"]

#: Clinicians generated per facility. Real counts vary hugely; this is enough
#: for continuity to be meaningful without inventing a staffing model.
CLINICIANS_PER_FACILITY = 4

#: Chance a routine visit is with the patient's usual clinician rather than a
#: colleague at the same practice.
USUAL_CLINICIAN_SHARE = 0.85


@dataclass
class Provider:
    """A healthcare facility."""
    id: str
    name: str
    organization_type: str
    address: str
    city: str
    state: str
    zip_code: str
    coordinates: Tuple[float, float]
    phone: str
    capacity: int = 100
    utilization: float = 0.0

    def has_capacity(self) -> bool:
        """Whether the facility can take another patient."""
        return self.utilization < 0.95


@dataclass
class Clinician:
    """An individual practitioner."""
    id: str
    first_name: str
    last_name: str
    specialty: str
    provider: Optional[Provider] = None
    npi: Optional[str] = None

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"


class ProviderManager:
    """Loads facilities and assigns them, with continuity, to patients."""

    def __init__(self, seed: Optional[int] = None):
        """
        Args:
            seed: Seed for clinician generation, kept separate from the patient
                stream so staffing changes do not perturb patients.
        """
        self.providers: Dict[str, Provider] = {}
        self.clinicians: Dict[str, Clinician] = {}
        self.providers_by_type: Dict[str, List[Provider]] = {}
        self.providers_by_location: Dict[str, List[Provider]] = {}
        self.clinicians_by_provider: Dict[str, List[Clinician]] = {}
        self._clinician_seed = seed if seed is not None else random_seed()
        self.random = random.Random(self._clinician_seed)
        self._state_filter: Optional[str] = None

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def load(self, location: Optional['Location'] = None):
        """Load facilities, narrowed to the location when one is given."""
        self._state_filter = getattr(location, 'state', None)

        self._load_facilities()

        if not self.providers:
            logger.warning(
                "No facility data found; falling back to synthetic providers. "
                "Run `synthea fetch-data facilities` for the full directory.",
            )
            self._create_default_providers(location)

        self._index_providers()

    def _load_facilities(self) -> None:
        for filename, provider_type in FACILITY_FILES.items():
            path = cached_path(f'providers/{filename}') or resource_path(
                'providers', filename)
            if not path or not path.exists():
                continue
            try:
                self._load_file(path, provider_type)
            except Exception as error:  # pragma: no cover - defensive
                logger.warning("Could not read facilities from %s: %s", path, error)

    def _load_file(self, path, provider_type: str) -> None:
        with open(path, 'r', encoding='utf-8-sig', newline='') as handle:
            for row in csv.DictReader(handle):
                provider = self._parse_row(row, provider_type)
                if provider is None:
                    continue
                if self._state_filter and provider.state and \
                        provider.state.upper() != _state_code(self._state_filter):
                    continue
                self.providers[provider.id] = provider

    def _parse_row(self, row: Dict[str, str], provider_type: str) -> Optional[Provider]:
        """Build a Provider from a facility row.

        Column names differ between the upstream files, so each field is looked
        up through a list of aliases rather than a fixed name.
        """
        identifier = _first(row, 'id', 'provider_num', 'npi', 'ccn')
        name = _first(row, 'name', 'facility_name', 'NAME')
        if not identifier or not name:
            return None

        latitude = _as_float(_first(row, 'lat', 'LAT', 'latitude'))
        longitude = _as_float(_first(row, 'lon', 'LON', 'longitude'))
        if latitude is None or longitude is None:
            return None

        return Provider(
            id=f"{provider_type}-{identifier}",
            name=name.strip(),
            organization_type=provider_type,
            address=(_first(row, 'address', 'ADDRESS') or '').strip(),
            city=(_first(row, 'city', 'CITY') or '').strip(),
            state=(_first(row, 'state', 'STATE') or '').strip(),
            zip_code=(_first(row, 'zip', 'ZIP') or '').strip(),
            coordinates=(latitude, longitude),
            phone=(_first(row, 'phone', 'PHONE') or '').strip(),
            capacity=int(_as_float(_first(row, 'bed_count', 'beds')) or 50),
        )

    def _create_default_providers(self, location: Optional['Location'] = None):
        """Synthetic facilities, used only when no real data is present."""
        state = getattr(location, 'state', None) or 'Massachusetts'
        city = getattr(location, 'city', None) or 'Boston'

        for index, (kind, label, capacity) in enumerate((
            ('hospital', 'General Hospital', 500),
            ('primary_care', 'Family Practice', 50),
            ('urgent_care', 'Urgent Care', 25),
        ), start=1):
            provider = Provider(
                id=f"{kind}-synthetic-{index}",
                name=f"{city} {label}",
                organization_type=kind,
                address=f"{index * 100} Main St",
                city=city,
                state=state,
                zip_code="00000",
                coordinates=(0.0, 0.0),
                phone=f"555-01{index:02d}",
                capacity=capacity,
            )
            self.providers[provider.id] = provider

    # ------------------------------------------------------------------
    # Staffing
    # ------------------------------------------------------------------

    def _staff(self, provider: Provider) -> List[Clinician]:
        """The clinicians at a facility, created on first use.

        Staffing every facility up front meant 200,000 clinicians for a
        nationwide load, almost all of whom no patient ever meets. They are
        created when a facility is first used instead, seeded from the facility
        id so the same practice always has the same people regardless of which
        patient arrives first.
        """
        existing = self.clinicians_by_provider.get(provider.id)
        if existing is not None:
            return existing

        rand = random.Random(derive_seed(self._clinician_seed, 0, provider.id))
        specialties = [name for name, _ in SPECIALTIES]
        weights = [share for _, share in SPECIALTIES]

        staff: List[Clinician] = []
        for index in range(CLINICIANS_PER_FACILITY):
            clinician = Clinician(
                id=f"{provider.id}-clinician-{index + 1}",
                first_name=rand.choice(FIRST_NAMES),
                last_name=rand.choice(LAST_NAMES),
                specialty=rand.choices(specialties, weights=weights)[0],
                provider=provider,
                # 9999 prefix: the NPI registry has never issued one.
                npi=f"9999{rand.randint(100000, 999999)}",
            )
            self.clinicians[clinician.id] = clinician
            staff.append(clinician)

        self.clinicians_by_provider[provider.id] = staff
        return staff

    def _index_providers(self):
        self.providers_by_type.clear()
        self.providers_by_location.clear()
        for provider in self.providers.values():
            self.providers_by_type.setdefault(
                provider.organization_type, []).append(provider)
            self.providers_by_location.setdefault(
                provider.state, []).append(provider)

    # ------------------------------------------------------------------
    # Assignment
    # ------------------------------------------------------------------

    def find_provider(self, encounter_class: str,
                      location: Optional[Tuple[float, float]] = None,
                      rand: Optional[random.Random] = None) -> Optional[Provider]:
        """The nearest suitable facility for an encounter of this class."""
        for provider_type in ENCOUNTER_PROVIDER_TYPES.get(
                encounter_class, ('primary_care', 'hospital')):
            candidates = self.providers_by_type.get(provider_type)
            if candidates:
                return self._nearest(candidates, location, rand)

        any_provider = list(self.providers.values())
        return self._nearest(any_provider, location, rand) if any_provider else None

    def _nearest(self, candidates: List[Provider],
                 location: Optional[Tuple[float, float]],
                 rand: Optional[random.Random]) -> Provider:
        """The closest facility, chosen from a few nearby rather than the
        single nearest, so a town's patients do not all attend one practice."""
        if not location or location == (0.0, 0.0):
            picker = rand or self.random
            return picker.choice(candidates)

        nearest = sorted(candidates, key=lambda p: _distance(location, p.coordinates))
        shortlist = nearest[:5] or nearest
        picker = rand or self.random
        return picker.choice(shortlist)

    def assign_primary_care(self, person: 'Person') -> Optional[Provider]:
        """The patient's usual practice, chosen once and kept."""
        existing = person.attributes.get('primary_care_provider')
        if existing is not None:
            return existing

        location = (person.attributes.get('latitude'),
                    person.attributes.get('longitude'))
        if location[0] is None or location[1] is None:
            location = None

        provider = self.find_provider('wellness', location, person.random)
        if provider is None:
            return None

        person.attributes['primary_care_provider'] = provider

        staff = self._staff(provider)
        if staff:
            person.attributes['primary_care_clinician'] = person.random.choice(staff)

        return provider

    def assign_to_encounter(self, person: 'Person', encounter) -> None:
        """Attach a facility and a clinician to an encounter.

        Routine care goes to the patient's usual practice, and usually to their
        usual clinician; anything else is chosen by proximity and staffed by
        whoever is on at that facility.
        """
        encounter_class = getattr(encounter.encounter_class, 'value',
                                  encounter.encounter_class)

        if encounter_class in ('wellness', 'ambulatory', 'outpatient', 'virtual'):
            provider = self.assign_primary_care(person)
            usual = person.attributes.get('primary_care_clinician')
            if provider is not None and usual is not None:
                encounter.provider = provider
                encounter.clinician = (
                    usual if person.random.random() < USUAL_CLINICIAN_SHARE
                    else self._colleague(provider, usual, person)
                )
                return

        location = (person.attributes.get('latitude'),
                    person.attributes.get('longitude'))
        if location[0] is None or location[1] is None:
            location = None

        provider = self.find_provider(encounter_class, location, person.random)
        if provider is None:
            return

        encounter.provider = provider
        staff = self._staff(provider)
        if staff:
            encounter.clinician = person.random.choice(staff)

    def _colleague(self, provider: Provider, usual: Clinician,
                   person: 'Person') -> Clinician:
        staff = [c for c in self._staff(provider) if c.id != usual.id]
        return person.random.choice(staff) if staff else usual


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def _first(row: Dict[str, str], *names: str) -> Optional[str]:
    """The first present, non-empty value among several column names."""
    for name in names:
        value = row.get(name)
        if value not in (None, ''):
            return value
    return None


def _as_float(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _distance(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    """Great-circle distance in kilometres."""
    radius = 6371.0
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * radius * math.asin(min(1.0, math.sqrt(h)))


#: US state names to their two-letter codes, for filtering facility rows.
_STATE_CODES = {
    'alabama': 'AL', 'alaska': 'AK', 'arizona': 'AZ', 'arkansas': 'AR',
    'california': 'CA', 'colorado': 'CO', 'connecticut': 'CT', 'delaware': 'DE',
    'district of columbia': 'DC', 'florida': 'FL', 'georgia': 'GA',
    'hawaii': 'HI', 'idaho': 'ID', 'illinois': 'IL', 'indiana': 'IN',
    'iowa': 'IA', 'kansas': 'KS', 'kentucky': 'KY', 'louisiana': 'LA',
    'maine': 'ME', 'maryland': 'MD', 'massachusetts': 'MA', 'michigan': 'MI',
    'minnesota': 'MN', 'mississippi': 'MS', 'missouri': 'MO', 'montana': 'MT',
    'nebraska': 'NE', 'nevada': 'NV', 'new hampshire': 'NH', 'new jersey': 'NJ',
    'new mexico': 'NM', 'new york': 'NY', 'north carolina': 'NC',
    'north dakota': 'ND', 'ohio': 'OH', 'oklahoma': 'OK', 'oregon': 'OR',
    'pennsylvania': 'PA', 'rhode island': 'RI', 'south carolina': 'SC',
    'south dakota': 'SD', 'tennessee': 'TN', 'texas': 'TX', 'utah': 'UT',
    'vermont': 'VT', 'virginia': 'VA', 'washington': 'WA',
    'west virginia': 'WV', 'wisconsin': 'WI', 'wyoming': 'WY',
}


def _state_code(state: str) -> str:
    """The two-letter code for a state name, or the input upper-cased."""
    return _STATE_CODES.get(str(state).strip().lower(), str(state).strip().upper())
