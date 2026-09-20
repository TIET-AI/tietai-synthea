"""Tests for LookupTableTransition row matching.

Matching used to re-parse every cell of every candidate row on every lookup,
which was 88% of the time spent generating a patient. The parsed form is now
built once per table. These tests pin the matching semantics so that
optimisation cannot quietly change which row a patient falls into, and check
the matcher against a direct, unoptimised reference implementation.
"""

from datetime import datetime

import pytest

from synthea.engine.transition import (
    LookupTableTransition,
    _as_float,
    _compile_column,
    _numeric_range,
)
from synthea.world.person import Person

TIME = datetime(2020, 6, 1)
EPOCH = datetime(1970, 1, 1)


@pytest.fixture(autouse=True)
def _clear_caches():
    """The table caches are class-level, so a stale one would leak across tests."""
    LookupTableTransition._csv_cache.clear()
    LookupTableTransition._compiled_cache.clear()
    yield
    LookupTableTransition._csv_cache.clear()
    LookupTableTransition._compiled_cache.clear()


def _person(**attributes):
    person = Person(seed=1)
    person.attributes.setdefault('birth_date', datetime(1980, 6, 1))
    person.attributes.update(attributes)
    return person


def _transition(rows, targets=('yes', 'no')):
    """A transition whose table is `rows`, bypassing the CSV loader."""
    transition = LookupTableTransition({'lookup_table_transition': [
        {'transition': target, 'default_probability': 0.0} for target in targets
    ]})
    LookupTableTransition._csv_cache['test.csv'] = rows
    for entry in transition.entries:
        entry['lookup_table_name'] = 'test.csv'
    return transition


# ----------------------------------------------------------------------
# Reference implementation: the straightforward reading of the semantics.
# ----------------------------------------------------------------------

def _reference_matches(column, value, person, time):
    if value is None or value == '':
        return True

    key = column.strip().lower()

    if key == 'age':
        return _reference_range(value, person.age_at(time))

    if key == 'time':
        return _reference_range(value, (time - EPOCH).total_seconds() * 1000.0)

    if key == 'gender':
        return value.strip().lower() == str(
            person.attributes.get('gender', '')).strip().lower()

    attribute = person.attributes.get(column) or person.attributes.get(key)
    if attribute is None:
        return False
    return str(attribute).strip().lower() == value.strip().lower()


def _reference_range(value, candidate):
    text = value.strip()
    if '-' not in text:
        bound = _as_float(text, None)
        return bound is not None and abs(candidate - bound) < 1e-9

    low_text, _, high_text = text.partition('-')
    low = _as_float(low_text, None)
    high = _as_float(high_text, None)
    if low is None or high is None:
        return False
    return low <= candidate <= high


def _reference_row(rows, person, time, targets):
    for row in rows:
        if all(
            _reference_matches(column, value, person, time)
            for column, value in row.items()
            if column not in targets and column
        ):
            return row
    return None


class TestNumericRanges:
    def test_a_range_is_inclusive(self):
        low, high = _numeric_range('18-64')
        assert low == 18 and high == 64

    def test_a_single_value_keeps_its_tolerance(self):
        low, high = _numeric_range('40')
        assert low < 40 < high
        assert high - low < 1e-6

    @pytest.mark.parametrize('text', ['', 'adult', 'a-b', '18-', '-64'])
    def test_an_unparseable_range_is_not_a_range(self, text):
        assert _numeric_range(text) is None

    def test_an_unparseable_range_never_matches(self):
        rows = [{'age': 'grown-up', 'yes': '1.0'}, {'age': '', 'yes': '0.5'}]
        row = _transition(rows)._matching_row(
            'test.csv', rows, _person(), TIME, {'yes'})

        assert row is rows[1], "the unparseable row must be skipped, not matched"

    def test_an_unparseable_range_compiles_to_never(self):
        kind = _compile_column('age', 'grown-up')[0]
        assert kind == 4  # _NEVER


class TestMatching:
    def test_the_first_matching_row_wins(self):
        rows = [
            {'age': '0-17', 'yes': '0.1'},
            {'age': '18-64', 'yes': '0.2'},
            {'age': '18-99', 'yes': '0.3'},
        ]
        row = _transition(rows)._matching_row(
            'test.csv', rows, _person(), TIME, {'yes'})

        assert row['yes'] == '0.2'

    def test_an_empty_cell_matches_anything(self):
        rows = [{'age': '', 'gender': '', 'yes': '0.4'}]
        row = _transition(rows)._matching_row(
            'test.csv', rows, _person(gender='F'), TIME, {'yes'})

        assert row is rows[0]

    def test_gender_is_compared_case_insensitively(self):
        rows = [{'gender': 'f', 'yes': '0.4'}]
        row = _transition(rows)._matching_row(
            'test.csv', rows, _person(gender='F'), TIME, {'yes'})

        assert row is rows[0]

    def test_a_missing_attribute_never_matches(self):
        """A table stratifying by something the patient lacks cannot apply."""
        rows = [{'smoker': 'true', 'yes': '0.4'}]
        row = _transition(rows)._matching_row(
            'test.csv', rows, _person(), TIME, {'yes'})

        assert row is None

    def test_attributes_are_matched_by_value(self):
        rows = [
            {'smoker': 'false', 'yes': '0.1'},
            {'smoker': 'true', 'yes': '0.9'},
        ]
        row = _transition(rows)._matching_row(
            'test.csv', rows, _person(smoker='True'), TIME, {'yes'})

        assert row['yes'] == '0.9'

    def test_target_columns_are_not_selectors(self):
        """Otherwise the probability column would be read as a filter."""
        rows = [{'age': '18-64', 'yes': '0.2', 'no': '0.8'}]
        row = _transition(rows)._matching_row(
            'test.csv', rows, _person(), TIME, {'yes', 'no'})

        assert row is rows[0]

    def test_time_windows_work_before_1970(self):
        """Regression: time.timestamp() raises OSError on Windows pre-epoch."""
        rows = [{'time': '0-100000000000', 'yes': '0.5'}]
        row = _transition(rows)._matching_row(
            'test.csv', rows, _person(), datetime(1955, 1, 1), {'yes'})

        assert row is None  # negative millis fall outside, and nothing raised


class TestAgainstReference:
    """The compiled matcher must agree with the plain reading of the rules."""

    ROWS = [
        {'age': '0-17', 'gender': 'M', 'smoker': '', 'yes': '0.1'},
        {'age': '0-17', 'gender': 'F', 'smoker': '', 'yes': '0.2'},
        {'age': '18-64', 'gender': 'M', 'smoker': 'true', 'yes': '0.3'},
        {'age': '18-64', 'gender': 'M', 'smoker': 'false', 'yes': '0.4'},
        {'age': '18-64', 'gender': 'F', 'smoker': '', 'yes': '0.5'},
        {'age': '65', 'gender': '', 'smoker': '', 'yes': '0.6'},
        {'age': '', 'gender': '', 'smoker': '', 'yes': '0.7'},
    ]

    @pytest.mark.parametrize('birth_year', [1930, 1955, 1980, 2010, 2018])
    @pytest.mark.parametrize('gender', ['M', 'F'])
    @pytest.mark.parametrize('smoker', [None, 'true', 'false'])
    def test_it_picks_the_row_the_reference_picks(self, birth_year, gender,
                                                  smoker):
        attributes = {'birth_date': datetime(birth_year, 1, 1),
                      'gender': gender}
        if smoker is not None:
            attributes['smoker'] = smoker

        person = _person(**attributes)
        targets = {'yes'}

        assert (
            _transition(self.ROWS)._matching_row(
                'ref.csv', self.ROWS, person, TIME, targets)
            is _reference_row(self.ROWS, person, TIME, targets)
        )


class TestCaching:
    def test_two_tables_do_not_share_a_compilation(self):
        """The cache is keyed per table; a second must not reuse the first."""
        first = [{'age': '0-17', 'yes': '0.1'}]
        second = [{'age': '18-99', 'yes': '0.9'}]
        transition = _transition(first)

        assert transition._matching_row(
            'first.csv', first, _person(), TIME, {'yes'}) is None
        assert transition._matching_row(
            'second.csv', second, _person(), TIME, {'yes'}) is second[0]

    def test_the_same_targets_reuse_the_compilation(self):
        rows = [{'age': '18-64', 'yes': '0.2'}]
        transition = _transition(rows)
        person = _person()

        first = transition._matching_row(
            'test.csv', rows, person, TIME, {'yes'})
        second = transition._matching_row(
            'test.csv', rows, person, TIME, {'yes'})

        assert first is second is rows[0]

    def test_different_targets_compile_separately(self):
        """With 'age' a target it stops being a selector, so anything matches."""
        rows = [{'age': '0-17', 'yes': '0.1'}]
        transition = _transition(rows)
        person = _person()

        assert transition._matching_row(
            'test.csv', rows, person, TIME, {'yes'}) is None
        assert transition._matching_row(
            'test.csv', rows, person, TIME, {'yes', 'age'}) is rows[0]
