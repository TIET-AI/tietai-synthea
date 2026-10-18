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
    #:
    #: Moved once, in 1.5.0, when lab observations gained referenceRange and
    #: interpretation and the red-cell indices started being derived rather
    #: than drawn independently (#113). The change was checked before these
    #: were updated: same 1360 resources with the same UUIDs, only
    #: Observations altered - 298 gained the two new elements and 15 values
    #: were recomputed. Nothing else in the record moved.
    #:
    #: Moved again when the engine was brought in line with upstream Synthea
    #: (EncounterEnd, CallSubmodule, transitions, PriorState, nil operators,
    #: whole-year lookup ages, Delay timing, face-value distributions), the
    #: upstream vital signs, cardiovascular risk and smoking were ported, and
    #: population rates became calibration.* settings. Patients now develop
    #: and are diagnosed with the diseases their modules describe; see the
    #: CHANGELOG. Checked by two runs agreeing.
    #:
    #: Update these only when generated output is *meant* to change, and say
    #: in the changelog that it did.
    EXPECTED = [
        '624166a9b5d44599571163c442d2994d22a184fc0a09a635d9fdaf2ea92b3d7a',
        '0ba4b347f9416a309c3f9a13a753ab62c2ccad38cfc9b8be0273afc68eaf0271',
        '9630fbbcc531268a3aea9024d6193eaa21c7f78eee42a7696e0a8b8df60ac0fa',
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


class TestCalibrationPrecedence:
    """bundled synthea.properties < locale pack < the user's own settings."""

    KEY = 'calibration.reproduction.exposure'

    @pytest.fixture
    def calibrated_pack(self):
        import dataclasses

        pack = dataclasses.replace(TEST_PACK, code='calibrated',
                                   calibration={self.KEY: 0.123})
        locale_registry.register(pack)
        yield pack
        locale_registry._registry.pop('calibrated', None)

    def _generator(self, config, locale):
        options = GeneratorOptions()
        options.population_size = 1
        options.seed = 1
        options.reference_date = REFERENCE_DATE
        options.locale = locale
        config.set('exporter.fhir.export', False)
        config.set('exporter.json.export', False)
        return Generator(options, config=config)

    def test_the_bundled_value_applies_without_a_pack_value(self):
        config = Config()
        config.load()
        self._generator(config, 'us')

        assert config.get(self.KEY) == 0.3

    def test_the_pack_overrides_the_bundled_value(self, calibrated_pack):
        config = Config()
        config.load()
        generator = self._generator(config, 'calibrated')

        assert config.get(self.KEY) == 0.123
        person = generator.generate_person(0)
        assert person.attributes[self.KEY] == 0.123

    def test_the_users_file_overrides_the_pack(self, calibrated_pack, tmp_path):
        user = tmp_path / 'mine.properties'
        user.write_text(f'{self.KEY} = 0.456\n', encoding='utf-8')
        config = Config()
        config.load(str(user))
        self._generator(config, 'calibrated')

        assert config.get(self.KEY) == 0.456

    def test_a_value_set_in_code_overrides_the_pack(self, calibrated_pack):
        config = Config()
        config.load()
        config.set(self.KEY, 0.789)
        self._generator(config, 'calibrated')

        assert config.get(self.KEY) == 0.789


class TestPackData:
    """A pack's data replaces the bundled US data; it never falls back to it."""

    def test_a_missing_pack_file_is_absent_not_american(self, tmp_path, caplog):
        pack = LocalePack(code='rooted', name='Rooted', country_code='RT',
                          resource_root=str(tmp_path))
        with caplog.at_level('WARNING'):
            assert pack.data_path('payers/insurance_companies.csv') is None
        assert any('not in' in r.message for r in caplog.records)

    def test_without_a_root_the_bundled_file_is_found(self):
        pack = LocalePack(code='bare', name='Bare', country_code='BR')
        assert pack.data_path('payers/insurance_companies.csv').exists()

    def test_pack_facilities_replace_the_bundled_directory(self, tmp_path):
        from synthea.world.provider import ProviderManager

        (tmp_path / 'clinics.csv').write_text(
            'id,name,lat,lon,facility_type,catchment,clinicians\n'
            'a,Clinic A,10.0,10.0,primary_care,North,7\n'
            'b,Hospital B,10.5,10.5,hospital,North|South,\n',
            encoding='utf-8')
        pack = LocalePack(code='fac', name='Fac', country_code='FC',
                          resource_root=str(tmp_path),
                          providers_files=('clinics.csv',))
        manager = ProviderManager(seed=1, pack=pack, clinicians_per_facility=3)
        manager.load()

        assert set(manager.providers) == {'primary_care-a', 'hospital-b'}
        clinic = manager.providers['primary_care-a']
        hospital = manager.providers['hospital-b']
        assert len(manager._staff(clinic)) == 7
        assert len(manager._staff(hospital)) == 3
        assert hospital.catchment == ('North', 'South')

        # A skilled nursing stay has no nursing home or long-term facility
        # here, so it falls back along its preferences to the hospital.
        assert manager.find_provider('snf', (10.0, 10.0), None,
                                     area='South') is hospital

    def test_a_pack_practitioner_identifier_replaces_the_npi(self, tmp_path):
        from synthea.locale.base import PractitionerIdentifierScheme
        from synthea.world.provider import ProviderManager

        (tmp_path / 'h.csv').write_text(
            'id,name,lat,lon\nh,Hospital H,1.0,1.0\n', encoding='utf-8')
        pack = LocalePack(
            code='prn', name='Prn', country_code='PR',
            resource_root=str(tmp_path),
            providers_files={'h.csv': 'hospital'},
            clinician_names=lambda rand: ('Ana', 'Prueba'),
            practitioner_identifier=PractitionerIdentifierScheme(
                system='urn:test:prn', format=lambda rand: 'P-1'))
        manager = ProviderManager(seed=1, pack=pack)
        manager.load()
        staff = manager._staff(manager.providers['hospital-h'])

        assert {(c.first_name, c.last_name) for c in staff} == {('Ana', 'Prueba')}
        assert {(c.identifier_system, c.identifier) for c in staff} == {
            ('urn:test:prn', 'P-1')}
        assert staff[0].npi is None


class TestPackGeography:
    def _geography(self, tmp_path):
        from synthea.world.location import PackGeography

        path = tmp_path / 'geo.csv'
        path.write_text(
            'region,region_code,city,municipality,municipality_code,'
            'postal_codes,lat,lon,population\n'
            'Norte,01,Alfa,Alfa,01001,01001|01002,40.0,-3.0,1000\n'
            'Norte,01,Alfa,Beta,01002,01010,40.1,-3.1,500\n'
            'Sur,02,Gamma,Gamma,02001,02001,37.0,-5.0,2000\n',
            encoding='utf-8')
        return PackGeography.from_csv(path)

    def test_a_place_has_a_postal_code_and_coordinates_near_it(self, tmp_path):
        import random

        geography = self._geography(tmp_path)
        rand = random.Random(3)
        for _ in range(50):
            place = geography.random_place(rand)
            assert place['zip_code'].startswith(place['region_code'])
            assert abs(place['latitude'] - 40) < 0.2 or \
                abs(place['latitude'] - 37) < 0.2

    def test_cities_and_regions_narrow_the_selection(self, tmp_path):
        import random

        geography = self._geography(tmp_path)
        geography.restrict(cities=['alfa'])
        rand = random.Random(1)
        assert {geography.random_place(rand)['urban_area']
                for _ in range(30)} == {'Alfa'}

        geography = self._geography(tmp_path)
        geography.restrict(regions=['02'])
        assert {geography.random_place(rand)['state']
                for _ in range(10)} == {'Sur'}

    def test_an_unknown_name_warns_and_keeps_everything(self, tmp_path, caplog):
        geography = self._geography(tmp_path)
        with caplog.at_level('WARNING'):
            unknown = geography.restrict(cities=['Atlantis'])

        assert unknown == ['Atlantis']
        assert len(geography.selected) == 3
        assert any('Atlantis' in r.message for r in caplog.records)

    def test_an_unknown_us_state_warns(self, caplog):
        from synthea.world.location import Location

        with caplog.at_level('WARNING'):
            Location().set_state('Atlantis')
        assert any('Atlantis' in r.message for r in caplog.records)


class TestCoveragePolicy:
    def test_universal_coverage_covers_everyone_from_birth(self, tmp_path):
        from synthea.world.payer import PayerManager, UniversalCoverage

        (tmp_path / 'payers.csv').write_text(
            'Id,Name,Ownership,States Covered\nN,National Service,Government,*\n',
            encoding='utf-8')
        (tmp_path / 'plans.csv').write_text(
            'Payer Id,Plan Id,Name,Eligibility Policy,Default Coinsurance\n'
            'N,N1,Public cover,NATIONAL,1.0\n', encoding='utf-8')
        pack = LocalePack(code='nhs', name='NHS', country_code='NH',
                          resource_root=str(tmp_path),
                          payers_file='payers.csv', plans_file='plans.csv',
                          coverage_policy=UniversalCoverage('NATIONAL'))
        manager = PayerManager(seed=1)
        manager.load(pack)

        for age in (0, 30, 70):
            person = _person(socioeconomic_status='low')
            coverage = manager.coverage_for(person, age, REFERENCE_DATE)
            assert coverage.kind == 'public'
            assert coverage.plan.payer.name == 'National Service'

    def test_the_default_policy_is_the_united_states(self):
        from synthea.world.payer import PayerManager, UnitedStatesCoverage

        assert isinstance(PayerManager().policy, UnitedStatesCoverage)


class TestCommandLineLocale:
    def test_the_locale_option_reaches_the_generator(self, tmp_path):
        """`--locale` was accepted and never applied."""
        from click.testing import CliRunner

        from synthea.cli import cli

        with mock.patch('synthea.cli.Generator') as generator:
            CliRunner().invoke(cli, ['-p', '1', '--locale', 'es',
                                     '-o', str(tmp_path)])

        options = generator.call_args[0][0]
        assert options.locale == 'es'
