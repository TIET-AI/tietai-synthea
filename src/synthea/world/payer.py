"""Who pays for care.

The payer tables have shipped since 1.2.0 and nothing read them: every patient
was uninsured, no encounter had a payer, and there were no claims. A record
without coverage cannot exercise a payer mix, an eligibility rule, or a claims
pipeline — which is a large part of what synthetic health data is used for.

Eligibility here is **deliberately simplified**. The upstream project drives it
from poverty multipliers, spend-down files and qualifying-code lists; this uses
age and socioeconomic status:

    65 or over            -> Medicare
    low income           -> Medicaid, or uninsured
    otherwise            -> a private plan available in the patient's state

That reproduces the shape of the United States payer mix without pretending to
implement means testing. Doing it properly belongs with the target-data work in
#55, and the resulting payer mix is asserted against published shares by test so
the simplification cannot drift unnoticed.
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, TYPE_CHECKING

from synthea.helpers.resources import resource_path
from synthea.helpers.rng import random_seed

logger = logging.getLogger(__name__)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from synthea.world.person import Person

#: Age at which Medicare eligibility begins.
MEDICARE_AGE = 65

#: Share of low-income adults who end up on Medicaid rather than uninsured.
#: The rest are the coverage gap, which is a real feature of the population.
MEDICAID_TAKEUP = 0.74

#: Share of working-age adults with private coverage who get it through an
#: employer rather than buying it directly. Recorded on the coverage so a
#: consumer can tell the two apart.
EMPLOYER_SHARE = 0.83


@dataclass
class Payer:
    """An insurance company."""
    id: str
    name: str
    ownership: str
    states_covered: List[str] = field(default_factory=list)

    def covers_state(self, state: str) -> bool:
        """Whether the payer operates in a state."""
        if not self.states_covered or '*' in self.states_covered:
            return True
        return _state_code(state) in {_state_code(s) for s in self.states_covered}


@dataclass
class Plan:
    """A specific insurance product."""
    id: str
    payer: Payer
    name: str
    deductible: float = 0.0
    coinsurance: float = 0.0
    copay: float = 0.0
    monthly_premium: float = 0.0
    max_out_of_pocket: float = 0.0
    eligibility: str = ''


@dataclass
class Coverage:
    """A patient's insurance over a period."""
    plan: Optional[Plan]
    start: datetime
    end: Optional[datetime] = None
    kind: str = 'none'          # medicare | medicaid | private | none
    via_employer: bool = False

    @property
    def is_insured(self) -> bool:
        return self.plan is not None


#: The plan every uninsured patient "has", so downstream code never has to
#: special-case a missing payer.
NO_INSURANCE = Payer(id='no-insurance', name='NO_INSURANCE',
                     ownership='NO_INSURANCE', states_covered=['*'])


class CoveragePolicy:
    """Who is covered by what. Locale packs supply one; see `coverage_policy`.

    Two questions, kept apart so a patient can keep the same plan while their
    eligibility is unchanged:

    - `kind_for` - which kind of cover the patient qualifies for at an age
      (`medicare`, `public`, `private`, `none`, ...);
    - `coverage_for` - the concrete :class:`Coverage` for that kind.

    Every random draw must come from `person.random`.
    """

    def kind_for(self, manager: 'PayerManager', person: 'Person',
                 age: float) -> str:  # pragma: no cover - interface
        raise NotImplementedError

    def coverage_for(self, manager: 'PayerManager', person: 'Person',
                     age: float, time: datetime,
                     kind: str) -> Coverage:  # pragma: no cover - interface
        raise NotImplementedError


class UnitedStatesCoverage(CoveragePolicy):
    """The engine default: simplified United States eligibility.

    65 or over -> Medicare; low income -> Medicaid where taken up, otherwise
    uninsured; everyone else -> a private plan available in their state. The
    order of random draws is part of the contract (seeded runs depend on it).
    """

    def kind_for(self, manager, person, age):
        if age >= MEDICARE_AGE:
            return 'medicare'

        status = str(person.attributes.get('socioeconomic_status', 'middle')).lower()
        if status != 'low':
            return 'private'

        # Low income: Medicaid where it is taken up, otherwise the coverage
        # gap, which is a real feature of the population rather than an
        # omission. Decided once per patient, not per year, because churning
        # in and out of Medicaid annually is not what happens.
        settled = person.attributes.get('medicaid_enrolled')
        if settled is None:
            settled = person.random.random() < MEDICAID_TAKEUP
            person.attributes['medicaid_enrolled'] = settled

        return 'medicaid' if settled else 'none'

    def coverage_for(self, manager, person, age, time, kind):
        state = person.attributes.get('state')

        if kind == 'medicare':
            plans = manager._plans_for('MedicareEligible')
            if plans:
                return Coverage(plan=person.random.choice(plans), start=time,
                                kind='medicare')

        if kind == 'medicaid':
            plans = manager._plans_for('MedicaidEligible')
            if plans:
                return Coverage(plan=person.random.choice(plans), start=time,
                                kind='medicaid')

        if kind == 'private':
            plans = manager._private_plans(state)
            if plans:
                return Coverage(
                    plan=person.random.choice(plans),
                    start=time,
                    kind='private',
                    via_employer=person.random.random() < EMPLOYER_SHARE,
                )

        return Coverage(plan=None, start=time, kind='none')


class UniversalCoverage(CoveragePolicy):
    """Everyone is covered, from birth, by the plans of one eligibility policy.

    The shape of a tax-funded national health system: cover is a right of
    residence, not of age, income or employment. `eligibility` selects plans
    by their `Eligibility Policy` column; with several, one is drawn per
    patient (the draw is made once and kept).
    """

    def __init__(self, eligibility: str, kind: str = 'public'):
        self.eligibility = eligibility
        self.kind = kind

    def kind_for(self, manager, person, age):
        return self.kind

    def coverage_for(self, manager, person, age, time, kind):
        plans = manager._plans_for(self.eligibility)
        if not plans:
            return Coverage(plan=None, start=time, kind='none')
        plan = plans[0] if len(plans) == 1 else person.random.choice(plans)
        return Coverage(plan=plan, start=time, kind=kind)


class PayerManager:
    """Loads payers and plans, and decides who covers a patient."""

    def __init__(self, seed: Optional[int] = None,
                 policy: Optional[CoveragePolicy] = None):
        self.payers: Dict[str, Payer] = {}
        self.plans: Dict[str, Plan] = {}
        self.plans_by_eligibility: Dict[str, List[Plan]] = {}
        self._seed = seed if seed is not None else random_seed()
        self.policy: CoveragePolicy = policy or UnitedStatesCoverage()

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def load(self, pack=None):
        """Load payers and their plans: the pack's files, else the bundled.

        A pack's coverage policy, if it has one, replaces the default.
        """
        payers_path = resource_path('payers', 'insurance_companies.csv')
        plans_path = resource_path('payers', 'insurance_plans.csv')
        if pack is not None:
            if getattr(pack, 'coverage_policy', None) is not None:
                self.policy = pack.coverage_policy
            if getattr(pack, 'payers_file', None):
                payers_path = pack.data_path(pack.payers_file)
            if getattr(pack, 'plans_file', None):
                plans_path = pack.data_path(pack.plans_file)

        if payers_path is not None:
            self._load_payers(payers_path)
        if plans_path is not None:
            self._load_plans(plans_path)

        if not self.plans:
            logger.warning(
                "No insurance plans found; every patient will be uninsured.")

    def _load_payers(self, path=None):
        path = path or resource_path('payers', 'insurance_companies.csv')
        if not path.exists():
            return
        try:
            with open(path, 'r', encoding='utf-8-sig', newline='') as handle:
                for row in csv.DictReader(handle):
                    identifier = (row.get('Id') or '').strip()
                    name = (row.get('Name') or '').strip()
                    if not identifier or not name:
                        continue
                    covered = (row.get('States Covered') or '*').strip()
                    self.payers[identifier] = Payer(
                        id=identifier,
                        name=name,
                        ownership=(row.get('Ownership') or 'Private').strip(),
                        states_covered=[s.strip() for s in covered.split('|') if s.strip()],
                    )
        except Exception as error:  # pragma: no cover - defensive
            logger.warning("Could not read payers from %s: %s", path, error)

    def _load_plans(self, path=None):
        path = path or resource_path('payers', 'insurance_plans.csv')
        if not path.exists():
            return
        try:
            with open(path, 'r', encoding='utf-8-sig', newline='') as handle:
                for row in csv.DictReader(handle):
                    payer = self.payers.get((row.get('Payer Id') or '').strip())
                    plan_id = (row.get('Plan Id') or '').strip()
                    if payer is None or not plan_id:
                        continue

                    plan = Plan(
                        id=plan_id,
                        payer=payer,
                        name=(row.get('Name') or payer.name).strip(),
                        deductible=_as_float(row.get('Deductible'), 0.0),
                        coinsurance=_as_float(row.get('Default Coinsurance'), 0.0),
                        copay=_as_float(row.get('Default Copay'), 0.0),
                        monthly_premium=_as_float(row.get('Monthly Premium'), 0.0),
                        max_out_of_pocket=_as_float(row.get('Max Out of Pocket'), 0.0),
                        eligibility=(row.get('Eligibility Policy') or '').strip(),
                    )
                    self.plans[plan_id] = plan
                    self.plans_by_eligibility.setdefault(
                        plan.eligibility, []).append(plan)
        except Exception as error:  # pragma: no cover - defensive
            logger.warning("Could not read plans from %s: %s", path, error)

    # ------------------------------------------------------------------
    # Eligibility
    # ------------------------------------------------------------------

    def _plans_for(self, policy: str) -> List[Plan]:
        return self.plans_by_eligibility.get(policy, [])

    def _private_plans(self, state: Optional[str]) -> List[Plan]:
        """Plans that are neither Medicare nor Medicaid and cover the state."""
        public = {'MedicareEligible', 'MedicaidEligible', 'DualEligible'}
        candidates = [
            plan for policy, plans in self.plans_by_eligibility.items()
            if policy not in public
            for plan in plans
        ]
        if state:
            covering = [p for p in candidates if p.payer.covers_state(state)]
            if covering:
                return covering
        return candidates

    def kind_for(self, person: 'Person', age: float) -> str:
        """Which kind of cover a patient qualifies for at this age.

        Separate from plan selection so a patient can keep the same plan while
        their eligibility is unchanged. Decided by the coverage policy.
        """
        return self.policy.kind_for(self, person, age)

    def coverage_for(self, person: 'Person', age: float, time: datetime,
                     kind: Optional[str] = None) -> Coverage:
        """The coverage a patient should have at this age."""
        kind = kind or self.kind_for(person, age)
        return self.policy.coverage_for(self, person, age, time, kind)

    # ------------------------------------------------------------------
    # Paying
    # ------------------------------------------------------------------

    @staticmethod
    def split(coverage: Optional[Coverage], cost: float) -> tuple:
        """Split a cost into (payer share, patient share).

        A copay is taken first, then coinsurance applies to the rest. This is a
        simplification: real adjudication runs the deductible down over the
        plan year and stops at the out-of-pocket maximum. What matters for a
        generated claim is that the two shares are plausible and sum to the
        total.
        """
        if coverage is None or not coverage.is_insured:
            return 0.0, round(cost, 2)

        plan = coverage.plan
        patient = min(cost, plan.copay)
        remainder = cost - patient

        # The file stores "Default Coinsurance" as the share the *payer*
        # covers, which is why Medicare reads 0.8.
        payer_share = remainder * plan.coinsurance
        patient += remainder - payer_share

        return round(payer_share, 2), round(patient, 2)


def _as_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


_STATE_CODES = {
    'alabama': 'AL', 'alaska': 'AK', 'arizona': 'AZ', 'arkansas': 'AR',
    'california': 'CA', 'colorado': 'CO', 'connecticut': 'CT', 'delaware': 'DE',
    'district of columbia': 'DC', 'florida': 'FL', 'georgia': 'GA',
    'hawaii': 'HI', 'idaho': 'ID', 'illinois': 'IL', 'indiana': 'IN',
    'iowa': 'IA', 'kansas': 'KS', 'kentucky': 'KY', 'louisiana': 'LA',
    'maine': 'ME', 'maryland': 'MD', 'massachusetts': 'MA', 'michigan': 'MI',
    'minnesota': 'MN', 'mississippi': 'MS', 'missouri': 'MO', 'montana': 'MT',
    'nebraska': 'NE', 'nevada': 'NV', 'new hampshire': 'NH', 'new jersey': 'NJ',
    'new mexico': 'NM', 'new york': 'NY', 'north carolina': 'NC',
    'north dakota': 'ND', 'ohio': 'OH', 'oklahoma': 'OK', 'oregon': 'OR',
    'pennsylvania': 'PA', 'rhode island': 'RI', 'south carolina': 'SC',
    'south dakota': 'SD', 'tennessee': 'TN', 'texas': 'TX', 'utah': 'UT',
    'vermont': 'VT', 'virginia': 'VA', 'washington': 'WA',
    'west virginia': 'WV', 'wisconsin': 'WI', 'wyoming': 'WY',
}


def _state_code(state: str) -> str:
    return _STATE_CODES.get(str(state).strip().lower(), str(state).strip().upper())
