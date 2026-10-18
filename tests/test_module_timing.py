"""Module.process timing semantics shared with upstream Synthea.

Regression tests for the COVID-19 module never diagnosing anyone: a
CallSubmodule abandoned its submodule at the first Delay, and a short
self-looping Delay cycled once per two time steps.
"""

from datetime import datetime, timedelta

from synthea.engine.module import Module
from synthea.world.person import Person

STEP = timedelta(days=7)
START = datetime(2020, 1, 1)


def _module(name, states):
    return Module._create_from_json(name, {'states': states})


def test_call_submodule_waits_for_submodule_delay(monkeypatch):
    sub = _module('test_sub/inner', {
        'Initial': {'type': 'Initial', 'direct_transition': 'Wait'},
        'Wait': {'type': 'Delay', 'exact': {'quantity': 30, 'unit': 'minutes'},
                 'direct_transition': 'After'},
        'After': {'type': 'Simple', 'direct_transition': 'Terminal'},
        'Terminal': {'type': 'Terminal'},
    })
    monkeypatch.setitem(Module._modules, sub.name, sub)
    parent = _module('test_parent', {
        'Initial': {'type': 'Initial', 'direct_transition': 'Call'},
        'Call': {'type': 'CallSubmodule', 'submodule': sub.name,
                 'direct_transition': 'Done'},
        'Done': {'type': 'Simple', 'direct_transition': 'Terminal'},
        'Terminal': {'type': 'Terminal'},
    })
    person = Person()

    assert parent.process(person, START) is False
    assert 'test_parent.Done_visited' not in person.attributes

    assert parent.process(person, START + STEP) is True
    # The state after the 30-minute delay happens 30 minutes later, not a
    # whole time step later.
    assert person.attributes['test_sub/inner.After_visited_at'] == (
        START + timedelta(minutes=30))
    assert person.attributes['test_parent.Done_visited']
    # Finished submodules start again at Initial on the next call.
    assert 'test_sub/inner_current_state' not in person.attributes


def test_short_self_looping_delay_keeps_its_cadence():
    module = _module('test_loop', {
        'Initial': {'type': 'Initial', 'direct_transition': 'Wait'},
        'Wait': {'type': 'Delay', 'exact': {'quantity': 4, 'unit': 'days'},
                 'direct_transition': 'Wait'},
    })
    person = Person()
    entries = []
    original = module.states['Wait'].run

    def run(p, time):
        if 'Wait' not in p.attributes.get('test_loop_delays', {}):
            entries.append(time)
        return original(p, time)

    module.states['Wait'].run = run
    for step in range(53):  # a year
        module.process(person, START + step * STEP)

    # Re-entered every 4 days (~91 a year); it was every 14 days (~26).
    assert len(entries) >= 90
    gaps = {b - a for a, b in zip(entries, entries[1:])}
    assert gaps == {timedelta(days=4)}
