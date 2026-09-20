"""Tests for the rest of the record in the FHIR export (#40).

The record model has held allergies, care plans, reports, devices and supplies
since the engine was ported, and the exporter emitted none of them: a consumer
reading a generated bundle saw a patient with no allergies who was never given
anything and never had a panel of labs run.

Each builder is exercised directly as well as over a generated population,
because some of these come from a handful of modules and a small population can
miss them by luck rather than because the builder is wrong.
"""

import collections
import json
from datetime import datetime

import pytest

from synthea.engine.generator import Generator, GeneratorOptions
from synthea.export import validation
from synthea.export.fhir import FHIRExporter
from synthea.helpers.config import Config
from synthea.world.health_record import Code, EncounterClass
from synthea.world.person import Person

REFERENCE_DATE = datetime(2020, 1, 1)
VISIT = datetime(2015, 6, 1)


def _code(code, display, system='SNOMED-CT'):
    return Code(system=system, code=code, display=display)


@pytest.fixture
def exporter(tmp_path):
    config = Config()
    config.load()
    return FHIRExporter(config, tmp_path)


@pytest.fixture
def person():
    person = Person(seed=3)
    person.init_health_record()
    person.attributes.update({
        'gender': 'F',
        'birth_date': datetime(1975, 6, 1),
        'first_name': 'Ada',
        'last_name': 'Lovelace',
    })
    return person


@pytest.fixture
def encounter(person):
    encounter = person.record.encounter_start(VISIT, EncounterClass.AMBULATORY)
    person.record.encounter_end(encounter, VISIT)
    return encounter


def _allergy(person, encounter, code):
    """Record an allergy against a finished encounter.

    `allergy_start` attaches to the encounter in progress, and these fixtures
    close theirs so the export sees a finished visit.
    """
    allergy = person.record.allergy_start(VISIT, code, attach=False)
    allergy.encounter = encounter
    return allergy


def _validated(resource):
    """Validate one resource the way the bundle gate does."""
    if not validation.available():
        pytest.skip("fhir.resources R4B models are not installed")
    issues = validation.validate_bundle({'entry': [{'resource': resource}]})
    assert issues == [], issues
    assert validation.find_nulls(resource) == []
    return resource


class TestAllergyIntolerance:
    def test_an_allergy_exports(self, exporter, person, encounter):
        allergy = _allergy(person, encounter,
                           _code('91935009', 'Allergy to peanuts'))

        resource = exporter.create_allergy_intolerance_entry(
            allergy, person)['resource']

        _validated(resource)
        assert resource['resourceType'] == 'AllergyIntolerance'
        assert resource['clinicalStatus']['coding'][0]['code'] == 'active'
        assert resource['patient']['reference'] == f"urn:uuid:{person.uuid}"

    def test_a_resolved_allergy_says_so(self, exporter, person, encounter):
        allergy = _allergy(person, encounter, _code('1', 'Allergy'))
        person.record.allergy_end(allergy, datetime(2018, 1, 1))

        resource = exporter.create_allergy_intolerance_entry(
            allergy, person)['resource']

        assert resource['clinicalStatus']['coding'][0]['code'] == 'resolved'

    def test_a_drug_allergy_is_a_medication_allergy(self, exporter, person,
                                                    encounter):
        allergy = _allergy(person, encounter,
                           _code('7980', 'Penicillin', system='RxNorm'))

        resource = exporter.create_allergy_intolerance_entry(
            allergy, person)['resource']

        assert resource['category'] == ['medication']

    def test_reactions_become_manifestations(self, exporter, person,
                                             encounter):
        allergy = _allergy(person, encounter, _code('1', 'Allergy'))
        allergy.reactions = ['Hives', 'Wheezing']
        allergy.severity = 'severe'

        resource = _validated(exporter.create_allergy_intolerance_entry(
            allergy, person)['resource'])

        manifestations = resource['reaction'][0]['manifestation']
        assert [m['text'] for m in manifestations] == ['Hives', 'Wheezing']
        assert resource['reaction'][0]['severity'] == 'severe'
        assert resource['criticality'] == 'high'

    def test_an_unknown_severity_is_not_guessed(self, exporter, person,
                                                encounter):
        allergy = _allergy(person, encounter, _code('1', 'Allergy'))
        allergy.severity = 'catastrophic'

        resource = exporter.create_allergy_intolerance_entry(
            allergy, person)['resource']

        assert resource['criticality'] == 'unable-to-assess'


class TestCarePlan:
    @pytest.fixture
    def careplan(self, person, encounter):
        careplan = person.record.careplan_start(
            VISIT, _code('698360004', 'Diabetes self management plan'))
        careplan.goals = ['Reduce HbA1c below 7%', 'Lose 5kg']
        careplan.activities = ['Diabetic diet', 'Exercise therapy']
        careplan.encounter = encounter
        return careplan

    def test_a_care_plan_exports(self, exporter, person, careplan):
        resource = _validated(
            exporter.create_care_plan_entry(careplan, person)['resource'])

        assert resource['status'] == 'active'
        assert resource['intent'] == 'plan'

    def test_it_references_its_goals(self, exporter, person, careplan):
        plan = exporter.create_care_plan_entry(careplan, person)['resource']
        goals = [exporter.create_goal_entry(careplan, index, goal, person)
                 for index, goal in enumerate(careplan.goals)]

        referenced = {g['reference'] for g in plan['goal']}
        assert referenced == {g['fullUrl'] for g in goals}

    def test_goals_carry_their_text(self, exporter, person, careplan):
        resource = _validated(exporter.create_goal_entry(
            careplan, 0, careplan.goals[0], person)['resource'])

        assert resource['description']['text'] == 'Reduce HbA1c below 7%'
        assert resource['lifecycleStatus'] == 'active'

    def test_activities_are_listed(self, exporter, person, careplan):
        resource = exporter.create_care_plan_entry(careplan, person)['resource']

        texts = [a['detail']['code']['text'] for a in resource['activity']]
        assert texts == ['Diabetic diet', 'Exercise therapy']

    def test_the_care_team_includes_the_patient(self, exporter, person,
                                                careplan):
        resource = _validated(
            exporter.create_care_team_entry(careplan, person)['resource'])

        members = [p['member']['reference'] for p in resource['participant']]
        assert f"urn:uuid:{person.uuid}" in members

    def test_a_finished_plan_and_its_team_are_inactive(self, exporter, person,
                                                       careplan):
        person.record.careplan_end(careplan, datetime(2018, 1, 1))

        plan = exporter.create_care_plan_entry(careplan, person)['resource']
        team = exporter.create_care_team_entry(careplan, person)['resource']

        assert plan['status'] == 'completed'
        assert team['status'] == 'inactive'


class TestDiagnosticReport:
    def test_a_report_references_its_observations(self, exporter, person,
                                                  encounter):
        first = person.record.observation(
            VISIT, _code('718-7', 'Haemoglobin', system='LOINC'),
            value=13.5, unit='g/dL', encounter=encounter)
        second = person.record.observation(
            VISIT, _code('789-8', 'Erythrocytes', system='LOINC'),
            value=4.6, unit='10*6/uL', encounter=encounter)

        report = person.record.reports[0] if person.record.reports else None
        if report is None:
            from synthea.world.health_record import Report

            report = Report(time=VISIT,
                            codes=[_code('58410-2', 'CBC panel',
                                         system='LOINC')])
            report.observations = [first, second]
            report.encounter = encounter

        resource = _validated(exporter.create_diagnostic_report_entry(
            report, person)['resource'])

        assert resource['status'] == 'final'
        results = {r['reference'] for r in resource['result']}
        assert results == {f"urn:uuid:{first.id}", f"urn:uuid:{second.id}"}


class TestDevice:
    def test_a_device_exports_with_a_udi(self, exporter, person, encounter):
        device = person.record.device_start(
            VISIT, _code('72506001', 'Implantable defibrillator'))

        resource = _validated(
            exporter.create_device_entry(device, person)['resource'])

        assert resource['status'] == 'active'
        carrier = resource['udiCarrier'][0]
        assert carrier['deviceIdentifier']
        assert carrier['carrierHRF'].startswith('(01)')

    def test_the_udi_is_stable_for_a_device(self, exporter, person):
        device = person.record.device_start(VISIT, _code('1', 'Device'))

        first = exporter.create_device_entry(device, person)['resource']
        second = exporter.create_device_entry(device, person)['resource']

        assert (first['udiCarrier'][0]['carrierHRF']
                == second['udiCarrier'][0]['carrierHRF'])

    def test_two_devices_get_different_udis(self, exporter, person):
        one = person.record.device_start(VISIT, _code('1', 'Device'))
        two = person.record.device_start(VISIT, _code('1', 'Device'))

        assert (exporter.create_device_entry(one, person)['resource']
                ['udiCarrier'][0]['carrierHRF']
                != exporter.create_device_entry(two, person)['resource']
                ['udiCarrier'][0]['carrierHRF'])

    def test_a_removed_device_is_inactive(self, exporter, person):
        device = person.record.device_start(VISIT, _code('1', 'Device'))
        person.record.device_end(device, datetime(2018, 1, 1))

        resource = exporter.create_device_entry(device, person)['resource']
        assert resource['status'] == 'inactive'


class TestSupplyDelivery:
    def test_supplies_export(self, exporter, person, encounter):
        supplies = person.record.supply_list(VISIT, [
            {'code': {'system': 'SNOMED-CT', 'code': '52291003',
                      'display': 'Glove'},
             'quantity': 12},
        ])

        resource = _validated(exporter.create_supply_delivery_entry(
            supplies[0], person)['resource'])

        assert resource['status'] == 'completed'
        assert resource['suppliedItem']['quantity']['value'] == 12


class TestProvenance:
    def test_it_targets_every_entry_in_the_bundle(self, exporter, person,
                                                  encounter):
        bundle = exporter.create_bundle(person)

        provenance = [e['resource'] for e in bundle['entry']
                      if e['resource']['resourceType'] == 'Provenance']
        assert len(provenance) == 1

        targets = {t['reference'] for t in provenance[0]['target']}
        others = {e['fullUrl'] for e in bundle['entry']
                  if e['resource']['resourceType'] != 'Provenance'}
        assert others <= targets

    def test_it_says_the_record_was_generated(self, exporter, person,
                                              encounter):
        bundle = exporter.create_bundle(person)
        provenance = next(e['resource'] for e in bundle['entry']
                          if e['resource']['resourceType'] == 'Provenance')

        assert provenance['activity']['coding'][0]['code'] == 'CREATE'
        assert 'PySynthea' in provenance['agent'][0]['who']['display']


class TestBundleIntegrity:
    def test_no_reference_dangles(self, exporter, person, encounter):
        """A transaction bundle whose references do not resolve cannot load."""
        _allergy(person, encounter, _code('1', 'Allergy'))
        careplan = person.record.careplan_start(VISIT, _code('2', 'Plan'))
        careplan.goals = ['Get better']
        careplan.encounter = encounter
        person.record.device_start(VISIT, _code('3', 'Device'))

        bundle = exporter.create_bundle(person)
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

    def test_a_referenced_resource_comes_first(self, exporter, person,
                                               encounter):
        """A transaction bundle is applied in order."""
        careplan = person.record.careplan_start(VISIT, _code('2', 'Plan'))
        careplan.goals = ['Get better']
        careplan.encounter = encounter

        bundle = exporter.create_bundle(person)
        order = [e['fullUrl'] for e in bundle['entry']]
        types = {e['fullUrl']: e['resource']['resourceType']
                 for e in bundle['entry']}

        plan = next(url for url in order if types[url] == 'CarePlan')
        goal = next(url for url in order if types[url] == 'Goal')
        team = next(url for url in order if types[url] == 'CareTeam')

        assert order.index(goal) < order.index(plan)
        assert order.index(team) < order.index(plan)


@pytest.fixture(scope='module')
def generated(tmp_path_factory):
    """A generated population, exported and read back."""
    out = tmp_path_factory.mktemp('export-coverage')

    config = Config()
    config.load()
    config.set('exporter.baseDirectory', str(out))
    config.set('exporter.fhir.export', True)
    config.set('exporter.use_uuid_filenames', True)

    options = GeneratorOptions()
    options.population_size = 6
    options.seed = 11
    options.min_age = 20
    options.max_age = 85
    options.reference_date = REFERENCE_DATE

    Generator(options, config=config).run()

    return [json.loads(path.read_text(encoding='utf-8'))
            for path in (out / 'fhir').glob('*.json')]


class TestGeneratedPopulation:
    @pytest.mark.parametrize('resource_type', [
        'AllergyIntolerance', 'CarePlan', 'CareTeam', 'DiagnosticReport',
        'Device', 'Provenance',
    ])
    def test_the_new_types_appear(self, generated, resource_type):
        counts = collections.Counter(
            entry['resource']['resourceType']
            for bundle in generated for entry in bundle['entry'])

        assert counts[resource_type] > 0, dict(counts)

    def test_report_results_resolve_within_the_bundle(self, generated):
        for bundle in generated:
            ids = {entry['fullUrl'] for entry in bundle['entry']}
            for entry in bundle['entry']:
                resource = entry['resource']
                if resource['resourceType'] != 'DiagnosticReport':
                    continue
                for result in resource.get('result', []):
                    assert result['reference'] in ids

    def test_every_patient_gets_one_provenance(self, generated):
        for bundle in generated:
            provenance = [e for e in bundle['entry']
                          if e['resource']['resourceType'] == 'Provenance']
            assert len(provenance) == 1

    @pytest.mark.skipif(not validation.available(),
                        reason="fhir.resources R4B models are not installed")
    def test_the_bundles_validate(self, generated):
        issues = [issue for bundle in generated
                  for issue in validation.validate_bundle(bundle)]
        nulls = [null for bundle in generated
                 for null in validation.find_nulls(bundle)]

        assert issues == []
        assert nulls == []


class TestDeterminism:
    """Regression: the export is reproducible from a seed, and must stay so."""

    def test_provenance_does_not_use_wall_clock_time(self, exporter, person,
                                                     encounter):
        """`datetime.now()` made two runs of the same population differ."""
        first = exporter.create_bundle(person)
        second = exporter.create_bundle(person)

        def recorded(bundle):
            return next(e['resource']['recorded'] for e in bundle['entry']
                        if e['resource']['resourceType'] == 'Provenance')

        assert recorded(first) == recorded(second)

    def test_provenance_is_dated_from_the_record(self, exporter, person,
                                                 encounter):
        resource = next(e['resource'] for e in exporter.create_bundle(person)
                        ['entry'] if e['resource']['resourceType'] == 'Provenance')

        assert resource['recorded'].startswith(VISIT.date().isoformat())


class TestClaimCoverage:
    """Regression: a Claim must reference a Coverage that is in the bundle."""

    def test_priced_care_without_a_coverage_history_still_resolves(
            self, exporter, person, encounter):
        """The insurance module may never have run for this patient."""
        encounter.cost = 120.0
        encounter.payer_cost = 0.0
        encounter.patient_cost = 120.0
        encounter.coverage = None

        bundle = exporter.create_bundle(person)
        ids = {e['fullUrl'] for e in bundle['entry']}

        claims = [e['resource'] for e in bundle['entry']
                  if e['resource']['resourceType'] in
                  ('Claim', 'ExplanationOfBenefit')]
        assert claims, "a priced encounter should produce a claim"

        for claim in claims:
            reference = claim['insurance'][0]['coverage']['reference']
            assert reference in ids, f"{claim['resourceType']} dangles"

    def test_that_coverage_is_self_pay(self, exporter, person, encounter):
        encounter.cost = 120.0
        encounter.payer_cost = 0.0
        encounter.patient_cost = 120.0
        encounter.coverage = None

        coverages = [e['resource'] for e in exporter.create_bundle(person)
                     ['entry'] if e['resource']['resourceType'] == 'Coverage']

        assert len(coverages) == 1
        assert coverages[0]['payor'][0]['reference'] == f"urn:uuid:{person.uuid}"

    def test_a_record_with_no_care_gets_no_invented_coverage(self, exporter,
                                                             person):
        """The self-pay period exists to anchor a claim, not for its own sake."""
        coverages = [e for e in exporter.create_bundle(person)['entry']
                     if e['resource']['resourceType'] == 'Coverage']

        assert coverages == []
