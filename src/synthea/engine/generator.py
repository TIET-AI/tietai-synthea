"""
Main generator engine for Synthea.

This module provides the core simulation engine that orchestrates the generation
of synthetic patients and their health records.
"""

import random
import multiprocessing as mp
from typing import Dict, Any, Optional, List, Set, Tuple
from datetime import datetime, timedelta
from pathlib import Path
import json
import time as time_module
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
from tqdm import tqdm

from synthea.engine.module import Module
from synthea.world.person import Person
from synthea.world.demographics import Demographics
from synthea.world.location import Location
from synthea.world.provider import Provider, ProviderManager
from synthea.world.payer import PayerManager
from synthea.helpers.config import Config
from synthea.export.exporter import Exporter


class GeneratorOptions:
    """Configuration options for the Generator."""
    
    def __init__(self):
        """Initialize generator options with defaults."""
        self.population_size: int = 1
        self.seed: Optional[int] = None
        self.clinician_seed: Optional[int] = None
        self.reference_date: datetime = datetime.now()
        self.end_date: datetime = datetime.now()
        self.min_age: int = 0
        self.max_age: int = 140
        self.gender: Optional[str] = None
        self.overflow_population: int = 0
        self.generate_dead_patients: bool = True
        self.only_dead_patients: bool = False
        self.keep_patients_path: Optional[str] = None
        self.state: Optional[str] = None
        self.city: Optional[str] = None
        self.log_level: str = 'info'
        self.threads: int = 1
    
    @classmethod
    def from_args(cls, args: Dict[str, Any]) -> 'GeneratorOptions':
        """Create options from command-line arguments."""
        options = cls()
        
        if 'population' in args:
            options.population_size = int(args['population'])
        if 'seed' in args:
            options.seed = int(args['seed'])
        if 'clinician_seed' in args:
            options.clinician_seed = int(args['clinician_seed'])
        if 'gender' in args:
            options.gender = args['gender']
        if 'min_age' in args:
            options.min_age = int(args['min_age'])
        if 'max_age' in args:
            options.max_age = int(args['max_age'])
        if 'state' in args:
            options.state = args['state']
        if 'city' in args:
            options.city = args['city']
        if 'reference_date' in args:
            options.reference_date = datetime.strptime(args['reference_date'], '%Y%m%d')
        if 'threads' in args:
            options.threads = int(args['threads'])
        
        return options


class Generator:
    """Main generator engine for creating synthetic patients."""
    
    def __init__(self, options: Optional[GeneratorOptions] = None):
        """
        Initialize the generator.
        
        Args:
            options: Configuration options for generation
        """
        self.options = options or GeneratorOptions()
        self.config = Config()
        
        # Initialize random seed if provided
        if self.options.seed is not None:
            random.seed(self.options.seed)
        
        # Components
        self.demographics: Optional[Demographics] = None
        self.location: Optional[Location] = None
        self.provider_manager: Optional[ProviderManager] = None
        self.payer_manager: Optional[PayerManager] = None
        self.exporter: Optional[Exporter] = None
        
        # Loaded modules
        self.modules: Dict[str, Module] = {}
        self.module_list: List[str] = []
        
        # Statistics
        self.stats = {
            'total_generated': 0,
            'living': 0,
            'dead': 0,
            'rejected': 0,
        }
        
        # Initialize components
        self._initialize()
    
    def _initialize(self):
        """Initialize all generator components."""
        # Load configuration
        self.config.load()
        
        # Initialize location and demographics
        self._init_location()
        self._init_demographics()
        
        # Load modules
        self._load_modules()
        
        # Initialize providers
        self._init_providers()
        
        # Initialize payers
        self._init_payers()
        
        # Initialize exporter
        self._init_exporter()
    
    def _init_location(self):
        """Initialize location data."""
        self.location = Location()
        
        if self.options.state:
            self.location.set_state(self.options.state)
            if self.options.city:
                self.location.set_city(self.options.city)
    
    def _init_demographics(self):
        """Initialize demographics data."""
        self.demographics = Demographics()
        self.demographics.load(self.location)
    
    def _load_modules(self):
        """Load all modules."""
        print("Loading modules...")
        
        # Load modules from default location
        self.modules = Module.load_modules()
        
        # Get list of modules to use
        self.module_list = self._get_module_list()
        
        print(f"Loaded {len(self.modules)} modules")
    
    def _get_module_list(self) -> List[str]:
        """Get the list of modules to process for each patient."""
        # Core modules that always run
        core_modules = [
            'lifecycle',
            'encounter',
            'health_insurance',
            'quality_of_life',
        ]
        
        # Get all available modules
        all_modules = Module.get_all_modules()
        
        # Filter based on configuration
        enabled_modules = []
        for module_name in all_modules:
            if module_name in core_modules:
                enabled_modules.append(module_name)
            elif self.config.get(f'generate.{module_name}', True):
                enabled_modules.append(module_name)
        
        # Add death module last if enabled
        if 'death' in all_modules:
            enabled_modules.append('death')
        
        return enabled_modules
    
    def _init_providers(self):
        """Initialize healthcare providers."""
        self.provider_manager = ProviderManager()
        self.provider_manager.load(self.location)
    
    def _init_payers(self):
        """Initialize insurance payers."""
        self.payer_manager = PayerManager()
        self.payer_manager.load()
    
    def _init_exporter(self):
        """Initialize the exporter."""
        self.exporter = Exporter(self.config)
    
    def run(self):
        """Run the generator to create the specified population."""
        print(f"Generating {self.options.population_size} patients...")
        
        start_time = time_module.time()
        
        if self.options.threads > 1:
            self._run_parallel()
        else:
            self._run_sequential()
        
        elapsed = time_module.time() - start_time
        
        # Print statistics
        self._print_stats(elapsed)
        
        # Run post-completion exporters
        if self.exporter:
            self.exporter.run_post_completion(self.stats)
    
    def _run_sequential(self):
        """Run generation sequentially."""
        with tqdm(total=self.options.population_size) as pbar:
            for i in range(self.options.population_size):
                person = self.generate_person(i)
                if person:
                    self.record_person(person)
                pbar.update(1)
    
    def _run_parallel(self):
        """Run generation in parallel."""
        with ProcessPoolExecutor(max_workers=self.options.threads) as executor:
            with tqdm(total=self.options.population_size) as pbar:
                futures = []
                
                for i in range(self.options.population_size):
                    future = executor.submit(self._generate_and_record, i)
                    futures.append(future)
                
                for future in futures:
                    future.result()
                    pbar.update(1)
    
    def _generate_and_record(self, index: int) -> bool:
        """Generate and record a single person."""
        person = self.generate_person(index)
        if person:
            self.record_person(person)
            return True
        return False
    
    def generate_person(self, index: int) -> Optional[Person]:
        """
        Generate a single person.
        
        Args:
            index: The index/seed for this person
            
        Returns:
            The generated Person, or None if rejected
        """
        # Create person with unique seed
        if self.options.seed is not None:
            person_seed = self.options.seed + index
        else:
            person_seed = random.randint(0, 2**32 - 1)
        
        person = Person(person_seed)
        
        # Set demographics
        self._set_demographics(person)
        
        # Set location
        self._set_location(person)
        
        # Check if person meets criteria
        if not self._meets_criteria(person):
            self.stats['rejected'] += 1
            return None
        
        # Run the simulation
        self._simulate_life(person)
        
        # Update statistics
        self.stats['total_generated'] += 1
        if person.alive:
            self.stats['living'] += 1
        else:
            self.stats['dead'] += 1
        
        return person
    
    def _set_demographics(self, person: Person):
        """Set demographic attributes for a person."""
        if self.demographics:
            # Set gender
            if self.options.gender:
                person.attributes['gender'] = self.options.gender.upper()
            else:
                person.attributes['gender'] = self.demographics.random_gender(person.random)
            
            # Set race/ethnicity
            person.attributes['race'] = self.demographics.random_race(person.random)
            person.attributes['ethnicity'] = self.demographics.random_ethnicity(
                person.attributes['race'], 
                person.random
            )
            
            # Set birth date
            if self.options.min_age == self.options.max_age:
                age = self.options.min_age
            else:
                age = person.random.randint(self.options.min_age, self.options.max_age)
            
            birth_date = self.options.reference_date - timedelta(days=age * 365.25)
            person.attributes['birth_date'] = birth_date
            
            # Set socioeconomic status
            person.attributes['socioeconomic_status'] = self.demographics.random_ses(person.random)
    
    def _set_location(self, person: Person):
        """Set location attributes for a person."""
        if self.location:
            person.attributes['state'] = self.location.state
            person.attributes['city'] = self.location.city
            person.attributes['zip_code'] = self.location.random_zip_code(person.random)
            
            # Assign coordinates
            coords = self.location.random_coordinates(person.random)
            person.attributes['latitude'] = coords[0]
            person.attributes['longitude'] = coords[1]
    
    def _meets_criteria(self, person: Person) -> bool:
        """Check if a person meets the generation criteria."""
        # Check gender filter
        if self.options.gender:
            if person.attributes.get('gender') != self.options.gender.upper():
                return False
        
        # Check if we want only dead patients
        if self.options.only_dead_patients:
            # This check happens after simulation
            pass
        
        return True
    
    def _simulate_life(self, person: Person):
        """Simulate a person's entire life."""
        # Initialize health record
        person.init_health_record()
        
        # Start from birth
        current_time = person.attributes.get('birth_date', datetime.now())
        end_time = self.options.end_date
        
        # Time step (1 week)
        time_step = timedelta(days=7)
        
        # Process each time step
        while current_time <= end_time and person.alive:
            # Process each module
            for module_name in self.module_list:
                module = Module.get_module(module_name)
                if module:
                    try:
                        module.process(person, current_time)
                    except Exception:
                        pass
            
            # Advance time
            current_time += time_step
            
            # Check if person has died
            if getattr(person, 'death_date', None) is not None:
                if current_time >= person.death_date:
                    person.alive = False
                    break
        
        # Finalize record
        person.finalize_health_record(current_time)
    
    def record_person(self, person: Person):
        """
        Record a person's data to files.
        
        Args:
            person: The person to record
        """
        if self.exporter:
            self.exporter.export(person)
    
    def _print_stats(self, elapsed_time: float):
        """Print generation statistics."""
        print("\n" + "=" * 50)
        print("Generation Complete!")
        print("=" * 50)
        print(f"Total Generated: {self.stats['total_generated']}")
        print(f"  Living: {self.stats['living']}")
        print(f"  Dead: {self.stats['dead']}")
        print(f"Rejected: {self.stats['rejected']}")
        print(f"Time Elapsed: {elapsed_time:.2f} seconds")
        
        if self.stats['total_generated'] > 0:
            rate = self.stats['total_generated'] / elapsed_time
            print(f"Generation Rate: {rate:.2f} patients/second")