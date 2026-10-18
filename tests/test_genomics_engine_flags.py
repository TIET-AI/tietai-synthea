"""GO-61: the opt-in engine switches used by --genomics-cohort, and that stock behaviour is unchanged."""
from datetime import datetime, timedelta

import pytest
import yaml
from click.testing import CliRunner

from synthea.engine.generator import Generator, GeneratorOptions
from synthea.engine.module import Module
from synthea.engine.state import EncounterEndState
from synthea.helpers.config import Config
from synthea.helpers.resources import resource_path
from synthea.world.person import Person

T0 = datetime(2021, 6, 1)


@pytest.fixture(autouse=True)
def _restore():
    yield
    EncounterEndState.completes = False
    Module.set_state_patches(None)


def _end(name="End"):
    return EncounterEndState(Module("t"), name, {"type": "EncounterEnd"})


def _person():
    p = Person(seed=7)
    p.init_health_record()
    return p


def test_encounter_end_default_never_completes():
    """The stock behaviour (a known defect): the state yields on every step."""
    p, s = _person(), _end()
    assert [s.run(p, T0 + timedelta(days=d)) for d in (0, 0, 1, 7, 30)] == [False] * 5


def test_encounter_end_completes_when_enabled_and_rearms():
    EncounterEndState.completes = True
    p, s = _person(), _end()
    assert s.run(p, T0) is False                      # ends the encounter, yields
    assert s.run(p, T0) is False                      # same step: still yields
    assert s.run(p, T0 + timedelta(days=1)) is True   # next step: moves on
    assert s.run(p, T0 + timedelta(days=40)) is False  # a later visit yields again


def test_state_patches_replace_a_state_and_refuse_unknown_ones():
    Module.set_state_patches({"lung_cancer": {"Lung Cancer Probabilities": {
        "type": "Simple", "distributed_transition": [{"distribution": 1.0, "transition": "Terminal"}]}}})
    Module.load_modules()
    assert type(Module.get_module("lung_cancer").states["Lung Cancer Probabilities"]).__name__ == "SimpleState"
    Module.set_state_patches(None)
    Module.load_modules()
    assert type(Module.get_module("lung_cancer").states["Lung Cancer Probabilities"]).__name__ != "SimpleState"


def test_generator_reads_module_patches_and_stock_is_empty():
    cfg = Config()
    cfg.load()
    cfg.set("exporter.fhir.export", False)
    o = GeneratorOptions()
    o.population_size = 1
    o.seed = 1
    g = Generator(o, config=cfg)
    assert g._load_module_patches() == {}
    assert EncounterEndState.completes is False and Module._state_patches == {}
    cfg.set("generate.module_patches", str(resource_path("genomics") / "cohort_patches.yaml"))
    cfg.set("generate.encounter_end_completes", True)
    g = Generator(o, config=cfg)
    patches = g._load_module_patches()
    assert set(patches) == {"lung_cancer", "colorectal_cancer", "breast_cancer", "prostate_cancer"}
    assert EncounterEndState.completes is True
    doc = yaml.safe_load((resource_path("genomics") / "cohort_patches.yaml").read_text())
    assert len(doc["patches"]) == 4


def test_cli_flags_set_config_and_default_is_off(tmp_path, monkeypatch):
    from synthea import cli
    seen = {}

    class FakeGenerator:
        def __init__(self, options, config=None):
            seen["config"] = config

        def run(self):
            pass

    monkeypatch.setattr(cli, "Generator", FakeGenerator)
    runner = CliRunner()
    base = ["--population", "1", "--output-dir", str(tmp_path)]
    assert runner.invoke(cli.main, base).exit_code == 0
    c = seen["config"]
    assert c.get_bool("exporter.genomics.export", False) is False
    assert not c.get("generate.module_patches") and c.get_bool("generate.encounter_end_completes", False) is False
    assert runner.invoke(cli.main, base + ["--genomics"]).exit_code == 0
    c = seen["config"]
    assert c.get_bool("exporter.genomics.export") is True and not c.get("generate.module_patches")
    assert runner.invoke(cli.main, ["--population", "1", "--output", str(tmp_path), "--genomics-cohort",
                                    "--regenerate-reference"]).exit_code == 0
    c = seen["config"]
    assert c.get_bool("exporter.genomics.export") is True
    assert str(c.get("generate.module_patches")).endswith("cohort_patches.yaml")
    assert c.get_bool("generate.encounter_end_completes") is True
    assert c.get_bool("exporter.genomics.regenerate_reference") is True
