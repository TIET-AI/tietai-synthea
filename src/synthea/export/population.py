"""Population-level measurements and explicit target bounds (#44).

Prevalence is lifetime recorded prevalence, not point prevalence. Rates use
observed lifetime person-years, ending at death or the simulation end date.
"""

import json
import math
from collections import Counter
from datetime import datetime
from pathlib import Path

import yaml


class TargetError(ValueError):
    pass


def age_band(age):
    start = min(100, max(0, int(age) // 5 * 5))
    return "100+" if start == 100 else f"{start:02d}-{start + 4:02d}"


def patient_summary(person, end):
    end = datetime.fromisoformat(end) if isinstance(end, str) else end
    birth = person.birth_date
    stop = min(end, person.death_date) if person.death_date else end
    years = max(0.0, (stop - birth).total_seconds() / (365.25 * 86400)) if birth else 0
    age = person.age_in_years(stop) if birth else 0
    conditions = {}
    for condition in person.record.conditions:
        if condition.codes:
            code = condition.codes[0]
            conditions[code.system + "|" + str(code.code)] = code.display
    return {
        "age_band": age_band(age),
        "sex": person.attributes.get("gender", "unknown"),
        "dead": not person.alive,
        "person_years": years,
        "conditions": conditions,
        "encounters": dict(Counter(e.encounter_class.value for e in person.record.encounters)),
        "medications": len(person.record.medications),
        "state_hits": getattr(person, "_report_state_hits", {}),
    }


class PopulationReport:
    def __init__(self, config):
        self.enabled = config.get_bool("exporter.report.export", True)
        self.targets_path = config.get("exporter.report.targets")
        if self.targets_path and not self.enabled:
            raise TargetError("Population targets require reporting; remove --no-report")
        self.targets = self._load_targets(self.targets_path) if self.targets_path else []
        self.count = self.dead = self.medications = 0
        self.years = 0.0
        self.pyramid = Counter()
        self.deaths = Counter()
        self.encounters = Counter()
        self.conditions = Counter()
        self.displays = {}
        self.hits = {}

    @staticmethod
    def _load_targets(path):
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        if (
            not isinstance(data, dict)
            or set(data) != {"targets"}
            or not isinstance(data["targets"], list)
        ):
            raise TargetError("Expected targets.yml containing a targets list")
        seen = set()
        for target in data["targets"]:
            if not isinstance(target, dict) or not isinstance(target.get("metric"), str):
                raise TargetError("Every target needs a metric path")
            if set(target) - {"metric", "min", "max"} or not ({"min", "max"} & set(target)):
                raise TargetError("Targets accept metric and min/max bounds only")
            if target["metric"] in seen:
                raise TargetError("Duplicate target: " + target["metric"])
            seen.add(target["metric"])
            for bound in ("min", "max"):
                if bound in target and (
                    isinstance(target[bound], bool)
                    or not isinstance(target[bound], (int, float))
                    or not math.isfinite(target[bound])
                ):
                    raise TargetError("Target bounds must be finite numbers")
            if target.get("min", -math.inf) > target.get("max", math.inf):
                raise TargetError("Target min must not exceed max")
        return data["targets"]

    def add(self, summary):
        self.count += 1
        self.dead += int(summary["dead"])
        self.years += summary["person_years"]
        self.medications += summary["medications"]
        self.pyramid[(summary["age_band"], summary["sex"])] += 1
        if summary["dead"]:
            self.deaths[summary["age_band"]] += 1
        self.encounters.update(summary["encounters"])
        self.conditions.update(summary["conditions"].keys())
        self.displays.update(summary["conditions"])
        for module, hits in summary["state_hits"].items():
            self.hits.setdefault(module, Counter()).update(hits)

    def result(self, stats, modules):
        hits = {
            name: {state: self.hits.get(name, {}).get(state, 0) for state in sorted(module.states)}
            for name, module in sorted(modules.items())
            if getattr(module, "states", None)
        }
        for name, counts in self.hits.items():
            hits.setdefault(name, {}).update(counts)
        conditions = {
            key: {
                "patients": value,
                "prevalence": value / self.count if self.count else 0,
                "display": self.displays[key],
            }
            for key, value in sorted(self.conditions.items())
        }
        report = {
            "schema_version": 1,
            "definitions": {
                "prevalence": "ever recorded during simulated lifetime",
                "age": "completed years at death or simulation end",
                "person_years": "birth through death or simulation end",
                "state_hits": "GMF state entries; waiting polls excluded; Python core modules excluded",
            },
            "population": {
                "generated": self.count,
                "living": self.count - self.dead,
                "dead": self.dead,
                "rejected": stats.get("rejected", 0),
            },
            "person_years": round(self.years, 6),
            "demographics": [
                {"age_band": band, "sex": sex, "count": n}
                for (band, sex), n in sorted(self.pyramid.items())
            ],
            "mortality_by_age_band": dict(sorted(self.deaths.items())),
            "conditions": conditions,
            "top_conditions": [
                key for key, _ in sorted(self.conditions.items(), key=lambda x: (-x[1], x[0]))[:50]
            ],
            "encounters": {
                key: {"count": n, "per_patient_year": n / self.years if self.years else 0}
                for key, n in sorted(self.encounters.items())
            },
            "medications": {
                "count": self.medications,
                "per_patient": self.medications / self.count if self.count else 0,
            },
            "module_state_hits": hits,
        }
        checks = []
        for target in self.targets:
            # Slash-separated paths allow code-system URIs and dotted module names
            # via JSON Pointer escaping (~1 = slash, ~0 = tilde).
            value = report
            try:
                for key in target["metric"].strip("/").split("/"):
                    value = value[key.replace("~1", "/").replace("~0", "~")]
            except (KeyError, TypeError):
                value = None
            numeric = isinstance(value, (int, float)) and not isinstance(value, bool)
            checks.append(
                dict(
                    target,
                    observed=value,
                    passed=numeric
                    and target.get("min", -math.inf) <= value <= target.get("max", math.inf),
                )
            )
        report["targets"] = checks
        report["targets_passed"] = all(c["passed"] for c in checks)
        return report

    def write(self, base_dir, stats, modules):
        report = self.result(stats, modules)
        directory = Path(base_dir) / "report"
        directory.mkdir(exist_ok=True)
        (directory / "population.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        lines = [
            "# Population report",
            "",
            f"Generated: {self.count}; living: {self.count-self.dead}; dead: {self.dead}.",
            f"Observed person-years: {self.years:.3f}. Medications per patient: {report['medications']['per_patient']:.3f}.",
            "",
            "Prevalence covers the entire simulated lifetime.",
            "",
            "| Condition | Patients | Prevalence |",
            "|---|---:|---:|",
        ]
        for key in report["top_conditions"]:
            c = report["conditions"][key]
            label = c["display"].replace("|", "\\|").replace("\n", " ")
            lines.append(f"| {label} | {c['patients']} | {c['prevalence']:.4f} |")
        lines += ["", "## Demographics", "", "| Age band | Sex | Patients |", "|---|---|---:|"]
        lines += [
            f"| {d['age_band']} | {d['sex']} | {d['count']} |" for d in report["demographics"]
        ]
        lines += ["", "## Encounters", "", "| Class | Count | Per person-year |", "|---|---:|---:|"]
        lines += [
            f"| {k} | {v['count']} | {v['per_patient_year']:.4f} |"
            for k, v in report["encounters"].items()
        ]
        lines += ["", "## Deaths by age band", "", "| Age band | Deaths |", "|---|---:|"]
        lines += [f"| {band} | {n} |" for band, n in report["mortality_by_age_band"].items()]
        lines += ["", "## Module state coverage", ""]
        lines += [
            f"- {name}: {sum(n > 0 for n in counts.values())}/{len(counts)} states entered"
            for name, counts in sorted(report["module_state_hits"].items())
        ]
        lines += ["", "## Targets", ""]
        lines += [
            f"- {c['metric']}: {'PASS' if c['passed'] else 'FAIL'} (observed {c['observed']})"
            for c in report["targets"]
        ]
        (directory / "population.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        if not report["targets_passed"]:
            raise TargetError("Population targets missed; see report/population.json")
        return report
