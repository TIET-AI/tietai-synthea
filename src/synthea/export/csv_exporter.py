"""Upstream CSV tables (#42). Headers pinned to Synthea 0857400eacbbecc5a67c7d05740efa227d22db39."""

import csv
from pathlib import Path

HEADERS = {
    "patients": [
        "Id",
        "BIRTHDATE",
        "DEATHDATE",
        "SSN",
        "DRIVERS",
        "PASSPORT",
        "PREFIX",
        "FIRST",
        "MIDDLE",
        "LAST",
        "SUFFIX",
        "MAIDEN",
        "MARITAL",
        "RACE",
        "ETHNICITY",
        "GENDER",
        "BIRTHPLACE",
        "ADDRESS",
        "CITY",
        "STATE",
        "COUNTY",
        "FIPS",
        "ZIP",
        "LAT",
        "LON",
        "HEALTHCARE_EXPENSES",
        "HEALTHCARE_COVERAGE",
        "INCOME",
    ],
    "allergies": [
        "START",
        "STOP",
        "PATIENT",
        "ENCOUNTER",
        "CODE",
        "SYSTEM",
        "DESCRIPTION",
        "TYPE",
        "CATEGORY",
        "REACTION1",
        "DESCRIPTION1",
        "SEVERITY1",
        "REACTION2",
        "DESCRIPTION2",
        "SEVERITY2",
    ],
    "medications": [
        "START",
        "STOP",
        "PATIENT",
        "PAYER",
        "ENCOUNTER",
        "CODE",
        "DESCRIPTION",
        "BASE_COST",
        "PAYER_COVERAGE",
        "DISPENSES",
        "TOTALCOST",
        "REASONCODE",
        "REASONDESCRIPTION",
    ],
    "conditions": ["START", "STOP", "PATIENT", "ENCOUNTER", "SYSTEM", "CODE", "DESCRIPTION"],
    "careplans": [
        "Id",
        "START",
        "STOP",
        "PATIENT",
        "ENCOUNTER",
        "CODE",
        "DESCRIPTION",
        "REASONCODE",
        "REASONDESCRIPTION",
    ],
    "observations": [
        "DATE",
        "PATIENT",
        "ENCOUNTER",
        "CATEGORY",
        "CODE",
        "DESCRIPTION",
        "VALUE",
        "UNITS",
        "TYPE",
    ],
    "procedures": [
        "START",
        "STOP",
        "PATIENT",
        "ENCOUNTER",
        "SYSTEM",
        "CODE",
        "DESCRIPTION",
        "BASE_COST",
        "REASONCODE",
        "REASONDESCRIPTION",
    ],
    "immunizations": ["DATE", "PATIENT", "ENCOUNTER", "CODE", "DESCRIPTION", "BASE_COST"],
    "encounters": [
        "Id",
        "START",
        "STOP",
        "PATIENT",
        "ORGANIZATION",
        "PROVIDER",
        "PAYER",
        "ENCOUNTERCLASS",
        "CODE",
        "DESCRIPTION",
        "BASE_ENCOUNTER_COST",
        "TOTAL_CLAIM_COST",
        "PAYER_COVERAGE",
        "REASONCODE",
        "REASONDESCRIPTION",
    ],
    "imaging_studies": [
        "Id",
        "DATE",
        "PATIENT",
        "ENCOUNTER",
        "SERIES_UID",
        "BODYSITE_CODE",
        "BODYSITE_DESCRIPTION",
        "MODALITY_CODE",
        "MODALITY_DESCRIPTION",
        "INSTANCE_UID",
        "SOP_CODE",
        "SOP_DESCRIPTION",
        "PROCEDURE_CODE",
    ],
    "devices": ["START", "STOP", "PATIENT", "ENCOUNTER", "CODE", "DESCRIPTION", "UDI"],
    "supplies": ["DATE", "PATIENT", "ENCOUNTER", "CODE", "DESCRIPTION", "QUANTITY"],
    "organizations": [
        "Id",
        "NAME",
        "ADDRESS",
        "CITY",
        "STATE",
        "ZIP",
        "LAT",
        "LON",
        "PHONE",
        "REVENUE",
        "UTILIZATION",
        "NPI",
    ],
    "providers": [
        "Id",
        "ORGANIZATION",
        "NAME",
        "GENDER",
        "SPECIALITY",
        "ADDRESS",
        "CITY",
        "STATE",
        "ZIP",
        "LAT",
        "LON",
        "ENCOUNTERS",
        "PROCEDURES",
        "NPI",
    ],
    "payers": [
        "Id",
        "NAME",
        "OWNERSHIP",
        "ADDRESS",
        "CITY",
        "STATE_HEADQUARTERED",
        "ZIP",
        "PHONE",
        "AMOUNT_COVERED",
        "AMOUNT_UNCOVERED",
        "REVENUE",
        "COVERED_ENCOUNTERS",
        "UNCOVERED_ENCOUNTERS",
        "COVERED_MEDICATIONS",
        "UNCOVERED_MEDICATIONS",
        "COVERED_PROCEDURES",
        "UNCOVERED_PROCEDURES",
        "COVERED_IMMUNIZATIONS",
        "UNCOVERED_IMMUNIZATIONS",
        "UNIQUE_CUSTOMERS",
        "QOLS_AVG",
        "MEMBER_MONTHS",
    ],
    "payer_transitions": [
        "PATIENT",
        "MEMBERID",
        "START_DATE",
        "END_DATE",
        "PAYER",
        "SECONDARY_PAYER",
        "PLAN_OWNERSHIP",
        "OWNER_NAME",
    ],
    "claims": [
        "Id",
        "PATIENTID",
        "PROVIDERID",
        "PRIMARYPATIENTINSURANCEID",
        "SECONDARYPATIENTINSURANCEID",
        "DEPARTMENTID",
        "PATIENTDEPARTMENTID",
        "DIAGNOSIS1",
        "DIAGNOSIS2",
        "DIAGNOSIS3",
        "DIAGNOSIS4",
        "DIAGNOSIS5",
        "DIAGNOSIS6",
        "DIAGNOSIS7",
        "DIAGNOSIS8",
        "REFERRINGPROVIDERID",
        "APPOINTMENTID",
        "CURRENTILLNESSDATE",
        "SERVICEDATE",
        "SUPERVISINGPROVIDERID",
        "STATUS1",
        "STATUS2",
        "STATUSP",
        "OUTSTANDING1",
        "OUTSTANDING2",
        "OUTSTANDINGP",
        "LASTBILLEDDATE1",
        "LASTBILLEDDATE2",
        "LASTBILLEDDATEP",
        "HEALTHCARECLAIMTYPEID1",
        "HEALTHCARECLAIMTYPEID2",
    ],
}


def ref(value):
    return (value or {}).get("reference", "").replace("urn:uuid:", "").split("/")[-1]


def first(values):
    return values[0] if values else {}


def code(concept):
    return first((concept or {}).get("coding", []))


def when(value):
    from synthea.export.fhir import fhir_datetime

    return fhir_datetime(value) if value else ""


def money(value):
    return round(value, 2) if value is not None else ""


def _selected(config):
    def names(key):
        value = config.get("exporter.csv." + key, "") or ""
        values = value if isinstance(value, list) else str(value).split(",")
        result = {v.strip().removesuffix(".csv") for v in values if v.strip()}
        known = set(HEADERS) | (
            {"patient_expenses", "claims_transactions"} if key == "excluded_files" else set()
        )
        unknown = result - known
        if unknown:
            raise ValueError("Unknown CSV files: " + ", ".join(sorted(unknown)))
        return result

    included, excluded = names("included_files"), names("excluded_files")
    return sorted((included or set(HEADERS)) - excluded)


class CSVExporter:
    """Stage rows per patient; the parent writes files once after workers finish.

    Resources are keyed by their FHIR id, so shared organizations/providers do
    not multiply by population size. Observations with components produce one
    row per component; ImagingStudy produces one row per DICOM instance.
    Unsupported source values remain empty instead of invented zeroes.
    """

    def __init__(self, config):
        if config.get_bool("exporter.csv.folder_per_run", False):
            raise ValueError("CSV folder_per_run is unsupported; choose a separate --output-dir")
        self.selected = _selected(config)
        self.append = config.get_bool("exporter.csv.append_mode", False)

    def rows(self, person, bundle):
        resources = [e["resource"] for e in bundle["entry"]]
        indexed = {r["id"]: r for r in resources}
        record = person.record
        objects = {
            e.id: e
            for name in (
                "encounters",
                "conditions",
                "medications",
                "procedures",
                "observations",
                "immunizations",
                "allergies",
                "careplans",
                "imaging_studies",
                "devices",
                "supplies",
            )
            for e in getattr(record, name, [])
        }
        from synthea.export.fhir import _claim_uuid, _payer_uuid

        claims = {_claim_uuid(e): e for e in record.encounters}
        payer_models = {
            _payer_uuid(c.plan.payer): c.plan.payer
            for c in person.attributes.get("coverage_history", [])
            if c.plan
        }
        result = []

        def emit(table, key, values):
            # Keep rows for all tables: later global utilization/finance can be
            # reconciled even when a table is excluded from the output selection.
            result.append(
                [
                    table,
                    key,
                    dict(
                        {h: values.get(h, "") for h in HEADERS[table]},
                        **{k: v for k, v in values.items() if k.startswith("_")},
                    ),
                ]
            )

        patient = next(r for r in resources if r["resourceType"] == "Patient")
        attrs = person.attributes
        name, address = first(patient.get("name")), first(patient.get("address"))
        patient_row = dict(
            Id=person.id,
            BIRTHDATE=patient.get("birthDate", ""),
            DEATHDATE=patient.get("deceasedDateTime", "")[:10],
            FIRST=next(iter(name.get("given", [])), ""),
            LAST=name.get("family", ""),
            PREFIX=" ".join(name.get("prefix", [])),
            GENDER={"male": "M", "female": "F"}.get(patient.get("gender"), ""),
            MARITAL=code(patient.get("maritalStatus")).get("code", ""),
            ADDRESS=" ".join(address.get("line", [])),
            CITY=address.get("city", ""),
            STATE=address.get("state", ""),
            ZIP=address.get("postalCode", ""),
        )
        for col, key in {
            "SSN": "identifier_ssn",
            "DRIVERS": "identifier_drivers",
            "PASSPORT": "identifier_passport",
            "MIDDLE": "middle_name",
            "SUFFIX": "name_suffix",
            "MAIDEN": "maiden_name",
            "RACE": "race",
            "ETHNICITY": "ethnicity",
            "BIRTHPLACE": "birthplace",
            "COUNTY": "county",
            "FIPS": "fips",
            "LAT": "latitude",
            "LON": "longitude",
            "INCOME": "income",
        }.items():
            patient_row[col] = attrs.get(key, "")
        priced = [e for e in objects.values() if e.cost is not None]
        patient_row["HEALTHCARE_EXPENSES"] = money(sum(e.patient_cost or 0 for e in priced))
        patient_row["HEALTHCARE_COVERAGE"] = money(sum(e.payer_cost or 0 for e in priced))
        emit("patients", person.id, patient_row)

        for r in resources:
            kind, rid = r["resourceType"], r["id"]
            obj = objects.get(rid)
            c = code(r.get("code"))
            encounter = getattr(obj, "encounter", None)
            row = dict(
                Id=rid,
                PATIENT=person.id,
                ENCOUNTER=encounter.id if encounter else ref(r.get("encounter")),
                START=when(getattr(obj, "time", None)),
                STOP=when(getattr(obj, "end_time", None)),
                DATE=when(getattr(obj, "time", None)),
                CODE=c.get("code", ""),
                SYSTEM=c.get("system", ""),
                DESCRIPTION=c.get("display", ""),
                BASE_COST=money(getattr(obj, "cost", None)),
            )
            if obj and obj.cost is not None:
                coverage = getattr(obj, "coverage", None)
                row.update(
                    _payer=_payer_uuid(coverage.plan.payer) if coverage and coverage.plan else "",
                    _covered=obj.payer_cost or 0,
                    _uncovered=obj.patient_cost or 0,
                )
            reason = getattr(obj, "reason_entry", None)
            if reason and reason.codes:
                row.update(
                    REASONCODE=reason.codes[0].code, REASONDESCRIPTION=reason.codes[0].display
                )
            if kind == "Encounter":
                participant = first(r.get("participant"))
                c = code(first(r.get("type")))
                coverage = getattr(obj, "coverage", None)
                row.update(
                    ORGANIZATION=ref(r.get("serviceProvider")),
                    PROVIDER=ref(participant.get("individual")),
                    PAYER=_payer_uuid(coverage.plan.payer) if coverage and coverage.plan else "",
                    ENCOUNTERCLASS=obj.encounter_class.value,
                    CODE=c.get("code", ""),
                    DESCRIPTION=c.get("display", ""),
                    BASE_ENCOUNTER_COST=money(obj.cost),
                    TOTAL_CLAIM_COST=money(obj.cost),
                    PAYER_COVERAGE=money(obj.payer_cost),
                )
                emit("encounters", rid, row)
            elif kind in (
                "Condition",
                "AllergyIntolerance",
                "CarePlan",
                "Procedure",
                "Immunization",
                "Device",
                "SupplyDelivery",
            ):
                table = {
                    "Condition": "conditions",
                    "AllergyIntolerance": "allergies",
                    "CarePlan": "careplans",
                    "Procedure": "procedures",
                    "Immunization": "immunizations",
                    "Device": "devices",
                    "SupplyDelivery": "supplies",
                }[kind]
                if obj and obj.codes:
                    row.update(
                        CODE=obj.codes[0].code,
                        DESCRIPTION=obj.codes[0].display,
                        SYSTEM=obj.codes[0].system,
                    )
                if kind in ("Condition", "AllergyIntolerance", "CarePlan", "Device"):
                    row["START"], row["STOP"] = row["START"][:10], row["STOP"][:10]
                if kind == "Procedure" and obj.duration:
                    from datetime import timedelta

                    row["STOP"] = when(obj.time + timedelta(minutes=obj.duration))
                if kind == "AllergyIntolerance":
                    row.update(
                        TYPE=r.get("type", ""), CATEGORY=next(iter(r.get("category", [])), "")
                    )
                    reactions = [
                        (manifestation, reaction.get("severity", ""))
                        for reaction in r.get("reaction", [])
                        for manifestation in reaction.get("manifestation", [])
                    ]
                    for n, (concept, severity) in enumerate(reactions[:2], 1):
                        manifestation = code(concept)
                        row.update(
                            {
                                f"REACTION{n}": manifestation.get("code", ""),
                                f"DESCRIPTION{n}": manifestation.get("display")
                                or concept.get("text", ""),
                                f"SEVERITY{n}": severity.upper(),
                            }
                        )
                if kind == "Device":
                    row["UDI"] = first(r.get("udiCarrier")).get("carrierHRF", "")
                if kind == "SupplyDelivery":
                    row["QUANTITY"] = obj.quantity
                emit(table, rid, row)
            elif kind in ("MedicationRequest", "MedicationAdministration"):
                c = code(r.get("medicationCodeableConcept"))
                coverage = getattr(obj, "coverage", None)
                row.update(
                    CODE=c.get("code", ""),
                    DESCRIPTION=c.get("display", ""),
                    PAYER=_payer_uuid(coverage.plan.payer) if coverage and coverage.plan else "",
                    PAYER_COVERAGE=money(obj.payer_cost),
                    DISPENSES=1,
                    TOTALCOST=money(obj.cost),
                )
                emit("medications", rid, row)
            elif kind == "Observation":
                row["CATEGORY"] = code(first(r.get("category"))).get("code", "")
                for n, value in enumerate(r.get("component") or [r]):
                    c = code(value.get("code"))
                    quantity = value.get("valueQuantity", {})
                    coded = code(value.get("valueCodeableConcept"))
                    v = quantity.get(
                        "value",
                        value.get("valueString", value.get("valueBoolean", coded.get("code", ""))),
                    )
                    emit(
                        "observations",
                        f"{rid}:{n}",
                        dict(
                            row,
                            CODE=c.get("code", ""),
                            DESCRIPTION=c.get("display", ""),
                            VALUE=v,
                            UNITS=quantity.get("unit", ""),
                            TYPE=(
                                "numeric"
                                if isinstance(v, (int, float)) and not isinstance(v, bool)
                                else "text"
                            ),
                        ),
                    )
            elif kind == "ImagingStudy":
                for si, series in enumerate(r.get("series", [])):
                    for ii, instance in enumerate(series.get("instance", [])):
                        body, modality, sop = (
                            series.get("bodySite", {}),
                            series.get("modality", {}),
                            instance.get("sopClass", {}),
                        )
                        emit(
                            "imaging_studies",
                            f"{rid}:{si}:{ii}",
                            dict(
                                row,
                                SERIES_UID=series.get("uid", ""),
                                INSTANCE_UID=instance.get("uid", ""),
                                BODYSITE_CODE=body.get("code", ""),
                                BODYSITE_DESCRIPTION=body.get("display", ""),
                                MODALITY_CODE=modality.get("code", ""),
                                MODALITY_DESCRIPTION=modality.get("display", ""),
                                SOP_CODE=sop.get("code", ""),
                                SOP_DESCRIPTION=sop.get("display", ""),
                                PROCEDURE_CODE=(
                                    obj.procedure_code.code if obj.procedure_code else ""
                                ),
                            ),
                        )
            elif kind == "Organization":
                a = first(r.get("address"))
                values = dict(
                    Id=rid,
                    NAME=r.get("name", ""),
                    ADDRESS=" ".join(a.get("line", [])),
                    CITY=a.get("city", ""),
                    STATE=a.get("state", ""),
                    ZIP=a.get("postalCode", ""),
                    PHONE=next(
                        (v["value"] for v in r.get("telecom", []) if v["system"] == "phone"), ""
                    ),
                )
                if code(first(r.get("type"))).get("code") == "ins":
                    model = payer_models.get(rid)
                    values["OWNERSHIP"] = model.ownership if model else ""
                    values["STATE_HEADQUARTERED"] = values["STATE"]
                    emit("payers", rid, values)
                else:
                    provider = next(
                        (
                            e.provider
                            for e in record.encounters
                            if e.provider and e.provider.name == r.get("name")
                        ),
                        None,
                    )
                    if provider:
                        values["LAT"], values["LON"] = provider.coordinates
                    emit("organizations", rid, values)
            elif kind == "Practitioner":
                n = first(r.get("name"))
                role = next(
                    (
                        v
                        for v in resources
                        if v["resourceType"] == "PractitionerRole"
                        and ref(v.get("practitioner")) == rid
                    ),
                    {},
                )
                organization = ref(role.get("organization"))
                a = first(indexed.get(organization, {}).get("address"))
                emit(
                    "providers",
                    rid,
                    dict(
                        Id=rid,
                        ORGANIZATION=organization,
                        NAME=" ".join(n.get("given", []) + [n.get("family", "")]),
                        GENDER=r.get("gender", ""),
                        SPECIALITY=code(first(role.get("specialty"))).get("display")
                        or first(role.get("specialty")).get("text", ""),
                        ADDRESS=" ".join(a.get("line", [])),
                        CITY=a.get("city", ""),
                        STATE=a.get("state", ""),
                        ZIP=a.get("postalCode", ""),
                        NPI=next(
                            (
                                v["value"]
                                for v in r.get("identifier", [])
                                if v.get("system") == "http://hl7.org/fhir/sid/us-npi"
                            ),
                            "",
                        ),
                    ),
                )
            elif kind == "Coverage":
                payer = ref(first(r.get("payor")))
                emit(
                    "payer_transitions",
                    rid,
                    dict(
                        PATIENT=person.id,
                        MEMBERID=rid,
                        START_DATE=r.get("period", {}).get("start", "")[:10],
                        END_DATE=r.get("period", {}).get("end", "")[:10],
                        PAYER=payer if payer != person.id else "",
                        OWNER_NAME=" ".join(name.get("given", []) + [name.get("family", "")]),
                    ),
                )
            elif kind == "Claim":
                e = claims[rid]
                participant = first(indexed[e.id].get("participant"))
                diagnoses = [
                    condition.codes[0].code for condition in e.conditions if condition.codes
                ][:8]
                values = dict(
                    Id=rid,
                    PATIENTID=person.id,
                    PROVIDERID=ref(participant.get("individual")),
                    PRIMARYPATIENTINSURANCEID=ref(r.get("insurer")),
                    APPOINTMENTID=e.id,
                    CURRENTILLNESSDATE=when(e.time),
                    SERVICEDATE=when(e.time),
                    HEALTHCARECLAIMTYPEID1=2,
                )
                values.update({f"DIAGNOSIS{i+1}": d for i, d in enumerate(diagnoses)})
                emit("claims", rid, values)
        return result

    def write(self, base_dir, connection):
        directory = Path(base_dir) / "csv"
        directory.mkdir(exist_ok=True)
        # Validate every existing header before changing any output.
        for table in self.selected:
            path = directory / (table + ".csv")
            if self.append and path.exists() and path.stat().st_size:
                with path.open(newline="", encoding="utf-8") as f:
                    if next(csv.reader(f), None) != HEADERS[table]:
                        raise ValueError("Cannot append to incompatible CSV header: " + str(path))
        import json
        import os

        index = directory / ".synthea-rows.ndjson"
        if self.append:
            if not index.exists() and any(
                (directory / (t + ".csv")).exists() for t in self.selected
            ):
                raise ValueError(
                    "CSV append needs the .synthea-rows.ndjson index from a previous PySynthea run"
                )
            if index.exists():
                with index.open(encoding="utf-8") as handle:
                    for line in handle:
                        table, key, row = json.loads(line)
                        if table not in HEADERS:
                            raise ValueError("Unknown table in CSV append index: " + table)
                        connection.execute(
                            "INSERT OR IGNORE INTO csv_rows VALUES (?,?,?)",
                            (table, key, json.dumps(row, sort_keys=True)),
                        )
        totals = self._totals(connection)
        # Rebuild the merged rows rather than appending duplicate shared
        # providers and payers. Per-resource keys preserve equal observations.
        for table in self.selected:
            path = directory / (table + ".csv")
            temporary = path.with_suffix(".csv.tmp")
            with temporary.open("w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f, lineterminator="\n")
                writer.writerow(HEADERS[table])
                for (payload,) in connection.execute(
                    "SELECT payload FROM csv_rows WHERE table_name=? ORDER BY row_key", (table,)
                ):
                    row = json.loads(payload)
                    row.update(totals.get((table, row.get("Id")), {}))
                    writer.writerow([row[h] if row[h] is not None else "" for h in HEADERS[table]])
            os.replace(temporary, path)
        temporary = index.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            for table, key, payload in connection.execute(
                "SELECT table_name,row_key,payload FROM csv_rows ORDER BY table_name,row_key"
            ):
                handle.write(json.dumps([table, key, json.loads(payload)], sort_keys=True) + "\n")
        os.replace(temporary, index)

    @staticmethod
    def _totals(connection):
        """Aggregate known utilization and prices across the whole run."""
        import json
        from collections import Counter, defaultdict

        totals = defaultdict(Counter)
        encounters = {}
        customers = defaultdict(set)
        for (payload,) in connection.execute(
            "SELECT payload FROM csv_rows WHERE table_name='encounters'"
        ):
            row = json.loads(payload)
            encounters[row["Id"]] = row
            totals[("organizations", row["ORGANIZATION"])]["UTILIZATION"] += 1
            totals[("providers", row["PROVIDER"])]["ENCOUNTERS"] += 1
        kinds = {
            "encounters": "ENCOUNTERS",
            "medications": "MEDICATIONS",
            "procedures": "PROCEDURES",
            "immunizations": "IMMUNIZATIONS",
        }
        for table, payload in connection.execute("SELECT table_name,payload FROM csv_rows"):
            row = json.loads(payload)
            if table not in kinds:
                continue
            e = row if table == "encounters" else encounters.get(row["ENCOUNTER"], {})
            if table == "procedures":
                totals[("providers", e.get("PROVIDER"))]["PROCEDURES"] += 1
            if "_covered" not in row:
                continue
            totals[("organizations", e.get("ORGANIZATION"))]["REVENUE"] += (
                row["_covered"] + row["_uncovered"]
            )
            if row["_payer"]:
                payer = totals[("payers", row["_payer"])]
                payer["AMOUNT_COVERED"] += row["_covered"]
                payer["AMOUNT_UNCOVERED"] += row["_uncovered"]
                payer[("COVERED_" if row["_covered"] > 0 else "UNCOVERED_") + kinds[table]] += 1
                customers[row["_payer"]].add(row["PATIENT"])
        for payer, patients in customers.items():
            totals[("payers", payer)]["UNIQUE_CUSTOMERS"] = len(patients)
        return {key: {k: round(v, 2) for k, v in values.items()} for key, values in totals.items()}
