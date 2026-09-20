"""Tests for the locale pack architecture.

The generator hard-coded United States assumptions throughout, so using it
anywhere else meant forking it. These tests cover the two properties that make
a pack a seam rather than a decoration:

1. Selecting `us` changes nothing — the reference pack reproduces the old
   behaviour exactly, including the order of draws from the patient's random
   generator.
2. Selecting a different pack really does change identity, identifiers and
   conventions, with no engine change.
"""

import sys
from datetime import datetime
from pathlib import Path
from unittest import mock

import pytest

from synthea import locale as locale_registry
from synthea.engine.generator import Generator, GeneratorOptions
from synthea.helpers.config import Config
from synthea.locale.base import IdentifierScheme, LocalePack
from synthea.world import identity
from synthea.world.person import Person

sys.path.insert(0, str(Path(__file__).parent / 'fixtures'))
from locale_test import PACK as TEST_PACK  # noqa: E402

REFERENCE_DATE = datetime(2020, 1, 1)


@pytest.fixture
def test_pack():
    """The fixture pack, registered for the duration of one test."""
    locale_registry.register(TEST_PACK)
    yield TEST_PACK
    locale_registry._registry.pop('test', None)


def _person(seed=7, **attributes):
    person = Person(seed=seed)
    person.init_health_record()
    person.attributes.setdefault('gender', 'F')
    person.attributes.setdefault('ethnicity', 'non_hispanic')
    person.attributes.setdefault('birth_date', datetime(1980, 1, 1))
    person.attributes.setdefault('age_at_creation', 40)
    person.attributes.update(attributes)
    return person


class TestRegistry:
    def test_the_us_pack_is_always_available(self):
        assert locale_registry.get('us').country_code == 'US'

    def test_the_default_is_the_us(self):
        assert locale_registry.get().code == locale_registry.DEFAULT_LOCALE

    def test_codes_are_case_insensitive(self):
        assert locale_registry.get('US').code == 'us'

    def test_a_regional_code_falls_back_to_its_language(self, test_pack):
        """`test-XX` should find `test` when no regional pack is installed."""
        assert locale_registry.get('test-XX').code == 'test'

    def test_an_unknown_locale_is_an_error_not_a_silent_fallback(self):
        """Quietly generating Americans for someone who asked for Spain is
        the kind of wrong that is only noticed much later."""
        with pytest.raises(LookupError) as error:
            locale_registry.get('atlantis')

        assert 'atlantis' in str(error.value)
        assert 'us' in str(error.value)

    def test_available_lists_packs(self, test_pack):
        codes = [code for code, _ in locale_registry.available()]

        assert 'us' in codes
        assert 'test' in codes

    def test_a_pack_describes_itself(self):
        described = locale_registry.get('us').describe()

        assert described['code'] == 'us'
        assert described['currency'] == 'USD'
        assert 'identifier_ssn' in described['identifiers']


class TestEntryPointDiscovery:
    def test_a_broken_pack_does_not_stop_the_generator_starting(self, caplog):
        """A third party's bug must not make this package unusable."""
        broken = mock.Mock()
        broken.name = 'broken'
        broken.load.side_effect = ImportError('no such module')

        locale_registry._discovered = False
        with mock.patch('importlib.metadata.entry_points', return_value=[broken]), \
                caplog.at_level('WARNING'):
            locale_registry._discover()

        assert locale_registry.get('us') is not None
        assert any('broken' in r.message for r in caplog.records)

    def test_something_that_is_not_a_pack_is_refused(self, caplog):
        point = mock.Mock()
        point.name = 'notapack'
        point.load.return_value = {'code': 'nope'}

        locale_registry._discovered = False
        with mock.patch('importlib.metadata.entry_points', return_value=[point]), \
                caplog.at_level('WARNING'):
            locale_registry._discover()

        assert 'notapack' not in dict(locale_registry.available())

    def test_a_callable_entry_point_is_called(self):
        pack = LocalePack(code='callable-test', name='Callable', country_code='CT')
        point = mock.Mock()
        point.name = 'callable-test'
        point.load.return_value = lambda: pack

        locale_registry._discovered = False
        with mock.patch('importlib.metadata.entry_points', return_value=[point]):
            locale_registry._discover()

        assert locale_registry.get('callable-test') is pack
        locale_registry._registry.pop('callable-test', None)


class TestUSPack:
    """The reference pack must reproduce what the generator did before."""

    def test_identity_still_looks_american(self):
        person = _person()
        identity.assign_identity(person, locale_registry.get('us'))

        assert person.attributes['first_name']
        assert person.attributes['telephone'].startswith('555-')
        assert person.attributes['email'].endswith('@example.com')

    def test_the_ssn_uses_the_never_issued_area(self):
        """999 has never been issued, so it cannot collide with a real one."""
        person = _person()
        identity.assign_identity(person, locale_registry.get('us'))

        assert person.attributes['identifier_ssn'].startswith('999-')

    def test_a_child_gets_no_driving_licence(self):
        person = _person(age_at_creation=10)
        identity.assign_identity(person, locale_registry.get('us'))

        assert 'identifier_drivers' not in person.attributes

    def test_an_adult_does(self):
        person = _person(age_at_creation=40)
        identity.assign_identity(person, locale_registry.get('us'))

        assert person.attributes['identifier_drivers'].startswith('S')

    def test_identity_is_reproducible_from_the_seed(self):
        def built():
            person = _person(seed=99)
            identity.assign_identity(person, locale_registry.get('us'))
            return person.attributes

        assert built() == built()


class TestPluggability:
    """Selecting another pack must change the output, with no engine change."""

    def test_names_follow_the_pack_not_the_engine(self, test_pack):
        person = _person()
        identity.assign_identity(person, test_pack)

        assert person.attributes['first_name'] in (
            'Ada', 'Grace', 'Alan', 'Edsger')
        assert ' ' in person.attributes['last_name'], "two surnames expected"

    def test_identifiers_follow_the_pack(self, test_pack):
        person = _person()
        identity.assign_identity(person, test_pack)

        assert 'identifier_ssn' not in person.attributes
        assert person.attributes['identifier_national'].startswith('TST')
        assert person.attributes['identifier_national'].endswith('ZZ')

    def test_contact_details_follow_the_pack(self, test_pack):
        person = _person()
        identity.assign_identity(person, test_pack)

        assert person.attributes['telephone'].startswith('+99 ')
        assert person.attributes['email'].endswith('@example.org')

    def test_address_and_postal_code_follow_the_pack(self, test_pack):
        person = _person()
        identity.assign_identity(person, test_pack)

        assert person.attributes['address'].startswith('Via Fixtura')
        assert len(person.attributes['postal_code']) == 4

    def test_a_locale_may_record_no_race_at_all(self, test_pack):
        """Most countries do not. An empty list must mean 'omit', not 'other'."""
        assert test_pack.race_categories == ()
        assert locale_registry.get('us').race_categories

    def test_conventions_follow_the_pack(self, test_pack):
        assert test_pack.currency == 'EUR'
        assert test_pack.temperature_unit == 'Cel'
        assert test_pack.export_profile == 'ips'

        us = locale_registry.get('us')
        assert us.currency == 'USD'
        assert us.temperature_unit == '[degF]'
        assert us.export_profile == 'us-core'

    def test_marital_statuses_come_from_the_pack(self, test_pack):
        person = _person()
        identity.assign_marital_status(person, 40, test_pack)

        assert person.attributes['marital_status']['code'] in ('M', 'S')


class TestIdentifierRules:
    def test_probability_gates_an_identifier(self):
        """A passport is not universal."""
        scheme = IdentifierScheme(
            key='k', type_code='PPN', type_display='Passport',
            system='urn:test', format=lambda p: 'VALUE', probability=0.0)
        pack = LocalePack(code='p', name='P', country_code='PP',
                          identifiers=(scheme,))

        assert pack.identifier_for(_person(), scheme) is None

    def test_a_certain_identifier_is_always_issued(self):
        scheme = IdentifierScheme(
            key='k', type_code='NI', type_display='National',
            system='urn:test', format=lambda p: 'VALUE')
        pack = LocalePack(code='p', name='P', country_code='PP',
                          identifiers=(scheme,))

        assert pack.identifier_for(_person(), scheme) == 'VALUE'

    def test_an_unknown_age_fails_an_age_limit(self):
        """Better to omit an identifier than to issue one to a newborn."""
        scheme = IdentifierScheme(
            key='k', type_code='DL', type_display='Licence',
            system='urn:test', format=lambda p: 'VALUE', minimum_age=16)
        pack = LocalePack(code='p', name='P', country_code='PP',
                          identifiers=(scheme,))

        person = _person()
        person.attributes.pop('age_at_creation', None)

        assert pack.identifier_for(person, scheme) is None


class TestGeneratorIntegration:
    def _config(self, **overrides):
        config = Config()
        config.load()
        config.set('exporter.fhir.export', False)
        config.set('exporter.json.export', False)
        for key, value in overrides.items():
            config.set(key, value)
        return config

    def _options(self, **overrides):
        options = GeneratorOptions()
        options.population_size = 1
        options.seed = 3
        options.reference_date = REFERENCE_DATE
        for key, value in overrides.items():
            setattr(options, key, value)
        return options

    def test_the_generator_defaults_to_the_us(self):
        generator = Generator(self._options(), config=self._config())

        assert generator.locale.code == 'us'

    def test_the_locale_comes_from_config(self, test_pack):
        generator = Generator(self._options(),
                              config=self._config(**{'generate.locale': 'test'}))

        assert generator.locale.code == 'test'

    def test_the_cli_option_wins_over_config(self, test_pack):
        generator = Generator(self._options(locale='us'),
                              config=self._config(**{'generate.locale': 'test'}))

        assert generator.locale.code == 'us'

    def test_an_unknown_locale_fails_at_startup(self):
        """Not after the first hour of a long run."""
        with pytest.raises(LookupError):
            Generator(self._options(locale='atlantis'), config=self._config())

    def test_generated_patients_carry_the_pack(self, test_pack):
        generator = Generator(self._options(),
                              config=self._config(**{'generate.locale': 'test'}))
        person = generator.generate_person(0)

        assert person is not None
        assert person.locale.code == 'test'
        assert person.attributes['identifier_national'].startswith('TST')


class TestReferencePackDeterminism:
    """`--locale us` must reproduce the pre-refactor population exactly.

    Moving identity behind the locale interface changed which function draws
    from `person.random`, but must not change the order of the draws. If it
    did, every seeded dataset anyone had generated would silently stop
    reproducing — the kind of break that is invisible until someone tries to
    regenerate a study cohort.

    The digests below were taken from `dev` immediately before the refactor.
    """

    #: sha256 of each patient's bundle, seed 42, ages 20-70, 2020-01-01.
    EXPECTED = [
        '4d1029db05b53bfc3b8e42a284d974be5764cb4fd28ab0793436a2b2cd7eb5c7',
        '640c4ae5204107ab6b73e8ab3178624411737b8f407695777420aa0d1f2003b6',
        'ae2e5bd929e6dfa4b5a5b1a0b36092b0f8cf74e370d25668be0fe4ac20a09fc1',
    ]

    def test_the_us_pack_reproduces_the_pre_refactor_export(self, tmp_path):
        import hashlib
        import json

        config = Config()
        config.load()
        config.set('exporter.baseDirectory', str(tmp_path))
        config.set('exporter.fhir.export', True)
        config.set('exporter.use_uuid_filenames', True)

        options = GeneratorOptions()
        options.population_size = 3
        options.seed = 42
        options.min_age = 20
        options.max_age = 70
        options.reference_date = REFERENCE_DATE

        Generator(options, config=config).run()

        digests = [
            hashlib.sha256(
                json.dumps(json.loads(path.read_text(encoding='utf-8')),
                           sort_keys=True).encode('utf-8')).hexdigest()
            for path in sorted((tmp_path / 'fhir').glob('*.json'))
        ]

        assert digests == self.EXPECTED, (
            "The US locale pack changed generated output. Either the draw "
            "order moved, or the export changed for an unrelated reason."
        )
