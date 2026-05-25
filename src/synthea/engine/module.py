"""
Module system for Synthea.

This module provides the core module loading and execution framework for both
built-in modules and JSON-defined generic modules.
"""

import json
import logging
import os
from typing import Dict, Any, Optional, List, Set, TYPE_CHECKING
from datetime import datetime
from pathlib import Path
import importlib
import inspect

from synthea.engine.state import State
from synthea.engine.transition import Transition

logger = logging.getLogger(__name__)

_MAX_MODULE_ITERATIONS = 500

if TYPE_CHECKING:
    from synthea.world.person import Person


class Module:
    """Base class for all Synthea modules."""
    
    # Class-level registry of loaded modules
    _modules: Dict[str, 'Module'] = {}
    _module_suppliers: Dict[str, Any] = {}
    _primary_keys: Set[str] = set()
    
    def __init__(self, name: str):
        """
        Initialize a module.
        
        Args:
            name: The name of this module
        """
        self.name = name
        self.states: Dict[str, State] = {}
        self.initial_state: Optional[str] = None
        self.remarks: List[str] = []
        self.gmf_version: Optional[float] = None
    
    def process(self, person: 'Person', time: datetime) -> bool:
        """
        Process this module for a person at a given time.
        
        Args:
            person: The person being simulated
            time: The current simulation time
            
        Returns:
            True if the module completed, False if it needs more time
        """
        # Get or initialize the current state for this module
        current_state_key = f'{self.name}_current_state'
        current_state_name = person.attributes.get(current_state_key, self.initial_state)
        
        if not current_state_name:
            return True  # No initial state, module is done
        
        # Process states until we hit a delay or terminal state
        # Cap iterations to detect multi-state cycles (e.g. A→B→C→A without a Delay)
        _iterations = 0
        while current_state_name:
            if current_state_name not in self.states:
                logger.warning("State '%s' not found in module '%s'", current_state_name, self.name)
                return True
            
            state = self.states[current_state_name]
            
            # Mark state as visited (for PriorState conditions)
            person.attributes[f'{self.name}.{current_state_name}_visited'] = True
            
            # Run the state
            completed = state.run(person, time)
            
            if not completed:
                # State needs more time (e.g., Delay state)
                person.attributes[current_state_key] = current_state_name
                return False
            
            # Get next state from transition
            next_state = self._get_next_state(state, person, time)
            
            if next_state == current_state_name:
                # Prevent direct self-loop
                return True

            _iterations += 1
            if _iterations >= _MAX_MODULE_ITERATIONS:
                logger.warning(
                    "Module '%s' hit the %d-iteration cycle cap at state '%s'; "
                    "yielding to next time step",
                    self.name, _MAX_MODULE_ITERATIONS, next_state,
                )
                person.attributes[current_state_key] = next_state
                return False

            current_state_name = next_state
            
            # Check if we've reached a terminal state
            if not current_state_name:
                # Module completed
                person.attributes[current_state_key] = None
                return True
        
        # Save current state for next time
        person.attributes[current_state_key] = current_state_name
        return current_state_name is None
    
    def _get_next_state(self, state: State, person: 'Person', time: datetime) -> Optional[str]:
        """Get the next state to transition to."""
        # Create transition object from state definition
        transition = Transition.create_transition(state.definition)
        if transition:
            return transition.follow(person, time)
        return None
    
    @classmethod
    def load_modules(cls, path: str = 'resources/modules') -> Dict[str, 'Module']:
        """
        Load all modules from the specified directory.
        
        Args:
            path: Path to the modules directory
            
        Returns:
            Dictionary of loaded modules
        """
        cls._modules.clear()
        cls._module_suppliers.clear()
        
        # Load built-in core modules
        cls._load_core_modules()
        
        # Load JSON modules
        cls._load_json_modules(path)
        
        return cls._modules
    
    @classmethod
    def _load_core_modules(cls):
        """Load built-in core modules."""
        core_modules = [
            'lifecycle',
            'encounter',
            'health_insurance',
            'death',
            'quality_of_life',
        ]
        
        for module_name in core_modules:
            try:
                # Try to import the core module
                module_path = f'synthea.modules.core.{module_name}'
                imported = importlib.import_module(module_path)
                
                # Find the module class in the imported module
                for name, obj in inspect.getmembers(imported):
                    if (inspect.isclass(obj) and 
                        issubclass(obj, Module) and 
                        obj != Module):
                        # Create a supplier function for lazy loading
                        cls._module_suppliers[module_name] = lambda m=obj: m()
                        cls._primary_keys.add(module_name)
                        break
            except ImportError:
                # Core module not implemented yet
                pass
    
    @classmethod
    def _load_json_modules(cls, path: str):
        """Load JSON-defined generic modules."""
        module_path = Path(path)
        
        if not module_path.exists():
            # Try alternative paths
            alternatives = [
                Path('src/main/resources/modules'),
                Path('../src/main/resources/modules'),
                Path('modules'),
            ]
            
            for alt in alternatives:
                if alt.exists():
                    module_path = alt
                    break
        
        if not module_path.exists():
            print(f"Warning: Module directory not found: {path}")
            return
        
        # Recursively find all .json files
        for json_file in module_path.rglob('*.json'):
            try:
                cls._load_json_module(json_file, module_path)
            except Exception as e:
                print(f"Error loading module {json_file}: {e}")

    @classmethod
    def _load_json_module(cls, filepath: Path, base_path: Path):
        """Load a single JSON module."""
        with open(filepath, 'r', encoding='utf-8') as f:
            definition = json.load(f)

        json_name = definition.get('name', filepath.stem)

        # Use relative path as the canonical module identity, matching Java
        # Synthea. This ensures unique state-tracking keys even when multiple
        # modules share the same JSON name (e.g. heart/cabg/operation and
        # heart/tavr/operation are both named "operation").
        relative_path = str(filepath.relative_to(base_path).with_suffix(''))
        path_key = relative_path.replace(os.sep, '/')

        def create_module():
            return cls._create_from_json(path_key, definition)

        # Register by path (primary key, used by CallSubmodule and generator)
        cls._module_suppliers[path_key] = create_module
        cls._primary_keys.add(path_key)

        # Also register by JSON name as an alias for convenience, but only
        # if no other module has already claimed that name
        if json_name not in cls._module_suppliers:
            cls._module_suppliers[json_name] = create_module
    
    @classmethod
    def _create_from_json(cls, name: str, definition: Dict[str, Any]) -> 'Module':
        """Create a module from JSON definition."""
        module = Module(name)
        
        # Set module properties
        module.gmf_version = definition.get('gmf_version')
        module.remarks = definition.get('remarks', [])
        if isinstance(module.remarks, str):
            module.remarks = [module.remarks]
        
        # Load states
        states_def = definition.get('states', {})
        for state_name, state_def in states_def.items():
            state = State.create_state(module, state_name, state_def)
            module.states[state_name] = state
            
            # Track initial state
            if state_def.get('type') == 'Initial':
                module.initial_state = state_name
        
        return module
    
    @classmethod
    def get_module(cls, name: str) -> Optional['Module']:
        """
        Get a module by name, loading it if necessary.
        
        Args:
            name: The name of the module
            
        Returns:
            The module instance, or None if not found
        """
        # Check if already loaded
        if name in cls._modules:
            return cls._modules[name]
        
        # Check if we have a supplier for it
        if name in cls._module_suppliers:
            module = cls._module_suppliers[name]()
            cls._modules[name] = module
            return module
        
        return None
    
    @classmethod
    def get_all_modules(cls) -> List[str]:
        """Get list of top-level module names (excludes submodules in subdirectories).

        Submodules (paths containing '/') are only executed when called via
        CallSubmodule states, not on every generator timestep. This matches
        the Java Synthea behaviour.
        """
        return sorted(k for k in cls._primary_keys if '/' not in k)
    
    @classmethod
    def clear_cache(cls):
        """Clear the module cache."""
        cls._modules.clear()
        cls._module_suppliers.clear()
        cls._primary_keys.clear()
    
    def validate(self) -> List[str]:
        """
        Validate this module for correctness.
        
        Returns:
            List of validation errors, empty if valid
        """
        errors = []
        
        # Check for initial state
        if not self.initial_state:
            errors.append(f"Module '{self.name}' has no Initial state")
        elif self.initial_state not in self.states:
            errors.append(f"Module '{self.name}' Initial state '{self.initial_state}' not found")
        
        # Check all transitions point to valid states
        for state_name, state in self.states.items():
            transition = Transition.create_transition(state.definition)
            if transition:
                # Get all possible next states
                next_states = self._get_possible_transitions(state.definition)
                for next_state in next_states:
                    if next_state and next_state not in self.states:
                        errors.append(
                            f"State '{state_name}' transitions to undefined state '{next_state}'"
                        )
        
        # Check for unreachable states (except Initial)
        reachable = self._find_reachable_states()
        for state_name in self.states:
            if state_name != self.initial_state and state_name not in reachable:
                errors.append(f"State '{state_name}' is unreachable")
        
        return errors
    
    def _get_possible_transitions(self, definition: Dict[str, Any]) -> Set[str]:
        """Get all possible transition targets from a state definition."""
        targets = set()
        
        if 'direct_transition' in definition:
            targets.add(definition['direct_transition'])
        elif 'transition' in definition:
            targets.add(definition['transition'])
        elif 'distributed_transition' in definition:
            for t in definition['distributed_transition']:
                if 'transition' in t:
                    targets.add(t['transition'])
        elif 'conditional_transition' in definition:
            for t in definition['conditional_transition']:
                if 'transition' in t:
                    targets.add(t['transition'])
        elif 'complex_transition' in definition:
            for t in definition['complex_transition']:
                if 'transition' in t:
                    targets.add(t['transition'])
                if 'distributions' in t:
                    for d in t['distributions']:
                        if 'transition' in d:
                            targets.add(d['transition'])
        elif 'lookup_table_transition' in definition:
            ltt = definition['lookup_table_transition']
            entries = ltt if isinstance(ltt, list) else ltt.get('transitions', [])
            for t in entries:
                if 'transition' in t:
                    targets.add(t['transition'])
        
        return targets
    
    def _find_reachable_states(self) -> Set[str]:
        """Find all states reachable from the initial state."""
        if not self.initial_state:
            return set()
        
        reachable = set()
        to_visit = [self.initial_state]
        
        while to_visit:
            current = to_visit.pop()
            if current in reachable:
                continue
            
            reachable.add(current)
            
            if current in self.states:
                state = self.states[current]
                next_states = self._get_possible_transitions(state.definition)
                to_visit.extend(next_states - reachable)
        
        return reachable