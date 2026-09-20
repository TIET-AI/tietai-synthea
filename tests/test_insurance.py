"""Tests for coverage, costs and claims.

The payer and cost tables shipped in 1.2.0 and nothing read them: every patient
was uninsured, every encounter free, and there were no claims. A record without
money in it cannot exercise a payer mix, an eligibility rule or a claims
pipeline.

Population-level assertions are loose bounds. The eligibility model is
deliberately simplified (age and socioeconomic status, not means testing), so
these check the shape of the result rather than pinning a distribution the
model does not claim to reproduce.
"""

import collections
from datetime import datetime

import pytest

from synthea.engine.generator import Generator, GeneratorOptions
from synthea.helpers.config import Config
from synthea.world.costs import CostTables, cost_of
from synthea.world.payer import MEDICARE_AGE, Coverage, PayerManager, Plan, Payer
from synthea.world.person import Person

REFERENCE_DATE = datetime(2020, 1, 1)


@pytest.fixture(scope='module')
def payers():
    manager = PayerManager(seed=7)
    manager.load()
    return manager


@pytest.fixture
def person():
    person = Person(seed=5)
    person.attributes.update({
        'gender': 'F',
        'birth_date': datetime(1980, 1, 1),
        'state': 'Massachusetts',
        'socioeconomic_status': 'middle',
    })
    return person


def _population(count=12, seed=13, low=20, high=85):
    config = Config()
    config.load()
    config.set('exporter.fhir.export', False)
    config.set('exporter.json.export', False)

    options = GeneratorOptions()
    options.population_size = count
    options.seed = seed
    options.min_age = low
    options.max_age = high
    options.reference_date = REFERENCE_DATE

    generator = Generator(options, config=config)
    return [p for p in (generator.generate_person(i) for i in range(count)) if p]


class TestPayerData:
    def test_payers_and_plans_load(self, payers):
        """Regression: the tables shipped and nothing read them."""
        assert payers.payers
        assert payers.plans

    def test_medicare_and_medicaid_are_present(self, payers):
        names = {p.name for p in payers.payers.values()}
        assert 'Medicare' in names
        assert 'Medicaid' in names

    def test_plans_carry_their_terms(self, payers):
        plan = next(iter(payers.plans.values()))
        assert plan.deductible >= 0
        assert 0 <= plan.coinsurance <= 1
        assert plan.monthly_premium >= 0

    def test_a_payer_knows_which_states_it_covers(self):
        national = Payer(id='1', name='National', ownership='Private',
                         states_covered=['*'])
        local = Payer(id='2', name='Local', ownership='Private',
                      states_covered=['MA'])

        assert national.covers_state('Texas')
        assert local.covers_state('Massachusetts')
        assert not local.covers_state('Texas')


class TestEligibility:
    def test_the_elderly_get_medicare(self, payers, person):
        assert payers.kind_for(person, MEDICARE_AGE) == 'medicare'
        assert payers.kind_for(person, 80) == 'medicare'

    def test_working_age_gets_private_cover(self, payers, person):
        assert payers.kind_for(person, 40) == 'private'

    def test_low_income_gets_medicaid_or_nothing(self, payers):
        kinds = set()
        for seed in range(30):
            candidate = Person(seed=seed)
            candidate.attributes.update({
                'gender': 'M', 'socioeconomic_status': 'low',
                'state': 'Massachusetts',
            })
            kinds.add(payers.kind_for(candidate, 40))

        assert kinds <= {'medicaid', 'none'}
        assert 'medicaid' in kinds, "some low-income patients must get Medicaid"

    def test_medicaid_enrolment_is_settled_once(self, payers, person):
        """Churning in and out of Medicaid every year is not what happens."""
        person.attributes['socioeconomic_status'] = 'low'
        first = payers.kind_for(person, 30)
        assert all(payers.kind_for(person, age) == first for age in (31, 40, 55))

    def test_turning_sixty_five_changes_cover(self, payers, person):
        assert payers.kind_for(person, 64) != payers.kind_for(person, 66)


class TestCostSplit:
    def _plan(self, copay=0.0, coinsurance=0.0):
        payer = Payer(id='p', name='Payer', ownership='Private')
        return Plan(id='plan', payer=payer, name='Plan',
                    copay=copay, coinsurance=coinsurance)

    def test_the_uninsured_pay_everything(self):
        payer_share, patient = PayerManager.split(
            Coverage(plan=None, start=REFERENCE_DATE, kind='none'), 100.0)

        assert payer_share == 0.0
        assert patient == 100.0

    def test_no_coverage_at_all_is_the_same(self):
        assert PayerManager.split(None, 100.0) == (0.0, 100.0)

    def test_a_copay_comes_off_first(self):
        coverage = Coverage(plan=self._plan(copay=20.0, coinsurance=1.0),
                            start=REFERENCE_DATE, kind='private')
        payer_share, patient = PayerManager.split(coverage, 100.0)

        assert patient == 20.0
        assert payer_share == 80.0

    def test_coinsurance_splits_the_remainder(self):
        coverage = Coverage(plan=self._plan(coinsurance=0.8),
                            start=REFERENCE_DATE, kind='medicare')
        payer_share, patient = PayerManager.split(coverage, 100.0)

        assert payer_share == 80.0
        assert patient == 20.0

    def test_the_shares_always_sum_to_the_cost(self):
        coverage = Coverage(plan=self._plan(copay=15.0, coinsurance=0.7),
                            start=REFERENCE_DATE, kind='private')
        for cost in (0.0, 10.0, 15.0, 250.0, 9999.99):
            payer_share, patient = PayerManager.split(coverage, cost)
            assert payer_share + patient == pytest.approx(cost, abs=0.02)

    def test_a_copay_never_exceeds_the_cost(self):
        coverage = Coverage(plan=self._plan(copay=50.0),
                            start=REFERENCE_DATE, kind='private')
        payer_share, patient = PayerManager.split(coverage, 10.0)

        assert patient == 10.0
        assert payer_share == 0.0


class TestCosts:
    def test_known_codes_are_priced_from_the_table(self, person):
        """predniSONE is 2 / 7 / 25 in medications.csv."""
        costs = [CostTables.sample('medication', '312617', person)
                 for _ in range(50)]

        assert all(2 <= c <= 25 for c in costs), (min(costs), max(costs))
        assert len(set(costs)) > 1, "a triangular draw should vary"

    def test_an_unknown_code_falls_back(self, person):
        cost = CostTables.sample('procedure', 'not-a-code', person)
        assert cost > 0

    def test_cost_of_reads_the_first_code(self, person):
        from synthea.world.health_record import Code

        code = Code(system='RxNorm', code='312617', display='predniSONE')
        assert 2 <= cost_of('medication', [code], person) <= 25

    def test_pricing_is_reproducible(self):
        def priced():
            candidate = Person(seed=99)
            candidate.attributes['state'] = 'Massachusetts'
            return CostTables.sample('encounter', '185349003', candidate)

        assert priced() == priced()


class TestGeneratedPopulation:
    @pytest.fixture(scope='class')
    def people(self):
        return _population()

    def test_everyone_has_coverage_decided(self, people):
        for person in people:
            assert person.attributes.get('current_coverage') is not None

    def test_the_payer_mix_is_plausible(self, people):
        mix = collections.Counter(
            p.attributes['current_coverage'].kind for p in people)
        total = sum(mix.values())

        assert mix['private'] / total > 0.4, dict(mix)
        assert mix['private'] / total < 0.95, dict(mix)
        assert mix['medicaid'] / total < 0.45, dict(mix)

    def test_the_elderly_are_on_medicare(self, people):
        for person in people:
            if person.age_at(REFERENCE_DATE) >= MEDICARE_AGE:
                assert person.attributes['current_coverage'].kind == 'medicare'

    def test_coverage_does_not_churn_every_year(self, people):
        """The switch chance used to fire weekly, giving sixty-odd periods."""
        for person in people:
            periods = person.attributes.get('coverage_history') or []
            years = max(1, person.age_at(REFERENCE_DATE))
            assert len(periods) <= max(6, years / 5), (
                f"{len(periods)} coverage periods in {years:.0f} years")

    def test_encounters_are_priced_and_split(self, people):
        priced = [e for p in people for e in p.record.encounters if e.cost]
        assert priced

        for encounter in priced:
            assert encounter.cost > 0
            assert encounter.payer_cost is not None
            assert encounter.patient_cost is not None
            assert encounter.payer_cost + encounter.patient_cost == pytest.approx(
                encounter.cost, abs=0.02)

    def test_the_insured_pay_less_than_the_uninsured(self, people):
        def share(kind):
            entries = [e for p in people for e in p.record.encounters
                       if e.cost and e.coverage is not None
                       and e.coverage.kind == kind]
            if not entries:
                return None
            return sum(e.patient_cost for e in entries) / sum(e.cost for e in entries)

        uninsured = share('none')
        insured = share('private')

        if uninsured is not None and insured is not None:
            assert insured < uninsured

    def test_medications_are_priced_too(self, people):
        medications = [m for p in people for m in p.record.medications if m.cost]
        assert medications
