"""Tests for states and conditions that previously did nothing.

Three gaps, each of which made the engine silently under-produce:

- ``VitalSign`` states set a value on the patient but recorded no Observation,
  so module-set vitals never reached any exporter.
- ``MedicationOrder`` ignored ``prescription``, ``administration`` and
  ``chronic``, so prescriptions had no dosage and drugs given during a visit
  exported as requests for a drug.
- ``ImagingStudy`` was mapped to a no-op, so 39 states across 19 modules did
  nothing at all.

Plus three condition types that returned False instead of being evaluated.
"""

from datetime import datetime, timedelta

import pytest

from synthea.engine.logic import Logic
from synthea.engine.module import Module
from synthea.engine.state import (
    ImagingStudyState,
    MedicationOrderState,
    VitalSignState,
)
from synthea.export.fhir import FHIRExporter
from synthea.helpers.config import Config
from synthea.world.health_record import Code
from synthea.world.person import Person

NOW = datetime(2020, 1, 1)


@pytest.fixture
def module():
    return Module('test')


@pytest.fixture
def person():
    person = Person(seed=17)
    person.attributes['gender'] = 'F'
    person.attributes['birth_date'] = datetime(1980, 1, 1)
    person.init_health_record()
    encounter = person.record.encounter_start(NOW, 'ambulatory')
    encounter.name = 'Visit'
    person.attributes['current_encounter'] = encounter
    return person


# ----------------------------------------------------------------------
# VitalSign -> Observation
# ----------------------------------------------------------------------

class TestVitalSignRecordsObservations:
    def test_a_vital_reaches_the_record(self, module, person):
        """Regression: the value lived only on the person."""
        VitalSignState(module, 'Set_BP', {
            'type': 'VitalSign',
            'vital_sign': 'Systolic Blood Pressure',
            'unit': 'mm[Hg]',
            'exact': {'quantity': 148},
        }).run(person, NOW)

        assert person.get_vital_sign('Systolic Blood Pressure') == 148
        assert len(person.record.observations) == 1

        observation = person.record.observations[0]
        assert observation.value == 148
        assert observation.category == 'vital-signs'

    def test_a_known_vital_gets_a_loinc_code(self, module, person):
        """A VitalSign state usually carries no codes of its own."""
        VitalSignState(module, 'Set_HR', {
            'type': 'VitalSign', 'vital_sign': 'Heart Rate', 'unit': '/min',
            'exact': {'quantity': 72},
        }).run(person, NOW)

        code = person.record.observations[0].codes[0]
        assert code.code == '8867-4'
        assert 'loinc' in code.system.lower()

    def test_an_explicit_code_wins(self, module, person):
        VitalSignState(module, 'Set', {
            'type': 'VitalSign', 'vital_sign': 'Heart Rate',
            'codes': [{'system': 'http://loinc.org', 'code': '11111-1',
                       'display': 'Custom'}],
            'exact': {'quantity': 72},
        }).run(person, NOW)

        assert person.record.observations[0].codes[0].code == '11111-1'

    def test_without_a_visit_the_value_still_reaches_the_person(self, module):
        person = Person(seed=3)
        person.init_health_record()

        VitalSignState(module, 'Set', {
            'type': 'VitalSign', 'vital_sign': 'Heart Rate',
            'exact': {'quantity': 80},
        }).run(person, NOW)

        assert person.get_vital_sign('Heart Rate') == 80
        assert person.record.observations == []

    def test_an_unknown_vital_is_not_invented(self, module, person):
        VitalSignState(module, 'Set', {
            'type': 'VitalSign', 'vital_sign': 'Made Up Measure',
            'exact': {'quantity': 1},
        }).run(person, NOW)

        assert person.get_vital_sign('Made Up Measure') == 1
        assert person.record.observations == []


# ----------------------------------------------------------------------
# MedicationOrder detail
# ----------------------------------------------------------------------

MED_CODES = [{'system': 'RxNorm', 'code': 860975, 'display': 'metformin 500 MG'}]


def _order(module, person, **extra):
    definition = {'type': 'MedicationOrder', 'codes': list(MED_CODES)}
    definition.update(extra)
    MedicationOrderState(module, 'Order', definition).run(person, NOW)
    return person.record.medications[-1]


class TestMedicationDetail:
    def test_prescription_is_kept(self, module, person):
        medication = _order(module, person, prescription={
            'dosage': {'amount': 1, 'frequency': 2, 'period': 1, 'unit': 'days'},
            'duration': {'quantity': 30, 'unit': 'days'},
            'refills': 3,
        })
        assert medication.prescription['refills'] == 3

    def test_a_timed_prescription_ends_when_it_runs_out(self, module, person):
        medication = _order(module, person, prescription={
            'duration': {'quantity': 30, 'unit': 'days'},
        })
        assert medication.end_time == NOW + timedelta(days=30)

    def test_a_chronic_medication_has_no_end(self, module, person):
        medication = _order(module, person, chronic=True, prescription={
            'duration': {'quantity': 30, 'unit': 'days'},
        })
        assert medication.chronic
        assert medication.end_time is None

    def test_an_administration_ends_with_the_visit(self, module, person):
        medication = _order(module, person, administration=True)
        assert medication.administration
        assert medication.end_time == NOW

    def test_reason_resolves_to_the_condition(self, module, person):
        from synthea.engine.state import ConditionOnsetState
        ConditionOnsetState(module, 'Diabetes', {
            'type': 'ConditionOnset',
            'codes': [{'system': 'SNOMED-CT', 'code': '44054006',
                       'display': 'Diabetes'}],
        }).run(person, NOW)

        medication = _order(module, person, reason='Diabetes')

        assert medication.reason_entry is person.record.conditions[-1]

    def test_an_unresolvable_reason_is_kept_as_text(self, module, person):
        medication = _order(module, person, reason='Something_Unknown')
        assert medication.reason == 'Something_Unknown'
        assert medication.reason_entry is None


class TestMedicationExport:
    def _export(self, person, medication, tmp_path):
        config = Config()
        config.load()
        exporter = FHIRExporter(config, tmp_path)
        return exporter.create_medication_entry(medication, person)['resource']

    def test_a_prescription_exports_dosage_and_refills(self, module, person, tmp_path):
        medication = _order(module, person, prescription={
            'dosage': {'amount': 1, 'frequency': 2, 'period': 1, 'unit': 'days'},
            'duration': {'quantity': 30, 'unit': 'days'},
            'refills': 3,
        })
        resource = self._export(person, medication, tmp_path)

        assert resource['resourceType'] == 'MedicationRequest'
        assert resource['dosageInstruction'][0]['timing']['repeat']['frequency'] == 2
        assert resource['dosageInstruction'][0]['timing']['repeat']['periodUnit'] == 'd'
        assert resource['dispenseRequest']['numberOfRepeatsAllowed'] == 3

    def test_as_needed_is_exported(self, module, person, tmp_path):
        medication = _order(module, person, prescription={'as_needed': True})
        resource = self._export(person, medication, tmp_path)
        assert resource['dosageInstruction'][0]['asNeededBoolean'] is True

    def test_an_administration_is_a_different_resource(self, module, person, tmp_path):
        """Regression: administrations exported as requests for a drug."""
        medication = _order(module, person, administration=True)
        resource = self._export(person, medication, tmp_path)

        assert resource['resourceType'] == 'MedicationAdministration'
        assert 'effectiveDateTime' in resource

    def test_reason_is_a_reference_not_free_text(self, module, person, tmp_path):
        from synthea.engine.state import ConditionOnsetState
        ConditionOnsetState(module, 'Diabetes', {
            'type': 'ConditionOnset',
            'codes': [{'system': 'SNOMED-CT', 'code': '44054006',
                       'display': 'Diabetes'}],
        }).run(person, NOW)
        medication = _order(module, person, reason='Diabetes')

        resource = self._export(person, medication, tmp_path)
        condition = person.record.conditions[-1]

        assert resource['reasonReference'][0]['reference'] == f"urn:uuid:{condition.id}"


# ----------------------------------------------------------------------
# ImagingStudy
# ----------------------------------------------------------------------

IMAGING = {
    'type': 'ImagingStudy',
    'procedure_code': {'system': 'SNOMED-CT', 'code': '399208008',
                       'display': 'Plain X-ray of chest'},
    'series': [{
        'body_site': {'system': 'SNOMED-CT', 'code': '51185008',
                      'display': 'Thoracic structure'},
        'modality': {'system': 'DICOM-DCM', 'code': 'CR',
                     'display': 'Computed Radiography'},
        'instances': [{
            'title': 'Chest X-ray',
            'sop_class': {'system': 'DICOM-SOP',
                          'code': '1.2.840.10008.5.1.4.1.1.1.1',
                          'display': 'Digital X-Ray Image Storage'},
        }],
    }],
}


class TestImagingStudy:
    def test_a_study_is_recorded(self, module, person):
        """Regression: the state was mapped to a no-op."""
        ImagingStudyState(module, 'CXR', dict(IMAGING)).run(person, NOW)

        assert len(person.record.imaging_studies) == 1
        study = person.record.imaging_studies[0]
        assert study.encounter is not None
        assert len(study.series) == 1

    def test_uids_are_valid_dicom_identifiers(self, module, person):
        ImagingStudyState(module, 'CXR', dict(IMAGING)).run(person, NOW)
        study = person.record.imaging_studies[0]

        for uid in [study.dicom_uid, study.series[0]['uid'],
                    study.series[0]['instances'][0]['uid']]:
            assert uid.startswith('2.25.'), uid
            assert len(uid) <= 64
            assert all(part.isdigit() for part in uid.split('.'))

    def test_uids_are_unique(self, module, person):
        ImagingStudyState(module, 'CXR', dict(IMAGING)).run(person, NOW)
        ImagingStudyState(module, 'CXR2', dict(IMAGING)).run(person, NOW)

        uids = {s.dicom_uid for s in person.record.imaging_studies}
        assert len(uids) == 2

    def test_a_study_also_records_its_procedure(self, module, person):
        ImagingStudyState(module, 'CXR', dict(IMAGING)).run(person, NOW)
        assert any(p.codes[0].code == '399208008'
                   for p in person.record.procedures)

    def test_it_exports_as_a_fhir_resource(self, module, person, tmp_path):
        ImagingStudyState(module, 'CXR', dict(IMAGING)).run(person, NOW)
        study = person.record.imaging_studies[0]

        config = Config()
        config.load()
        resource = FHIRExporter(config, tmp_path).create_imaging_study_entry(
            study, person)['resource']

        assert resource['resourceType'] == 'ImagingStudy'
        assert resource['numberOfSeries'] == 1
        assert resource['numberOfInstances'] == 1
        assert resource['series'][0]['modality']['code'] == 'CR'
        assert resource['identifier'][0]['value'].startswith('urn:oid:2.25.')


# ----------------------------------------------------------------------
# Logic conditions
# ----------------------------------------------------------------------

ALLERGY_CODE = {'system': 'SNOMED-CT', 'code': '419474003', 'display': 'Allergy to mold'}


class TestLogicConditions:
    def test_active_allergy(self, person):
        condition = {'condition_type': 'Active Allergy', 'codes': [ALLERGY_CODE]}
        assert Logic.test(condition, person, NOW) is False

        allergy = person.record.allergy_start(NOW, Code(**ALLERGY_CODE))
        assert Logic.test(condition, person, NOW) is True

        person.record.allergy_end(allergy, NOW)
        assert Logic.test(condition, person, NOW) is False

    def test_at_least(self, person):
        def condition(minimum):
            return {
                'condition_type': 'At Least', 'minimum': minimum,
                'conditions': [
                    {'condition_type': 'True'},
                    {'condition_type': 'True'},
                    {'condition_type': 'False'},
                ],
            }

        assert Logic.test(condition(1), person, NOW) is True
        assert Logic.test(condition(2), person, NOW) is True
        assert Logic.test(condition(3), person, NOW) is False

    def test_at_most(self, person):
        def condition(maximum):
            return {
                'condition_type': 'At Most', 'maximum': maximum,
                'conditions': [
                    {'condition_type': 'True'},
                    {'condition_type': 'True'},
                    {'condition_type': 'False'},
                ],
            }

        assert Logic.test(condition(1), person, NOW) is False
        assert Logic.test(condition(2), person, NOW) is True

    def test_prior_state_within_a_window(self, person):
        person.attributes['test.Visit_visited'] = True
        person.attributes['test.Visit_visited_at'] = NOW - timedelta(days=30)

        recent = {'condition_type': 'PriorState', 'module': 'test', 'name': 'Visit',
                  'within': {'quantity': 1, 'unit': 'years'}}
        assert Logic.test(recent, person, NOW) is True

        person.attributes['test.Visit_visited_at'] = NOW - timedelta(days=5 * 365)
        assert Logic.test(recent, person, NOW) is False

    def test_prior_state_without_a_window_means_ever(self, person):
        person.attributes['test.Visit_visited'] = True
        person.attributes['test.Visit_visited_at'] = NOW - timedelta(days=9000)

        assert Logic.test(
            {'condition_type': 'PriorState', 'module': 'test', 'name': 'Visit'},
            person, NOW,
        ) is True

    def test_an_unknown_condition_warns_once(self, person, caplog):
        condition = {'condition_type': 'Telepathy'}

        with caplog.at_level('WARNING'):
            assert Logic.test(condition, person, NOW) is False
            Logic.test(condition, person, NOW)

        assert sum('Telepathy' in r.message for r in caplog.records) <= 1


class TestDeathTiming:
    """Death states must honour their time unit and not kill on the spot."""

    def _die(self, module, person, **extra):
        from synthea.engine.state import DeathState
        definition = {'type': 'Death'}
        definition.update(extra)
        DeathState(module, 'Death', definition).run(person, NOW)

    def test_the_time_unit_is_honoured(self, module, person):
        """Regression: every quantity was read as years.

        29 of the 35 delayed Death states in the bundled modules use months,
        days, weeks or hours, so almost every timed death was wrong by orders
        of magnitude.
        """
        self._die(module, person, exact={'quantity': 1, 'unit': 'days'})
        assert person.attributes['death_time'] == NOW + timedelta(days=1)

    def test_months_are_months_not_years(self, module, person):
        self._die(module, person, exact={'quantity': 6, 'unit': 'months'})
        scheduled = person.attributes['death_time']
        assert timedelta(days=170) < scheduled - NOW < timedelta(days=190)

    def test_a_scheduled_death_does_not_kill_immediately(self, module, person):
        """Regression: 'expected lifespan 4 to 10 years' ended the simulation
        on the spot, so the intervening years of care were never generated."""
        self._die(module, person, range={'low': 4, 'high': 10, 'unit': 'years'})

        assert person.alive
        assert person.record.death_date is None
        assert person.attributes['death_time'] > NOW + timedelta(days=3 * 365)

    def test_an_immediate_death_is_recorded_now(self, module, person):
        self._die(module, person, codes=[{'system': 'SNOMED-CT', 'code': '419620001',
                                          'display': 'Death'}])
        assert not person.alive
        assert person.record.death_date == NOW

    def test_the_earliest_scheduled_death_wins(self, module, person):
        self._die(module, person, exact={'quantity': 10, 'unit': 'years'})
        self._die(module, person, exact={'quantity': 1, 'unit': 'years'})

        assert person.attributes['death_time'] == NOW + timedelta(days=365)

    def test_a_distribution_is_honoured(self, module, person):
        self._die(module, person,
                  distribution={'kind': 'EXACT', 'parameters': {'value': 30}},
                  unit='days')
        assert person.attributes['death_time'] == NOW + timedelta(days=30)


class TestRecordIndexes:
    """The code indexes must agree with a full scan of the record."""

    def test_an_active_condition_is_found(self, module, person):
        from synthea.engine.state import ConditionOnsetState
        from synthea.world.health_record import Code

        code = Code(system='SNOMED-CT', code='44054006', display='Diabetes')
        assert not person.record.has_active_condition(code)

        ConditionOnsetState(module, 'Onset', {
            'type': 'ConditionOnset',
            'codes': [{'system': 'SNOMED-CT', 'code': '44054006',
                       'display': 'Diabetes'}],
        }).run(person, NOW)

        assert person.record.has_active_condition(code)

    def test_ending_a_condition_removes_it_from_the_index(self, module, person):
        from synthea.engine.state import ConditionEndState, ConditionOnsetState
        from synthea.world.health_record import Code

        code = Code(system='SNOMED-CT', code='44054006', display='Diabetes')
        ConditionOnsetState(module, 'Onset', {
            'type': 'ConditionOnset',
            'codes': [{'system': 'SNOMED-CT', 'code': '44054006',
                       'display': 'Diabetes'}],
        }).run(person, NOW)

        ConditionEndState(module, 'End', {
            'type': 'ConditionEnd', 'condition_onset': 'Onset',
        }).run(person, NOW + timedelta(days=30))

        assert not person.record.has_active_condition(code)

    def test_the_index_agrees_with_a_full_scan(self, module, person):
        """The index is only useful if it answers what scanning would."""
        from synthea.engine.state import ConditionEndState, ConditionOnsetState
        from synthea.world.health_record import Code

        codes = ['44054006', '59621000', '195967001']
        for index, value in enumerate(codes):
            ConditionOnsetState(module, f'Onset{index}', {
                'type': 'ConditionOnset',
                'codes': [{'system': 'SNOMED-CT', 'code': value, 'display': value}],
            }).run(person, NOW)

        ConditionEndState(module, 'End', {
            'type': 'ConditionEnd', 'condition_onset': 'Onset1',
        }).run(person, NOW + timedelta(days=10))

        for value in codes:
            code = Code(system='SNOMED-CT', code=value, display=value)
            scanned = any(
                c.is_active and any(cc.code == value for cc in c.codes)
                for c in person.record.conditions
            )
            assert person.record.has_active_condition(code) is scanned, value

    def test_the_latest_observation_is_the_latest(self, module, person):
        from synthea.world.health_record import Code

        code = Code(system='http://loinc.org', code='2339-0', display='Glucose')
        for offset, value in ((0, 90), (10, 110), (20, 130)):
            person.record.observation(
                NOW + timedelta(days=offset), code, value, 'mg/dL',
                person.attributes['current_encounter'],
            )

        assert person.record.get_latest_observation(code).value == 130
