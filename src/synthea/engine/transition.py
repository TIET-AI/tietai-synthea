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
    def _resolve_distribution(dist_value: Any, person: Optional['Person']) -> float:
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
        """Normalize fixed distributions to sum to 1.0; skip when any entry is attribute-based."""
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

        # Resolve all weights for this person, then normalize before selecting so that
        # attribute-based weights (which bypass static normalization) are handled correctly.
        weights = [self._resolve_distribution(t.get('distribution', 0), person)
                   for t in self.transitions]
        total = sum(weights)
        if total <= 0:
            return self.transitions[-1].get('transition')

        rand = random.random() * total
        cumulative = 0.0
        for transition, weight in zip(self.transitions, weights):
            cumulative += weight
            if rand < cumulative:
                return transition.get('transition')

        return self.transitions[-1].get('transition')


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
                                   person: Optional['Person'] = None) -> Optional[str]:
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
    """
    A transition that uses CSV lookup tables for age/gender-stratified
    probabilities.

    GMF format:
        "lookup_table_transition": [
          {"transition": "State_A", "default_probability": 0.6,
           "lookup_table_name": "table.csv"},
          {"transition": "State_B", "default_probability": 0.4,
           "lookup_table_name": "table.csv"}
        ]

    When the CSV is available the per-row probability columns are used;
    otherwise ``default_probability`` values are used as weights and
    normalised to a valid distribution before sampling.
    """

    # Shared cache so the same CSV is read once per process.
    _csv_cache: Dict[str, Optional[List[Dict[str, str]]]] = {}

    _CSV_BASES = [
        'resources/lookup_tables/',
        'src/main/resources/lookup_tables/',
    ]

    def __init__(self, definition: Dict[str, Any]):
        super().__init__(definition)
        raw = definition.get('lookup_table_transition')
        if not isinstance(raw, list):
            logger.warning(
                "lookup_table_transition expected a list but got %s; "
                "transition will fall back to first entry",
                type(raw).__name__,
            )
            raw = []
        self.entries: List[Dict[str, Any]] = raw

    def _load_csv(self, name: str) -> Optional[List[Dict[str, str]]]:
        if name in self._csv_cache:
            return self._csv_cache[name]
        for base in self._CSV_BASES:
            full = os.path.join(base, name)
            if os.path.exists(full):
                try:
                    with open(full, 'r', encoding='utf-8') as f:
                        rows = list(csv.DictReader(f))
                    self._csv_cache[name] = rows
                    return rows
                except Exception as e:
                    logger.warning("Failed to read lookup table %s: %s", full, e)
                    break
        self._csv_cache[name] = None
        return None

    def follow(self, person: 'Person', time: datetime) -> Optional[str]:
        if not self.entries:
            return None

        weights: List[float] = []
        for entry in self.entries:
            prob = float(entry.get('default_probability', 0.0))
            # If a CSV exists, try to find a matching row and override prob.
            csv_name = entry.get('lookup_table_name')
            if csv_name:
                rows = self._load_csv(csv_name)
                if rows:
                    matched = self._find_matching_row(rows, person, time)
                    if matched is not None:
                        prob = matched
            weights.append(prob)

        total = sum(weights)
        if total <= 0:
            return self.entries[-1].get('transition')

        rand = random.random() * total
        cumulative = 0.0
        for entry, w in zip(self.entries, weights):
            cumulative += w
            if rand < cumulative:
                return entry.get('transition')
        return self.entries[-1].get('transition')

    def _find_matching_row(self, rows: List[Dict[str, str]],
                           person: 'Person', time: datetime) -> Optional[float]:
        """
        Return the probability value from the first matching CSV row, or
        None if no row matches or no numeric value is found.
        """
        age = getattr(person, 'age_at', lambda t: None)(time)
        gender = person.attributes.get('gender', '')

        for row in rows:
            if 'age_min' in row:
                try:
                    if age is None or age < int(row['age_min']):
                        continue
                except (ValueError, TypeError):
                    pass
            if 'age_max' in row:
                try:
                    if age is None or age > int(row['age_max']):
                        continue
                except (ValueError, TypeError):
                    pass
            if 'gender' in row and row['gender']:
                if row['gender'].lower() != gender.lower():
                    continue
            # First numeric column that isn't a filter column is the probability.
            for key, val in row.items():
                if key in ('age_min', 'age_max', 'gender', 'age'):
                    continue
                try:
                    return float(val)
                except (ValueError, TypeError):
                    continue
        return None