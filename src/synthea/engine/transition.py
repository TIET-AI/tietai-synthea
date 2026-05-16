"""
Transition implementations for state machines.

This module defines the various transition types used to move between states
in Synthea's Generic Module Framework.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List, TYPE_CHECKING
from datetime import datetime
import logging
import random
import csv
import os

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from synthea.world.person import Person


class Transition(ABC):
    """Abstract base class for all transition types."""
    
    def __init__(self, definition: Dict[str, Any]):
        """
        Initialize a transition.
        
        Args:
            definition: The JSON definition of this transition
        """
        self.definition = definition
    
    @abstractmethod
    def follow(self, person: 'Person', time: datetime) -> Optional[str]:
        """
        Determine which state to transition to.
        
        Args:
            person: The person being simulated
            time: The current simulation time
            
        Returns:
            The name of the next state, or None if no transition
        """
        pass
    
    @staticmethod
    def create_transition(definition: Dict[str, Any]) -> 'Transition':
        """
        Factory method to create the appropriate transition type.
        
        Args:
            definition: The JSON definition of the transition
            
        Returns:
            An instance of the appropriate Transition subclass
        """
        # Check for different transition types in order of precedence
        if 'direct_transition' in definition:
            return DirectTransition(definition)
        elif 'distributed_transition' in definition:
            return DistributedTransition(definition)
        elif 'conditional_transition' in definition:
            return ConditionalTransition(definition)
        elif 'complex_transition' in definition:
            return ComplexTransition(definition)
        elif 'lookup_table_transition' in definition:
            return LookupTableTransition(definition)
        elif 'transition' in definition:
            # Simple transition specified as just a string
            return DirectTransition({'direct_transition': definition['transition']})
        else:
            return None


class DirectTransition(Transition):
    """A simple transition that always goes to the same state."""
    
    def follow(self, person: 'Person', time: datetime) -> Optional[str]:
        """Return the direct transition target."""
        if 'direct_transition' in self.definition:
            return self.definition['direct_transition']
        elif 'transition' in self.definition:
            return self.definition['transition']
        return None


class DistributedTransition(Transition):
    """A transition that randomly selects from weighted options."""

    def __init__(self, definition: Dict[str, Any]):
        super().__init__(definition)
        self.transitions = definition.get('distributed_transition', [])
        self._validate_distribution()

    @staticmethod
    def _resolve_distribution(dist_value: Any, person: 'Person') -> float:
        """Resolve a distribution value, which may be a float or an attribute reference dict."""
        if isinstance(dist_value, dict):
            attr = dist_value.get('attribute')
            default = dist_value.get('default', 0.0)
            if attr and person is not None:
                val = person.attributes.get(attr, default)
                try:
                    return float(val)
                except (TypeError, ValueError):
                    return float(default)
            return float(default)
        try:
            return float(dist_value)
        except (TypeError, ValueError):
            return 0.0

    def _validate_distribution(self):
        """Validate that fixed distributions sum to 1.0; normalize if needed."""
        # Skip normalization if any distribution is attribute-based (resolved at runtime)
        if any(isinstance(t.get('distribution'), dict) for t in self.transitions):
            return
        total = sum(self._resolve_distribution(t.get('distribution', 0), None)
                    for t in self.transitions)
        if total > 0 and abs(total - 1.0) > 0.001:
            for t in self.transitions:
                t['distribution'] = self._resolve_distribution(t.get('distribution', 0), None) / total

    def follow(self, person: 'Person', time: datetime) -> Optional[str]:
        """Select a transition based on the probability distribution."""
        if not self.transitions:
            return None

        rand = random.random()
        cumulative = 0.0

        for transition in self.transitions:
            cumulative += self._resolve_distribution(transition.get('distribution', 0), person)
            if rand < cumulative:
                return transition.get('transition')

        # Fallback to last transition if rounding errors occur
        return self.transitions[-1].get('transition') if self.transitions else None


class ConditionalTransition(Transition):
    """A transition that selects based on logical conditions."""
    
    def __init__(self, definition: Dict[str, Any]):
        super().__init__(definition)
        self.conditions = definition.get('conditional_transition', [])
    
    def follow(self, person: 'Person', time: datetime) -> Optional[str]:
        """Evaluate conditions and return the first matching transition."""
        from synthea.engine.logic import Logic
        
        for condition in self.conditions:
            if 'condition' in condition:
                if Logic.test(condition['condition'], person, time):
                    return condition.get('transition')
            else:
                # Default transition with no condition
                return condition.get('transition')
        
        return None


class ComplexTransition(Transition):
    """A transition that combines conditional and distributed transitions."""
    
    def __init__(self, definition: Dict[str, Any]):
        super().__init__(definition)
        self.transitions = definition.get('complex_transition', [])
    
    def follow(self, person: 'Person', time: datetime) -> Optional[str]:
        """
        Evaluate complex transitions.
        
        First evaluates conditions, then applies distributions among matching conditions.
        """
        from synthea.engine.logic import Logic
        
        # Find all transitions whose conditions are met
        matching = []
        for transition in self.transitions:
            if 'condition' in transition:
                if Logic.test(transition['condition'], person, time):
                    matching.append(transition)
            else:
                # No condition means always matches
                matching.append(transition)
        
        if not matching:
            return None
        
        # If only one match, use it
        if len(matching) == 1:
            return self._resolve_transition(matching[0], person, time)
        
        # Multiple matches - check for distributions
        has_distributions = any('distributions' in t for t in matching)
        
        if has_distributions:
            # Use distributed selection among matching transitions
            return self._select_distributed(matching, person, time)
        else:
            # No distributions - use first matching transition
            return self._resolve_transition(matching[0], person, time)
    
    def _resolve_transition(self, transition: Dict[str, Any], person: 'Person',
                          time: datetime) -> Optional[str]:
        """Resolve a single transition which may itself be distributed."""
        if 'distributions' in transition:
            return self._select_from_distributions(transition['distributions'], person)
        else:
            return transition.get('transition')

    def _select_distributed(self, transitions: List[Dict[str, Any]],
                          person: 'Person', time: datetime) -> Optional[str]:
        """Select from multiple transitions with distributions."""
        all_options = []
        for trans in transitions:
            if 'distributions' in trans:
                for dist in trans['distributions']:
                    all_options.append({
                        'transition': dist.get('transition'),
                        'distribution': DistributedTransition._resolve_distribution(
                            dist.get('distribution', 0), person),
                    })
            else:
                all_options.append({
                    'transition': trans.get('transition'),
                    'distribution': 1.0 / len(transitions),
                })

        total = sum(opt['distribution'] for opt in all_options)
        if total > 0:
            for opt in all_options:
                opt['distribution'] /= total

        rand = random.random()
        cumulative = 0.0
        for option in all_options:
            cumulative += option['distribution']
            if rand < cumulative:
                return option['transition']

        return all_options[-1]['transition'] if all_options else None
    
    def _select_from_distributions(self, distributions: List[Dict[str, Any]],
                                   person: 'Person' = None) -> Optional[str]:
        """Select from a list of distributions."""
        if not distributions:
            return None

        resolved = [DistributedTransition._resolve_distribution(d.get('distribution', 0), person)
                    for d in distributions]
        total = sum(resolved)
        if total == 0:
            return distributions[0].get('transition') if distributions else None

        rand = random.random()
        cumulative = 0.0
        for dist, prob in zip(distributions, resolved):
            cumulative += prob / total
            if rand < cumulative:
                return dist.get('transition')

        return distributions[-1].get('transition') if distributions else None


class LookupTableTransition(Transition):
    """A transition that uses CSV lookup tables for probabilities."""
    
    def __init__(self, definition: Dict[str, Any]):
        super().__init__(definition)
        raw = definition.get('lookup_table_transition')
        if raw is not None and not isinstance(raw, dict):
            logger.warning(
                "lookup_table_transition expected a dict but got %s; transition will be skipped",
                type(raw).__name__,
            )
        self.lookup_info = raw if isinstance(raw, dict) else {}
        self.table_data = None
        self._load_table()
    
    def _load_table(self):
        """Load the CSV lookup table."""
        if not self.lookup_info:
            return
        
        csv_path = self.lookup_info.get('lookup_table_name')
        if not csv_path:
            return
        
        # Try to find the CSV file in resources
        base_paths = [
            'resources/lookup_tables/',
            'src/main/resources/lookup_tables/',
            './'
        ]
        
        for base_path in base_paths:
            full_path = os.path.join(base_path, csv_path)
            if os.path.exists(full_path):
                self._read_csv(full_path)
                break
    
    def _read_csv(self, filepath: str):
        """Read and parse the CSV file."""
        self.table_data = []
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    self.table_data.append(row)
        except Exception as e:
            print(f"Error loading lookup table {filepath}: {e}")
            self.table_data = []
    
    def follow(self, person: 'Person', time: datetime) -> Optional[str]:
        """
        Select transition based on lookup table.
        
        Matches person attributes against table rows and uses probabilities
        from matching rows.
        """
        if not self.table_data or not self.lookup_info:
            return None
        
        transitions = self.lookup_info.get('transitions', [])
        if not transitions:
            return None
        
        # Find matching rows based on person attributes
        matching_rows = self._find_matching_rows(person, time)
        if not matching_rows:
            return None
        
        # Calculate probabilities from matching rows
        probabilities = self._calculate_probabilities(matching_rows, transitions)
        
        # Select based on probabilities
        return self._select_by_probability(probabilities)
    
    def _find_matching_rows(self, person: 'Person', time: datetime) -> List[Dict[str, str]]:
        """Find all rows that match the person's attributes."""
        if not self.table_data:
            return []
        
        matching = []
        for row in self.table_data:
            if self._row_matches(row, person, time):
                matching.append(row)
        
        return matching
    
    def _row_matches(self, row: Dict[str, str], person: 'Person', 
                    time: datetime) -> bool:
        """Check if a row matches the person's attributes."""
        # Check age if present
        if 'age' in row or 'age_min' in row or 'age_max' in row:
            age = person.age_at(time)
            
            if 'age' in row:
                try:
                    if age != int(row['age']):
                        return False
                except ValueError:
                    pass
            
            if 'age_min' in row:
                try:
                    if age < int(row['age_min']):
                        return False
                except ValueError:
                    pass
            
            if 'age_max' in row:
                try:
                    if age > int(row['age_max']):
                        return False
                except ValueError:
                    pass
        
        # Check gender if present
        if 'gender' in row and row['gender']:
            if row['gender'].lower() != person.attributes.get('gender', '').lower():
                return False
        
        # Check other attributes
        for key, value in row.items():
            if key not in ['age', 'age_min', 'age_max', 'gender'] and value:
                # Check if this is a probability column (for transitions)
                is_prob_column = any(
                    t.get('lookup_table_column') == key 
                    for t in self.lookup_info.get('transitions', [])
                )
                
                if not is_prob_column:
                    # This is an attribute to match
                    person_value = person.attributes.get(key)
                    if str(person_value) != str(value):
                        return False
        
        return True
    
    def _calculate_probabilities(self, rows: List[Dict[str, str]], 
                                transitions: List[Dict[str, Any]]) -> Dict[str, float]:
        """Calculate transition probabilities from matching rows."""
        probabilities = {}
        
        for transition in transitions:
            column = transition.get('lookup_table_column')
            target = transition.get('transition')
            
            if not column or not target:
                continue
            
            # Average probabilities from all matching rows
            values = []
            for row in rows:
                if column in row:
                    try:
                        values.append(float(row[column]))
                    except ValueError:
                        pass
            
            if values:
                probabilities[target] = sum(values) / len(values)
            else:
                probabilities[target] = 0.0
        
        # Normalize probabilities
        total = sum(probabilities.values())
        if total > 0:
            for key in probabilities:
                probabilities[key] /= total
        
        return probabilities
    
    def _select_by_probability(self, probabilities: Dict[str, float]) -> Optional[str]:
        """Select a transition based on probabilities."""
        if not probabilities:
            return None
        
        rand = random.random()
        cumulative = 0.0
        
        for target, prob in probabilities.items():
            cumulative += prob
            if rand < cumulative:
                return target
        
        # Return last option if rounding errors occur
        return list(probabilities.keys())[-1] if probabilities else None