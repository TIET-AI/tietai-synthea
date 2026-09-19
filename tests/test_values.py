"""Tests for GMF value generation.

Covers every value form the bundled modules use, the distribution kinds and
their parameters, and the end-to-end effect: observations must carry a value
and delays must actually delay.
"""

import statistics
from datetime import datetime, timedelta

import pytest

from synthea.engine.module import Module
from synthea.engine.state import DelayState, ObservationState, SetAttributeState, SymptomState
from synthea.engine.values import (
    duration_for,
    passes_probability,
    sample_distribution,
    to_timedelta,
    unit_for,
    value_for,
)
from synthea.world.person import Person


@pytest.fixture
def person():
    return Person(seed=20260919)


class TestDistributionKinds:
    """Each kind the bundled modules use must be sampled correctly."""

    def test_exact(self, person):
        spec = {'kind': 'EXACT', 'parameters': {'value': 7}}
        assert sample_distribution(spec, person) == 7.0

    def test_uniform_stays_within_bounds(self, person):
        spec = {'kind': 'UNIFORM', 'parameters': {'low': 30, 'high': 60}}
        samples = [sample_distribution(spec, person) for _ in range(500)]

        assert all(30 <= s <= 60 for s in samples)
        assert min(samples) < 35 and max(samples) > 55

    def test_gaussian_matches_its_parameters(self, person):
        spec = {'kind': 'GAUSSIAN', 'parameters': {'mean': 90, 'standardDeviation': 30}}
        samples = [sample_distribution(spec, person) for _ in range(10000)]

        assert statistics.mean(samples) == pytest.approx(90, abs=2)
        assert statistics.stdev(samples) == pytest.approx(30, abs=2)

    def test_gaussian_respects_min_and_max(self, person):
        spec = {
            'kind': 'GAUSSIAN',
            'parameters': {'mean': 0, 'standardDeviation': 50, 'min': 10, 'max': 20},
        }
        samples = [sample_distribution(spec, person) for _ in range(500)]

        assert all(10 <= s <= 20 for s in samples)

    def test_exponential_matches_its_mean(self, person):
        spec = {'kind': 'EXPONENTIAL', 'parameters': {'mean': 14}}
        samples = [sample_distribution(spec, person) for _ in range(10000)]

        assert statistics.mean(samples) == pytest.approx(14, rel=0.1)
        assert all(s >= 0 for s in samples)

    def test_round_produces_whole_numbers(self, person):
        spec = {
            'kind': 'GAUSSIAN', 'round': True,
            'parameters': {'mean': 90, 'standardDeviation': 30},
        }
        samples = [sample_distribution(spec, person) for _ in range(50)]

        assert all(s == int(s) for s in samples)

    def test_unrounded_produces_fractions(self, person):
        spec = {'kind': 'EXPONENTIAL', 'round': False, 'parameters': {'mean': 14}}
        samples = [sample_distribution(spec, person) for _ in range(50)]

        assert any(s != int(s) for s in samples)

    def test_unknown_kind_falls_back_and_warns_once(self, person, caplog):
        spec = {'kind': 'WEIBULL', 'parameters': {'value': 3}}

        with caplog.at_level('WARNING'):
            first = sample_distribution(spec, person)
            sample_distribution(spec, person)

        assert first == 3.0
        assert sum('WEIBULL' in r.message for r in caplog.records) <= 1


class TestValueForms:
    """Every way a state can name a value."""

    def test_exact(self, person):
        assert value_for({'exact': {'quantity': 5}}, person) == 5

    def test_range_stays_within_bounds(self, person):
        values = [value_for({'range': {'low': 250, 'high': 500}}, person) for _ in range(200)]
        assert all(250 <= v <= 500 for v in values)

    def test_distribution(self, person):
        value = value_for(
            {'distribution': {'kind': 'EXACT', 'parameters': {'value': 12}}}, person
        )
        assert value == 12.0

    def test_value_attribute_reads_an_attribute(self, person):
        person.attributes['breast_cancer_condition'] = 'metastatic'
        assert value_for({'value_attribute': 'breast_cancer_condition'}, person) == 'metastatic'

    def test_attribute_source_is_opt_in(self, person):
        """``attribute`` is the target on SetAttribute and a source on Observation."""
        person.attributes['bmi'] = 27.5
        definition = {'attribute': 'bmi'}

        assert value_for(definition, person) is None
        assert value_for(definition, person, attribute_key='attribute') == 27.5

    def test_vital_sign_source(self, person):
        person.set_vital_sign('Glucose', 105.0, 'mg/dL', datetime(2020, 1, 1))
        assert value_for({'vital_sign': 'Glucose'}, person) == 105.0

    def test_value_code(self, person):
        code = {'system': 'SNOMED-CT', 'code': '1', 'display': 'x'}
        assert value_for({'value_code': code}, person) == code

    def test_missing_value_returns_default(self, person):
        assert value_for({}, person, default=0.0) == 0.0


class TestProbabilityGate:
    def test_absent_probability_always_passes(self, person):
        assert passes_probability({}, person) is True

    def test_probability_one_always_passes(self, person):
        assert all(passes_probability({'probability': 1.0}, person) for _ in range(50))

    def test_probability_zero_never_passes(self, person):
        assert not any(passes_probability({'probability': 0.0}, person) for _ in range(50))

    def test_probability_is_approximately_honoured(self, person):
        hits = sum(passes_probability({'probability': 0.83}, person) for _ in range(5000))
        assert 0.80 < hits / 5000 < 0.86


class TestDurations:
    def test_units(self):
        assert to_timedelta(2, 'weeks') == timedelta(weeks=2)
        assert to_timedelta(3, 'days') == timedelta(days=3)
        assert to_timedelta(1, 'years') == timedelta(days=365)

    def test_unknown_unit_falls_back_to_days(self, caplog):
        with caplog.at_level('WARNING'):
            assert to_timedelta(5, 'fortnights') == timedelta(days=5)

    def test_unit_comes_from_the_value_block_first(self):
        assert unit_for({'exact': {'quantity': 1, 'unit': 'weeks'}, 'unit': 'days'}) == 'weeks'

    def test_unit_falls_back_to_the_state(self):
        assert unit_for({'distribution': {'kind': 'EXACT'}, 'unit': 'months'}) == 'months'

    def test_distribution_duration(self, person):
        definition = {
            'distribution': {'kind': 'EXACT', 'parameters': {'value': 90}},
            'unit': 'days',
        }
        assert duration_for(definition, person) == timedelta(days=90)


class TestStatesUseTheValues:
    """The states must actually consult the value generator."""

    def test_delay_uses_a_state_level_duration(self, person):
        """Regression: the engine looked for a nested ``delay`` key that no
        bundled module uses, so all 534 Delay states resolved to zero."""
        state = DelayState(Module('test'), 'wait',
                           {'type': 'Delay', 'exact': {'quantity': 30, 'unit': 'days'}})
        start = datetime(2020, 1, 1)

        assert state.run(person, start) is False
        assert state.run(person, start + timedelta(days=29)) is False
        assert state.run(person, start + timedelta(days=31)) is True

    def test_delay_uses_a_distribution(self, person):
        state = DelayState(Module('test'), 'wait', {
            'type': 'Delay',
            'distribution': {'kind': 'EXACT', 'parameters': {'value': 90}},
            'unit': 'days',
        })
        start = datetime(2020, 1, 1)

        assert state.run(person, start) is False
        assert state.run(person, start + timedelta(days=89)) is False
        assert state.run(person, start + timedelta(days=91)) is True

    def test_zero_delay_completes_immediately(self, person):
        state = DelayState(Module('test'), 'wait',
                           {'type': 'Delay', 'exact': {'quantity': 0, 'unit': 'days'}})
        assert state.run(person, datetime(2020, 1, 1)) is True

    def test_set_attribute_uses_a_distribution(self, person):
        state = SetAttributeState(Module('test'), 'los', {
            'type': 'SetAttribute',
            'attribute': 'length_of_stay',
            'distribution': {'kind': 'EXACT', 'round': True, 'parameters': {'value': 14}},
        })
        state.run(person, datetime(2020, 1, 1))

        assert person.attributes['length_of_stay'] == 14.0

    def test_set_attribute_copies_another_attribute(self, person):
        person.attributes['source'] = 'copied'
        state = SetAttributeState(Module('test'), 'copy', {
            'type': 'SetAttribute',
            'attribute': 'target',
            'value_attribute': 'source',
        })
        state.run(person, datetime(2020, 1, 1))

        assert person.attributes['target'] == 'copied'

    def test_symptom_probability_gates_the_symptom(self, person):
        state = SymptomState(Module('test'), 'lump', {
            'type': 'Symptom', 'symptom': 'Lump/mass',
            'probability': 0.0, 'range': {'low': 10, 'high': 20},
        })
        state.run(person, datetime(2020, 1, 1))

        assert 'Lump/mass' not in person.symptoms

    def test_observation_records_a_ranged_value(self, person):
        person.init_health_record()
        encounter = person.record.encounter_start(datetime(2020, 1, 1), 'ambulatory')
        person.attributes['current_encounter'] = encounter

        state = ObservationState(Module('test'), 'anc', {
            'type': 'Observation',
            'category': 'laboratory',
            'unit': '10*3/uL',
            'codes': [{'system': 'LOINC', 'code': '751-8', 'display': 'Neutrophils'}],
            'range': {'low': 250, 'high': 500},
        })
        state.run(person, datetime(2020, 1, 1))

        observation = person.record.observations[-1]
        assert observation.value is not None
        assert 250 <= observation.value <= 500
