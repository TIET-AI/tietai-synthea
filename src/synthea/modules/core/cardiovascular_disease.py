"""Cardiovascular disease risk: the attributes the heart-disease modules read.

A port of upstream Synthea's ``CardiovascularDiseaseModule``
(``src/main/java/org/mitre/synthea/modules/CardiovascularDiseaseModule.java``).
Upstream converted most of that class into generic JSON modules, but kept the
annual risk numbers in Java, and the JSON modules still depend on them:

=============================== ==============================================
Attribute                       Read by
=============================== ==============================================
``mi_risk``                     ``myocardial_infarction`` (``Chance_of_MI``)
``ihd_risk``                    ``stable_ischemic_heart_disease``
``atrial_fibrillation_risk``    ``atrial_fibrillation`` (``Chance_of_AFib``)
``stroke_risk``                 ``stroke`` (``Chance_of_Stroke``)
=============================== ==============================================

Each of those modules loops on a one-month Delay with a distributed transition
whose weight is ``{"attribute": "<x>_risk", "default": 0}``. Without this module
nothing set them, so the weight was always 0 and no patient ever had a heart
attack, ischemic heart disease, atrial fibrillation or a stroke.

The scores themselves are in :mod:`synthea.world.cardiovascular_risk`. It runs
after :mod:`lifecycle`, which sets the blood pressure, lipids and BMI they need.

How the scores become per-period risks is calibration, read from the
``calibration.*`` settings in ``synthea.properties`` (copied onto every patient
by the generator), so it can be tuned without touching code.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from synthea.engine.module import Module
from synthea.world import cardiovascular_risk as risk
from synthea.world.calibration import calibration

if TYPE_CHECKING:  # pragma: no cover - typing only
    from synthea.world.person import Person

#: Upstream ``oneMonthInMS``: 30 days.
ONE_MONTH_DAYS = 30.0

#: ``calibration.cardiovascular.ihd_risk_multiplier``: ``ihd_risk`` is the
#: monthly ASCVD risk times this. Upstream hard-codes 5 "to account for the
#: relative prevalence of the various outcomes".
IHD_RISK_MULTIPLIER = 'cardiovascular.ihd_risk_multiplier'

#: ``calibration.cardiovascular.af_risk_period_days`` and ``...stroke_...``:
#: the period each 10-year risk is converted to. The modules test these once a
#: month; upstream converts them to the simulation timestep (a week), which
#: makes both about four times rarer than their scores say. 0 means the
#: timestep, as upstream.
AF_RISK_PERIOD_DAYS = 'cardiovascular.af_risk_period_days'
STROKE_RISK_PERIOD_DAYS = 'cardiovascular.stroke_risk_period_days'


class CardiovascularDiseaseModule(Module):
    """Refreshes the cardiovascular risk attributes every timestep."""

    #: Upstream's ``useFramingham`` switch, off by default: coronary risk comes
    #: from the ASCVD pooled cohort equations rather than Framingham CHD points.
    USE_FRAMINGHAM = False

    def __init__(self):
        super().__init__('cardiovascular_disease')

    def process(self, person: 'Person', time: datetime) -> bool:
        if not person.alive:
            return True

        step_days = risk.timestep_days(person)

        if self.USE_FRAMINGHAM:
            ten_year = risk.chd_10_year(person, time)
            person.attributes['framingham_risk'] = ten_year
        else:
            ten_year = risk.ascvd_10_year(person, time)
            person.attributes['ascvd_risk'] = ten_year

        person.attributes['cardio_risk'] = risk.convert_risk_to_timestep(
            ten_year, risk.TEN_YEARS_DAYS, step_days)
        monthly = risk.convert_risk_to_timestep(
            ten_year, risk.TEN_YEARS_DAYS, ONE_MONTH_DAYS)
        person.attributes['mi_risk'] = monthly
        person.attributes['ihd_risk'] = monthly * calibration(
            person, IHD_RISK_MULTIPLIER, 1.5)

        af_period = calibration(person, AF_RISK_PERIOD_DAYS, 30.0) or step_days
        stroke_period = calibration(person, STROKE_RISK_PERIOD_DAYS, 15.0) or step_days
        person.attributes['atrial_fibrillation_risk'] = risk.convert_risk_to_timestep(
            risk.atrial_fibrillation_10_year(person, time), risk.TEN_YEARS_DAYS, af_period)
        person.attributes['stroke_risk'] = risk.convert_risk_to_timestep(
            risk.stroke_10_year(person, time), risk.TEN_YEARS_DAYS, stroke_period)

        # Upstream: "java modules will never finish". Risk is refreshed each step.
        return False
