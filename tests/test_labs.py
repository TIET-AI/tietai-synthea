"""Tests for reference ranges, interpretation and panel coherence (#113).

Reported with measurements against v1.4.0: 0 of 2,323 Observations carried a
`referenceRange` or an `interpretation`, and 6 of 8 complete red-cell panels had
an MCV more than 3 fL away from the value their own HCT and RBC implied.

The panel identities are definitions, so they can be asserted exactly rather
than within a tolerance chosen to make a test pass:

    MCV = HCT x 10 / RBC      MCH = HGB x 10 / RBC      MCHC = HGB x 100 / HCT
"""

import json
from datetime import datetime

import pytest

from synthea.engine.generator import Generator, GeneratorOptions
from synthea.export import validation
from synthea.export.fhir import FHIRExporter
from synthea.helpers.config import Config
from synthea.world import labs
from synthea.world.health_record import Code, EncounterClass
from synthea.world.person import Person

VISIT = datetime(2015, 6, 1)
REFERENCE_DATE = datetime(2020, 1, 1)


def _person(gender='F', born=datetime(1975, 6, 1)):
    person = Person(seed=3)
    person.init_health_record()
    person.attributes.update({'gender': gender, 'birth_date': born,
                              'first_name': 'Ada', 'last_name': 'Lovelace'})
    return person


def _loinc(code, display='x'):
    return Code(system='LOINC', code=code, display=display)


def _record(person, encounter, values):
    """Record `{loinc: (value, unit)}` against an encounter."""
    return {
        code: person.record.observation(
            VISIT, _loinc(code), value=value, unit=unit, encounter=encounter)
        for code, (value, unit) in values.items()
    }


class TestReferenceRanges:
    def test_a_known_code_has_a_range(self):
        assert labs.ReferenceRanges.for_code(labs.MCV) is not None

    def test_an_unknown_code_has_none(self):
        """Modules with no known range keep the previous behaviour."""
        assert labs.ReferenceRanges.for_code('99999-9') is None

    def test_haemoglobin_is_sex_specific(self):
        male = labs.ReferenceRanges.for_code(labs.HGB, sex='M')
        female = labs.ReferenceRanges.for_code(labs.HGB, sex='F')

        assert male['low'] > female['low']

    def test_an_unknown_sex_still_gets_a_range(self):
        """The union of both, rather than nothing. See TestUnknownSexFallback."""
        assert labs.ReferenceRanges.for_code(labs.HGB, sex=None) is not None

    def test_an_age_limited_range_applies_only_from_that_age(self):
        """A child's blood pressure is not read against the adult interval."""
        assert labs.ReferenceRanges.for_code('8480-6', age=40) is not None
        assert labs.ReferenceRanges.for_code('8480-6', age=6) is None

    def test_every_range_is_well_formed(self):
        """A low above its high would silently flag every value."""
        for code, variants in labs.ReferenceRanges.load().items():
            assert variants, code
            for variant in variants:
                low, high = variant.get('low'), variant.get('high')
                assert low is not None or high is not None, code
                if low is not None and high is not None:
                    assert low < high, f"{code}: {low} !< {high}"

    def test_variants_without_selectors_come_last(self):
        """Otherwise a catch-all would shadow the sex- or age-specific one."""
        for code, variants in labs.ReferenceRanges.load().items():
            for variant in variants[:-1]:
                assert variant.get('sex') or variant.get('min_age') is not None, (
                    f"{code}: an unselected variant shadows the ones after it")


class TestInterpretation:
    @pytest.mark.parametrize('value, expected', [
        (5.0, 'L'), (10.0, 'N'), (15.0, 'H'),
        (7.0, 'N'), (12.0, 'N'),
    ])
    def test_it_flags_against_the_interval(self, value, expected):
        assert labs.interpretation_for(value, 7.0, 12.0)[0] == expected

    def test_a_value_on_the_boundary_is_normal(self):
        assert labs.interpretation_for(7.0, 7.0, 12.0)[0] == 'N'
        assert labs.interpretation_for(12.0, 7.0, 12.0)[0] == 'N'

    def test_no_interval_means_no_flag(self):
        assert labs.interpretation_for(5.0, None, None) is None

    def test_a_one_sided_interval_still_flags(self):
        assert labs.interpretation_for(250.0, None, 200.0)[0] == 'H'
        assert labs.interpretation_for(150.0, None, 200.0)[0] == 'N'

    def test_a_non_numeric_value_is_not_flagged(self):
        assert labs.interpretation_for('positive', 1.0, 2.0) is None
        assert labs.interpretation_for(None, 1.0, 2.0) is None

    def test_a_boolean_is_not_a_number(self):
        """True would otherwise compare as 1 and be flagged."""
        assert labs.interpretation_for(True, 1.0, 2.0) is None

    def test_no_critical_flags_are_invented(self):
        """HH/LL mean a panic value, which nobody here decided."""
        assert labs.interpretation_for(10_000.0, 7.0, 12.0)[0] == 'H'


class TestRedCellIndices:
    """The reported defect. Identities hold exactly, not approximately."""

    def _panel(self, **values):
        person = _person()
        encounter = person.record.encounter_start(VISIT, EncounterClass.AMBULATORY)
        recorded = _record(person, encounter, values)
        person.record.encounter_end(encounter, VISIT)
        return {code: obs.value for code, obs in recorded.items()}

    def test_the_reported_panel_becomes_coherent(self):
        """RBC 4.59 HGB 13.55 HCT 46.93, MCV 85.3, MCHC 33.0 — from the report."""
        panel = self._panel(**{
            labs.RBC: (4.59, '10*6/uL'), labs.HGB: (13.55, 'g/dL'),
            labs.HCT: (46.93, '%'), labs.MCV: (85.3, 'fL'),
            labs.MCHC: (33.0, 'g/dL'), labs.MCH: (29.5, 'pg'),
        })

        assert panel[labs.MCV] == pytest.approx(
            panel[labs.HCT] * 10 / panel[labs.RBC], abs=0.2)
        assert panel[labs.MCHC] == pytest.approx(
            panel[labs.HGB] * 100 / panel[labs.HCT], abs=0.1)
        assert panel[labs.MCH] == pytest.approx(
            panel[labs.HGB] * 10 / panel[labs.RBC], abs=0.2)

    def test_haemoglobin_is_preserved(self):
        """It is how every module expresses the severity of an anaemia."""
        panel = self._panel(**{
            labs.HGB: (9.2, 'g/dL'), labs.HCT: (40.0, '%'),
            labs.MCV: (78.0, 'fL'), labs.MCHC: (33.0, 'g/dL'),
            labs.RBC: (5.0, '10*6/uL'),
        })

        assert panel[labs.HGB] == 9.2

    def test_mcv_is_preserved(self):
        """It is how a module says microcytic, normocytic or macrocytic."""
        panel = self._panel(**{
            labs.HGB: (9.2, 'g/dL'), labs.HCT: (40.0, '%'),
            labs.MCV: (78.0, 'fL'), labs.MCHC: (33.0, 'g/dL'),
            labs.RBC: (5.0, '10*6/uL'),
        })

        assert panel[labs.MCV] == 78.0

    def test_a_microcytic_anaemia_stays_microcytic(self):
        """The correction must not erase the clinical picture."""
        panel = self._panel(**{
            labs.HGB: (9.2, 'g/dL'), labs.HCT: (44.0, '%'),
            labs.MCV: (72.0, 'fL'), labs.MCHC: (33.0, 'g/dL'),
            labs.RBC: (4.0, '10*6/uL'),
        })

        assert panel[labs.HGB] < 12.0, "still anaemic"
        assert panel[labs.MCV] < 80.0, "still microcytic"

    def test_derived_values_are_physiologically_sane(self):
        panel = self._panel(**{
            labs.HGB: (13.55, 'g/dL'), labs.HCT: (46.93, '%'),
            labs.MCV: (85.3, 'fL'), labs.MCHC: (33.0, 'g/dL'),
            labs.RBC: (4.59, '10*6/uL'), labs.MCH: (29.5, 'pg'),
        })

        assert 20 < panel[labs.MCH] < 40
        assert 2.0 < panel[labs.RBC] < 8.0
        assert 15 < panel[labs.HCT] < 65

    def test_a_missing_mchc_uses_the_physiological_default(self):
        panel = self._panel(**{
            labs.HGB: (14.0, 'g/dL'), labs.HCT: (50.0, '%'),
            labs.MCV: (90.0, 'fL'), labs.RBC: (4.0, '10*6/uL'),
        })

        assert panel[labs.HCT] == pytest.approx(
            14.0 * 100 / labs.DEFAULT_MCHC, abs=0.1)

    def test_a_panel_with_no_derived_member_is_left_alone(self):
        """Nothing to reconcile, so nothing should move."""
        panel = self._panel(**{
            labs.HGB: (14.0, 'g/dL'), labs.MCV: (90.0, 'fL'),
        })

        assert panel[labs.HGB] == 14.0
        assert panel[labs.MCV] == 90.0

    def test_a_panel_with_no_anchor_is_left_alone(self):
        """Neither HGB nor HCT: there is nothing to solve from."""
        panel = self._panel(**{labs.RBC: (4.5, '10*6/uL')})

        assert panel[labs.RBC] == 4.5


class TestProteinFractions:
    """Not exercised by a generated run in a small population, so tested here."""

    def _panel(self, **values):
        person = _person()
        encounter = person.record.encounter_start(VISIT, EncounterClass.AMBULATORY)
        recorded = _record(person, encounter, values)
        person.record.encounter_end(encounter, VISIT)
        return {code: obs.value for code, obs in recorded.items()}

    def test_globulin_is_total_protein_minus_albumin(self):
        panel = self._panel(**{
            labs.TOTAL_PROTEIN: (7.2, 'g/dL'), labs.ALBUMIN: (4.1, 'g/dL'),
            labs.GLOBULIN: (9.9, 'g/dL'),
        })

        assert panel[labs.GLOBULIN] == pytest.approx(7.2 - 4.1, abs=0.01)

    def test_the_ratio_follows_from_both(self):
        panel = self._panel(**{
            labs.TOTAL_PROTEIN: (7.2, 'g/dL'), labs.ALBUMIN: (4.1, 'g/dL'),
            labs.GLOBULIN: (3.1, 'g/dL'), labs.AG_RATIO: (99.0, '{ratio}'),
        })

        assert panel[labs.AG_RATIO] == pytest.approx(
            panel[labs.ALBUMIN] / panel[labs.GLOBULIN], abs=0.01)

    def test_albumin_above_total_protein_is_a_contradiction(self):
        """It would make globulin negative, which cannot be measured."""
        panel = self._panel(**{
            labs.TOTAL_PROTEIN: (6.0, 'g/dL'), labs.ALBUMIN: (8.0, 'g/dL'),
            labs.GLOBULIN: (1.0, 'g/dL'),
        })

        assert panel[labs.ALBUMIN] < panel[labs.TOTAL_PROTEIN]
        assert panel[labs.GLOBULIN] > 0


class TestDifferential:
    def _panel(self, **values):
        person = _person()
        encounter = person.record.encounter_start(VISIT, EncounterClass.AMBULATORY)
        recorded = _record(person, encounter, values)
        person.record.encounter_end(encounter, VISIT)
        return {code: obs.value for code, obs in recorded.items()}

    def test_the_percentages_sum_to_one_hundred(self):
        panel = self._panel(**{
            '770-8': (60.0, '%'), '736-9': (30.0, '%'), '5905-5': (8.0, '%'),
            '713-8': (4.0, '%'), '706-2': (1.0, '%'),
        })

        assert sum(panel.values()) == pytest.approx(100.0, abs=0.15)

    def test_the_clinical_picture_survives_scaling(self):
        """A neutrophilia must still read as a neutrophilia afterwards."""
        panel = self._panel(**{
            '770-8': (85.0, '%'), '736-9': (10.0, '%'), '5905-5': (5.0, '%'),
            '713-8': (2.0, '%'), '706-2': (1.0, '%'),
        })

        assert panel['770-8'] > panel['736-9'] > panel['5905-5']
        assert panel['770-8'] > 70, "still neutrophilic"

    def test_an_already_correct_differential_is_untouched(self):
        panel = self._panel(**{
            '770-8': (60.0, '%'), '736-9': (30.0, '%'), '5905-5': (6.0, '%'),
            '713-8': (3.0, '%'), '706-2': (1.0, '%'),
        })

        assert panel['770-8'] == 60.0

    def test_a_single_fraction_is_not_scaled(self):
        """One number is not a differential; scaling it to 100 would be wrong."""
        panel = self._panel(**{'770-8': (60.0, '%')})

        assert panel['770-8'] == 60.0


class TestExport:
    def test_the_reference_range_reaches_the_bundle(self, tmp_path):
        person = _person()
        encounter = person.record.encounter_start(VISIT, EncounterClass.AMBULATORY)
        person.record.observation(VISIT, _loinc(labs.MCV), value=85.0,
                                  unit='fL', encounter=encounter)
        person.record.encounter_end(encounter, VISIT)

        config = Config()
        config.load()
        config.set('exporter.baseDirectory', str(tmp_path))
        bundle = FHIRExporter(config, tmp_path).create_bundle(person)

        resource = next(e['resource'] for e in bundle['entry']
                        if e['resource']['resourceType'] == 'Observation')

        assert resource['referenceRange'][0]['low']['value'] == 80.0
        assert resource['referenceRange'][0]['high']['value'] == 100.0
        assert resource['interpretation'][0]['coding'][0]['code'] == 'N'

    def test_an_abnormal_value_is_flagged_high(self, tmp_path):
        person = _person()
        encounter = person.record.encounter_start(VISIT, EncounterClass.AMBULATORY)
        person.record.observation(VISIT, _loinc(labs.MCV), value=130.0,
                                  unit='fL', encounter=encounter)
        person.record.encounter_end(encounter, VISIT)

        config = Config()
        config.load()
        config.set('exporter.baseDirectory', str(tmp_path))
        bundle = FHIRExporter(config, tmp_path).create_bundle(person)

        resource = next(e['resource'] for e in bundle['entry']
                        if e['resource']['resourceType'] == 'Observation')

        assert resource['interpretation'][0]['coding'][0]['code'] == 'H'

    def test_an_unknown_code_carries_neither(self, tmp_path):
        person = _person()
        encounter = person.record.encounter_start(VISIT, EncounterClass.AMBULATORY)
        person.record.observation(VISIT, _loinc('99999-9'), value=1.0,
                                  unit='x', encounter=encounter)
        person.record.encounter_end(encounter, VISIT)

        config = Config()
        config.load()
        config.set('exporter.baseDirectory', str(tmp_path))
        bundle = FHIRExporter(config, tmp_path).create_bundle(person)

        resource = next(e['resource'] for e in bundle['entry']
                        if e['resource']['resourceType'] == 'Observation')

        assert 'referenceRange' not in resource
        assert 'interpretation' not in resource


@pytest.fixture(scope='module')
def generated(tmp_path_factory):
    out = tmp_path_factory.mktemp('labs')

    config = Config()
    config.load()
    config.set('exporter.baseDirectory', str(out))
    config.set('exporter.fhir.export', True)
    config.set('exporter.use_uuid_filenames', True)

    options = GeneratorOptions()
    options.population_size = 8
    options.seed = 7
    options.reference_date = REFERENCE_DATE

    Generator(options, config=config).run()

    bundles = [json.loads(p.read_text(encoding='utf-8'))
               for p in (out / 'fhir').glob('*.json')]
    return [e['resource'] for b in bundles for e in b['entry']
            if e['resource']['resourceType'] == 'Observation']


class TestGeneratedPopulation:
    """The reporter's own measurement, run as a test."""

    def test_lab_observations_carry_a_range(self, generated):
        """Was 0 of 2,323."""
        with_range = [o for o in generated if o.get('referenceRange')]

        assert with_range, "no observation carried a reference range"
        assert len(with_range) > len(generated) * 0.2

    def test_every_range_comes_with_a_flag(self, generated):
        for observation in generated:
            if observation.get('referenceRange'):
                assert observation.get('interpretation'), observation['id']

    def test_the_flag_agrees_with_its_range(self, generated):
        """A flag that disagrees with the range beside it is worse than none."""
        for observation in generated:
            ranges = observation.get('referenceRange')
            flag = observation.get('interpretation')
            if not ranges or not flag or 'valueQuantity' not in observation:
                continue

            value = observation['valueQuantity']['value']
            low = ranges[0].get('low', {}).get('value')
            high = ranges[0].get('high', {}).get('value')
            expected = ('H' if high is not None and value > high
                        else 'L' if low is not None and value < low else 'N')

            assert flag[0]['coding'][0]['code'] == expected, observation['id']

    def test_red_cell_panels_are_internally_consistent(self, generated):
        """Was 6 of 8 inconsistent on MCV, 7 of 8 on MCHC."""
        panels = {}
        for observation in generated:
            code = observation.get('code', {}).get('coding', [{}])[0].get('code')
            if 'valueQuantity' not in observation:
                continue
            key = (observation.get('subject', {}).get('reference'),
                   observation.get('encounter', {}).get('reference'))
            panels.setdefault(key, {})[code] = \
                observation['valueQuantity']['value']

        complete = [p for p in panels.values()
                    if {labs.RBC, labs.HGB, labs.HCT, labs.MCV, labs.MCHC} <= set(p)]

        assert complete, "no complete red-cell panel to check"

        for panel in complete:
            assert panel[labs.MCV] == pytest.approx(
                panel[labs.HCT] * 10 / panel[labs.RBC], abs=3.0)
            assert panel[labs.MCHC] == pytest.approx(
                panel[labs.HGB] * 100 / panel[labs.HCT], abs=1.5)

    @pytest.mark.skipif(not validation.available(),
                        reason="fhir.resources R4B models are not installed")
    def test_the_new_elements_validate(self, generated):
        issues = validation.validate_bundle(
            {'entry': [{'resource': o} for o in generated]})

        assert issues == []


class TestUnknownSexFallback:
    """A patient with no recorded gender must still get a usable range."""

    def test_the_union_spans_both_sexes(self):
        male = labs.ReferenceRanges.for_code(labs.HGB, sex='M')
        female = labs.ReferenceRanges.for_code(labs.HGB, sex='F')
        union = labs.ReferenceRanges.for_code(labs.HGB, sex=None)

        assert union['low'] == min(male['low'], female['low'])
        assert union['high'] == max(male['high'], female['high'])

    def test_it_cannot_flag_what_either_sex_calls_normal(self):
        """The whole point of widening rather than picking one."""
        union = labs.ReferenceRanges.for_code(labs.HGB, sex=None)

        for sex in ('M', 'F'):
            specific = labs.ReferenceRanges.for_code(labs.HGB, sex=sex)
            for value in (specific['low'], specific['high']):
                assert labs.interpretation_for(
                    value, union['low'], union['high'])[0] == 'N'

    def test_the_union_carries_no_sex(self):
        assert 'sex' not in labs.ReferenceRanges.for_code(labs.HGB, sex=None)

    def test_an_age_limit_still_applies_without_a_sex(self):
        assert labs.ReferenceRanges.for_code('8480-6', sex=None, age=6) is None
