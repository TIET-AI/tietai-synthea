"""Tests for configuration keys that are documented and must therefore work.

Nine keys were recognised, accepted without error, and read by nothing. Setting
`exporter.only_living = true` got you deceased patients anyway, with no warning.
Silence is the worst of the three possible behaviours: worse than working, and
worse than refusing.

These tests exist so a documented key cannot quietly become inert again.
"""

import json
from datetime import datetime
from unittest import mock

import pytest

from synthea.engine.generator import Generator, GeneratorOptions, _name_set
from synthea.export.exporter import Exporter, FHIRServerExporter
from synthea.helpers.config import Config

REFERENCE_DATE = datetime(2020, 6, 1)


def _config(**overrides):
    config = Config()
    config.load()
    config.set('exporter.fhir.export', False)
    config.set('exporter.json.export', False)
    for key, value in overrides.items():
        config.set(key.replace('__', '.'), value)
    return config


def _options(**overrides):
    options = GeneratorOptions()
    options.population_size = 1
    options.seed = 5
    options.reference_date = REFERENCE_DATE
    for key, value in overrides.items():
        setattr(options, key, value)
    return options


class TestNameSet:
    """The module filters accept the shapes a properties file can express."""

    @pytest.mark.parametrize('value, expected', [
        ('asthma', {'asthma'}),
        ('asthma,hypertension', {'asthma', 'hypertension'}),
        ('asthma, hypertension', {'asthma', 'hypertension'}),
        ('asthma hypertension', {'asthma', 'hypertension'}),
        ('  Asthma , HYPERTENSION ', {'asthma', 'hypertension'}),
        (['asthma', 'hypertension'], {'asthma', 'hypertension'}),
    ])
    def test_it_parses_the_forms_a_user_would_write(self, value, expected):
        assert _name_set(value) == expected

    @pytest.mark.parametrize('value', [None, '', False, '   ', ','])
    def test_an_empty_filter_is_no_filter(self, value):
        assert _name_set(value) == set()


class TestModuleFilters:
    def test_enabled_restricts_to_the_named_modules(self):
        generator = Generator(_options(),
                              config=_config(generate__modules__enabled='asthma'))

        assert 'asthma' in generator.module_list
        assert 'hypertension' not in generator.module_list

    def test_disabled_removes_the_named_modules(self):
        generator = Generator(_options(),
                              config=_config(generate__modules__disabled='asthma'))

        assert 'asthma' not in generator.module_list
        assert 'hypertension' in generator.module_list

    def test_core_modules_survive_a_filter(self):
        """Otherwise patients would lose their identity and vitals."""
        from synthea.engine.module import Module

        generator = Generator(_options(),
                              config=_config(generate__modules__enabled='asthma'))

        for core in Module.CORE_MODULE_ORDER:
            if core in Module.get_all_modules():
                assert core in generator.module_list, core

    def test_disabled_wins_over_enabled(self, caplog):
        generator = Generator(
            _options(),
            config=_config(generate__modules__enabled='asthma',
                           generate__modules__disabled='asthma'))

        assert 'asthma' not in generator.module_list

    def test_a_filter_matching_nothing_warns(self, caplog):
        """A typo should say so, not silently produce patients with no disease."""
        with caplog.at_level('WARNING'):
            Generator(_options(),
                      config=_config(generate__modules__enabled='not-a-module'))

        assert any('left no disease modules' in r.message for r in caplog.records)

    def test_no_filter_keeps_everything(self):
        generator = Generator(_options(), config=_config())

        assert 'asthma' in generator.module_list
        assert 'hypertension' in generator.module_list


class TestReferenceYear:
    def test_it_sets_the_year_of_the_reference_date(self):
        generator = Generator(_options(),
                              config=_config(generate__reference_year=2015))

        assert generator.options.reference_date.year == 2015

    def test_an_explicit_reference_date_wins(self):
        """`-r` is a specific instruction; a configured year is a default."""
        options = _options()
        options.reference_date_explicit = True

        generator = Generator(options,
                              config=_config(generate__reference_year=2015))

        assert generator.options.reference_date == REFERENCE_DATE

    def test_a_nonsense_year_is_ignored_with_a_warning(self, caplog):
        with caplog.at_level('WARNING'):
            generator = Generator(_options(),
                                  config=_config(generate__reference_year='soon'))

        assert generator.options.reference_date == REFERENCE_DATE
        assert any('reference_year' in r.message for r in caplog.records)

    def test_no_year_leaves_the_date_alone(self):
        generator = Generator(_options(), config=_config())

        assert generator.options.reference_date == REFERENCE_DATE


class TestGeography:
    def test_the_state_comes_from_config_when_the_cli_gives_none(self):
        generator = Generator(
            _options(),
            config=_config(generate__geography__state='Massachusetts'))

        assert generator.location.state == 'Massachusetts'

    def test_the_cli_wins_over_config(self):
        generator = Generator(
            _options(state='California'),
            config=_config(generate__geography__state='Massachusetts'))

        assert generator.location.state == 'California'

    def test_a_city_without_a_state_is_ignored_with_a_warning(self, caplog):
        """City names are not unique across states."""
        with caplog.at_level('WARNING'):
            Generator(_options(), config=_config(generate__geography__city='Boston'))

        assert any('without a state' in r.message for r in caplog.records)

    def test_demographics_can_be_switched_off(self):
        generator = Generator(
            _options(state='Massachusetts'),
            config=_config(generate__geography__use_demographics=False))

        assert generator.demographics is not None

    def test_demographics_are_loaded_by_default(self):
        generator = Generator(_options(), config=_config())

        assert generator.demographics is not None


class TestOnlyLiving:
    class _Recorder:
        def __init__(self):
            self.seen = []

        def export(self, person, time):
            self.seen.append(person)

    def _exporter_with(self, recorder, **overrides):
        exporter = Exporter(_config(**overrides))
        exporter.patient_exporters = [recorder]
        return exporter

    def test_deceased_patients_are_dropped(self):
        recorder = self._Recorder()
        exporter = self._exporter_with(recorder, exporter__only_living=True)

        living = mock.Mock(alive=True)
        dead = mock.Mock(alive=False)
        exporter.export(living)
        exporter.export(dead)

        assert recorder.seen == [living]

    def test_everyone_is_exported_by_default(self):
        recorder = self._Recorder()
        exporter = self._exporter_with(recorder)

        living = mock.Mock(alive=True)
        dead = mock.Mock(alive=False)
        exporter.export(living)
        exporter.export(dead)

        assert recorder.seen == [living, dead]


class TestFHIRServerExport:
    def test_no_server_exporter_without_a_url(self):
        exporter = Exporter(_config())

        assert not any(isinstance(e, FHIRServerExporter)
                       for e in exporter.patient_exporters)

    def test_a_url_registers_the_server_exporter(self, tmp_path):
        config = _config(exporter__fhir__server_url='https://fhir.example.com/r4')
        config.set('exporter.baseDirectory', str(tmp_path))

        exporter = Exporter(config)

        assert any(isinstance(e, FHIRServerExporter)
                   for e in exporter.patient_exporters)

    def test_it_posts_the_bundle_as_fhir_json(self, tmp_path):
        config = _config()
        config.set('exporter.baseDirectory', str(tmp_path))
        server = FHIRServerExporter(config, 'https://fhir.example.com/r4/')

        person = _one_patient()
        captured = {}

        class _Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def fake_urlopen(request, timeout=None):
            captured['url'] = request.full_url
            captured['body'] = json.loads(request.data.decode('utf-8'))
            captured['headers'] = request.headers
            return _Response()

        with mock.patch('urllib.request.urlopen', fake_urlopen):
            server.export(person, 0)

        assert captured['url'] == 'https://fhir.example.com/r4'
        assert captured['body']['resourceType'] == 'Bundle'
        assert captured['headers']['Content-type'] == 'application/fhir+json'
        assert server.posted == 1
        assert server.failed == 0

    def test_a_failing_server_does_not_stop_the_run(self, tmp_path, caplog):
        """A long generation should not be lost because a server went away."""
        config = _config()
        config.set('exporter.baseDirectory', str(tmp_path))
        server = FHIRServerExporter(config, 'https://fhir.example.com/r4')

        def boom(request, timeout=None):
            raise OSError('connection refused')

        with mock.patch('urllib.request.urlopen', boom), \
                caplog.at_level('ERROR'):
            result = server.export(_one_patient(), 0)

        assert result is None
        assert server.failed == 1
        assert any('could not post' in r.message.lower() for r in caplog.records)


def _one_patient():
    """A generated patient, for the exporter tests."""
    config = _config()
    options = _options()
    return Generator(options, config=config).generate_person(0)
