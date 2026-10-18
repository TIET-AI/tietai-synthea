"""Tests for the cardiovascular risk calculators and the module that applies them.

The myocardial infarction, stable ischemic heart disease, atrial fibrillation
and stroke modules each wait on a distributed transition weighted by a risk
attribute (``mi_risk``, ``ihd_risk``, ``atrial_fibrillation_risk``,
``stroke_risk``). Upstream sets those in Java; until they were ported nothing
set them, the weight defaulted to 0, and none of the four conditions ever
occurred.
"""

from datetime import datetime

import pytest

from synthea.engine.module import Module
from synthea.modules.core.cardiovascular_disease import CardiovascularDiseaseModule
from synthea.modules.core.lifecycle import LifecycleModule, likelihood_of_smoking
from synthea.world import cardiovascular_risk as risk
from synthea.world.person import Person

NOW = datetime(2020, 6, 1)


def _person(age, gender='F', race='white', systolic=120.0, chol=213.0, hdl=50.0,
            bmi=25.0, **attributes):
    person = Person(seed=7)
    person.attributes['birth_date'] = datetime(NOW.year - age, 1, 1)
    person.attributes['gender'] = gender
    person.attributes['race'] = race
    person.attributes['timestep_years'] = 7 / 365.25
    person.attributes.update(attributes)
    for name, value in (('Systolic Blood Pressure', systolic),
                        ('Diastolic Blood Pressure', 80.0),
                        ('Total Cholesterol', chol), ('HDL', hdl),
                        ('Body Mass Index', bmi)):
        if value is not None:
            person.set_vital_sign(name, value, None, NOW)
    return person


class TestAscvd:
    # The worked example published with the Pooled Cohort Equations (Goff et
    # al. 2013, Appendix 7 Table B): age 55, total cholesterol 213, HDL 50,
    # untreated systolic 120, non-smoker, not diabetic. The table is quoted to
    # one decimal place from unrounded coefficients, hence the tolerance.
    @pytest.mark.parametrize('gender,race,expected', [
        ('F', 'white', 0.021),
        ('F', 'black', 0.030),
        ('M', 'white', 0.053),
        ('M', 'black', 0.061),
    ])
    def test_matches_the_published_worked_example(self, gender, race, expected):
        person = _person(55, gender, race)
        assert risk.ascvd_10_year(person, NOW) == pytest.approx(expected, abs=0.001)

    def test_outside_40_to_79_has_no_score(self):
        assert risk.ascvd_10_year(_person(39), NOW) == -1
        assert risk.ascvd_10_year(_person(80), NOW) == -1

    def test_missing_lipids_have_no_score(self):
        assert risk.ascvd_10_year(_person(55, chol=None), NOW) == -1

    def test_risk_factors_raise_it(self):
        base = risk.ascvd_10_year(_person(55, 'M'), NOW)
        assert risk.ascvd_10_year(_person(55, 'M', smoker=True), NOW) > base
        assert risk.ascvd_10_year(_person(55, 'M', diabetes=True), NOW) > base


class TestFramingham:
    def test_chd_bands_truncate_like_upstream(self):
        # Upstream's integer division truncates toward zero, so a cholesterol of
        # 150 scores in the 160-199 band; floor division would not.
        low = risk.chd_10_year(_person(50, 'M', chol=150.0), NOW)
        band = risk.chd_10_year(_person(50, 'M', chol=170.0), NOW)
        assert low == band

    def test_af_starts_at_45_and_stops_once_diagnosed(self):
        assert risk.atrial_fibrillation_10_year(_person(44), NOW) == -1
        assert risk.atrial_fibrillation_10_year(_person(70, 'M'), NOW) == 0.08
        assert risk.atrial_fibrillation_10_year(
            _person(70, 'M', atrial_fibrillation=object()), NOW) == -1

    def test_af_points(self):
        # Male 70-74: 6 points; obese, SBP >= 160 and treated add one each.
        person = _person(72, 'M', systolic=165.0, bmi=31.0, blood_pressure_controlled=True)
        assert risk.atrial_fibrillation_10_year(person, NOW) == 0.22

    def test_stroke_by_age_band(self):
        assert risk.stroke_10_year(_person(19), NOW) == -1
        assert risk.stroke_10_year(_person(30, 'M'), NOW) == 0.002
        assert risk.stroke_10_year(_person(50, 'F'), NOW) == 0.022
        older = risk.stroke_10_year(_person(70, 'M'), NOW)
        with_af = risk.stroke_10_year(_person(70, 'M', atrial_fibrillation=object()), NOW)
        assert 0 < older < with_af


class TestModule:
    def test_runs_as_a_core_module_after_lifecycle(self):
        order = Module.CORE_MODULE_ORDER
        assert order.index('lifecycle') < order.index('cardiovascular_disease')

    def test_sets_the_attributes_the_heart_modules_read(self):
        person = _person(65, 'M', systolic=150.0, hypertension=True)
        CardiovascularDiseaseModule().process(person, NOW)
        ten_year = person.attributes['ascvd_risk']
        monthly = risk.convert_risk_to_timestep(ten_year, 3650, 30)
        assert person.attributes['mi_risk'] == pytest.approx(monthly)
        # Calibrated default (calibration.cardiovascular.ihd_risk_multiplier).
        assert person.attributes['ihd_risk'] == pytest.approx(1.5 * monthly)
        assert person.attributes['atrial_fibrillation_risk'] > 0
        assert person.attributes['stroke_risk'] > 0

    def test_calibration_settings_are_honoured(self):
        """Upstream's values, set through calibration.*, reproduce upstream."""
        person = _person(65, 'M', systolic=150.0, hypertension=True)
        person.attributes['calibration.cardiovascular.ihd_risk_multiplier'] = 5
        person.attributes['calibration.cardiovascular.af_risk_period_days'] = 0
        CardiovascularDiseaseModule().process(person, NOW)

        monthly = risk.convert_risk_to_timestep(person.attributes['ascvd_risk'], 3650, 30)
        weekly_af = risk.convert_risk_to_timestep(
            risk.atrial_fibrillation_10_year(person, NOW), 3650, risk.timestep_days(person))
        assert person.attributes['ihd_risk'] == pytest.approx(5 * monthly)
        assert person.attributes['atrial_fibrillation_risk'] == pytest.approx(weekly_af)

    def test_no_score_is_no_risk(self):
        person = _person(10)
        CardiovascularDiseaseModule().process(person, NOW)
        for name in ('mi_risk', 'ihd_risk', 'atrial_fibrillation_risk', 'stroke_risk'):
            assert person.attributes[name] <= 0


class TestSmoking:
    def test_prevalence_by_year(self):
        assert likelihood_of_smoking(1950) == 0.424
        assert likelihood_of_smoking(2015) == pytest.approx(0.161, abs=0.002)

    def test_decided_at_16(self):
        person = _person(16)
        LifecycleModule()._smoking(person, NOW)
        assert isinstance(person.attributes['smoker'], bool)
        assert person.attributes['quit smoking probability'] == pytest.approx(0.01)
