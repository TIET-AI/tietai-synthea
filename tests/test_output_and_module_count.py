"""Regression tests for two generator bugs.

- #21: the ``-o/--output-dir`` override was ignored (output always went to
  ``./output/``) because the exporter was built from the generator's internal
  config before the CLI's config was attached.
- #22: generation logged ``Loaded 0 modules`` because the count was taken from
  the materialized module dict rather than the (lazily supplied) module set.
"""

from pathlib import Path

from synthea.engine.generator import Generator, GeneratorOptions
from synthea.helpers.config import Config


def test_output_dir_override_reaches_exporter(tmp_path):
    """#21: a caller-provided output directory must be used by the exporter."""
    out = tmp_path / "custom_out"
    cfg = Config()
    cfg.load()
    cfg.set("exporter.baseDirectory", str(out))

    gen = Generator(GeneratorOptions(), config=cfg)

    assert gen.exporter is not None
    # The exporter must have been built from the provided config's directory...
    assert Path(gen.exporter.base_dir).resolve() == out.resolve()
    # ...and the override must not have been clobbered by a config reload.
    assert gen.config.get("exporter.baseDirectory") == str(out)


def test_generator_reports_loaded_module_count(tmp_path, capsys):
    """#22: the 'Loaded N modules' log must reflect the real count, not 0."""
    cfg = Config()
    cfg.load()
    cfg.set("exporter.baseDirectory", str(tmp_path / "out"))

    Generator(GeneratorOptions(), config=cfg)

    out = capsys.readouterr().out
    assert "Loading modules..." in out
    assert "Loaded 0 modules" not in out
