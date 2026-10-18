"""Transition, submodule and PriorState semantics, as upstream Synthea has them.

Each of these silently stopped or skewed metabolic_syndrome_care:

- a complex or conditional transition with no matching option returned None,
  which ended the module for good (Check_Complications has no option for
  ``ckd == 0``, so care stopped at the first (pre)diabetes check-up);
- a complex transition pooled the distributions of every matching option, so
  a conditionless fallback fired alongside the branch that matched;
- a submodule kept its final state, so it ran once per lifetime;
- PriorState without a ``module`` key was always false.
"""

from datetime import datetime, timedelta

import pytest

from synthea.engine.module import Module
from synthea.engine.state import CallSubmoduleState
from synthea.engine.transition import ComplexTransition, ConditionalTransition
from synthea.world.person import Person

NOW = datetime(2020, 1, 1)
WEEK = timedelta(days=7)


@pytest.fixture
def person():
    person = Person(seed=3)
    person.attributes['gender'] = 'F'
    person.attributes['birth_date'] = datetime(1970, 1, 1)
    person.init_health_record()
    return person


def _flag(value):
    return {'condition_type': 'Attribute', 'attribute': 'flag',
            'operator': '==', 'value': value}


class TestComplexTransition:
    def test_the_first_matching_option_wins(self, person):
        person.attributes['flag'] = True
        transition = ComplexTransition({'complex_transition': [
            {'condition': _flag(True), 'transition': 'Matched'},
            {'distributions': [{'distribution': 1.0, 'transition': 'Fallback'}]},
        ]})

        assert {transition.follow(person, NOW) for _ in range(50)} == {'Matched'}

    def test_no_match_follows_the_last_option(self, person):
        person.attributes['flag'] = 0
        transition = ComplexTransition({'complex_transition': [
            {'condition': _flag(1), 'transition': 'One'},
            {'condition': _flag(2), 'distributions': [
                {'distribution': 1.0, 'transition': 'Two'}]},
        ]})

        assert transition.follow(person, NOW) == 'Two'


class TestConditionalTransition:
    def test_no_match_follows_the_last_option(self, person):
        person.attributes['flag'] = 0
        transition = ConditionalTransition({'conditional_transition': [
            {'condition': _flag(1), 'transition': 'One'},
            {'condition': _flag(2), 'transition': 'Two'},
        ]})

        assert transition.follow(person, NOW) == 'Two'


def _module(name, states):
    return Module._create_from_json(name, {'name': name, 'states': states})


class TestCallSubmodule:
    def _call(self):
        return CallSubmoduleState(Module('parent'), 'Call',
                                  {'type': 'CallSubmodule', 'submodule': 'test/sub',
                                   'direct_transition': 'Next'})

    def test_every_call_runs_the_submodule_from_the_start(self, person, monkeypatch):
        monkeypatch.setitem(Module._modules, 'test/sub', _module('test/sub', {
            'Initial': {'type': 'Initial', 'direct_transition': 'Count'},
            'Count': {'type': 'Counter', 'attribute': 'calls', 'action': 'increment',
                      'direct_transition': 'Terminal'},
            'Terminal': {'type': 'Terminal'},
        }))
        call = self._call()

        assert call.run(person, NOW) is True
        assert call.run(person, NOW + WEEK) is True
        assert person.attributes['calls'] == 2

    def test_the_caller_waits_for_a_submodule_delay(self, person, monkeypatch):
        monkeypatch.setitem(Module._modules, 'test/sub', _module('test/sub', {
            'Initial': {'type': 'Initial', 'direct_transition': 'Wait'},
            'Wait': {'type': 'Delay', 'exact': {'quantity': 1, 'unit': 'weeks'},
                     'direct_transition': 'Done'},
            'Done': {'type': 'SetAttribute', 'attribute': 'done', 'value': True,
                     'direct_transition': 'Terminal'},
            'Terminal': {'type': 'Terminal'},
        }))
        call = self._call()

        assert call.run(person, NOW) is False
        assert 'done' not in person.attributes
        assert call.run(person, NOW + WEEK) is True
        assert person.attributes['done'] is True


class TestModuleProcessing:
    def test_prior_state_without_a_module_reads_the_current_module(self, person):
        module = _module('test', {
            'Initial': {'type': 'Initial', 'direct_transition': 'Seen'},
            'Seen': {'type': 'Simple', 'direct_transition': 'Check'},
            'Check': {'type': 'Simple', 'conditional_transition': [
                {'condition': {'condition_type': 'PriorState', 'name': 'Seen'},
                 'transition': 'Yes'},
                {'transition': 'No'},
            ]},
            'Yes': {'type': 'SetAttribute', 'attribute': 'answer', 'value': 'yes',
                    'direct_transition': 'Terminal'},
            'No': {'type': 'SetAttribute', 'attribute': 'answer', 'value': 'no',
                   'direct_transition': 'Terminal'},
            'Terminal': {'type': 'Terminal'},
        })

        module.process(person, NOW)

        assert person.attributes['answer'] == 'yes'

    def test_a_delay_that_loops_to_itself_rearms_at_once(self, person):
        module = _module('test', {
            'Initial': {'type': 'Initial', 'direct_transition': 'Tick'},
            'Tick': {'type': 'Delay', 'exact': {'quantity': 1, 'unit': 'weeks'},
                     'direct_transition': 'Tick'},
        })

        assert module.process(person, NOW) is False
        assert module.process(person, NOW + WEEK) is False
        assert person.attributes['test_current_state'] == 'Tick'
        assert person.attributes['test_delays']['Tick'] == NOW + 2 * WEEK


def test_a_named_transition_wins_over_empty_distributions(person):
    """wellness_encounters' Pediatric Dentist pairs the two; upstream follows the name."""
    transition = ComplexTransition({'complex_transition': [
        {'condition': {'condition_type': 'True'}, 'distributions': [],
         'transition': 'End'},
    ]})

    assert transition.follow(person, NOW) == 'End'
