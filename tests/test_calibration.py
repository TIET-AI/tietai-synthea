"""Population rates are set from configuration, and the value set is the value used."""

from datetime import datetime

import pytest

from synthea.engine.module import Module
from synthea.engine.transition import select_cumulative
from synthea.helpers.config import Config
from synthea.world.calibration import apply_calibration, calibration
from synthea.world.person import Person

NOW = datetime(2020, 6, 1)


def _person(**attributes):
    person = Person(seed=3)
    person.attributes.update(attributes)
    person.init_health_record()
    return person


class TestConfigOverlay:
    def test_a_user_file_overrides_without_dropping_the_bundled_defaults(self, tmp_path):
        user = tmp_path / 'mine.properties'
        user.write_text('calibration.pregnancy.preeclampsia = 0.05\n', encoding='utf-8')

        config = Config()
        config.load(str(user))

        assert config.get('calibration.pregnancy.preeclampsia') == 0.05
        # Not in the user's file: still the bundled value.
        assert config.get('calibration.reproduction.exposure') == 0.3
        assert config.get('exporter.years_of_history') == 10


class TestApplied:
    def test_calibration_keys_are_copied_onto_the_person(self):
        person = _person()
        apply_calibration(person, {'calibration.x.rate': 0.2, 'exporter.other': 1})

        assert person.attributes['calibration.x.rate'] == 0.2
        assert 'exporter.other' not in person.attributes
        assert calibration(person, 'x.rate', 0.9) == 0.2
        assert calibration(person, 'missing', 0.9) == 0.9


class TestExactProbability:
    """``[{p from an attribute}, {1}]`` must fire with probability p, not p/(1+p)."""

    OPTIONS = [
        {'distribution': {'attribute': 'calibration.test.p', 'default': 0.0},
         'transition': 'Hit'},
        {'distribution': 1, 'transition': 'Miss'},
    ]

    @pytest.mark.parametrize('p', [0.05, 0.3, 0.9])
    def test_the_configured_probability_is_the_branch_probability(self, p):
        person = _person(**{'calibration.test.p': p})
        draws = 20000

        hits = sum(select_cumulative(self.OPTIONS, person) == 'Hit' for _ in range(draws))

        assert hits / draws == pytest.approx(p, abs=0.012)

    def test_the_last_option_takes_the_remainder(self):
        person = _person()
        options = [{'distribution': 0.0, 'transition': 'Never'},
                   {'distribution': 0.0, 'transition': 'Rest'}]

        assert select_cumulative(options, person) == 'Rest'


class TestModulesReadIt:
    MODULE = {
        'name': 'calibrated',
        'states': {
            'Initial': {'type': 'Initial', 'distributed_transition': [
                {'distribution': {'attribute': 'calibration.test.p', 'default': 0.0},
                 'transition': 'Yes'},
                {'distribution': 1, 'transition': 'No'},
            ]},
            'Yes': {'type': 'SetAttribute', 'attribute': 'outcome', 'value': 'yes',
                    'direct_transition': 'Terminal'},
            'No': {'type': 'SetAttribute', 'attribute': 'outcome', 'value': 'no',
                   'direct_transition': 'Terminal'},
            'Terminal': {'type': 'Terminal'},
        },
    }

    @pytest.mark.parametrize('p, expected', [(1.0, 'yes'), (0.0, 'no')])
    def test_a_json_module_follows_the_configured_rate(self, p, expected):
        module = Module._create_from_json('calibrated', self.MODULE)
        person = _person(**{'calibration.test.p': p})

        module.process(person, NOW)

        assert person.attributes['outcome'] == expected
