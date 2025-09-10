"""
Insurance payer model for Synthea.

This module manages insurance payers and coverage.
"""

from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from pathlib import Path
import csv
import random
from datetime import datetime, timedelta


@dataclass
class Payer:
    """Represents an insurance payer."""
    id: str
    name: str
    ownership: str  # private, government
    states_covered: List[str]
    deductible: float
    default_copay: float
    default_coinsurance: float
    monthly_premium: float
    
    def covers_state(self, state: str) -> bool:
        """Check if payer covers a state."""
        return not self.states_covered or state in self.states_covered


@dataclass
class InsurancePlan:
    """Represents an individual's insurance plan."""
    payer: Payer
    start_date: datetime
    end_date: Optional[datetime] = None
    member_id: str = ""
    group_id: str = ""
    
    @property
    def is_active(self) -> bool:
        """Check if plan is currently active."""
        return self.end_date is None or self.end_date > datetime.now()


class PayerManager:
    """Manages insurance payers."""
    
    def __init__(self):
        """Initialize payer manager."""
        self.payers: Dict[str, Payer] = {}
        self.private_payers: List[Payer] = []
        self.government_payers: List[Payer] = []
        
        # Special payers
        self.no_insurance: Optional[Payer] = None
        self.medicare: Optional[Payer] = None
        self.medicaid: Optional[Payer] = None
    
    def load(self):
        """Load payer data."""
        # Try to load from CSV file
        self._load_from_csv()
        
        # If no payers loaded, create defaults
        if not self.payers:
            self._create_default_payers()
        
        # Index payers
        self._index_payers()
    
    def _load_from_csv(self):
        """Load payers from CSV file."""
        paths = [
            Path('resources/payers/payers.csv'),
            Path('src/main/resources/payers/payers.csv'),
            Path('../resources/payers/payers.csv'),
        ]
        
        for path in paths:
            if path.exists():
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        reader = csv.DictReader(f)
                        for row in reader:
                            payer = self._parse_payer_row(row)
                            if payer:
                                self.payers[payer.id] = payer
                    break
                except Exception:
                    pass
    
    def _parse_payer_row(self, row: Dict[str, str]) -> Optional[Payer]:
        """Parse a payer from CSV row."""
        try:
            states = row.get('states_covered', '').split('|') if row.get('states_covered') else []
            
            return Payer(
                id=row.get('id', ''),
                name=row.get('name', ''),
                ownership=row.get('ownership', 'private'),
                states_covered=states,
                deductible=float(row.get('deductible', 0)),
                default_copay=float(row.get('default_copay', 25)),
                default_coinsurance=float(row.get('default_coinsurance', 0.2)),
                monthly_premium=float(row.get('monthly_premium', 400))
            )
        except (ValueError, KeyError):
            return None
    
    def _create_default_payers(self):
        """Create default payers."""
        # No Insurance
        no_insurance = Payer(
            id="no_insurance",
            name="No Insurance",
            ownership="private",
            states_covered=[],
            deductible=0,
            default_copay=0,
            default_coinsurance=1.0,  # 100% responsibility
            monthly_premium=0
        )
        self.payers[no_insurance.id] = no_insurance
        self.no_insurance = no_insurance
        
        # Medicare
        medicare = Payer(
            id="medicare",
            name="Medicare",
            ownership="government",
            states_covered=[],  # All states
            deductible=1600,
            default_copay=20,
            default_coinsurance=0.2,
            monthly_premium=170
        )
        self.payers[medicare.id] = medicare
        self.medicare = medicare
        
        # Medicaid
        medicaid = Payer(
            id="medicaid",
            name="Medicaid",
            ownership="government",
            states_covered=[],  # All states
            deductible=0,
            default_copay=5,
            default_coinsurance=0,
            monthly_premium=0
        )
        self.payers[medicaid.id] = medicaid
        self.medicaid = medicaid
        
        # Blue Cross Blue Shield
        bcbs = Payer(
            id="bcbs",
            name="Blue Cross Blue Shield",
            ownership="private",
            states_covered=[],
            deductible=2000,
            default_copay=30,
            default_coinsurance=0.2,
            monthly_premium=450
        )
        self.payers[bcbs.id] = bcbs
        
        # Aetna
        aetna = Payer(
            id="aetna",
            name="Aetna",
            ownership="private",
            states_covered=[],
            deductible=1500,
            default_copay=25,
            default_coinsurance=0.15,
            monthly_premium=400
        )
        self.payers[aetna.id] = aetna
        
        # United Healthcare
        united = Payer(
            id="united",
            name="United Healthcare",
            ownership="private",
            states_covered=[],
            deductible=1800,
            default_copay=25,
            default_coinsurance=0.2,
            monthly_premium=425
        )
        self.payers[united.id] = united
        
        # Cigna
        cigna = Payer(
            id="cigna",
            name="Cigna",
            ownership="private",
            states_covered=[],
            deductible=1600,
            default_copay=30,
            default_coinsurance=0.2,
            monthly_premium=410
        )
        self.payers[cigna.id] = cigna
    
    def _index_payers(self):
        """Index payers by type."""
        self.private_payers.clear()
        self.government_payers.clear()
        
        for payer in self.payers.values():
            if payer.ownership == 'government':
                self.government_payers.append(payer)
            else:
                self.private_payers.append(payer)
            
            # Identify special payers
            if 'medicare' in payer.name.lower():
                self.medicare = payer
            elif 'medicaid' in payer.name.lower():
                self.medicaid = payer
            elif 'no insurance' in payer.name.lower():
                self.no_insurance = payer
    
    def select_payer(self, person: 'Person', rand: random.Random) -> Payer:
        """
        Select an insurance payer for a person.
        
        Args:
            person: The person to select payer for
            rand: Random generator
            
        Returns:
            Selected payer
        """
        age = person.age
        ses = person.attributes.get('socioeconomic_status', 'middle')
        
        # Medicare eligibility (65+)
        if age >= 65 and self.medicare:
            return self.medicare
        
        # Medicaid eligibility (low income)
        if ses == 'low' and self.medicaid:
            if rand.random() < 0.4:  # 40% of low income on Medicaid
                return self.medicaid
        
        # Probability of having insurance
        insurance_prob = {
            'low': 0.6,
            'middle': 0.85,
            'high': 0.95
        }
        
        has_insurance = rand.random() < insurance_prob.get(ses, 0.85)
        
        if not has_insurance and self.no_insurance:
            return self.no_insurance
        
        # Select from private payers
        if self.private_payers:
            # Filter by state if needed
            state = person.attributes.get('state')
            if state:
                available = [p for p in self.private_payers if p.covers_state(state)]
            else:
                available = self.private_payers
            
            if available:
                # Weight by market share (simplified)
                return rand.choice(available)
        
        # Fallback
        return self.no_insurance or list(self.payers.values())[0]
    
    def assign_insurance(self, person: 'Person', time: datetime,
                        rand: random.Random) -> InsurancePlan:
        """
        Assign insurance to a person.
        
        Args:
            person: The person to assign insurance to
            time: Current simulation time
            rand: Random generator
            
        Returns:
            Insurance plan
        """
        payer = self.select_payer(person, rand)
        
        # Create insurance plan
        plan = InsurancePlan(
            payer=payer,
            start_date=time,
            member_id=f"{person.id[:8]}-{rand.randint(1000, 9999)}",
            group_id=f"GRP-{rand.randint(100000, 999999)}"
        )
        
        return plan