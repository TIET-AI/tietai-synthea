"""Module-engine semantics that must match Java Synthea.

- PriorState honours ``since``: false when that state was visited after the
  named one. It used to be ignored.
- EncounterEnd in a module attached to a routine check-up leaves the visit
  rather than closing it; the core encounter module closes it.
"""

from datetime import datetime, timedelta

import pytest

from synthea.engine.module import Module
from synthea.world.person import Person

NOW = datetime(2020, 1, 1)


@pytest.fixture
def person():
    person = Person(seed=17)
    person.attributes['gender'] = 'F'
    person.attributes['birth_date'] = datetime(2010, 1, 1)  # 10 years old at NOW
    return person


@pytest.fixture
def register(monkeypatch):
    """Register in-memory JSON modules for the duration of a test."""
    def _register(name, states):
        monkeypatch.setitem(
            Module._module_suppliers, name,
            lambda: Module._create_from_json(name, {'states': states}),
        )
        monkeypatch.delitem(Module._modules, name, raising=False)
        return Module.get_module(name)
    yield _register
    for name in [k for k in Module._modules if k.startswith('semantics_test')]:
        Module._modules.pop(name, None)


class TestPriorStateSince:
    def test_since_cuts_the_history_off(self, register, person):
        module = register('semantics_test_since', {
            'Initial': {'type': 'Initial', 'direct_transition': 'Seen'},
            'Seen': {'type': 'Simple', 'direct_transition': 'Boundary'},
            'Boundary': {'type': 'Simple', 'direct_transition': 'Check'},
            'Check': {'type': 'Guard',
                      'allow': {'condition_type': 'PriorState', 'name': 'Seen',
                                'since': 'Boundary'},
                      'direct_transition': 'Terminal'},
            'Terminal': {'type': 'Terminal'},
        })

        assert module.process(person, NOW) is False



class TestWellnessEncounterEnd:
    def test_a_module_leaves_a_check_up_without_closing_it(self, register, person):
        """Java: only the core encounter module closes a routine check-up."""
        person.init_health_record()
        visit = person.record.encounter_start(NOW, 'wellness')
        person.attributes['current_wellness_encounter'] = visit
        module = register('semantics_test_wellness', {
            'Initial': {'type': 'Initial', 'direct_transition': 'Visit'},
            'Visit': {'type': 'Encounter', 'wellness': True, 'direct_transition': 'Leave'},
            'Leave': {'type': 'EncounterEnd', 'direct_transition': 'Terminal'},
            'Terminal': {'type': 'Terminal'},
        })

        module.process(person, NOW)

        assert visit.end_time is None
        assert 'current_encounter' not in person.attributes
