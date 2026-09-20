"""
Main generator engine for Synthea.

This module provides the core simulation engine that orchestrates the generation
of synthetic patients and their health records.
"""

import logging
import multiprocessing as mp
from typing import Dict, Any, Optional, List, Set, Tuple
from datetime import datetime, timedelta
from pathlib import Path
import json
import time as time_module
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
from tqdm import tqdm

logger = logging.getLogger(__name__)

from synthea.engine.module import Module
from synthea.world.person import Person
from synthea.world.demographics import Demographics
from synthea.world.location import Location
from synthea.world.provider import Provider, ProviderManager
from synthea.world.payer import PayerManager
from synthea.helpers.config import Config
from synthea.helpers.rng import resolve_seed
from synthea.export.exporter import Exporter
from synthea import locale as locale_registry


def _name_set(value) -> set:
    """A set of lower-cased module names from a comma or space separated list."""
    if value in (None, '', False):
        return set()
    if isinstance(value, (list, tuple, set)):
        parts = list(value)
    else:
        parts = str(value).replace(',', ' ').split()
    return {str(part).strip().lower() for part in parts if str(part).strip()}


class GeneratorOptions:
    """Configuration options for the Generator."""
    
    def __init__(self):
        """Initialize generator options with defaults."""
        self.population_size: int = 1
        self.seed: Optional[int] = None
        self.clinician_seed: Optional[int] = None
        self.reference_date: datetime = datetime.now()
        #: True when the caller asked for a specific reference date, so
        #: `generate.reference_year` must not override it.
        self.reference_date_explicit: bool = False
        # ``None`` means "run the simulation up to the reference date". Setting
        # it explicitly is only needed when the simulation should stop earlier.
        self.end_date: Optional[datetime] = None
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
        self.locale: Optional[str] = None
        self.threads: int = 1

    @property
    def resolved_end_date(self) -> datetime:
        """The time the simulation runs to; the reference date unless overridden."""
        return self.end_date if self.end_date is not None else self.reference_date

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
        if args.get('locale'):
            options.locale = args['locale']

        if 'reference_date' in args:
            options.reference_date = datetime.strptime(args['reference_date'], '%Y%m%d')
            options.reference_date_explicit = True
        if 'threads' in args:
            options.threads = int(args['threads'])
        
        return options


class Generator:
    """Main generator engine for creating synthetic patients."""
    
    def __init__(self, options: Optional[GeneratorOptions] = None,
                 config: Optional[Config] = None):
        """
        Initialize the generator.

        Args:
            options: Configuration options for generation
            config: A pre-loaded configuration to use (e.g. from the CLI, with
                overrides such as ``exporter.baseDirectory`` already applied).
                When omitted, a default config is created and loaded.
        """
        self.options = options or GeneratorOptions()
        self.config = config if config is not None else Config()
        self._config_provided = config is not None
        self._apply_reference_year()

        # Resolved once, not per patient: an unknown locale should fail at
        # start-up rather than after the first hour of a long run.
        self.locale = locale_registry.get(
            self.options.locale or self.config.get('generate.locale')
        )

        # No global ``random.seed()`` here: every draw during simulation comes
        # from the person's own generator, whose seed is derived from
        # ``(population seed, patient index)``. Seeding the global module would
        # make results depend on how many draws other code happened to make.

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
    
    def _apply_reference_year(self):
        """Honour `generate.reference_year` when no reference date was given.

        `GeneratorOptions.reference_date` defaults to "now", so a configured
        year only takes effect if the caller did not ask for a specific date.
        An explicit `-r` always wins.
        """
        if getattr(self.options, 'reference_date_explicit', False):
            return

        year = self.config.get('generate.reference_year')
        if year in (None, ''):
            return

        try:
            year = int(year)
        except (TypeError, ValueError):
            logger.warning("generate.reference_year is not a year: %r", year)
            return

        try:
            self.options.reference_date = self.options.reference_date.replace(
                year=year)
        except ValueError:
            # 29 February in a non-leap year.
            self.options.reference_date = self.options.reference_date.replace(
                year=year, day=28)

    def _initialize(self):
        """Initialize all generator components."""
        # Load configuration. Skip when a pre-configured Config was supplied
        # (e.g. by the CLI), so caller overrides like exporter.baseDirectory are
        # preserved and reach the exporter built below.
        if not self._config_provided:
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
        """Initialize location data.

        The CLI wins over the configuration file, so `--state` overrides
        `generate.geography.state` rather than the other way round.
        """
        self.location = Location()

        state = self.options.state or self.config.get('generate.geography.state')
        city = self.options.city or self.config.get('generate.geography.city')

        if state:
            self.location.set_state(str(state))
            if city:
                self.location.set_city(str(city))
        elif city:
            logger.warning(
                "A city (%s) was given without a state, so it is ignored: "
                "city names are not unique across states.", city,
            )

    def _init_demographics(self):
        """Initialize demographics data.

        `generate.geography.use_demographics` turns off the census-derived
        age, sex and race distributions, falling back to the built-in national
        defaults. Useful when the population should be shaped by your own
        filters rather than by a place.
        """
        self.demographics = Demographics()

        if self.config.get_bool('generate.geography.use_demographics', True):
            self.demographics.load(self.location)
        else:
            self.demographics.load(None)

    def _load_modules(self):
        """Load all modules."""
        print("Loading modules...")
        
        # Load modules from default location
        self.modules = Module.load_modules()

        # Get list of modules to use
        self.module_list = self._get_module_list()

        # Modules are registered as lazy suppliers, so count the full registry
        # rather than the materialized dict (which is empty at this point).
        print(f"Loaded {len(Module.get_all_modules())} modules")
    
    def _get_module_list(self) -> List[str]:
        """The modules to process for each patient, in execution order.

        Core modules run first and in their declared order, because disease
        modules read the attributes they set. Previously the list was sorted
        alphabetically, which would have interleaved them.
        """
        all_modules = set(Module.get_all_modules())
        core = Module.CORE_MODULE_ORDER

        enabled: List[str] = []

        if self.config.get_bool('generate.core_modules', True):
            enabled.extend(name for name in core if name in all_modules)
        else:
            logger.warning(
                "generate.core_modules is off: patients will have no identity, "
                "growth, vital signs, routine visits or background mortality.",
            )

        allowed = _name_set(self.config.get('generate.modules.enabled'))
        blocked = _name_set(self.config.get('generate.modules.disabled'))

        overlap = allowed & blocked
        if overlap:
            logger.warning(
                "These modules are in both generate.modules.enabled and "
                "generate.modules.disabled, and are disabled: %s",
                ', '.join(sorted(overlap)),
            )

        for module_name in sorted(all_modules):
            if module_name in core:
                continue
            if allowed and module_name.lower() not in allowed:
                continue
            if module_name.lower() in blocked:
                continue
            if self.config.get(f'generate.{module_name}', True):
                enabled.append(module_name)

        # A filter that matches nothing is a typo, not an instruction to
        # generate patients with no disease modules at all.
        if (allowed or blocked) and not [
                name for name in enabled if name not in core]:
            logger.warning(
                "The module filters left no disease modules enabled. Check "
                "generate.modules.enabled / .disabled against --list-modules.",
            )

        return enabled

    def _init_providers(self):
        """Initialize healthcare providers."""
        clinician_seed = self.options.clinician_seed
        if clinician_seed is None and self.options.seed is not None:
            # Derive it from the population seed so a seeded run is fully
            # reproducible without the caller having to set both.
            clinician_seed = resolve_seed(self.options.seed, 0, 'clinician')
        self.provider_manager = ProviderManager(seed=clinician_seed)
        self.provider_manager.load(self.location)
    
    def _init_payers(self):
        """Initialize insurance payers."""
        # Its own stream, so a change to payer selection cannot perturb
        # patients or clinicians.
        payer_seed = (resolve_seed(self.options.seed, 0, 'payer')
                      if self.options.seed is not None else None)
        self.payer_manager = PayerManager(seed=payer_seed)
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
        """Run generation across worker processes.

        Each worker builds its own Generator once (via the pool initializer)
        rather than having one pickled per patient, and returns the statistics
        it produced so the parent's totals are correct. Because every person's
        seed is derived from ``(population seed, index)``, the population is
        identical to a sequential run with the same seed.
        """
        with ProcessPoolExecutor(
            max_workers=self.options.threads,
            initializer=_init_worker,
            initargs=(self.options, self.config),
        ) as executor:
            with tqdm(total=self.options.population_size) as pbar:
                for delta in executor.map(
                    _generate_one,
                    range(self.options.population_size),
                    chunksize=_parallel_chunksize(
                        self.options.population_size, self.options.threads
                    ),
                ):
                    for key, value in delta.items():
                        self.stats[key] += value
                    pbar.update(1)

    def _generate_and_record(self, index: int) -> Dict[str, int]:
        """Generate and record a single person, returning its statistics delta."""
        before = dict(self.stats)
        person = self.generate_person(index)
        if person is not None:
            self.record_person(person)
        return {key: self.stats[key] - before.get(key, 0) for key in self.stats}
    
    def generate_person(self, index: int) -> Optional[Person]:
        """
        Generate a single person.
        
        Args:
            index: The index/seed for this person
            
        Returns:
            The generated Person, or None if rejected
        """
        # Create person with a seed derived purely from (population seed, index),
        # so patient N is identical however many patients ran before it and on
        # however many threads.
        person_seed = resolve_seed(self.options.seed, index, 'person')

        person = Person(person_seed)
        # States and core modules create encounters in several places, so
        # the provider manager travels with the person rather than being
        # threaded through every call site. The insurance module needs the
        # payer tables for the same reason: entries are priced as they are
        # recorded.
        person.providers = self.provider_manager
        person.payers = self.payer_manager

        # Identity, coding and export conventions all come from here.
        person.locale = self.locale
        
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
            
            # Set birth date. Ages follow the demographic age distribution
            # rather than being uniform between the bounds: a uniform draw over
            # 0-140 produced as many 130-year-olds as 30-year-olds.
            age = self._choose_age(person)

            # Spread birthdays across the year instead of stacking them on the
            # reference date.
            birth_date = (
                self.options.reference_date
                - timedelta(days=age * 365.25 + person.random.uniform(0, 365))
            )
            person.attributes['birth_date'] = birth_date
            person.attributes['age_at_creation'] = age
            
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
    
    def _choose_age(self, person: Person) -> int:
        """Draw an age within the requested bounds, weighted by demographics."""
        low = max(0, int(self.options.min_age))
        high = max(low, int(self.options.max_age))
        if low == high:
            return low

        if self.demographics is not None:
            for _ in range(50):
                candidate = self.demographics.random_age(person.random)
                if low <= candidate <= high:
                    return candidate

        # The requested band may sit outside the distribution's mass; fall back
        # to a uniform draw rather than looping forever.
        return person.random.randint(low, high)

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
        end_time = self.options.resolved_end_date
        
        # Time step (1 week)
        time_step = timedelta(days=7)
        # Background mortality is expressed per year, so the lifecycle module
        # needs to know how much of a year a step represents.
        person.attributes['timestep_years'] = time_step.days / 365.25
        
        # Process each time step
        while current_time <= end_time and person.alive:
            # Process each module
            for module_name in self.module_list:
                module = Module.get_module(module_name)
                if module:
                    try:
                        module.process(person, current_time)
                    except Exception:
                        logger.warning(
                            "Module '%s' raised an exception at time %s",
                            module_name, current_time,
                            exc_info=True,
                        )
            
            # Advance time
            current_time += time_step
            
            # Check if person has died
            if getattr(person, 'death_date', None) is not None:
                if current_time >= person.death_date:
                    person.alive = False
                    break
        
        # Finalize record
        person.finalize_health_record(current_time)

        # Notes are written against the finished record, so that "active at
        # the time of the visit" is resolved from what actually happened
        # rather than guessed while the simulation is still running.
        if self.config.get_bool('generate.clinical_notes', True):
            from synthea.world import notes
            notes.write_notes(person)
    
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

# ---------------------------------------------------------------------------
# Process-pool workers
#
# These live at module level so they can be pickled by ProcessPoolExecutor on
# spawn-based platforms (Windows, macOS). The pool initializer builds one
# Generator per worker process; without it a Generator would be pickled and
# rebuilt for every patient.
# ---------------------------------------------------------------------------

_WORKER_GENERATOR: Optional[Generator] = None


def _init_worker(options: GeneratorOptions, config: Config) -> None:
    """Build this worker process's Generator once."""
    global _WORKER_GENERATOR
    _WORKER_GENERATOR = Generator(options, config=config)


def _generate_one(index: int) -> Dict[str, int]:
    """Generate, record and report one patient in a worker process."""
    if _WORKER_GENERATOR is None:  # pragma: no cover - defensive
        raise RuntimeError("worker generator was not initialized")
    return _WORKER_GENERATOR._generate_and_record(index)


def _parallel_chunksize(population_size: int, threads: int) -> int:
    """Pick a chunk size that keeps workers busy without starving the tail."""
    if threads <= 1:
        return 1
    return max(1, population_size // (threads * 4))
