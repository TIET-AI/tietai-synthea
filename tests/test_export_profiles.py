"""Tests for export profiles: US Core, IPS, EHDS (#47).

Profiling used to be a single boolean, `exporter.fhir.use_us_core_ig`. That is
fine while the only audience is American and useless the moment it is not.

The properties worth holding onto:

1. US Core output is unchanged — this is the default and every existing user
   depends on it.
2. US-specific extensions never leak into an international profile. Emitting
   OMB race categories for a country that does not record race is inventing
   data.
3. An IPS document states "no known allergies" rather than omitting the
   section. An absent section means "we did not look", which is a different
   and more dangerous thing to tell a clinician.
4. Every document stands alone: no reference points outside its own bundle.
"""

import json
from datetime import datetime

import pytest

from synthea.engine.generator import Generator, GeneratorOptions
from synthea.export import profiles, validation
from synthea.export.fhir import FHIRExporter
from synthea.helpers.config import Config
from synthea.locale.base import LocalePack
from synthea.world.health_record import Code, EncounterClass
from synthea.world.person import Person

REFERENCE_DATE = datetime(2020, 1, 1)
VISIT = datetime(2015, 6, 1)


def _config(**overrides):
    config = Config()
    config.load()
    for key, value in overrides.items():
        config.set(key, value)
    return config


@pytest.fixture
def person():
    person = Person(seed=3)
    person.init_health_record()
    person.attributes.update({
        'gender': 'F',
        'birth_date': datetime(1975, 6, 1),
        'first_name': 'Ada',
        'last_name': 'Lovelace',
        'race': 'white',
        'ethnicity': 'non_hispanic',
    })
    encounter = person.record.encounter_start(VISIT, EncounterClass.AMBULATORY)
    person.record.condition_start(
        VISIT, Code(system='SNOMED-CT', code='73211009', display='Diabetes'))
    person.record.encounter_end(encounter, VISIT)
    return person


def _exporter(tmp_path, profile=None, locale=None):
    overrides = {'exporter.baseDirectory': str(tmp_path)}
    if profile:
        overrides['exporter.fhir.profile'] = profile
    return FHIRExporter(_config(**overrides), tmp_path, locale)


class TestSelection:
    def test_us_core_is_the_default(self):
        assert profiles.resolve(_config()).code == 'us-core'

    def test_an_explicit_profile_wins(self):
        config = _config(**{'exporter.fhir.profile': 'ips'})

        assert profiles.resolve(config).code == 'ips'

    def test_the_locale_default_is_used_when_nothing_is_set(self):
        """A Spanish locale should produce IPS without being asked."""
        pack = LocalePack(code='xx', name='X', country_code='XX',
                          export_profile='ips')

        assert profiles.resolve(_config(), pack).code == 'ips'

    def test_an_explicit_profile_beats_the_locale(self):
        """An operator who asks must win over a default."""
        pack = LocalePack(code='xx', name='X', country_code='XX',
                          export_profile='ips')
        config = _config(**{'exporter.fhir.profile': 'us-core'})

        assert profiles.resolve(config, pack).code == 'us-core'

    def test_the_old_boolean_still_means_no_profile(self):
        """Every existing config file says this; it must keep working."""
        config = _config(**{'exporter.fhir.use_us_core_ig': False})

        assert profiles.resolve(config).code == 'none'

    def test_an_unknown_profile_warns_and_falls_back(self, caplog):
        """A typo should not lose a long generation; the bundle is still valid."""
        with caplog.at_level('WARNING'):
            profile = profiles.get('not-a-profile')

        assert profile.code == 'us-core'
        assert any('not-a-profile' in r.message for r in caplog.records)

    def test_every_profile_is_listed(self):
        codes = {profile.code for profile in profiles.available()}

        assert codes == {'us-core', 'ips', 'ehds', 'none'}


class TestUSCore:
    def test_resources_carry_us_core_profiles(self, tmp_path, person):
        bundle = _exporter(tmp_path, 'us-core').create_bundle(person)

        patient = next(e['resource'] for e in bundle['entry']
                       if e['resource']['resourceType'] == 'Patient')
        assert any('us-core-patient' in uri
                   for uri in patient['meta']['profile'])

    def test_race_and_ethnicity_extensions_are_present(self, tmp_path, person):
        bundle = _exporter(tmp_path, 'us-core').create_bundle(person)

        patient = next(e['resource'] for e in bundle['entry']
                       if e['resource']['resourceType'] == 'Patient')
        urls = {ext['url'] for ext in patient.get('extension', [])}

        assert any('us-core-race' in url for url in urls)

    def test_it_is_not_a_document(self, tmp_path, person):
        bundle = _exporter(tmp_path, 'us-core').create_bundle(person)

        assert bundle['type'] in ('transaction', 'collection')
        assert not [e for e in bundle['entry']
                    if e['resource']['resourceType'] == 'Composition']


class TestNoProfile:
    def test_nothing_claims_a_profile(self, tmp_path, person):
        bundle = _exporter(tmp_path, 'none').create_bundle(person)

        claimed = [uri for e in bundle['entry']
                   for uri in e['resource'].get('meta', {}).get('profile', [])]

        assert claimed == []

    def test_no_us_extensions(self, tmp_path, person):
        bundle = _exporter(tmp_path, 'none').create_bundle(person)

        patient = next(e['resource'] for e in bundle['entry']
                       if e['resource']['resourceType'] == 'Patient')

        assert not patient.get('extension')


class TestIPS:
    def test_the_bundle_is_a_document(self, tmp_path, person):
        bundle = _exporter(tmp_path, 'ips').create_bundle(person)

        assert bundle['type'] == 'document'

    def test_the_composition_comes_first(self, tmp_path, person):
        """FHIR requires it, and a reader treats entry[0] as the index."""
        bundle = _exporter(tmp_path, 'ips').create_bundle(person)

        assert bundle['entry'][0]['resource']['resourceType'] == 'Composition'

    def test_the_three_required_sections_are_present(self, tmp_path, person):
        bundle = _exporter(tmp_path, 'ips').create_bundle(person)
        composition = bundle['entry'][0]['resource']
        titles = {section['title'] for section in composition['section']}

        assert {'Problems', 'Medication Summary',
                'Allergies and Intolerances'} <= titles

    def test_an_empty_required_section_says_no_known_rather_than_vanishing(
            self, tmp_path, person):
        """"No known allergies" is a clinical statement. An absent section
        means "we did not look", which is worse than saying nothing."""
        assert not person.record.allergies, "fixture should have no allergies"

        bundle = _exporter(tmp_path, 'ips').create_bundle(person)
        composition = bundle['entry'][0]['resource']

        allergies = next(s for s in composition['section']
                         if s['title'] == 'Allergies and Intolerances')

        assert 'entry' not in allergies
        assert allergies['emptyReason']['coding'][0]['code'] == 'nilknown'
        assert 'no known' in allergies['text']['div'].lower()

    def test_an_empty_optional_section_is_omitted(self, tmp_path, person):
        """Optional sections are not padded out."""
        bundle = _exporter(tmp_path, 'ips').create_bundle(person)
        composition = bundle['entry'][0]['resource']
        titles = {section['title'] for section in composition['section']}

        assert 'Medical Devices' not in titles

    def test_sections_reference_resources_in_the_bundle(self, tmp_path, person):
        bundle = _exporter(tmp_path, 'ips').create_bundle(person)
        ids = {e['fullUrl'] for e in bundle['entry']}
        composition = bundle['entry'][0]['resource']

        for section in composition['section']:
            for entry in section.get('entry', []):
                assert entry['reference'] in ids

    def test_no_us_core_extensions_leak_in(self, tmp_path, person):
        """The whole point of a non-US profile."""
        bundle = _exporter(tmp_path, 'ips').create_bundle(person)

        leaked = [
            ext for e in bundle['entry']
            for ext in e['resource'].get('extension', [])
            if 'us-core' in str(ext.get('url', ''))
        ]

        assert leaked == []

    def test_resources_carry_ips_profiles(self, tmp_path, person):
        bundle = _exporter(tmp_path, 'ips').create_bundle(person)
        claimed = {uri for e in bundle['entry']
                   for uri in e['resource'].get('meta', {}).get('profile', [])}

        assert any('uv-ips' in uri for uri in claimed)
        assert not any('us-core' in uri for uri in claimed)


class TestLocaleInteraction:
    def test_a_locale_that_records_no_race_gets_no_race_extension(
            self, tmp_path, person):
        """Most countries do not record race. Mapping a population onto OMB
        categories would be inventing data that looks authoritative."""
        pack = LocalePack(code='xx', name='X', country_code='XX',
                          race_categories=(), export_profile='us-core')

        bundle = _exporter(tmp_path, 'us-core', pack).create_bundle(person)
        patient = next(e['resource'] for e in bundle['entry']
                       if e['resource']['resourceType'] == 'Patient')

        assert not patient.get('extension')

    def test_a_locale_that_does_record_race_keeps_it(self, tmp_path, person):
        pack = LocalePack(code='xx', name='X', country_code='XX',
                          race_categories=('white', 'black'),
                          export_profile='us-core')

        bundle = _exporter(tmp_path, 'us-core', pack).create_bundle(person)
        patient = next(e['resource'] for e in bundle['entry']
                       if e['resource']['resourceType'] == 'Patient')

        assert patient.get('extension')


@pytest.fixture(scope='module')
def ehds_run(tmp_path_factory):
    out = tmp_path_factory.mktemp('ehds')

    config = Config()
    config.load()
    config.set('exporter.baseDirectory', str(out))
    config.set('exporter.fhir.export', True)
    config.set('exporter.fhir.profile', 'ehds')
    config.set('exporter.use_uuid_filenames', True)

    options = GeneratorOptions()
    options.population_size = 2
    options.seed = 11
    options.min_age = 30
    options.max_age = 70
    options.reference_date = REFERENCE_DATE

    Generator(options, config=config).run()

    files = sorted((out / 'fhir').rglob('*.json'))
    return files, [json.loads(p.read_text(encoding='utf-8')) for p in files]


class TestEHDS:
    def test_each_category_is_its_own_document(self, ehds_run):
        """A consumer asks for a category, not for "a patient"."""
        files, bundles = ehds_run
        categories = {path.parent.name for path in files}

        assert len(files) > 2, "more documents than patients"
        assert 'patient-summary' in categories
        assert 'eprescription' in categories

    def test_every_document_is_a_document(self, ehds_run):
        _, bundles = ehds_run

        assert all(bundle['type'] == 'document' for bundle in bundles)

    def test_every_document_leads_with_its_composition(self, ehds_run):
        _, bundles = ehds_run

        for bundle in bundles:
            assert bundle['entry'][0]['resource']['resourceType'] == 'Composition'

    def test_every_composition_has_sections(self, ehds_run):
        """Regression: category sections were built from the profile's IPS
        section list and then filtered away, leaving every document empty."""
        _, bundles = ehds_run

        for bundle in bundles:
            composition = bundle['entry'][0]['resource']
            assert composition.get('section'), composition.get('title')

    def test_the_sections_match_the_category(self, ehds_run):
        files, bundles = ehds_run

        expected = {
            'eprescription': {'Prescriptions'},
            'laboratory-result': {'Results'},
            'discharge-report': {'Hospital Course'},
        }

        for path, bundle in zip(files, bundles):
            category = path.parent.name
            if category not in expected:
                continue
            titles = {s['title']
                      for s in bundle['entry'][0]['resource']['section']}
            assert titles == expected[category], category

    def test_an_empty_category_produces_no_document(self, ehds_run):
        """An empty discharge report is not a document, it is noise."""
        files, bundles = ehds_run

        for bundle in bundles:
            clinical = [e for e in bundle['entry']
                        if e['resource']['resourceType']
                        not in ('Composition', 'Patient')]
            assert clinical, "a document with nothing in it was written"

    def test_each_document_stands_alone(self, ehds_run):
        """A reference out of the document breaks it for whoever receives it."""
        _, bundles = ehds_run

        for bundle in bundles:
            ids = {e['fullUrl'] for e in bundle['entry']}
            dangling = []

            def walk(node):
                if isinstance(node, dict):
                    reference = node.get('reference')
                    if (isinstance(reference, str)
                            and reference.startswith('urn:uuid:')
                            and reference not in ids):
                        dangling.append(reference)
                    for value in node.values():
                        walk(value)
                elif isinstance(node, list):
                    for item in node:
                        walk(item)

            walk(bundle)
            assert dangling == []

    @pytest.mark.skipif(not validation.available(),
                        reason="fhir.resources R4B models are not installed")
    def test_the_documents_validate(self, ehds_run):
        _, bundles = ehds_run

        issues = [issue for bundle in bundles
                  for issue in validation.validate_bundle(bundle)]
        nulls = [null for bundle in bundles
                 for null in validation.find_nulls(bundle)]

        assert issues == []
        assert nulls == []
