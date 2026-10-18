"""Tests for the Spain (`es`) locale pack.

The pack is the first in-tree pack that is not the reference one, so these
tests are also the proof that the generic interface is enough: everything
Spanish here - where patients live, who they are, where they are treated, who
pays, how the record is exported - comes from the pack and its data, with no
engine branch on the locale.
"""

import hashlib
import json
import re
from datetime import datetime

import pytest
from click.testing import CliRunner

from synthea import locale as locale_registry
from synthea.engine.generator import Generator, GeneratorOptions
from synthea.export.fhir import FHIRExporter
from synthea.helpers.config import Config
from synthea.locale import es
from synthea.world import identity
from synthea.world.person import Person
from synthea.world.provider import _distance

REFERENCE_DATE = datetime(2020, 1, 1)

#: The cities the pack covers, each with its one hospital.
CITIES = ('Madrid', 'Barcelona', 'Valencia', 'Bilbao', 'Sevilla', 'Málaga',
          'Santiago de Compostela')


def _config(tmp_path=None, export=False, **overrides):
    config = Config()
    config.load()
    config.set('exporter.fhir.export', export)
    config.set('exporter.json.export', False)
    if tmp_path is not None:
        config.set('exporter.baseDirectory', str(tmp_path))
        config.set('exporter.use_uuid_filenames', True)
    for key, value in overrides.items():
        config.set(key.replace('__', '.'), value)
    return config


def _options(count=1, seed=11, min_age=0, max_age=140, **overrides):
    options = GeneratorOptions()
    options.population_size = count
    options.seed = seed
    options.min_age = min_age
    options.max_age = max_age
    options.reference_date = REFERENCE_DATE
    options.locale = 'es'
    for key, value in overrides.items():
        setattr(options, key, value)
    return options


@pytest.fixture(scope='module')
def generator():
    return Generator(_options(count=8, min_age=35, max_age=85),
                     config=_config())


@pytest.fixture(scope='module')
def people(generator):
    return [p for p in (generator.generate_person(i) for i in range(8)) if p]


@pytest.fixture(scope='module')
def bundles(generator, people, tmp_path_factory):
    exporter = FHIRExporter(generator.config,
                            tmp_path_factory.mktemp('es-fhir'), generator.locale)
    return [exporter.create_bundle(person) for person in people]


def _resources(bundle, resource_type):
    return [entry['resource'] for entry in bundle['entry']
            if entry['resource']['resourceType'] == resource_type]


class TestPack:
    def test_the_pack_is_registered(self):
        pack = locale_registry.get('es')

        assert pack.country_code == 'ES'
        assert pack.currency == 'EUR'
        assert pack.language == 'es'
        assert pack.race_categories == ()
        assert pack.export_profile == 'ehds'
        assert pack.produces_claims is False

    def test_every_data_file_it_declares_is_present(self):
        pack = locale_registry.get('es')
        declared = [pack.geography_file, pack.demographics_file,
                    pack.payers_file, pack.plans_file, *pack.providers_files]
        for relative in declared:
            assert pack.data_path(relative) is not None, relative

    def test_every_data_file_has_provenance(self):
        text = (es.RESOURCE_ROOT / 'RESOURCES.md').read_text(encoding='utf-8')
        for path in es.RESOURCE_ROOT.rglob('*.csv'):
            relative = path.relative_to(es.RESOURCE_ROOT).as_posix()
            assert relative in text, f"{relative} has no provenance entry"


class TestWhereTheyLive:
    def test_patients_live_in_the_seven_cities(self, people):
        for person in people:
            assert person.attributes['urban_area'] in CITIES
            assert person.attributes['zip_code']
            assert person.attributes['zip_code'].startswith(
                person.attributes['region_code'])

    def test_the_cities_can_be_narrowed(self):
        generator = Generator(
            _options(count=6, min_age=0, max_age=2),
            config=_config(generate__geography__cities='Bilbao'))
        people = [generator.generate_person(i) for i in range(6)]

        assert {p.attributes['urban_area'] for p in people if p} == {'Bilbao'}

    def test_an_unknown_city_is_a_warning_not_a_silent_fallback(self, caplog):
        with caplog.at_level('WARNING'):
            Generator(_options(),
                      config=_config(generate__geography__cities='Atlantis'))

        assert any('Atlantis' in record.message for record in caplog.records)


class TestCare:
    def test_every_encounter_is_at_the_patients_city_hospital(self, people):
        """One hospital per city, and all of a patient's care is there."""
        for person in people:
            city = person.attributes['urban_area']
            assert person.record.encounters
            for encounter in person.record.encounters:
                assert encounter.provider is not None
                assert encounter.provider.name == f"TietAI Hospital {city}", (
                    encounter.encounter_class, encounter.provider.name)

    def test_that_hospital_is_the_nearest_one(self, generator, people):
        hospitals = list(generator.provider_manager.providers.values())
        assert len(hospitals) == len(CITIES)

        for person in people:
            home = (person.attributes['latitude'], person.attributes['longitude'])
            nearest = min(hospitals, key=lambda h: _distance(home, h.coordinates))
            for encounter in person.record.encounters:
                assert encounter.provider is nearest

    def test_every_hospital_is_fictional(self, generator):
        for hospital in generator.provider_manager.providers.values():
            assert hospital.name.startswith('TietAI Hospital ')
            assert hospital.organization_type == 'hospital'

    def test_hospitals_are_staffed_beyond_the_default_four(self, generator):
        hospital = next(iter(generator.provider_manager.providers.values()))
        assert len(generator.provider_manager._staff(hospital)) > 4

    def test_clinicians_carry_the_packs_identifier(self, generator, bundles):
        for bundle in bundles:
            for practitioner in _resources(bundle, 'Practitioner'):
                identifier = practitioner['identifier'][0]
                assert identifier['system'] == es.SYSTEM_PREFIX + 'colegiado'
                assert identifier['value'].startswith('99')

    def test_everyone_is_covered_by_the_sns(self, people, bundles):
        for person in people:
            history = person.attributes['coverage_history']
            assert history
            assert {c.plan.payer.name for c in history} == {
                'Sistema Nacional de Salud'}

        for bundle in bundles:
            coverages = _resources(bundle, 'Coverage')
            assert coverages
            assert all(c['payor'][0]['display'] == 'Sistema Nacional de Salud'
                       for c in coverages)


class TestExport:
    def test_no_claim_or_explanation_of_benefit(self, bundles):
        for bundle in bundles:
            assert not _resources(bundle, 'Claim')
            assert not _resources(bundle, 'ExplanationOfBenefit')

    def test_money_is_in_euros(self, generator, tmp_path):
        exporter = FHIRExporter(generator.config, tmp_path, generator.locale)
        assert exporter.currency == 'EUR'

    def test_the_address_is_spanish(self, people, bundles):
        for person, bundle in zip(people, bundles):
            address = _resources(bundle, 'Patient')[0]['address'][0]
            assert address['country'] == 'ES'
            assert address['postalCode'] == person.attributes['zip_code']
            assert address['city'] == person.attributes['city']
            assert re.match(r'^(Calle|Avenida|Plaza|Paseo|Camino) de ',
                            address['line'][0])

            for organization in _resources(bundle, 'Organization'):
                for facility_address in organization.get('address', []):
                    assert facility_address['country'] == 'ES'

    def test_no_race_or_ethnicity_anywhere(self, people, bundles):
        for person in people:
            assert 'race' not in person.attributes
            assert 'ethnicity' not in person.attributes

        for bundle in bundles:
            patient = _resources(bundle, 'Patient')[0]
            urls = [ext['url'] for ext in patient.get('extension', [])]
            assert not any('race' in url or 'ethnicity' in url for url in urls)

    def test_the_patient_speaks_spanish(self, bundles):
        for bundle in bundles:
            patient = _resources(bundle, 'Patient')[0]
            coding = patient['communication'][0]['language']['coding'][0]
            assert coding['code'] == 'es'

    def test_the_packs_identifiers_are_exported(self, people, bundles):
        for person, bundle in zip(people, bundles):
            systems = {i.get('system')
                       for i in _resources(bundle, 'Patient')[0]['identifier']}
            assert es.SYSTEM_PREFIX + 'cip' in systems
            national = (es.SYSTEM_PREFIX + 'nie'
                        if person.attributes['foreign_national']
                        else es.SYSTEM_PREFIX + 'dni')
            assert national in systems
            assert 'http://hl7.org/fhir/sid/us-ssn' not in systems

    def test_no_us_core_document_category(self, bundles):
        for bundle in bundles:
            for document in _resources(bundle, 'DocumentReference'):
                assert 'category' not in document

    def test_notes_are_in_spanish_and_never_mention_race(self, people):
        from synthea.world.notes import NOTE_ATTRIBUTE

        notes = [getattr(e, NOTE_ATTRIBUTE, None)
                 for p in people for e in p.record.encounters]
        notes = [note for note in notes if note]
        assert notes
        for note in notes:
            assert '# Enfermedad actual' in note
            opening = note.split('# Enfermedad actual', 1)[1].split('\n#', 1)[0]
            opening = opening.split('Antecedentes:', 1)[0].lower()
            for word in ('white', 'black', 'asian', 'hispanic', 'native',
                         'blanc', 'negr', 'hispan'):
                assert word not in opening, opening

    def test_the_ehds_patient_summary_carries_the_coverage(self, tmp_path):
        Generator(_options(count=2, min_age=30, max_age=60),
                  config=_config(tmp_path, export=True)).run()

        summaries = list((tmp_path / 'fhir' / 'patient-summary').glob('*.json'))
        assert summaries
        for path in summaries:
            bundle = json.loads(path.read_text(encoding='utf-8'))
            assert _resources(bundle, 'Coverage')
            assert 'USD' not in path.read_text(encoding='utf-8')


class TestIdentifiers:
    def _issued(self, count=400):
        pack = locale_registry.get('es')
        values = {'identifier_dni': [], 'identifier_nie': [],
                  'identifier_nuss': [], 'identifier_cip': []}
        for seed in range(count):
            person = Person(seed=seed)
            person.init_health_record()
            person.locale = pack
            person.attributes.update({
                'gender': 'F' if seed % 2 else 'M',
                'birth_date': datetime(1980, 1, 1),
                'age_at_creation': 40,
                'region_code': '28',
            })
            identity.assign_identity(person, pack)
            for key in values:
                if key in person.attributes:
                    values[key].append(person.attributes[key])
        return values

    def test_dni_check_letters_are_always_invalid(self):
        dnis = self._issued()['identifier_dni']
        assert len(dnis) > 100
        for dni in dnis:
            assert re.fullmatch(r'\d{8}[A-Z]', dni), dni
            assert dni[-1] in es.DNI_LETTERS
            assert dni[-1] != es.dni_letter(int(dni[:8])), dni

    def test_nie_check_letters_are_always_invalid(self):
        nies = self._issued()['identifier_nie']
        assert nies, "some residents are foreign nationals"
        for nie in nies:
            assert re.fullmatch(r'[XYZ]\d{7}[A-Z]', nie), nie
            number = int(str(es.NIE_PREFIXES[nie[0]]) + nie[1:8])
            assert nie[-1] != es.dni_letter(number), nie

    def test_nationals_have_a_dni_and_foreigners_an_nie_never_both(self):
        pack = locale_registry.get('es')
        for seed in range(200):
            person = Person(seed=seed)
            person.init_health_record()
            person.attributes.update({'gender': 'M', 'age_at_creation': 30,
                                      'region_code': '08'})
            identity.assign_identity(person, pack)
            has_dni = 'identifier_dni' in person.attributes
            has_nie = 'identifier_nie' in person.attributes
            assert has_dni != has_nie

    def test_a_child_has_no_dni_yet(self):
        pack = locale_registry.get('es')
        for seed in range(50):
            person = Person(seed=seed)
            person.init_health_record()
            person.attributes.update({'gender': 'F', 'age_at_creation': 9,
                                      'region_code': '28'})
            identity.assign_identity(person, pack)
            assert 'identifier_dni' not in person.attributes
            assert 'identifier_nuss' not in person.attributes

    def test_nuss_control_digits_are_always_invalid(self):
        for nuss in self._issued()['identifier_nuss']:
            assert re.fullmatch(r'\d{12}', nuss), nuss
            province, number, control = int(nuss[:2]), int(nuss[2:10]), int(nuss[10:])
            assert control != es.nuss_control(province, number), nuss

    def test_health_card_codes_carry_the_synthetic_prefix(self):
        for code in self._issued(100)['identifier_cip']:
            assert code.startswith(es.CIP_PREFIX)

    def test_two_surnames(self):
        pack = locale_registry.get('es')
        person = Person(seed=5)
        person.init_health_record()
        person.attributes.update({'gender': 'F', 'age_at_creation': 30,
                                  'region_code': '41'})
        identity.assign_identity(person, pack)

        assert len(person.attributes['last_name'].split(' ')) >= 2

    def test_phone_numbers_are_in_the_unattributed_30x_segment(self):
        import random

        rand = random.Random(1)
        for _ in range(100):
            assert re.fullmatch(r'\+34 30\d \d{3} \d{3}', es.fictional_phone(rand))


class TestDeterminism:
    @staticmethod
    def _digests(root):
        return {
            path.relative_to(root).as_posix():
                hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob('*.json'))
        }

    def test_two_runs_with_the_same_seed_are_identical(self, tmp_path):
        first, second = tmp_path / 'a', tmp_path / 'b'
        for root in (first, second):
            Generator(_options(count=3, seed=42, min_age=20, max_age=70),
                      config=_config(root, export=True)).run()

        digests = self._digests(first)
        assert digests
        assert digests == self._digests(second)


class TestCalibration:
    def test_the_packs_calibration_applies(self):
        generator = Generator(_options(min_age=0, max_age=1), config=_config())
        person = generator.generate_person(0)

        assert person.attributes['calibration.reproduction.exposure'] == \
            es.CALIBRATION['calibration.reproduction.exposure']


class TestCommandLine:
    def test_locale_es_from_the_command_line(self, tmp_path):
        from synthea.cli import cli

        result = CliRunner().invoke(cli, [
            '-p', '2', '-s', '3', '-a', '20-40', '--locale', 'es',
            '-o', str(tmp_path),
            '--log-level', 'warning'])

        assert result.exit_code == 0, result.output
        patients = [json.loads(path.read_text(encoding='utf-8'))
                    for path in (tmp_path / 'fhir').rglob('*.json')]
        assert patients
        for bundle in patients:
            for patient in _resources(bundle, 'Patient'):
                assert patient['address'][0]['country'] == 'ES'
