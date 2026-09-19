"""Tests for the core lifecycle: identity, growth, vitals, visits and mortality.

Before these modules existed every patient was nameless, ageless and immortal:
exported files were called ``Unknown_Person_*``, ages were drawn uniformly from
0 to 140, and nobody died unless a disease module killed them.

The population-level assertions here are deliberately loose bounds rather than
exact figures. Matching a real population closely is calibration work (#55,
#56); these tests exist to catch a model that has become implausible, not to
pin a distribution the engine does not yet claim to reproduce.
"""

import statistics
from datetime import datetime

import pytest

from synthea.engine.generator import Generator, GeneratorOptions
from synthea.engine.module import Module
from synthea.helpers.config import Config
from synthea.modules.core.encounter import interval_months
from synthea.world import mortality
from synthea.world.growth import GrowthCharts, bmi, z_score

REFERENCE_DATE = datetime(2020, 1, 1)


def _config(core_only=True):
    config = Config()
    config.load()
    config.set('exporter.fhir.export', False)
    config.set('exporter.json.export', False)
    if core_only:
        Module.load_modules()
        for name in Module.get_all_modules():
            if name not in Module.CORE_MODULE_ORDER:
                config.set(f'generate.{name}', False)
    return config


def _people(age_low, age_high, count=6, seed=11, core_only=True):
    options = GeneratorOptions()
    options.population_size = count
    options.seed = seed
    options.min_age = age_low
    options.max_age = age_high
    options.reference_date = REFERENCE_DATE
    generator = Generator(options, config=_config(core_only))
    return [p for p in (generator.generate_person(i) for i in range(count)) if p]


# ----------------------------------------------------------------------
# Identity
# ----------------------------------------------------------------------

class TestIdentity:
    def test_patients_have_names(self):
        """Regression: every exported file used to be Unknown_Person_*."""
        for person in _people(30, 60, count=5):
            assert person.attributes.get('first_name')
            assert person.attributes.get('last_name')

    def test_patients_have_an_address_and_contact_details(self):
        person = _people(30, 60, count=1)[0]
        assert person.attributes.get('address')
        assert person.attributes.get('telephone')
        assert person.attributes.get('email')

    def test_identifiers_cannot_collide_with_real_ones(self):
        """SSNs use the 999 area, which has never been issued."""
        for person in _people(30, 60, count=5):
            assert person.attributes['identifier_ssn'].startswith('999-')
            assert person.attributes['identifier_mrn']
            # 555 telephone exchanges are reserved for fiction.
            assert person.attributes['telephone'].startswith('555-')
            assert person.attributes['email'].endswith('@example.com')

    def test_children_have_no_driving_licence(self):
        for person in _people(5, 10, count=4):
            assert 'identifier_drivers' not in person.attributes

    def test_adults_have_marital_status_and_children_do_not(self):
        assert 'marital_status' in _people(40, 40, count=1)[0].attributes
        assert 'marital_status' not in _people(8, 8, count=1)[0].attributes

    def test_identity_is_reproducible(self):
        first = _people(40, 40, count=1, seed=99)[0]
        second = _people(40, 40, count=1, seed=99)[0]
        assert first.attributes['first_name'] == second.attributes['first_name']
        assert first.attributes['identifier_ssn'] == second.attributes['identifier_ssn']


# ----------------------------------------------------------------------
# Growth
# ----------------------------------------------------------------------

class TestGrowth:
    def test_z_score_matches_known_percentiles(self):
        assert z_score(0.5) == pytest.approx(0.0, abs=1e-6)
        assert z_score(0.975) == pytest.approx(1.95996, abs=1e-4)
        assert z_score(0.025) == pytest.approx(-1.95996, abs=1e-4)

    def test_charts_are_ordered_by_percentile(self):
        low = GrowthCharts.value_at('height', 'M', 120, 0.10)
        mid = GrowthCharts.value_at('height', 'M', 120, 0.50)
        high = GrowthCharts.value_at('height', 'M', 120, 0.90)
        assert low < mid < high

    def test_children_grow_monotonically(self):
        heights = [GrowthCharts.value_at('height', 'F', months, 0.5)
                   for months in (12, 36, 60, 120, 180, 240)]
        assert all(b > a for a, b in zip(heights, heights[1:]))

    def test_a_child_tracks_one_percentile_over_time(self):
        """Height at 5 and at 15 come from the same percentile, not two draws."""
        person = _people(5, 5, count=1, seed=7)[0]
        percentile = person.attributes['growth_percentile_height']
        assert 0.0 < percentile < 1.0

        older = _people(15, 15, count=1, seed=7)[0]
        assert older.attributes['growth_percentile_height'] == percentile

    def test_adult_height_stops_changing(self):
        at_forty = _people(40, 40, count=1, seed=7)[0].get_vital_sign('Height')
        at_seventy = _people(70, 70, count=1, seed=7)[0].get_vital_sign('Height')
        assert at_forty == pytest.approx(at_seventy, abs=0.2)

    def test_bmi_is_derived_from_height_and_weight(self):
        person = _people(40, 40, count=1)[0]
        height = person.get_vital_sign('Height')
        weight = person.get_vital_sign('Weight')
        assert person.get_vital_sign('Body Mass Index') == pytest.approx(
            bmi(weight, height), abs=0.1,
        )

    def test_adult_population_is_not_implausibly_heavy(self):
        """Guards the pounds-per-year reading of adult_weight_gain.

        Read as kilograms the same data gave a mean BMI of 32 with two thirds
        of adults obese, which is well outside any real population.
        """
        values = [p.get_vital_sign('Body Mass Index')
                  for p in _people(20, 79, count=40, seed=21) if p.alive]
        values = [v for v in values if v]

        assert 24 < statistics.mean(values) < 31
        assert 0.55 < sum(1 for v in values if v >= 25) / len(values) < 0.90


# ----------------------------------------------------------------------
# Vital signs
# ----------------------------------------------------------------------

class TestVitalSigns:
    def test_every_patient_has_vitals(self):
        person = _people(40, 40, count=1)[0]
        for vital in ('Height', 'Weight', 'Body Mass Index', 'Heart Rate',
                      'Respiration Rate', 'Oxygen Saturation',
                      'Systolic Blood Pressure', 'Diastolic Blood Pressure'):
            assert person.get_vital_sign(vital) is not None, vital

    def test_vitals_are_physiologically_plausible(self):
        for person in _people(25, 65, count=6):
            assert 90 <= person.get_vital_sign('Systolic Blood Pressure') <= 200
            assert 40 <= person.get_vital_sign('Heart Rate') <= 140
            assert 85 <= person.get_vital_sign('Oxygen Saturation') <= 100

    def test_systolic_exceeds_diastolic(self):
        for person in _people(25, 65, count=6):
            assert (person.get_vital_sign('Systolic Blood Pressure')
                    > person.get_vital_sign('Diastolic Blood Pressure'))

    def test_vitals_are_recorded_at_every_visit(self):
        """Regression: visits used to be empty containers."""
        person = _people(45, 45, count=1)[0]
        wellness = [e for e in person.record.encounters
                    if e.encounter_class.value == 'wellness']
        assert wellness

        for encounter in wellness:
            names = {o.name for o in encounter.observations}
            assert {'Height', 'Weight', 'Body Mass Index'} <= names
            assert all(o.category == 'vital-signs' for o in encounter.observations)

    def test_blood_pressure_is_one_observation_with_components(self):
        person = _people(45, 45, count=1)[0]
        panels = [o for e in person.record.encounters for o in e.observations
                  if o.name == 'Blood Pressure']
        assert panels
        assert len(panels[0].components) == 2


# ----------------------------------------------------------------------
# Routine visits
# ----------------------------------------------------------------------

class TestWellnessEncounters:
    def test_interval_widens_then_narrows_with_age(self):
        assert interval_months(0.5) < interval_months(10)
        assert interval_months(10) < interval_months(30)
        assert interval_months(70) < interval_months(30)

    def test_patients_attend_check_ups(self):
        person = _people(45, 45, count=1)[0]
        wellness = [e for e in person.record.encounters
                    if e.encounter_class.value == 'wellness']
        # Annual from 20, three-yearly before that: roughly 20 to 40 visits.
        assert 10 <= len(wellness) <= 60

    def test_visits_are_spread_over_the_patients_life(self):
        person = _people(45, 45, count=1)[0]
        times = sorted(e.time for e in person.record.encounters
                       if e.encounter_class.value == 'wellness')
        span_years = (times[-1] - times[0]).days / 365.25
        assert span_years > 20, "visits must not all fall in the first weeks"


# ----------------------------------------------------------------------
# Immunizations
# ----------------------------------------------------------------------

class TestImmunizations:
    def test_children_are_vaccinated(self):
        """Regression: the bundled schedule was never read."""
        for person in _people(6, 6, count=4):
            assert len(person.record.immunizations) > 20

    def test_vaccines_are_given_at_a_visit(self):
        person = _people(6, 6, count=1)[0]
        assert all(i.encounter is not None for i in person.record.immunizations)

    def test_vaccines_carry_cvx_codes(self):
        person = _people(6, 6, count=1)[0]
        for immunization in person.record.immunizations:
            assert immunization.codes
            assert 'cvx' in immunization.codes[0].system.lower()

    def test_older_patients_have_more_doses(self):
        young = len(_people(6, 6, count=1, seed=5)[0].record.immunizations)
        older = len(_people(30, 30, count=1, seed=5)[0].record.immunizations)
        assert older > young, "annual vaccines should accumulate"


# ----------------------------------------------------------------------
# Mortality
# ----------------------------------------------------------------------

class TestMortality:
    def test_life_expectancy_is_plausible(self):
        """The fitted parameters must keep producing a realistic population."""
        male = mortality.life_expectancy('M')
        female = mortality.life_expectancy('F')

        assert 72 < male < 80
        assert 77 < female < 85
        assert female > male

    def test_hazard_rises_with_age(self):
        ages = [20, 40, 60, 80, 95]
        hazards = [mortality.hazard(age, 'M') for age in ages]
        assert all(b > a for a, b in zip(hazards, hazards[1:]))

    def test_infancy_is_riskier_than_early_childhood(self):
        assert mortality.hazard(0, 'F') > mortality.hazard(5, 'F')

    def test_probability_scales_with_the_interval(self):
        annual = mortality.probability_of_death(70, 'M', 1.0)
        weekly = mortality.probability_of_death(70, 'M', 7 / 365.25)
        assert 0 < weekly < annual < 1

    def test_some_patients_die_of_natural_causes(self):
        """Regression: without background mortality nobody ever died."""
        people = _people(0, 95, count=40, seed=4)
        assert any(not p.alive for p in people)

    def test_the_dead_have_a_death_date_on_the_record(self):
        people = _people(0, 95, count=40, seed=4)
        for person in (p for p in people if not p.alive):
            assert person.attributes.get('death_date')
            assert person.record.death_date is not None


class TestVaccineState:
    """Vaccines a disease module gives for its own reasons."""

    def test_a_module_driven_vaccine_is_recorded(self):
        """Regression: the Vaccine state was mapped to a no-op."""
        from datetime import datetime as _dt

        from synthea.engine.module import Module as _Module
        from synthea.engine.state import VaccineState
        from synthea.world.person import Person

        person = Person(seed=31)
        person.init_health_record()
        encounter = person.record.encounter_start(_dt(2020, 1, 1), 'ambulatory')
        person.attributes['current_encounter'] = encounter

        VaccineState(_Module('hiv_care'), 'Administer Tdap', {
            'type': 'Vaccine',
            'series': 1,
            'codes': [{'system': 'CVX', 'code': 115, 'display': 'Tdap'}],
        }).run(person, _dt(2020, 1, 1))

        assert len(person.record.immunizations) == 1
        immunization = person.record.immunizations[0]
        assert immunization.encounter is encounter
        assert immunization.dose_number == 1

    def test_without_a_visit_nothing_is_recorded(self):
        from datetime import datetime as _dt

        from synthea.engine.module import Module as _Module
        from synthea.engine.state import VaccineState
        from synthea.world.person import Person

        person = Person(seed=31)
        person.init_health_record()

        VaccineState(_Module('hiv_care'), 'Administer Tdap', {
            'type': 'Vaccine',
            'codes': [{'system': 'CVX', 'code': 115, 'display': 'Tdap'}],
        }).run(person, _dt(2020, 1, 1))

        assert person.record.immunizations == []
