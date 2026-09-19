"""The FHIR validation gate.

The exporter hand-builds dictionaries, so nothing stopped it producing
resources no server would accept. This validates a generated population against
the R4B models from ``fhir.resources`` and fails the build when it drifts.

It is generic on purpose: resources are looked up by ``resourceType`` rather
than from a list kept here, so a newly exported type is covered the moment it
appears rather than when someone remembers to extend this file.

Setting ``SYNTHEA_FHIR_URL`` additionally posts a bundle to a real server, which
is the only way to catch what a model check cannot.
"""

import json
import os
from datetime import datetime

import pytest

from synthea.engine.generator import Generator, GeneratorOptions
from synthea.export import validation
from synthea.export.terminology import system_uri, ucum_code
from synthea.helpers.config import Config

REFERENCE_DATE = datetime(2020, 1, 1)

pytestmark = pytest.mark.skipif(
    not validation.available(),
    reason="fhir.resources R4B models are not installed",
)


@pytest.fixture(scope='module')
def bundles(tmp_path_factory):
    """A generated population, exported and read back."""
    out = tmp_path_factory.mktemp('fhir-validity')

    options = GeneratorOptions()
    options.population_size = 6
    options.seed = 5
    options.min_age = 20
    options.max_age = 80
    options.reference_date = REFERENCE_DATE

    config = Config()
    config.load()
    config.set('exporter.baseDirectory', str(out))
    config.set('exporter.fhir.export', True)
    config.set('exporter.use_uuid_filenames', True)

    Generator(options, config=config).run()

    loaded = [
        json.loads(path.read_text(encoding='utf-8'))
        for path in sorted((out / 'fhir').glob('*.json'))
    ]
    assert loaded, "the run produced no bundles"
    return loaded


class TestBundlesValidate:
    def test_every_resource_validates_against_r4(self, bundles):
        """The gate. Any invalid resource fails here, named and located."""
        issues = []
        for bundle in bundles:
            issues.extend(validation.validate_bundle(bundle))

        assert not issues, "invalid resources:\n" + "\n".join(
            str(issue) for issue in issues[:20])

    def test_no_nulls_anywhere(self, bundles):
        """FHIR has no null: an absent value is an absent field.

        An open encounter's `period.end` used to serialise as JSON null.
        """
        nulls = []
        for bundle in bundles:
            nulls.extend(validation.find_nulls(bundle))

        assert not nulls, f"null values at: {nulls[:20]}"

    def test_a_population_covers_several_resource_types(self, bundles):
        types = {
            entry['resource']['resourceType']
            for bundle in bundles for entry in bundle['entry']
        }
        assert {'Patient', 'Encounter', 'Condition', 'Observation'} <= types


class TestSpecificDefects:
    """Each of these was a real defect the gate now prevents returning."""

    def _resources(self, bundles, resource_type):
        return [
            entry['resource']
            for bundle in bundles for entry in bundle['entry']
            if entry['resource']['resourceType'] == resource_type
        ]

    def test_encounter_class_is_an_actcode(self, bundles):
        """It used to be the enum name upper-cased, e.g. AMBULATORY."""
        valid = {'AMB', 'EMER', 'IMP', 'HH', 'VR', 'FLD', 'SS', 'OBSENC', 'PRENC'}
        for encounter in self._resources(bundles, 'Encounter'):
            assert encounter['class']['code'] in valid, encounter['class']
            assert encounter['class']['system'].endswith('v3-ActCode')

    def test_datetimes_carry_a_timezone(self, bundles):
        """A dateTime with a time must carry an offset."""
        for encounter in self._resources(bundles, 'Encounter'):
            start = encounter['period']['start']
            assert start.endswith('+00:00') or start.endswith('Z'), start

    def test_coding_systems_are_uris(self, bundles):
        """Modules write 'SNOMED-CT', which no server can resolve."""
        def check(node):
            if isinstance(node, dict):
                if 'system' in node and 'code' in node:
                    system = node['system']
                    assert '://' in system or system.startswith('urn:'), system
                for value in node.values():
                    check(value)
            elif isinstance(node, list):
                for value in node:
                    check(value)

        for bundle in bundles:
            check(bundle)

    def test_quantities_use_ucum(self, bundles):
        for observation in self._resources(bundles, 'Observation'):
            value = observation.get('valueQuantity')
            if value and 'code' in value:
                assert value['system'] == 'http://unitsofmeasure.org'

    def test_observation_categories_are_valid_codes(self, bundles):
        valid = {'vital-signs', 'laboratory', 'imaging', 'survey', 'exam',
                 'procedure', 'therapy', 'activity', 'social-history'}
        for observation in self._resources(bundles, 'Observation'):
            code = observation['category'][0]['coding'][0]['code']
            assert code in valid, code

    def test_conditions_are_categorised(self, bundles):
        valid = {'encounter-diagnosis', 'problem-list-item'}
        for condition in self._resources(bundles, 'Condition'):
            assert condition['category'][0]['coding'][0]['code'] in valid

    def test_references_are_resolvable_uuids(self, bundles):
        """`urn:uuid:` must be followed by a UUID; patient ids were 16 hex."""
        import uuid as uuid_module

        for bundle in bundles:
            for entry in bundle['entry']:
                full_url = entry['fullUrl']
                assert full_url.startswith('urn:uuid:')
                uuid_module.UUID(full_url[len('urn:uuid:'):])

    def test_every_reference_resolves_inside_the_bundle(self, bundles):
        """A dangling reference makes a transaction bundle unloadable."""
        for bundle in bundles:
            present = {entry['fullUrl'] for entry in bundle['entry']}
            referenced = set()

            def collect(node):
                if isinstance(node, dict):
                    if 'reference' in node and isinstance(node['reference'], str):
                        referenced.add(node['reference'])
                    for value in node.values():
                        collect(value)
                elif isinstance(node, list):
                    for value in node:
                        collect(value)

            collect(bundle)
            assert not (referenced - present), sorted(referenced - present)[:5]

    def test_patients_carry_us_core_profiles(self, bundles):
        for patient in self._resources(bundles, 'Patient'):
            assert any('us-core-patient' in profile
                       for profile in patient['meta']['profile'])

    def test_patients_have_birth_sex(self, bundles):
        for patient in self._resources(bundles, 'Patient'):
            urls = {extension['url'] for extension in patient.get('extension', [])}
            assert any('us-core-birthsex' in url for url in urls)


class TestTerminologyMapping:
    def test_known_systems_map_to_canonical_uris(self):
        assert system_uri('SNOMED-CT') == 'http://snomed.info/sct'
        assert system_uri('LOINC') == 'http://loinc.org'
        assert system_uri('CVX') == 'http://hl7.org/fhir/sid/cvx'
        assert system_uri('RxNorm').startswith('http://')

    def test_an_existing_uri_passes_through(self):
        assert system_uri('http://loinc.org') == 'http://loinc.org'

    def test_an_unknown_system_still_yields_a_uri(self, caplog):
        with caplog.at_level('WARNING'):
            result = system_uri('Some Local Codes')
        assert result.startswith('urn:')

    def test_display_units_map_to_ucum(self):
        assert ucum_code('mm[Hg]') == 'mm[Hg]'
        assert ucum_code('mmHg') == 'mm[Hg]'
        assert ucum_code('years') == 'a'
        assert ucum_code('%') == '%'

    def test_no_unit_stays_absent(self):
        assert ucum_code(None) is None
        assert ucum_code('') is None


@pytest.mark.skipif(
    not os.environ.get('SYNTHEA_FHIR_URL'),
    reason="set SYNTHEA_FHIR_URL to validate against a real FHIR server",
)
def test_a_real_server_accepts_a_bundle(bundles):
    """The check a model validator cannot make.

    Opt-in: a model check proves a resource is structurally sound, not that a
    server will take it.
    """
    import requests

    url = os.environ['SYNTHEA_FHIR_URL'].rstrip('/')
    response = requests.post(
        url,
        json=bundles[0],
        headers={'Content-Type': 'application/fhir+json'},
        timeout=120,
    )

    assert response.status_code < 300, (
        f"{url} rejected the bundle ({response.status_code}): {response.text[:2000]}"
    )
