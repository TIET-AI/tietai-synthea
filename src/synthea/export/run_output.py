"""Disk-backed, deterministic run exports shared by sequential and worker runs."""

import json
import os
import shutil
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from synthea.export.population import PopulationReport, patient_summary


def dumps(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def bulk_resources(bundle):
    """Resolve bundle-local URNs to portable ResourceType/id references."""
    references = {
        e["fullUrl"]: e["resource"]["resourceType"] + "/" + e["resource"]["id"]
        for e in bundle["entry"]
    }

    def rewrite(value):
        if isinstance(value, dict):
            return {
                key: (
                    references[item]
                    if key == "reference" and isinstance(item, str) and item.startswith("urn:uuid:")
                    else rewrite(item)
                )
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [rewrite(item) for item in value]
        return value

    return [rewrite(e["resource"]) for e in bundle["entry"]]


class RunOutput:
    def __init__(self, config, base_dir, locale=None):
        self.config, self.base_dir, self.locale = config, Path(base_dir), locale
        self.report = PopulationReport(config)
        self.bulk = config.get_bool("exporter.fhir.bulk_data", False)
        self.csv = None
        if config.get_bool("exporter.csv.export", False):
            from synthea.export.csv_exporter import CSVExporter

            self.csv = CSVExporter(config)
        self.enabled = self.report.enabled or self.bulk or self.csv is not None
        self.stage = None
        self.previous_bulk = set()

    def begin(self):
        if not self.enabled:
            return
        self.report = PopulationReport(self.config)
        self.stage = Path(tempfile.mkdtemp(prefix=".synthea-run-", dir=self.base_dir))
        self.config.set("exporter.run_stage", str(self.stage))
        # An old success marker must not survive a failed subsequent run.
        if self.bulk:
            manifest = self.base_dir / "fhir" / "bulk" / "manifest.json"
            if manifest.exists():
                previous = json.loads(manifest.read_text(encoding="utf-8"))
                self.previous_bulk = {
                    item["url"]
                    for item in previous.get("output", [])
                    if item.get("url") == item.get("type", "") + ".ndjson"
                    and item.get("type", "").isalpha()
                }
                manifest.unlink()
        if self.report.enabled:
            for filename in ("population.json", "population.md"):
                (self.base_dir / "report" / filename).unlink(missing_ok=True)

    def add(self, person, exported=True):
        if not self.enabled:
            return
        if self.stage is None:
            shared = self.config.get("exporter.run_stage")
            if shared:
                self.stage = Path(shared)
            else:
                self.begin()
        value = {}
        if self.report.enabled:
            end = self.config.get("exporter.report.reference_date") or getattr(
                person, "_simulation_end", None
            )
            if not end:
                from synthea.export.fhir import _record_end

                end = _record_end(person)
            value["summary"] = patient_summary(person, end)
        if exported and (self.bulk or self.csv):
            from synthea.export.fhir import FHIRExporter

            bundle = FHIRExporter(self.config, self.base_dir, self.locale).create_bundle(person)
            if self.bulk:
                value["resources"] = bulk_resources(bundle)
            if self.csv:
                value["rows"] = self.csv.rows(person, bundle)
        target = self.stage / (str(person.id) + ".json")
        temporary = target.with_suffix(".tmp")
        temporary.write_text(dumps(value), encoding="utf-8")
        os.replace(temporary, target)

    def finish(self, stats):
        if not self.enabled:
            return
        if self.stage is None:
            self.begin()
        from synthea.engine.module import Module

        try:
            # SQLite's transaction context does not close the file handle.
            # Close it before abort() removes staging, including on failure.
            with (
                closing(sqlite3.connect(str(self.stage / "aggregate.sqlite"))) as connection,
                connection,
            ):
                connection.execute(
                    "CREATE TABLE resources (kind TEXT, id TEXT, payload TEXT, PRIMARY KEY(kind,id))"
                )
                connection.execute(
                    "CREATE TABLE csv_rows (table_name TEXT, row_key TEXT, payload TEXT, PRIMARY KEY(table_name,row_key))"
                )
                for path in sorted(self.stage.glob("*.json")):
                    data = json.loads(path.read_text(encoding="utf-8"))
                    if "summary" in data:
                        self.report.add(data["summary"])
                    for resource in data.get("resources", []):
                        payload = dumps(resource)
                        key = (resource["resourceType"], resource["id"])
                        previous = connection.execute(
                            "SELECT payload FROM resources WHERE kind=? AND id=?", key
                        ).fetchone()
                        if previous and previous[0] != payload:
                            raise ValueError("Conflicting shared FHIR resource: " + "/".join(key))
                        connection.execute(
                            "INSERT OR IGNORE INTO resources VALUES (?,?,?)", key + (payload,)
                        )
                    for table, key, row in data.get("rows", []):
                        connection.execute(
                            "INSERT OR IGNORE INTO csv_rows VALUES (?,?,?)",
                            (table, key, dumps(row)),
                        )
                if self.csv:
                    self.csv.write(self.base_dir, connection)
                # Validate all targets before publishing the bulk success manifest.
                if self.report.enabled:
                    modules = {name: Module.get_module(name) for name in Module.get_all_modules()}
                    self.report.write(self.base_dir, stats, modules)
                if self.bulk:
                    self._write_bulk(connection)
        finally:
            self.abort()

    def abort(self):
        if self.stage is not None:
            shutil.rmtree(self.stage)
            self.stage = None
        self.config.set("exporter.run_stage", "")

    def _write_bulk(self, connection):
        directory = self.base_dir / "fhir" / "bulk"
        directory.mkdir(parents=True, exist_ok=True)
        output = []
        for kind, count in connection.execute(
            "SELECT kind, count(*) FROM resources GROUP BY kind ORDER BY kind"
        ):
            temporary = self.stage / (kind + ".ndjson")
            with temporary.open("w", encoding="utf-8", newline="\n") as handle:
                for (payload,) in connection.execute(
                    "SELECT payload FROM resources WHERE kind=? ORDER BY id", (kind,)
                ):
                    handle.write(payload + "\n")
            os.replace(temporary, directory / temporary.name)
            output.append({"type": kind, "url": kind + ".ndjson", "count": count})
        # Only remove stale files in the namespace this exporter owns.
        current = {item["url"] for item in output}
        for name in self.previous_bulk - current:
            (directory / name).unlink(missing_ok=True)
        from datetime import datetime
        from synthea.export.fhir import fhir_datetime

        date = datetime.fromisoformat(self.config.get("exporter.report.reference_date"))
        manifest = {
            "transactionTime": fhir_datetime(date),
            "request": "urn:tietai:synthea:generate",
            "requiresAccessToken": False,
            "output": output,
            "error": [],
        }
        temporary = self.stage / "manifest.json"
        temporary.write_text(dumps(manifest) + "\n", encoding="utf-8")
        os.replace(temporary, directory / "manifest.json")
