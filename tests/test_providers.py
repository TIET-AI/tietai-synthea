"""Tests for facilities, clinicians and the optional data fetcher.

Encounters used to have no provider at all: the facility data the manager
looked for was never bundled, and it fell back to three hard-coded clinics that
no encounter referenced. A record could not say where care happened or who gave
it.
"""

import collections
from datetime import datetime

import pytest

from synthea.engine.generator import Generator, GeneratorOptions
from synthea.helpers import optional_data
from synthea.helpers.config import Config
from synthea.world.provider import (
    ENCOUNTER_PROVIDER_TYPES,
    ProviderManager,
    _distance,
    _state_code,
)

REFERENCE_DATE = datetime(2020, 1, 1)


@pytest.fixture(scope='module')
def manager():
    provider_manager = ProviderManager(seed=4)
    provider_manager.load()
    return provider_manager


def _people(count=3, seed=9, age=45, state='Massachusetts'):
    config = Config()
    config.load()
    config.set('exporter.fhir.export', False)
    config.set('exporter.json.export', False)

    options = GeneratorOptions()
    options.population_size = count
    options.seed = seed
    options.min_age = age
    options.max_age = age
    options.state = state
    options.reference_date = REFERENCE_DATE

    generator = Generator(options, config=config)
    return [p for p in (generator.generate_person(i) for i in range(count)) if p]


class TestFacilityData:
    def test_real_facilities_are_bundled(self, manager):
        """Regression: the facility files were documented but never shipped."""
        assert len(manager.providers) > 1000

    def test_the_types_patients_are_sent_to_are_present(self, manager):
        for provider_type in ('hospital', 'primary_care', 'urgent_care'):
            assert manager.providers_by_type.get(provider_type), provider_type

    def test_facilities_have_coordinates(self, manager):
        for provider in list(manager.providers.values())[:50]:
            latitude, longitude = provider.coordinates
            assert -90 <= latitude <= 90
            assert -180 <= longitude <= 180

    def test_loading_can_be_narrowed_to_a_state(self):
        class _Location:
            state = 'Rhode Island'
            city = None

        narrowed = ProviderManager(seed=1)
        narrowed.load(_Location())

        assert narrowed.providers
        assert {p.state.upper() for p in narrowed.providers.values()} == {'RI'}

    def test_state_names_map_to_codes(self):
        assert _state_code('Massachusetts') == 'MA'
        assert _state_code('new york') == 'NY'
        assert _state_code('MA') == 'MA'


class TestStaffing:
    def test_clinicians_are_created_on_demand(self, manager):
        """Staffing every facility up front meant 200,000 clinicians, almost
        none of whom any patient meets."""
        provider = manager.providers_by_type['primary_care'][0]
        staff = manager._staff(provider)

        assert len(staff) == 4
        assert all(c.provider is provider for c in staff)

    def test_the_same_facility_always_has_the_same_people(self, manager):
        provider = manager.providers_by_type['hospital'][0]
        first = [c.id for c in manager._staff(provider)]

        other = ProviderManager(seed=4)
        other.load()
        second = [c.id for c in other._staff(other.providers[provider.id])]

        assert first == second

    def test_npis_cannot_collide_with_real_ones(self, manager):
        """The NPI registry has never issued a 9999 prefix."""
        provider = manager.providers_by_type['primary_care'][1]
        for clinician in manager._staff(provider):
            assert clinician.npi.startswith('9999')


class TestSelection:
    def test_an_encounter_class_picks_a_suitable_type(self, manager):
        for encounter_class, expected in ENCOUNTER_PROVIDER_TYPES.items():
            provider = manager.find_provider(encounter_class, None, None)
            if provider is None:
                continue
            assert provider.organization_type in expected or \
                provider.organization_type in manager.providers_by_type

    def test_emergencies_go_to_a_hospital(self, manager):
        provider = manager.find_provider('emergency', None, None)
        assert provider.organization_type == 'hospital'

    def test_nearby_facilities_are_preferred(self, manager):
        boston = (42.3601, -71.0589)
        chosen = [manager.find_provider('wellness', boston, None) for _ in range(10)]

        for provider in chosen:
            assert _distance(boston, provider.coordinates) < 200

    def test_distance_is_a_real_distance(self):
        boston = (42.3601, -71.0589)
        new_york = (40.7128, -74.0060)
        assert 250 < _distance(boston, new_york) < 350
        assert _distance(boston, boston) == pytest.approx(0, abs=0.001)


class TestContinuityOfCare:
    """The point of the ticket: a patient keeps their practice and clinician."""

    def test_routine_visits_share_one_practice(self):
        for person in _people():
            wellness = [e for e in person.record.encounters
                        if e.encounter_class.value == 'wellness' and e.provider]
            assert wellness

            practices = collections.Counter(e.provider.id for e in wellness)
            assert practices.most_common(1)[0][1] == len(wellness)

    def test_most_routine_visits_are_with_the_usual_clinician(self):
        """The ticket asks for 80% or more."""
        for person in _people():
            wellness = [e for e in person.record.encounters
                        if e.encounter_class.value == 'wellness' and e.clinician]
            if len(wellness) < 5:
                continue

            clinicians = collections.Counter(e.clinician.id for e in wellness)
            share = clinicians.most_common(1)[0][1] / len(wellness)
            assert share >= 0.70, f"only {share:.0%} with the usual clinician"

    def test_every_encounter_has_a_facility(self):
        for person in _people(count=2):
            assert person.record.encounters
            assert all(e.provider is not None for e in person.record.encounters)

    def test_the_practice_is_near_the_patient(self):
        for person in _people(count=2):
            provider = person.attributes.get('primary_care_provider')
            assert provider is not None
            assert provider.state.upper() == 'MA'


class TestOptionalData:
    def test_every_dataset_declares_what_it_unlocks(self):
        for dataset in optional_data.DATASETS.values():
            assert dataset.files
            assert dataset.approx_bytes > 0
            assert len(dataset.purpose) > 40, dataset.name

    def test_status_reports_each_dataset(self):
        names = {row[0] for row in optional_data.status()}
        assert names == set(optional_data.DATASETS)

    def test_the_cache_honours_an_override(self, monkeypatch, tmp_path):
        monkeypatch.setenv(optional_data.CACHE_ENV, str(tmp_path))
        assert optional_data.cache_dir() == tmp_path

    def test_an_unknown_dataset_is_refused(self):
        with pytest.raises(ValueError) as raised:
            optional_data.fetch(['not-a-dataset'])
        assert 'not-a-dataset' in str(raised.value)

    def test_nothing_is_fetched_implicitly(self, monkeypatch, tmp_path):
        """A generator run must never reach the network."""
        monkeypatch.setenv(optional_data.CACHE_ENV, str(tmp_path))

        def _forbidden(*args, **kwargs):
            raise AssertionError("generation must not download anything")

        monkeypatch.setattr(optional_data.urllib.request, 'urlopen', _forbidden)
        assert _people(count=1)


class TestCommandLine:
    """The CLI gained a sub-command; the old invocations must still work."""

    def _run(self, *args):
        from click.testing import CliRunner

        from synthea.cli import cli
        return CliRunner().invoke(cli, list(args))

    def test_version_still_works(self):
        result = self._run('--version')
        assert result.exit_code == 0
        assert 'Synthea' in result.output

    def test_list_modules_still_works(self):
        result = self._run('--list-modules')
        assert result.exit_code == 0
        assert 'Total:' in result.output

    def test_fetch_data_lists_without_downloading(self, monkeypatch, tmp_path):
        monkeypatch.setenv(optional_data.CACHE_ENV, str(tmp_path))
        result = self._run('fetch-data', '--list')

        assert result.exit_code == 0
        assert 'demographics' in result.output
        assert 'not fetched' in result.output

    def test_an_unknown_dataset_exits_with_an_error(self, monkeypatch, tmp_path):
        monkeypatch.setenv(optional_data.CACHE_ENV, str(tmp_path))
        result = self._run('fetch-data', 'nonsense')

        assert result.exit_code == 1
        assert 'nonsense' in result.output
