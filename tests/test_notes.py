"""Tests for clinical note generation.

`templates/notes/note.ftl` shipped from the Java port and was never used, so
records had no free text at all. These cover the sentence-level decisions the
port makes in Python, the rendered layout, and the DocumentReference and text
file the note ends up in.
"""

import base64
import json
from datetime import datetime

import pytest

from synthea.engine.generator import Generator, GeneratorOptions
from synthea.export import validation
from synthea.helpers.config import Config
from synthea.world import notes
from synthea.world.health_record import Code, EncounterClass
from synthea.world.person import Person

REFERENCE_DATE = datetime(2020, 1, 1)
VISIT = datetime(2015, 6, 1)


@pytest.fixture
def person():
    person = Person(seed=3)
    person.init_health_record()
    person.attributes.update({
        'gender': 'F',
        'birth_date': datetime(1975, 6, 1),
        'first_name': 'Ada',
        'last_name': 'Lovelace',
        'race': 'white',
        'ethnicity': 'non_hispanic',
        'socioeconomic_status': 'middle',
        'education': 'bs_degree',
        'marital_status': {'code': 'M', 'display': 'Married'},
    })
    return person


@pytest.fixture
def encounter(person):
    encounter = person.record.encounter_start(VISIT, EncounterClass.AMBULATORY)
    person.record.encounter_end(encounter, VISIT)
    return encounter


def _code(code, display):
    return Code(system='SNOMED-CT', code=code, display=display)


class TestAgePhrase:
    """How a clinician writes an age: years, else months, else newborn."""

    @pytest.mark.parametrize('born, expected', [
        (datetime(1975, 6, 1), '40 year-old'),
        (datetime(2015, 1, 1), '5 month-old'),
        (datetime(2015, 5, 25), 'newborn'),
    ])
    def test_it_reads_the_way_a_clinician_writes_it(self, person, born,
                                                    expected):
        person.attributes['birth_date'] = born
        assert notes.age_phrase(person, VISIT) == expected

    def test_a_year_old_is_years_not_months(self, person):
        person.attributes['birth_date'] = datetime(2014, 6, 1)
        assert notes.age_phrase(person, VISIT) == '1 year-old'


class TestSocialHistory:
    def test_the_insurance_sentence_is_always_there(self, person):
        sentences = notes.social_history(person, 40)
        assert any('insurance' in s or 'currently has' in s for s in sentences)

    def test_an_uninsured_patient_says_so(self, person):
        assert 'no insurance' in ' '.join(notes.social_history(person, 40))

    def test_a_child_gets_no_marital_or_smoking_sentence(self, person):
        sentences = ' '.join(notes.social_history(person, 8))
        assert 'married' not in sentences
        assert 'single' not in sentences
        assert 'smok' not in sentences

    def test_marital_status_is_read_from_the_coded_attribute(self, person):
        assert 'Patient is married.' in notes.social_history(person, 40)

        person.attributes['marital_status'] = {'code': 'S', 'display': 'Single'}
        assert 'Patient is single.' in notes.social_history(person, 40)

    def test_a_smoker_and_alcoholic_read_in_one_sentence(self, person):
        person.attributes.update({'smoker': True, 'alcoholic': True})
        sentences = ' '.join(notes.social_history(person, 40))

        assert 'Patient is an active smoker and is an alcoholic.' in sentences

    def test_someone_who_quit_says_when(self, person):
        person.attributes['quit_smoking_age'] = 32
        assert 'quit smoking at age 32' in ' '.join(
            notes.social_history(person, 40))

    def test_education_only_applies_to_adults(self, person):
        assert 'college graduate' in ' '.join(notes.social_history(person, 40))
        assert 'college graduate' not in ' '.join(
            notes.social_history(person, 12))

    def test_an_unknown_education_is_omitted_rather_than_guessed(self, person):
        person.attributes['education'] = 'something_else'
        assert not any('high school' in s or 'college' in s
                       for s in notes.social_history(person, 40))


class TestHistoryOfPresentIllness:
    def test_it_names_the_patient_and_their_description(self, person):
        sentence = notes.history_of_present_illness(person, VISIT)
        assert sentence.startswith(
            'Ada is a 40 year-old non hispanic white female.')

    def test_active_conditions_become_a_history(self, person):
        person.record.condition_start(
            datetime(2010, 1, 1), _code('1', 'Diabetes'))
        person.record.condition_start(
            datetime(2011, 1, 1), _code('2', 'Hypertension'))

        sentence = notes.history_of_present_illness(person, VISIT)
        assert 'Patient has a history of diabetes and hypertension.' in sentence

    def test_a_resolved_condition_is_not_a_current_history(self, person):
        condition = person.record.condition_start(
            datetime(2010, 1, 1), _code('1', 'Diabetes'))
        person.record.condition_end(condition, datetime(2012, 1, 1))

        assert 'history of' not in notes.history_of_present_illness(
            person, VISIT)

    def test_a_condition_that_starts_later_is_not_yet_history(self, person):
        person.record.condition_start(
            datetime(2018, 1, 1), _code('1', 'Diabetes'))

        assert 'history of' not in notes.history_of_present_illness(
            person, VISIT)

    def test_a_missing_name_does_not_produce_a_blank(self, person):
        del person.attributes['first_name']
        assert notes.history_of_present_illness(person, VISIT).startswith(
            'The patient is a')


class TestRendering:
    def test_every_section_is_present(self, person, encounter):
        text = notes.note_for(person, encounter)

        for heading in ('# Chief Complaint', '# History of Present Illness',
                        '# Social History', '# Allergies', '# Medications',
                        '# Vital Signs', '# Assessment and Plan', '## Plan'):
            assert heading in text, heading

    def test_an_empty_visit_still_says_something_in_every_section(
            self, person, encounter):
        text = notes.note_for(person, encounter)

        assert 'No complaints.' in text
        assert 'No Known Allergies.' in text
        assert 'No Active Medications.' in text
        assert 'None recorded at this visit.' in text
        assert 'No orders placed at this visit.' in text

    def test_it_opens_with_the_date_of_the_visit(self, person, encounter):
        assert notes.note_for(person, encounter).startswith('2015-06-01')

    def test_orders_are_listed_under_the_plan(self, person, encounter):
        person.record.procedure(VISIT, _code('p1', 'Appendectomy'),
                                encounter=encounter)
        person.record.medication_start(VISIT, _code('m1', 'Ibuprofen'),
                                       encounter=encounter)

        text = notes.note_for(person, encounter)

        assert '- appendectomy' in text
        assert '- ibuprofen' in text
        assert 'The following procedures were conducted:' in text
        assert 'The patient was prescribed the following medications:' in text

    def test_each_list_item_is_on_its_own_line(self, person, encounter):
        """Regression: trim_blocks joined items that ended in a block tag."""
        person.record.procedure(VISIT, _code('p1', 'Appendectomy'),
                                encounter=encounter)
        person.record.procedure(VISIT, _code('p2', 'Biopsy'),
                                encounter=encounter)

        lines = notes.note_for(person, encounter).splitlines()
        assert '- appendectomy' in lines
        assert '- biopsy' in lines

    def test_a_heading_always_has_a_blank_line_before_it(self, person,
                                                        encounter):
        lines = notes.note_for(person, encounter).splitlines()
        for index, line in enumerate(lines):
            if line.startswith('#') and index > 0:
                assert lines[index - 1] == '', f"no blank line before {line!r}"

    def test_there_are_no_runs_of_blank_lines(self, person, encounter):
        lines = notes.note_for(person, encounter).splitlines()
        assert not any(a == '' and b == ''
                       for a, b in zip(lines, lines[1:]))


class TestVitals:
    def test_vitals_are_listed_with_their_units(self, person, encounter):
        person.record.observation(VISIT, _code('8302-2', 'Body Height'),
                                  value=170.0, unit='cm', encounter=encounter)

        assert '- Body Height: 170.0 cm' in notes.note_for(person, encounter)

    def test_a_repeated_vital_is_reported_once(self, person, encounter):
        """A visit can record the same vital twice; a note listing it twice
        reads like a bug."""
        for value in (168.0, 170.0):
            person.record.observation(VISIT, _code('8302-2', 'Body Height'),
                                      value=value, unit='cm',
                                      encounter=encounter)

        text = notes.note_for(person, encounter)
        assert text.count('Body Height') == 1
        assert '170.0' in text, "the last value recorded is the one that stands"

    def test_a_non_numeric_observation_is_left_out(self, person, encounter):
        person.record.observation(VISIT, _code('8302-2', 'Body Height'),
                                  value='tall', unit='cm', encounter=encounter)

        assert 'None recorded at this visit.' in notes.note_for(
            person, encounter)

    def test_a_lab_result_is_not_a_vital_sign(self, person, encounter):
        person.record.observation(VISIT, _code('2345-7', 'Glucose'),
                                  value=5.4, unit='mmol/L', encounter=encounter)

        text = notes.note_for(person, encounter)
        assert 'Glucose' not in text.split('# Assessment')[0].split(
            '# Vital Signs')[1]


class TestWriteNotes:
    def test_finished_encounters_get_a_note(self, person, encounter):
        assert notes.write_notes(person) == 1
        assert getattr(encounter, notes.NOTE_ATTRIBUTE)

    def test_an_open_encounter_does_not(self, person):
        person.record.encounter_start(VISIT, EncounterClass.AMBULATORY)

        assert notes.write_notes(person) == 0


class TestPostProcessor:
    def teardown_method(self):
        notes.set_post_processor(None)

    def test_a_hook_can_rewrite_the_note(self, person, encounter):
        notes.set_post_processor(lambda text, p, e: 'rewritten')

        assert notes.note_for(person, encounter) == 'rewritten'

    def test_a_failing_hook_keeps_the_rendered_note(self, person, encounter):
        """A broken integration must not silently lose the note."""
        def explode(text, p, e):
            raise RuntimeError('no')

        notes.set_post_processor(explode)
        text = notes.note_for(person, encounter)

        assert text and '# Chief Complaint' in text


@pytest.fixture(scope='module')
def generated(tmp_path_factory):
    """A generated population exported to FHIR and text."""
    out = tmp_path_factory.mktemp('notes')

    config = Config()
    config.load()
    config.set('exporter.baseDirectory', str(out))
    config.set('exporter.fhir.export', True)
    config.set('exporter.text.export', True)
    config.set('exporter.use_uuid_filenames', True)

    options = GeneratorOptions()
    options.population_size = 3
    options.seed = 5
    options.min_age = 25
    options.max_age = 60
    options.reference_date = REFERENCE_DATE

    Generator(options, config=config).run()

    bundles = [json.loads(path.read_text(encoding='utf-8'))
               for path in (out / 'fhir').glob('*.json')]
    return out, bundles


def _resources(bundles, resource_type):
    return [entry['resource'] for bundle in bundles for entry in bundle['entry']
            if entry['resource']['resourceType'] == resource_type]


class TestExport:
    def test_every_encounter_has_a_note(self, generated):
        """The acceptance criterion for #43."""
        _, bundles = generated
        encounters = _resources(bundles, 'Encounter')
        documents = _resources(bundles, 'DocumentReference')

        assert encounters
        assert len(documents) == len(encounters)

    def test_no_note_is_empty(self, generated):
        _, bundles = generated
        for document in _resources(bundles, 'DocumentReference'):
            data = document['content'][0]['attachment']['data']
            assert base64.b64decode(data).strip()

    def test_a_note_names_the_encounter_it_belongs_to(self, generated):
        _, bundles = generated
        for bundle in bundles:
            ids = {e['resource']['id'] for e in bundle['entry']
                   if e['resource']['resourceType'] == 'Encounter'}
            for entry in bundle['entry']:
                resource = entry['resource']
                if resource['resourceType'] != 'DocumentReference':
                    continue
                reference = resource['context']['encounter'][0]['reference']
                assert reference.replace('urn:uuid:', '') in ids

    def test_a_note_names_the_visit_s_conditions(self, generated):
        """A note that does not mention the diagnosis is not a note."""
        _, bundles = generated
        found = False

        for bundle in bundles:
            documents = {
                e['resource']['context']['encounter'][0]['reference']:
                    base64.b64decode(
                        e['resource']['content'][0]['attachment']['data']
                    ).decode('utf-8').lower()
                for e in bundle['entry']
                if e['resource']['resourceType'] == 'DocumentReference'
            }
            for entry in bundle['entry']:
                resource = entry['resource']
                if resource['resourceType'] != 'Condition':
                    continue
                reference = resource.get('encounter', {}).get('reference')
                text = documents.get(reference)
                if not text:
                    continue
                display = resource['code']['coding'][0]['display'].lower()
                assert display in text
                found = True

        assert found, "no condition was linked to an encounter to check"

    def test_the_content_is_plain_text(self, generated):
        _, bundles = generated
        for document in _resources(bundles, 'DocumentReference'):
            assert document['content'][0]['attachment']['contentType'].startswith(
                'text/plain')
            assert document['status'] == 'current'
            assert document['category'][0]['coding'][0]['code'] == 'clinical-note'

    @pytest.mark.skipif(not validation.available(),
                        reason="fhir.resources R4B models are not installed")
    def test_the_bundles_still_validate(self, generated):
        _, bundles = generated
        issues = [issue for bundle in bundles
                  for issue in validation.validate_bundle(bundle)]
        nulls = [null for bundle in bundles
                 for null in validation.find_nulls(bundle)]

        assert issues == []
        assert nulls == []

    def test_text_files_are_written(self, generated):
        out, _ = generated
        files = list((out / 'notes').glob('*.txt'))

        assert files
        for path in files:
            assert path.read_text(encoding='utf-8').strip()
