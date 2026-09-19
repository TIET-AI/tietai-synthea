"""Reproducibility tests.

A population seed must fully determine the generated population: the same seed
produces the same patients, in the same order, whether generation runs on one
worker or several. These tests are the regression net for every later change to
the engine, so they deliberately compare exported bytes rather than summary
statistics.
"""

import json
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from synthea.engine.generator import Generator, GeneratorOptions
from synthea.engine.module import Module
from synthea.helpers.config import Config
from synthea.helpers.rng import derive_seed, random_seed, resolve_seed

#: A small module set keeps these tests fast while still exercising delays,
#: distributed transitions and encounters.
TEST_MODULES = ['allergies', 'hypertension', 'ear_infections']

#: Fixed so that "now" never leaks into the comparison.
REFERENCE_DATE = datetime(2020, 1, 1)


def _options(seed=42, population=4, threads=1):
    options = GeneratorOptions()
    options.population_size = population
    options.seed = seed
    options.threads = threads
    options.min_age = 20
    options.max_age = 60
    options.reference_date = REFERENCE_DATE
    return options


def _config(output_dir: Path) -> Config:
    """Config restricted to TEST_MODULES.

    The restriction goes through config rather than ``generator.module_list``
    so that it survives pickling into worker processes, which build their own
    Generator.
    """
    config = Config()
    config.load()
    config.set('exporter.baseDirectory', str(output_dir))
    config.set('exporter.fhir.export', True)
    config.set('exporter.csv.export', False)
    config.set('exporter.json.export', False)
    config.set('exporter.use_uuid_filenames', True)

    Module.load_modules()
    for name in Module.get_all_modules():
        config.set(f'generate.{name}', name in TEST_MODULES)
    return config


def _run(tmp: Path, seed=42, population=4, threads=1) -> dict:
    """Run a generation and return {filename: parsed bundle}."""
    out = tmp / f"run-{seed}-{population}-{threads}"
    generator = Generator(_options(seed, population, threads), config=_config(out))
    generator.run()

    fhir_dir = out / 'fhir'
    return {
        path.name: json.loads(path.read_text(encoding='utf-8'))
        for path in sorted(fhir_dir.glob('*.json'))
    }


@pytest.fixture
def tmp_out():
    path = Path(tempfile.mkdtemp())
    yield path
    shutil.rmtree(path, ignore_errors=True)


class TestSeedDerivation:
    """The seed derivation itself must be pure and stable."""

    def test_derive_seed_is_deterministic(self):
        assert derive_seed(42, 7) == derive_seed(42, 7)

    def test_derive_seed_is_stable_across_processes(self):
        # Guards against anyone switching to the salted built-in hash().
        assert derive_seed(42, 0) == 17395415385865885532

    def test_different_indices_give_different_seeds(self):
        seeds = {derive_seed(42, i) for i in range(100)}
        assert len(seeds) == 100

    def test_different_streams_give_different_seeds(self):
        assert derive_seed(42, 0, 'person') != derive_seed(42, 0, 'clinician')

    def test_resolve_seed_without_population_seed_is_random(self):
        assert resolve_seed(None, 0) != resolve_seed(None, 0)

    def test_random_seed_is_in_range(self):
        assert 0 <= random_seed() < 2 ** 64


class TestPersonReproducibility:
    """Person-level draws must come from the person's own generator."""

    def test_same_seed_same_person(self):
        first = Generator(_options()).generate_person(3)
        second = Generator(_options()).generate_person(3)

        assert first.seed == second.seed
        assert first.id == second.id
        assert first.attributes['gender'] == second.attributes['gender']
        assert first.attributes['birth_date'] == second.attributes['birth_date']

    def test_patient_index_is_independent_of_generation_order(self):
        """Patient 3 is the same whether or not patients 0-2 ran first."""
        sequential = Generator(_options())
        for index in range(3):
            sequential.generate_person(index)
        in_order = sequential.generate_person(3)

        standalone = Generator(_options()).generate_person(3)

        assert in_order.seed == standalone.seed
        assert in_order.id == standalone.id

    def test_global_random_state_does_not_leak_in(self):
        import random

        random.seed(1)
        first = Generator(_options()).generate_person(0)
        random.seed(999)
        second = Generator(_options()).generate_person(0)

        assert first.id == second.id
        assert first.attributes['birth_date'] == second.attributes['birth_date']


class TestExportReproducibility:
    """Whole runs must be byte-identical for the same seed."""

    def test_two_runs_produce_identical_exports(self, tmp_out):
        first = _run(tmp_out / 'a')
        second = _run(tmp_out / 'b')

        assert sorted(first) == sorted(second)
        assert first == second

    def test_different_seeds_produce_different_exports(self, tmp_out):
        first = _run(tmp_out / 'a', seed=42)
        second = _run(tmp_out / 'b', seed=43)

        assert first != second


class TestParallelReproducibility:
    """Threaded generation must not change the population."""

    def test_parallel_matches_sequential(self, tmp_out):
        sequential = _run(tmp_out / 'seq', population=4, threads=1)
        parallel = _run(tmp_out / 'par', population=4, threads=2)

        assert sorted(sequential) == sorted(parallel)
        assert sequential == parallel

    def test_parallel_collects_statistics(self, tmp_out):
        """The parallel path used to discard every worker's statistics."""
        out = tmp_out / 'stats'
        generator = Generator(_options(population=4, threads=2), config=_config(out))
        generator.run()

        assert generator.stats['total_generated'] == 4
        assert generator.stats['living'] + generator.stats['dead'] == 4
