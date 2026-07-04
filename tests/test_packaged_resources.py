"""Guard that bundled resources ship inside the ``synthea`` package.

These tests fail if the ``resources/`` tree is ever moved back outside the
package or dropped from the wheel: since there is no ``resources/`` directory at
the repo root anymore, the only way the loaders can find data is via the
package-relative resolver in :mod:`synthea.helpers.resources`.
"""

from pathlib import Path

from synthea.engine.module import Module
from synthea.helpers.resources import resource_path, resources_root


def test_resources_root_is_inside_package():
    root = resources_root()
    assert root.is_dir(), f"resources root not found: {root}"
    # Must resolve to the packaged directory, not a CWD-relative 'resources'.
    assert root.name == "resources"
    assert root.parent.name == "synthea"


def test_key_resource_files_present():
    for rel in ("synthea.properties", "cdc_growth_charts.json"):
        assert resource_path(rel).is_file(), f"missing bundled resource: {rel}"
    assert resource_path("modules").is_dir()


def test_modules_load_from_packaged_resources():
    Module.load_modules()
    modules = Module.get_all_modules()
    assert len(modules) > 0, "no disease modules loaded from packaged resources"
