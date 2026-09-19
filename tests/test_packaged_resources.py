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


class TestProvenance:
    """Imported upstream data must match the manifest that documents it."""

    def test_every_recorded_file_is_present_and_unmodified(self):
        import hashlib
        import json

        from synthea.helpers.resources import resources_root

        root = resources_root()
        manifest_path = root / 'PROVENANCE.json'
        assert manifest_path.exists(), "PROVENANCE.json must ship with the package"

        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        assert manifest['source_commit']
        assert manifest['licence'] == 'Apache-2.0'
        assert manifest['files']

        for entry in manifest['files']:
            path = root / entry['path']
            assert path.exists(), f"missing bundled resource: {entry['path']}"
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            assert digest == entry['sha256'], f"modified resource: {entry['path']}"

    def test_every_lookup_table_a_module_references_is_bundled(self):
        """289 references used to resolve to nothing at all."""
        import json

        from synthea.helpers.resources import resource_path

        referenced = set()

        def walk(node):
            if isinstance(node, dict):
                if 'lookup_table_name' in node:
                    referenced.add(node['lookup_table_name'])
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        for module_file in resource_path('modules').rglob('*.json'):
            text = module_file.read_text(encoding='utf-8')
            if 'lookup_table_name' in text:
                walk(json.loads(text))

        assert referenced, "expected the modules to reference lookup tables"

        bundled = {p.name for p in resource_path('lookup_tables').glob('*.csv')}
        assert not (referenced - bundled), sorted(referenced - bundled)


class TestExporterConfiguration:
    """A configuration flag must not promise output that cannot be produced."""

    def test_enabling_an_unimplemented_exporter_is_refused_clearly(self, tmp_path):
        import pytest

        from synthea.export.exporter import Exporter
        from synthea.helpers.config import Config

        for flag in ('exporter.csv.export', 'exporter.ccda.export'):
            config = Config()
            config.load()
            config.set('exporter.baseDirectory', str(tmp_path))
            config.set(flag, True)

            with pytest.raises(NotImplementedError) as raised:
                Exporter(config)

            message = str(raised.value)
            assert flag in message
            assert 'issues/' in message, "the error should point at the tracking issue"

    def test_the_supported_exporters_still_build(self, tmp_path):
        from synthea.export.exporter import Exporter
        from synthea.helpers.config import Config

        config = Config()
        config.load()
        config.set('exporter.baseDirectory', str(tmp_path))
        config.set('exporter.fhir.export', True)
        config.set('exporter.json.export', True)

        assert len(Exporter(config).patient_exporters) == 2
