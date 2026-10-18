"""EncounterEnd completes, as in the Java reference engine (issue #119).

Before: the state ended the encounter and returned False ("needs more time") on every
call, so the module sat on it for ever and nothing after an EncounterEnd was reachable.
"""
from datetime import datetime, timedelta

import pytest

from synthea.engine.module import Module
from synthea.engine.state import EncounterEndState
from synthea.world.person import Person

T0 = datetime(2021, 6, 1)
CODE = [{"system": "SNOMED-CT", "code": "185349003", "display": "Encounter for check up"}]
COND = [{"system": "SNOMED-CT", "code": "44054006", "display": "Diabetes"}]


@pytest.fixture(autouse=True)
def _default_setting():
    from synthea.engine.logic import Logic
    EncounterEndState.legacy_stall = False
    Logic.legacy = False
    yield
    EncounterEndState.legacy_stall = False
    Logic.legacy = False


def _module(states):
    return Module._create_from_json("t", {"name": "t", "states": states})


def _person():
    p = Person(seed=11)
    p.init_health_record()
    return p


ENC = {"type": "Encounter", "encounter_class": "ambulatory", "codes": CODE}


def test_module_proceeds_past_encounter_end_in_one_pass():
    m = _module({
        "Initial": {"type": "Initial", "direct_transition": "Visit"},
        "Visit": dict(ENC, direct_transition="End"),
        "End": {"type": "EncounterEnd", "direct_transition": "Onset"},
        "Onset": {"type": "ConditionOnset", "codes": COND, "direct_transition": "Terminal"},
        "Terminal": {"type": "Terminal"},
    })
    p = _person()
    assert m.process(p, T0) is True                  # reached Terminal
    assert [c.codes[0].code for c in p.record.conditions] == ["44054006"]
    assert p.record.encounters[0].end_time == T0     # the encounter was ended
    assert "current_encounter" not in p.attributes


def test_encounter_end_next_to_terminal_completes_the_module():
    m = _module({
        "Initial": {"type": "Initial", "direct_transition": "Visit"},
        "Visit": dict(ENC, direct_transition="End"),
        "End": {"type": "EncounterEnd", "direct_transition": "Terminal"},
        "Terminal": {"type": "Terminal"},
    })
    p = _person()
    assert m.process(p, T0) is True
    assert p.attributes["t_current_state"] is None


def test_encounter_end_not_next_to_terminal_reaches_a_later_delay():
    m = _module({
        "Initial": {"type": "Initial", "direct_transition": "Visit"},
        "Visit": dict(ENC, direct_transition="End"),
        "End": {"type": "EncounterEnd", "direct_transition": "Wait"},
        "Wait": {"type": "Delay", "exact": {"quantity": 30, "unit": "days"}, "direct_transition": "Onset"},
        "Onset": {"type": "ConditionOnset", "codes": COND, "direct_transition": "Terminal"},
        "Terminal": {"type": "Terminal"},
    })
    p = _person()
    assert m.process(p, T0) is False                 # parked on the Delay, not on EncounterEnd
    assert p.attributes["t_current_state"] == "Wait"
    assert m.process(p, T0 + timedelta(days=31)) is True
    assert len(p.record.conditions) == 1


def test_a_loop_through_encounter_end_still_terminates():
    """Encounter -> EncounterEnd -> Encounter with no Delay is an authoring error; the iteration cap holds."""
    m = _module({
        "Initial": {"type": "Initial", "direct_transition": "Visit"},
        "Visit": dict(ENC, direct_transition="End"),
        "End": {"type": "EncounterEnd", "direct_transition": "Visit"},
    })
    p = _person()
    assert m.process(p, T0) is False                 # yielded by the cycle cap, did not hang
    assert p.attributes["t_current_state"] in ("Visit", "End")


def test_state_returns_true_and_ends_the_open_encounter():
    p = _person()
    enc = p.record.encounter_start(T0, "ambulatory")
    p.attributes["current_encounter"] = enc
    s = EncounterEndState(Module("t"), "End", {"type": "EncounterEnd"})
    assert s.run(p, T0 + timedelta(minutes=20)) is True
    assert enc.end_time == T0 + timedelta(minutes=20)
    assert s.run(p, T0 + timedelta(minutes=20)) is True      # no encounter open: still completes


def test_legacy_stall_reproduces_the_old_behaviour():
    EncounterEndState.legacy_stall = True
    p = _person()
    s = EncounterEndState(Module("t"), "End", {"type": "EncounterEnd"})
    assert [s.run(p, T0 + timedelta(days=d)) for d in (0, 0, 1, 7)] == [False] * 4


def test_generator_reads_the_opt_out_setting():
    from synthea.engine.generator import Generator, GeneratorOptions
    from synthea.helpers.config import Config
    cfg = Config()
    cfg.load()
    cfg.set("exporter.fhir.export", False)
    o = GeneratorOptions()
    o.population_size = 1
    o.seed = 1
    Generator(o, config=cfg)
    assert EncounterEndState.legacy_stall is False
    cfg.set("generate.encounter_end_legacy_stall", True)
    Generator(o, config=cfg)
    assert EncounterEndState.legacy_stall is True


def test_a_routine_visit_is_joined_once_per_module_per_step():
    """Wellness Encounter -> ... -> EncounterEnd -> back to the wellness Encounter must wait for the
    next visit instead of re-joining the same one until the iteration cap (found when EncounterEnd
    started completing)."""
    m = _module({
        "Initial": {"type": "Initial", "direct_transition": "Visit"},
        "Visit": {"type": "Encounter", "wellness": True, "codes": CODE, "direct_transition": "Onset"},
        "Onset": {"type": "ConditionOnset", "codes": COND, "direct_transition": "End"},
        "End": {"type": "EncounterEnd", "direct_transition": "Visit"},
    })
    p = _person()
    visit = p.record.encounter_start(T0, "wellness")
    p.attributes["current_wellness_encounter"] = visit
    assert m.process(p, T0) is False                       # parked on the Visit state, no cap warning
    assert p.attributes["t_current_state"] == "Visit"
    assert len(p.record.conditions) == 1                   # exactly one onset for this visit
    # next routine visit: joined again, once
    visit2 = p.record.encounter_start(T0 + timedelta(days=365), "wellness")
    p.attributes["current_wellness_encounter"] = visit2
    assert m.process(p, T0 + timedelta(days=365)) is False
    assert len(p.record.conditions) == 2


def test_legacy_stall_keeps_the_old_wellness_behaviour():
    EncounterEndState.legacy_stall = True
    m = _module({
        "Initial": {"type": "Initial", "direct_transition": "A"},
        "A": {"type": "Encounter", "wellness": True, "codes": CODE, "direct_transition": "B"},
        "B": {"type": "Encounter", "wellness": True, "codes": CODE, "direct_transition": "Terminal"},
        "Terminal": {"type": "Terminal"},
    })
    p = _person()
    p.attributes["current_wellness_encounter"] = p.record.encounter_start(T0, "wellness")
    assert m.process(p, T0) is True                        # two wellness states in one step, as before


# --- companions found while making EncounterEnd complete (issue #119) -------------------------

def _logic(cond, attrs=None, module=None):
    from synthea.engine.logic import Logic
    p = _person()
    p.attributes.update(attrs or {})
    previous, Logic.current_module = Logic.current_module, module
    try:
        return Logic.test(cond, p, T0)
    finally:
        Logic.current_module = previous


def test_is_nil_and_is_not_nil_attribute_operators():
    nil = {"condition_type": "Attribute", "attribute": "x", "operator": "is nil"}
    not_nil = {"condition_type": "Attribute", "attribute": "x", "operator": "is not nil"}
    assert _logic(nil) is True and _logic(not_nil) is False
    assert _logic(nil, {"x": 0}) is False and _logic(not_nil, {"x": 0}) is True


def test_prior_state_without_a_module_means_the_module_being_processed():
    cond = {"condition_type": "PriorState", "name": "S", "within": {"quantity": 5, "unit": "years"}}
    attrs = {"mod.S_visited": True, "mod.S_visited_at": T0 - timedelta(days=30)}
    assert _logic(cond, attrs, module="mod") is True
    assert _logic(cond, attrs, module="other") is False
    attrs["mod.S_visited_at"] = T0 - timedelta(days=366 * 6)
    assert _logic(cond, attrs, module="mod") is False                      # outside the window


def test_module_process_sets_and_restores_the_current_module():
    from synthea.engine.logic import Logic
    m = _module({"Initial": {"type": "Initial", "direct_transition": "Terminal"}, "Terminal": {"type": "Terminal"}})
    assert Logic.current_module is None
    m.process(_person(), T0)
    assert Logic.current_module is None


def test_a_state_is_not_run_twice_in_one_step_but_runs_again_next_step():
    m = _module({
        "Initial": {"type": "Initial", "direct_transition": "Visit"},
        "Visit": dict(ENC, direct_transition="Onset"),
        "Onset": {"type": "ConditionOnset", "codes": COND, "direct_transition": "End"},
        "End": {"type": "EncounterEnd", "direct_transition": "Visit"},
    })
    p = _person()
    assert m.process(p, T0) is False
    assert len(p.record.conditions) == 1                   # not 250 (cap / 2) in one step
    assert m.process(p, T0 + timedelta(days=7)) is False
    assert len(p.record.conditions) == 2                   # one more cycle on the next step


def test_a_valueless_observation_gets_no_reference_range():
    from synthea.world.health_record import Code
    p = _person()
    ob = p.record.observation(T0, Code("LOINC", "39156-5", "BMI"), None, "kg/m2")
    assert ob.reference_range is None and ob.interpretation is None
