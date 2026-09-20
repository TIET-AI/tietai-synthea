"""
FHIR exporter for Synthea.

This module exports patient data in FHIR R4 format.
"""

from pathlib import Path
from typing import Dict, Any, Optional, List, TYPE_CHECKING
from datetime import datetime, timezone
import base64
import hashlib
import json
import uuid

from synthea.export.exporter import PatientExporter
from synthea.export.terminology import system_uri, ucum_code

if TYPE_CHECKING:
    from synthea.world.person import Person
    from synthea.helpers.config import Config
    from synthea.world.health_record import HealthRecord, Encounter, Condition, Medication, Procedure, Observation


#: GMF time units mapped to the UCUM codes FHIR timing expects.
_PERIOD_UNITS = {
    'seconds': 's', 'second': 's',
    'minutes': 'min', 'minute': 'min',
    'hours': 'h', 'hour': 'h',
    'days': 'd', 'day': 'd',
    'weeks': 'wk', 'week': 'wk',
    'months': 'mo', 'month': 'mo',
    'years': 'a', 'year': 'a',
}


#: Encounter class, as the modules name it, mapped to the ActCode value FHIR
#: requires. The enum name upper-cased ("AMBULATORY") is not an ActCode and no
#: server will accept it.
ACT_CODES = {
    'ambulatory': ('AMB', 'ambulatory'),
    'wellness': ('AMB', 'ambulatory'),
    'outpatient': ('AMB', 'ambulatory'),
    'urgentcare': ('AMB', 'ambulatory'),
    'emergency': ('EMER', 'emergency'),
    'inpatient': ('IMP', 'inpatient encounter'),
    'snf': ('IMP', 'inpatient encounter'),
    'hospice': ('HH', 'home health'),
    'home': ('HH', 'home health'),
    'virtual': ('VR', 'virtual'),
}

ACT_CODE_SYSTEM = 'http://terminology.hl7.org/CodeSystem/v3-ActCode'
OBSERVATION_CATEGORY_SYSTEM = (
    'http://terminology.hl7.org/CodeSystem/observation-category')
CONDITION_CATEGORY_SYSTEM = (
    'http://terminology.hl7.org/CodeSystem/condition-category')

#: The only Observation categories FHIR defines. Anything else is reported as
#: `exam`, because an unrecognised category code is invalid.
OBSERVATION_CATEGORIES = {
    'vital-signs', 'laboratory', 'imaging', 'survey', 'exam', 'procedure',
    'therapy', 'activity', 'social-history',
}

US_CORE = 'http://hl7.org/fhir/us/core/StructureDefinition/'
US_CORE_PROFILES = {
    'Patient': US_CORE + 'us-core-patient',
    'Encounter': US_CORE + 'us-core-encounter',
    'Condition': US_CORE + 'us-core-condition-problems-health-concerns',
    'Observation': US_CORE + 'us-core-observation-lab',
    'Procedure': US_CORE + 'us-core-procedure',
    'MedicationRequest': US_CORE + 'us-core-medicationrequest',
    'Immunization': US_CORE + 'us-core-immunization',
    'Organization': US_CORE + 'us-core-organization',
    'Practitioner': US_CORE + 'us-core-practitioner',
    'PractitionerRole': US_CORE + 'us-core-practitionerrole',
    'Location': US_CORE + 'us-core-location',
    'DocumentReference': US_CORE + 'us-core-documentreference',
    'AllergyIntolerance': US_CORE + 'us-core-allergyintolerance',
    'CarePlan': US_CORE + 'us-core-careplan',
    'CareTeam': US_CORE + 'us-core-careteam',
    'DiagnosticReport': US_CORE + 'us-core-diagnosticreport-lab',
    'Goal': US_CORE + 'us-core-goal',
    'Provenance': US_CORE + 'us-core-provenance',
}

US_CORE_VITAL_SIGNS = 'http://hl7.org/fhir/StructureDefinition/vitalsigns'


def _observation_category(observation) -> str:
    """A category code FHIR recognises; anything else becomes `exam`."""
    category = getattr(observation, 'category', None)
    return category if category in OBSERVATION_CATEGORIES else 'exam'


def _act_code(encounter) -> Dict[str, str]:
    """The ActCode for an encounter class.

    The enum name upper-cased ("AMBULATORY") is not an ActCode value and no
    server accepts it.
    """
    code, display = ACT_CODES.get(encounter.encounter_class.value, ('AMB', 'ambulatory'))
    return {"system": ACT_CODE_SYSTEM, "code": code, "display": display}


def prune(node: Any) -> Any:
    """Drop every null from a structure.

    FHIR has no null: an absent value is an absent field. An open encounter's
    `period.end` used to serialise as JSON null, which makes it invalid.
    """
    if isinstance(node, dict):
        return {k: prune(v) for k, v in node.items() if v is not None}
    if isinstance(node, list):
        return [prune(v) for v in node if v is not None]
    return node


def fhir_datetime(value) -> Optional[str]:
    """An ISO timestamp with a timezone, as FHIR requires.

    A dateTime carrying a time must carry an offset too. Simulation times are
    naive, so they are stamped UTC rather than left ambiguous.
    """
    if value is None:
        return None
    if getattr(value, 'tzinfo', None) is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def coding(raw: Any) -> Dict[str, Any]:
    """A FHIR coding whose system is a URI.

    The modules write 'SNOMED-CT' and 'RxNorm'. Those are not URIs, so every
    code exported was correct and simultaneously unresolvable by any server.
    """
    if hasattr(raw, 'system'):
        system, code, display = raw.system, raw.code, raw.display
    elif isinstance(raw, dict):
        system, code, display = raw.get('system'), raw.get('code'), raw.get('display')
    else:
        return {'display': str(raw)}

    result = {'system': system_uri(system), 'code': str(code)}
    if display:
        result['display'] = display
    return result


def codings(items) -> List[Dict[str, Any]]:
    return [coding(item) for item in (items or [])]


def quantity(value, unit) -> Dict[str, Any]:
    """A FHIR Quantity whose `code` is a UCUM symbol, not a display unit."""
    result: Dict[str, Any] = {'value': value}
    ucum = ucum_code(unit)
    if unit:
        result['unit'] = str(unit)
    if ucum:
        result['system'] = 'http://unitsofmeasure.org'
        result['code'] = ucum
    return result


def _stable_uuid(namespace: str, value: str) -> str:
    """A reproducible UUID for a thing that has an id but not a UUID.

    Payers, facilities and clinicians come from CSV rows, so their identifiers
    are not UUIDs, and FHIR's `urn:uuid:` references need one. Deriving it from
    the id keeps the same payer or facility the same resource across every
    patient in a run.
    """
    digest = hashlib.sha256(f"{namespace}:{value}".encode('utf-8')).digest()
    return str(uuid.UUID(bytes=digest[:16], version=4))


def _organization_uuid(provider) -> str:
    return _stable_uuid('organization', provider.id)


def _note_uuid(encounter) -> str:
    return _stable_uuid('note', encounter.id)


def _location_uuid(provider) -> str:
    return _stable_uuid('location', provider.id)


def _practitioner_uuid(clinician) -> str:
    return _stable_uuid('practitioner', clinician.id)


def _practitioner_role_uuid(clinician) -> str:
    return _stable_uuid('practitioner-role', clinician.id)


def _facility_address(provider) -> Dict[str, Any]:
    return {
        "line": [provider.address] if provider.address else None,
        "city": provider.city or None,
        "state": provider.state or None,
        "postalCode": provider.zip_code or None,
        "country": "US",
    }


#: Coverage kind mapped to the ActCode FHIR wants on Coverage.type.
COVERAGE_TYPES = {
    'medicare': 'PUBLICPOL',
    'medicaid': 'PUBLICPOL',
    'private': 'HIP',
    'none': 'PUBLICPOL',
}


def _money(amount) -> Dict[str, Any]:
    """A FHIR Money value in US dollars."""
    return {"value": round(float(amount or 0.0), 2), "currency": "USD"}


def _adjudication(code: str, amount) -> Dict[str, Any]:
    return {
        "category": {"coding": [{
            "system": "http://terminology.hl7.org/CodeSystem/adjudication",
            "code": code,
        }]},
        "amount": _money(amount),
    }


def _coverage_index(person, coverage) -> int:
    """Which coverage period this claim falls under.

    The claim must reference a Coverage that is in the bundle, so the index is
    resolved against the patient's own history rather than invented.
    """
    history = person.attributes.get('coverage_history') or []
    for index, candidate in enumerate(history):
        if candidate is coverage:
            return index
    return 0


def _payer_uuid(payer) -> str:
    return _stable_uuid('payer', payer.id)


def _coverage_uuid(person, index: int) -> str:
    return _stable_uuid('coverage', f"{person.id}:{index}")


def _claim_uuid(encounter) -> str:
    return _stable_uuid('claim', encounter.id)


def _eob_uuid(encounter) -> str:
    return _stable_uuid('eob', encounter.id)
def _goal_uuid(careplan, index: int) -> str:
    return _stable_uuid('goal', f"{careplan.id}:{index}")


def _care_team_uuid(careplan) -> str:
    return _stable_uuid('care-team', careplan.id)


def _provenance_uuid(person) -> str:
    return _stable_uuid('provenance', person.id)


def _device_identifier(device) -> str:
    """A device identifier derived from the record's own id."""
    return _stable_uuid('device-di', device.id).replace('-', '')[:14]


def _device_udi(device) -> str:
    """A UDI in the HRF shape, built from synthetic parts only."""
    identifier = _device_identifier(device)
    serial = _stable_uuid('device-serial', device.id).replace('-', '')[:10]
    return (f"(01){identifier}"
            f"(11){device.time.strftime('%y%m%d')}"
            f"(21){serial}")


#: The `category` an allergy falls into, from the code system it was written
#: in. A drug allergy coded in RxNorm is a medication allergy; anything else
#: the modules produce is a substance.
def _allergy_category(allergy) -> str:
    if not allergy.codes:
        return 'environment'
    system = str(allergy.codes[0].system or '').lower()
    if 'rxnorm' in system:
        return 'medication'
    display = str(allergy.codes[0].display or '').lower()
    if 'food' in display or 'peanut' in display or 'milk' in display:
        return 'food'
    return 'environment'


#: FHIR criticality is a three-value code, not the module's severity word.
_CRITICALITY = {
    'mild': 'low',
    'moderate': 'low',
    'severe': 'high',
}


def _allergy_criticality(severity: str) -> str:
    return _CRITICALITY.get(str(severity).lower(), 'unable-to-assess')


def _version() -> str:
    """The generator's version, for the Provenance agent."""
    try:
        from importlib.metadata import version

        return version('pysynthea')
    except Exception:  # pragma: no cover - source checkout without metadata
        return 'unknown'


class FHIRExporter(PatientExporter):
    """Exports patients in FHIR R4 format."""
    
    def __init__(self, config: 'Config', base_dir: Path):
        """
        Initialize FHIR exporter.
        
        Args:
            config: Configuration object
            base_dir: Base output directory
        """
        self.config = config
        self.base_dir = base_dir
        self.output_dir = base_dir / 'fhir'
        self.output_dir.mkdir(exist_ok=True)
        
        self.use_transaction_bundle = config.get_bool('exporter.fhir.transaction_bundle', True)
        self.use_us_core = config.get_bool('exporter.fhir.use_us_core_ig', True)
    
    def export(self, person: 'Person', time: int) -> Optional[str]:
        """Export person to FHIR."""
        if not hasattr(person, 'record') or not person.record:
            return None
        
        # Create FHIR bundle
        bundle = self.create_bundle(person)
        
        # Generate filename
        if self.config.get_bool('exporter.use_uuid_filenames', False):
            filename = f"{person.id}.json"
        else:
            first_name = person.attributes.get('first_name', 'Unknown')
            last_name = person.attributes.get('last_name', 'Person')
            filename = f"{first_name}_{last_name}_{person.id[:8]}.json"
        
        filepath = self.output_dir / filename
        
        # Write FHIR bundle
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(bundle, f, indent=2, default=str)
        
        return str(filepath)
    
    def _entry(self, resource_type: str, resource_id: str,
               resource: Dict[str, Any], vital_signs: bool = False) -> Dict[str, Any]:
        """Wrap a resource as a bundle entry: profiled, pruned, addressable.

        Every builder goes through here, so profile assignment and null pruning
        cannot be forgotten for a newly added resource type.
        """
        profile = US_CORE_VITAL_SIGNS if vital_signs else US_CORE_PROFILES.get(resource_type)
        if profile and self.use_us_core:
            meta = resource.setdefault("meta", {})
            if not meta.get("profile"):
                meta["profile"] = [profile]

        entry = {
            "fullUrl": f"urn:uuid:{resource_id}",
            "resource": prune(resource),
        }
        if self.use_transaction_bundle:
            entry["request"] = {"method": "POST", "url": resource_type}
        return entry

    def _subject(self, person: 'Person') -> Dict[str, str]:
        return {"reference": f"urn:uuid:{person.uuid}"}

    def create_bundle(self, person: 'Person') -> Dict[str, Any]:
        """
        Create a FHIR bundle for a person.
        
        Args:
            person: The person to create bundle for
            
        Returns:
            FHIR bundle as dictionary
        """
        bundle = {
            "resourceType": "Bundle",
            "type": "transaction" if self.use_transaction_bundle else "collection",
            "entry": []
        }
        
        # Add patient resource
        patient_entry = self.create_patient_entry(person)
        bundle["entry"].append(patient_entry)
        
        # Add encounters
        for encounter in person.record.encounters:
            encounter_entry = self.create_encounter_entry(encounter, person)
            bundle["entry"].append(encounter_entry)
        
        # Add conditions
        for condition in person.record.conditions:
            condition_entry = self.create_condition_entry(condition, person)
            bundle["entry"].append(condition_entry)
        
        # Add medications
        for medication in person.record.medications:
            medication_entry = self.create_medication_entry(medication, person)
            bundle["entry"].append(medication_entry)
        
        # Add procedures
        for procedure in person.record.procedures:
            procedure_entry = self.create_procedure_entry(procedure, person)
            bundle["entry"].append(procedure_entry)
        
        # Add observations
        for observation in person.record.observations:
            observation_entry = self.create_observation_entry(observation, person)
            bundle["entry"].append(observation_entry)

        # Add immunizations
        for immunization in getattr(person.record, 'immunizations', []):
            bundle["entry"].append(
                self.create_immunization_entry(immunization, person)
            )

        
        # Add imaging studies
        for study in getattr(person.record, 'imaging_studies', []):
            bundle['entry'].append(self.create_imaging_study_entry(study, person))

        for allergy in getattr(person.record, 'allergies', []):
            bundle['entry'].append(
                self.create_allergy_intolerance_entry(allergy, person))

        # A CarePlan references its Goals and its CareTeam, so those go in
        # first: a transaction bundle is processed in order, and a reference
        # to an entry that has not been created yet does not resolve.
        for careplan in getattr(person.record, 'careplans', []):
            for index, goal in enumerate(careplan.goals or []):
                bundle['entry'].append(
                    self.create_goal_entry(careplan, index, goal, person))
            bundle['entry'].append(self.create_care_team_entry(careplan, person))
            bundle['entry'].append(self.create_care_plan_entry(careplan, person))

        # Observations are already in the bundle, so a report can reference
        # them by id.
        for report in getattr(person.record, 'reports', []):
            bundle['entry'].append(
                self.create_diagnostic_report_entry(report, person))

        for device in getattr(person.record, 'devices', []):
            bundle['entry'].append(self.create_device_entry(device, person))

        for supply in getattr(person.record, 'supplies', []):
            bundle['entry'].append(
                self.create_supply_delivery_entry(supply, person))

        self._add_care_team(bundle, person)
        self._add_financial(bundle, person)
        self._add_notes(bundle, person)
        bundle['entry'].append(self.create_provenance_entry(bundle, person))

        return bundle
    
    def create_patient_entry(self, person: 'Person') -> Dict[str, Any]:
        """Create a FHIR Patient resource entry."""
        patient = {
            "resourceType": "Patient",
            "id": person.uuid,
            "meta": {
                "profile": ["http://hl7.org/fhir/us/core/StructureDefinition/us-core-patient"]
            } if self.use_us_core else {},
            "identifier": self._identifiers(person),
            "active": person.alive,
            "name": self._names(person),
            "gender": {"M": "male", "F": "female"}.get(person.gender, "unknown"),
            "birthDate": person.birth_date.strftime('%Y-%m-%d') if person.birth_date else None,
        }
        
        # Add death information if applicable
        if not person.alive and person.death_date:
            patient["deceasedDateTime"] = fhir_datetime(person.death_date)
        
        # Add address
        address = {
            "use": "home",
            "city": person.attributes.get('city', 'Unknown'),
            "state": person.attributes.get('state', 'Unknown'),
            "postalCode": person.attributes.get('zip_code', '00000'),
            "country": "US",
        }
        if person.attributes.get('address'):
            address["line"] = [person.attributes['address']]
        latitude = person.attributes.get('latitude')
        longitude = person.attributes.get('longitude')
        if latitude is not None and longitude is not None:
            address["extension"] = [{
                "url": "http://hl7.org/fhir/StructureDefinition/geolocation",
                "extension": [
                    {"url": "latitude", "valueDecimal": latitude},
                    {"url": "longitude", "valueDecimal": longitude},
                ],
            }]
        patient["address"] = [address]

        telecom = []
        if person.attributes.get('telephone'):
            telecom.append({"system": "phone", "value": person.attributes['telephone'],
                            "use": "home"})
        if person.attributes.get('email'):
            telecom.append({"system": "email", "value": person.attributes['email'],
                            "use": "home"})
        if telecom:
            patient["telecom"] = telecom

        marital = person.attributes.get('marital_status')
        if marital:
            patient["maritalStatus"] = {"coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/v3-MaritalStatus",
                "code": marital.get('code'),
                "display": marital.get('display'),
            }]}

        language = person.attributes.get('language_code')
        if language:
            patient["communication"] = [{"language": {"coding": [{
                "system": language.get('system', 'urn:ietf:bcp:47'),
                "code": language.get('code'),
                "display": language.get('display'),
            }]}}]
        
        # Add race/ethnicity extensions if US Core
        if self.use_us_core:
            patient["extension"] = []
            
            # Race extension
            race_ext = {
                "url": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-race",
                "extension": [
                    {
                        "url": "ombCategory",
                        "valueCoding": {
                            "system": "urn:oid:2.16.840.1.113883.6.238",
                            "code": self._map_race_code(person.race),
                            "display": person.race
                        }
                    },
                    {
                        "url": "text",
                        "valueString": person.race
                    }
                ]
            }
            patient["extension"].append(race_ext)
            
            # Ethnicity extension
            ethnicity_ext = {
                "url": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-ethnicity",
                "extension": [
                    {
                        "url": "ombCategory",
                        "valueCoding": {
                            "system": "urn:oid:2.16.840.1.113883.6.238",
                            "code": "2186-5" if person.ethnicity == "non_hispanic" else "2135-2",
                            "display": "Not Hispanic or Latino" if person.ethnicity == "non_hispanic" else "Hispanic or Latino"
                        }
                    },
                    {
                        "url": "text",
                        "valueString": person.ethnicity
                    }
                ]
            }
            patient["extension"].append(ethnicity_ext)

            patient["extension"].append({
                "url": US_CORE + "us-core-birthsex",
                "valueCode": person.gender if person.gender in ('M', 'F') else 'UNK',
            })
        
        return self._entry("Patient", person.uuid, patient)
    
    def create_encounter_entry(self, encounter: 'Encounter', person: 'Person') -> Dict[str, Any]:
        """Create a FHIR Encounter resource entry."""
        encounter_resource = {
            "resourceType": "Encounter",
            "id": encounter.id,
            "status": "finished" if encounter.end_time else "in-progress",
            "class": _act_code(encounter),
            "type": [
                {
                    "coding": codings(encounter.codes)
                }
            ] if encounter.codes else [],
            "subject": {
                "reference": f"urn:uuid:{person.uuid}",
                "display": f"{person.attributes.get('first_name', '')} {person.attributes.get('last_name', '')}"
            },
            "period": {
                "start": fhir_datetime(encounter.time),
                "end": fhir_datetime(encounter.end_time) if encounter.end_time else None
            }
        }
        
        if encounter.reason:
            encounter_resource["reasonCode"] = [
                {
                    "text": encounter.reason
                }
            ]
        
        provider = getattr(encounter, 'provider', None)
        if provider is not None:
            encounter_resource['serviceProvider'] = {
                'reference': f'urn:uuid:{_organization_uuid(provider)}'
            }
            encounter_resource['location'] = [{'location': {
                'reference': f'urn:uuid:{_location_uuid(provider)}'
            }}]

        clinician = getattr(encounter, 'clinician', None)
        if clinician is not None:
            encounter_resource['participant'] = [{
                'type': [{'coding': [{
                    'system': 'http://terminology.hl7.org/CodeSystem/v3-ParticipationType',
                    'code': 'PPRF',
                    'display': 'primary performer',
                }]}],
                'individual': {
                    'reference': f'urn:uuid:{_practitioner_uuid(clinician)}'
                },
            }]

        return self._entry("Encounter", encounter.id, encounter_resource)
    
    def create_condition_entry(self, condition: 'Condition', person: 'Person') -> Dict[str, Any]:
        """Create a FHIR Condition resource entry."""
        condition_resource = {
            "resourceType": "Condition",
            "id": condition.id,
            "clinicalStatus": {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                        "code": "resolved" if condition.end_time else "active"
                    }
                ]
            },
            "verificationStatus": {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/condition-ver-status",
                        "code": "confirmed"
                    }
                ]
            },
            "category": [{"coding": [{
                "system": CONDITION_CATEGORY_SYSTEM,
                "code": ("encounter-diagnosis" if condition.encounter
                         else "problem-list-item"),
            }]}],
            "code": {
                "coding": codings(condition.codes)
            } if condition.codes else {},
            "subject": {
                "reference": f"urn:uuid:{person.uuid}"
            },
            "onsetDateTime": fhir_datetime(condition.time)
        }
        
        if condition.end_time:
            condition_resource["abatementDateTime"] = fhir_datetime(condition.end_time)
        
        if condition.encounter:
            condition_resource["encounter"] = {
                "reference": f"urn:uuid:{condition.encounter.id}"
            }
        
        return self._entry("Condition", condition.id, condition_resource)
    
    def create_medication_entry(self, medication, person) -> Dict[str, Any]:
        """Create a MedicationRequest, or a MedicationAdministration.

        A drug handed to the patient during the visit is not a request for one:
        it is an administration. Exporting both as MedicationRequest, which is
        what happened before, misrepresents 145 states in the bundled modules.
        """
        if getattr(medication, 'administration', False):
            return self._medication_administration(medication, person)
        return self._medication_request(medication, person)

    def _medication_request(self, medication, person) -> Dict[str, Any]:
        resource = {
            "resourceType": "MedicationRequest",
            "id": medication.id,
            "status": "stopped" if medication.end_time else "active",
            "intent": "order",
            "medicationCodeableConcept": {
                "coding": codings(medication.codes)
            } if medication.codes else {},
            "subject": {"reference": f"urn:uuid:{person.uuid}"},
            "authoredOn": fhir_datetime(medication.time),
        }

        if medication.encounter:
            resource["encounter"] = {
                "reference": f"urn:uuid:{medication.encounter.id}"
            }

        self._add_reason(resource, medication)

        prescription = getattr(medication, 'prescription', None) or {}
        dosage = self._dosage_instruction(prescription)
        if dosage:
            resource["dosageInstruction"] = [dosage]

        dispense = self._dispense_request(prescription)
        if dispense:
            resource["dispenseRequest"] = dispense

        return self._entry("MedicationRequest", medication.id, resource)

    def _medication_administration(self, medication, person) -> Dict[str, Any]:
        resource = {
            "resourceType": "MedicationAdministration",
            "id": medication.id,
            "status": "completed",
            "medicationCodeableConcept": {
                "coding": codings(medication.codes)
            } if medication.codes else {},
            "subject": {"reference": f"urn:uuid:{person.uuid}"},
            "effectiveDateTime": fhir_datetime(medication.time),
        }

        if medication.encounter:
            resource["context"] = {
                "reference": f"urn:uuid:{medication.encounter.id}"
            }

        self._add_reason(resource, medication)

        return self._entry("MedicationAdministration", medication.id, resource)

    def _add_reason(self, resource: Dict[str, Any], medication) -> None:
        """Point at the condition being treated rather than naming it in text.

        `reason` used to be exported as the raw module state name in a free-text
        field, which no consumer could resolve to anything.
        """
        entry = getattr(medication, 'reason_entry', None)
        if entry is not None:
            resource["reasonReference"] = [{"reference": f"urn:uuid:{entry.id}"}]
        elif medication.reason:
            resource["reasonCode"] = [{"text": medication.reason}]

    @staticmethod
    def _dosage_instruction(prescription: Dict[str, Any]) -> Dict[str, Any]:
        """Turn a GMF prescription block into a FHIR dosageInstruction."""
        if not prescription:
            return {}

        dosage: Dict[str, Any] = {"sequence": 1}

        if prescription.get('as_needed'):
            dosage["asNeededBoolean"] = True

        detail = prescription.get('dosage') or {}
        amount = detail.get('amount')
        frequency = detail.get('frequency')
        period = detail.get('period')
        unit = detail.get('unit')

        if frequency and period and unit:
            dosage["timing"] = {"repeat": {
                "frequency": frequency,
                "period": period,
                "periodUnit": _PERIOD_UNITS.get(str(unit).lower(), 'd'),
            }}

        if amount:
            dosage["doseAndRate"] = [{"doseQuantity": {"value": amount}}]

        instructions = prescription.get('instructions')
        if instructions:
            dosage["additionalInstruction"] = [
                {"coding": [coding(instruction)]} for instruction in instructions
            ]

        return dosage if len(dosage) > 1 else {}

    @staticmethod
    def _dispense_request(prescription: Dict[str, Any]) -> Dict[str, Any]:
        """Refills and supply duration."""
        if not prescription:
            return {}

        dispense: Dict[str, Any] = {}

        refills = prescription.get('refills')
        if refills is not None:
            dispense["numberOfRepeatsAllowed"] = refills

        duration = prescription.get('duration')
        if duration and duration.get('quantity'):
            unit = str(duration.get('unit', 'days')).lower()
            dispense["expectedSupplyDuration"] = {
                "value": duration['quantity'],
                "unit": unit,
                "system": "http://unitsofmeasure.org",
                "code": _PERIOD_UNITS.get(unit, 'd'),
            }

        return dispense

    def create_imaging_study_entry(self, study, person) -> Dict[str, Any]:
        """Create a FHIR ImagingStudy resource entry."""
        series = []
        for index, definition in enumerate(study.series or [], start=1):
            instances = definition.get('instances') or []

            entry_series: Dict[str, Any] = {
                "uid": definition.get('uid'),
                "number": index,
                "numberOfInstances": len(instances),
            }
            if definition.get('modality') is not None:
                entry_series["modality"] = coding(definition['modality'])
            if definition.get('body_site') is not None:
                entry_series["bodySite"] = coding(definition['body_site'])

            entry_series["instance"] = [
                {
                    "uid": instance.get('uid'),
                    "number": position,
                    "title": instance.get('title'),
                    "sopClass": coding(instance.get('sop_class')),
                }
                for position, instance in enumerate(instances, start=1)
                if instance.get('sop_class') is not None
            ]
            series.append(entry_series)

        resource = {
            "resourceType": "ImagingStudy",
            "id": study.id,
            "status": "available",
            "subject": {"reference": f"urn:uuid:{person.uuid}"},
            "started": fhir_datetime(study.time),
            "numberOfSeries": len(series),
            "numberOfInstances": sum(s.get("numberOfInstances", 0) for s in series),
            "series": series,
        }

        if study.dicom_uid:
            resource["identifier"] = [{
                "system": "urn:dicom:uid",
                "value": f"urn:oid:{study.dicom_uid}",
            }]

        if study.encounter:
            resource["encounter"] = {"reference": f"urn:uuid:{study.encounter.id}"}

        if study.procedure_code is not None:
            resource["procedureCode"] = [{"coding": [coding(study.procedure_code)]}]

        return self._entry("ImagingStudy", study.id, resource)

    def create_procedure_entry(self, procedure: 'Procedure', person: 'Person') -> Dict[str, Any]:
        """Create a FHIR Procedure resource entry."""
        procedure_resource = {
            "resourceType": "Procedure",
            "id": procedure.id,
            "status": "completed",
            "code": {
                "coding": codings(procedure.codes)
            } if procedure.codes else {},
            "subject": {
                "reference": f"urn:uuid:{person.uuid}"
            },
            "performedDateTime": fhir_datetime(procedure.time)
        }
        
        if procedure.encounter:
            procedure_resource["encounter"] = {
                "reference": f"urn:uuid:{procedure.encounter.id}"
            }
        
        if procedure.reason:
            procedure_resource["reasonCode"] = [
                {
                    "text": procedure.reason
                }
            ]
        
        return self._entry("Procedure", procedure.id, procedure_resource)
    
    def create_observation_entry(self, observation: 'Observation', person: 'Person') -> Dict[str, Any]:
        """Create a FHIR Observation resource entry."""
        observation_resource = {
            "resourceType": "Observation",
            "id": observation.id,
            "status": "final",
            "category": [{"coding": [{
                "system": OBSERVATION_CATEGORY_SYSTEM,
                "code": _observation_category(observation),
            }]}],
            "code": {
                "coding": codings(observation.codes)
            } if observation.codes else {},
            "subject": {
                "reference": f"urn:uuid:{person.uuid}"
            },
            "effectiveDateTime": fhir_datetime(observation.time)
        }
        
        # Panels (blood pressure) carry their parts as components rather than
        # a single value.
        components = getattr(observation, 'components', None)
        if components:
            observation_resource["component"] = [
                {
                    "code": {"coding": [coding(code)]},
                    "valueQuantity": quantity(value, unit),
                }
                for code, value, unit in components
            ]

        # Add value based on type. A coded value is a CodeableConcept, which
        # wraps a list of codings; assigning the raw code dict produced a
        # Coding where a CodeableConcept belongs, and left the module's short
        # system name ('SNOMED-CT') in place of a URI.
        value = observation.value
        if value is not None:
            if isinstance(value, bool):
                observation_resource["valueBoolean"] = value
            elif isinstance(value, (int, float)):
                observation_resource["valueQuantity"] = quantity(
                    value, observation.unit)
            elif isinstance(value, dict) or hasattr(value, 'system'):
                observation_resource["valueCodeableConcept"] = {
                    "coding": [coding(value)]}
            else:
                observation_resource["valueString"] = str(value)
        
        if observation.encounter:
            observation_resource["encounter"] = {
                "reference": f"urn:uuid:{observation.encounter.id}"
            }
        
        return self._entry("Observation", observation.id, observation_resource, vital_signs=(_observation_category(observation) == 'vital-signs'))
    
    # ------------------------------------------------------------------
    # Patient identity
    # ------------------------------------------------------------------

    #: Identifier attribute -> (type code, display, system). The systems are
    #: synthetic, matching the synthetic identifiers themselves.
    IDENTIFIER_TYPES = [
        ('identifier_mrn', 'MR', 'Medical Record Number',
         'http://hospital.smarthealthit.org'),
        ('identifier_ssn', 'SS', 'Social Security Number',
         'http://hl7.org/fhir/sid/us-ssn'),
        ('identifier_drivers', 'DL', "Driver's License",
         'urn:oid:2.16.840.1.113883.4.3.25'),
        ('identifier_passport', 'PPN', 'Passport Number',
         'http://standardhealthrecord.org/fhir/StructureDefinition/passportNumber'),
    ]

    def _identifiers(self, person: 'Person') -> List[Dict[str, Any]]:
        """Every identifier the patient carries, typed.

        The generator's own patient id comes first so a bundle can always be
        matched back to the run that produced it.
        """
        identifiers = [{
            "system": "https://github.com/TIET-AI/tietai-synthea",
            "value": person.id,
        }]

        for attribute, code, display, system in self.IDENTIFIER_TYPES:
            value = person.attributes.get(attribute)
            if not value:
                continue
            identifiers.append({
                "type": {"coding": [{
                    "system": "http://terminology.hl7.org/CodeSystem/v2-0203",
                    "code": code,
                    "display": display,
                }]},
                "system": system,
                "value": str(value),
            })

        return identifiers

    def _names(self, person: 'Person') -> List[Dict[str, Any]]:
        """Official name, plus a maiden name when the patient has one."""
        given = person.attributes.get('first_name')
        family = person.attributes.get('last_name')

        official: Dict[str, Any] = {"use": "official"}
        official["family"] = family if family else "Unknown"
        official["given"] = [given] if given else ["Unknown"]
        if person.attributes.get('name_prefix'):
            official["prefix"] = [person.attributes['name_prefix']]

        names = [official]

        maiden = person.attributes.get('maiden_name')
        if maiden:
            names.append({
                "use": "maiden",
                "family": maiden,
                "given": [given] if given else ["Unknown"],
            })

        return names

    def create_immunization_entry(self, immunization, person: 'Person') -> Dict[str, Any]:
        """Create a FHIR Immunization resource entry."""
        resource = {
            "resourceType": "Immunization",
            "id": immunization.id,
            "status": "completed",
            "vaccineCode": {
                "coding": codings(immunization.codes)
            } if immunization.codes else {},
            "patient": {"reference": f"urn:uuid:{person.uuid}"},
            "occurrenceDateTime": fhir_datetime(immunization.time),
            "primarySource": True,
        }

        if immunization.encounter:
            resource["encounter"] = {
                "reference": f"urn:uuid:{immunization.encounter.id}"
            }

        return self._entry("Immunization", immunization.id, resource)

    def _add_notes(self, bundle: Dict[str, Any], person: 'Person') -> None:
        """Add a DocumentReference for every encounter that has a note."""
        from synthea.world.notes import NOTE_ATTRIBUTE

        for encounter in person.record.encounters:
            text = getattr(encounter, NOTE_ATTRIBUTE, None)
            if text:
                bundle["entry"].append(
                    self.create_document_reference_entry(encounter, text, person))

    def create_document_reference_entry(self, encounter, text: str,
                                        person: 'Person') -> Dict[str, Any]:
        """The encounter's clinical note, as a DocumentReference.

        The note is carried base64-encoded in `content.attachment.data`, which
        is how a FHIR server expects an inline document; a consumer that wants
        the text decodes it rather than parsing a narrative.
        """
        from synthea.world.notes import NOTE_CODE, NOTE_DISPLAY

        encoded = base64.b64encode(text.encode('utf-8')).decode('ascii')
        written = encounter.end_time or encounter.time

        resource: Dict[str, Any] = {
            "resourceType": "DocumentReference",
            "id": _note_uuid(encounter),
            "status": "current",
            "docStatus": "final",
            "type": {"coding": [{
                "system": "http://loinc.org",
                "code": NOTE_CODE,
                "display": NOTE_DISPLAY,
            }]},
            "category": [{"coding": [{
                "system": "http://hl7.org/fhir/us/core/CodeSystem/us-core-documentreference-category",
                "code": "clinical-note",
                "display": "Clinical Note",
            }]}],
            "subject": self._subject(person),
            "date": fhir_datetime(written),
            "content": [{
                "attachment": {
                    "contentType": "text/plain; charset=utf-8",
                    "data": encoded,
                },
                "format": {
                    "system": "http://ihe.net/fhir/ValueSet/IHE.FormatCode.codesystem",
                    "code": "urn:ihe:iti:xds:2017:mimeTypeSufficient",
                    "display": "mimeType Sufficient",
                },
            }],
            "context": {
                "encounter": [{"reference": f"urn:uuid:{encounter.id}"}],
                "period": {
                    "start": fhir_datetime(encounter.time),
                    "end": fhir_datetime(encounter.end_time),
                },
            },
        }

        clinician = getattr(encounter, 'clinician', None)
        if clinician is not None:
            resource["author"] = [{
                "reference": f"urn:uuid:{_practitioner_uuid(clinician)}"
            }]

        provider = getattr(encounter, 'provider', None)
        if provider is not None:
            resource["custodian"] = {
                "reference": f"urn:uuid:{_organization_uuid(provider)}"
            }

        return self._entry("DocumentReference", resource["id"], resource)

    def _add_care_team(self, bundle: Dict[str, Any], person: 'Person') -> None:
        """Add every facility and practitioner the record references, once.

        A bundle that references an Organization must contain it, or the
        transaction cannot be loaded.
        """
        providers: Dict[str, Any] = {}
        clinicians: Dict[str, Any] = {}

        for encounter in person.record.encounters:
            provider = getattr(encounter, 'provider', None)
            if provider is not None:
                providers.setdefault(provider.id, provider)
            clinician = getattr(encounter, 'clinician', None)
            if clinician is not None:
                clinicians.setdefault(clinician.id, clinician)
                if clinician.provider is not None:
                    providers.setdefault(clinician.provider.id, clinician.provider)

        for provider in providers.values():
            bundle["entry"].append(self.create_organization_entry(provider))
            bundle["entry"].append(self.create_location_entry(provider))

        for clinician in clinicians.values():
            bundle["entry"].append(self.create_practitioner_entry(clinician))
            bundle["entry"].append(self.create_practitioner_role_entry(clinician))

    def create_organization_entry(self, provider) -> Dict[str, Any]:
        """Create a FHIR Organization resource entry for a facility."""
        resource: Dict[str, Any] = {
            "resourceType": "Organization",
            "id": _organization_uuid(provider),
            "active": True,
            "identifier": [{
                "system": "https://github.com/synthetichealth/synthea",
                "value": provider.id,
            }],
            "name": provider.name,
            "type": [{"coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/organization-type",
                "code": "prov",
                "display": "Healthcare Provider",
            }]}],
            "address": [_facility_address(provider)],
        }
        if provider.phone:
            resource["telecom"] = [{"system": "phone", "value": provider.phone}]

        return self._entry("Organization", resource["id"], resource)

    def create_location_entry(self, provider) -> Dict[str, Any]:
        """Create a FHIR Location resource entry for a facility."""
        resource: Dict[str, Any] = {
            "resourceType": "Location",
            "id": _location_uuid(provider),
            "status": "active",
            "name": provider.name,
            "address": _facility_address(provider),
            "managingOrganization": {
                "reference": f"urn:uuid:{_organization_uuid(provider)}"
            },
        }

        latitude, longitude = provider.coordinates
        if latitude or longitude:
            resource["position"] = {"latitude": latitude, "longitude": longitude}

        return self._entry("Location", resource["id"], resource)

    def create_practitioner_entry(self, clinician) -> Dict[str, Any]:
        """Create a FHIR Practitioner resource entry."""
        resource: Dict[str, Any] = {
            "resourceType": "Practitioner",
            "id": _practitioner_uuid(clinician),
            "active": True,
            "name": [{
                "use": "official",
                "family": clinician.last_name,
                "given": [clinician.first_name],
                "prefix": ["Dr."],
            }],
        }
        if clinician.npi:
            resource["identifier"] = [{
                "system": "http://hl7.org/fhir/sid/us-npi",
                "value": clinician.npi,
            }]

        return self._entry("Practitioner", resource["id"], resource)

    def create_practitioner_role_entry(self, clinician) -> Dict[str, Any]:
        """Link a practitioner to the facility they work at."""
        resource: Dict[str, Any] = {
            "resourceType": "PractitionerRole",
            "id": _practitioner_role_uuid(clinician),
            "active": True,
            "practitioner": {
                "reference": f"urn:uuid:{_practitioner_uuid(clinician)}"
            },
            "specialty": [{"text": clinician.specialty}],
        }
        if clinician.provider is not None:
            resource["organization"] = {
                "reference": f"urn:uuid:{_organization_uuid(clinician.provider)}"
            }

        return self._entry("PractitionerRole", resource["id"], resource)

    def _add_financial(self, bundle: Dict[str, Any], person: 'Person') -> None:
        """Add coverage, and a claim per encounter that cost something.

        A claim is only meaningful with the payer that was in force on the day,
        which is why the cost split is computed as entries are recorded rather
        than here.
        """
        history = person.attributes.get('coverage_history') or []
        insurers: Dict[str, Any] = {}

        for index, coverage in enumerate(history):
            if coverage.plan is not None:
                insurers.setdefault(coverage.plan.payer.id, coverage.plan.payer)
            bundle["entry"].append(
                self.create_coverage_entry(coverage, index, person))

        for payer in insurers.values():
            bundle["entry"].append(self.create_payer_entry(payer))

        for encounter in person.record.encounters:
            if not getattr(encounter, 'cost', None):
                continue
            bundle["entry"].append(self.create_claim_entry(encounter, person))
            bundle["entry"].append(
                self.create_explanation_of_benefit_entry(encounter, person))

    def create_payer_entry(self, payer) -> Dict[str, Any]:
        """The insurer, as an Organization."""
        resource: Dict[str, Any] = {
            "resourceType": "Organization",
            "id": _payer_uuid(payer),
            "active": True,
            "identifier": [{
                "system": "https://github.com/synthetichealth/synthea",
                "value": payer.id,
            }],
            "name": payer.name,
            "type": [{"coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/organization-type",
                "code": "ins",
                "display": "Insurance Company",
            }]}],
        }
        return self._entry("Organization", resource["id"], resource)

    def create_coverage_entry(self, coverage, index: int,
                              person: 'Person') -> Dict[str, Any]:
        """One period of insurance cover."""
        resource: Dict[str, Any] = {
            "resourceType": "Coverage",
            "id": _coverage_uuid(person, index),
            "status": "active" if coverage.end is None else "cancelled",
            "beneficiary": self._subject(person),
            "period": {
                "start": fhir_datetime(coverage.start),
                "end": fhir_datetime(coverage.end),
            },
            "type": {"coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
                "code": COVERAGE_TYPES.get(coverage.kind, 'PUBLICPOL'),
            }]},
        }

        if coverage.plan is not None:
            resource["payor"] = [{
                "reference": f"urn:uuid:{_payer_uuid(coverage.plan.payer)}",
                "display": coverage.plan.payer.name,
            }]
            resource["class"] = [{
                "type": {"coding": [{
                    "system": "http://terminology.hl7.org/CodeSystem/coverage-class",
                    "code": "plan",
                }]},
                "value": coverage.plan.id,
                "name": coverage.plan.name,
            }]
        else:
            # An uninsured period is still a fact about the patient, and FHIR
            # requires a payor, so the patient is their own.
            resource["payor"] = [self._subject(person)]

        return self._entry("Coverage", resource["id"], resource)

    def create_claim_entry(self, encounter, person: 'Person') -> Dict[str, Any]:
        """The claim submitted for an encounter."""
        resource: Dict[str, Any] = {
            "resourceType": "Claim",
            "id": _claim_uuid(encounter),
            "status": "active",
            "type": {"coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/claim-type",
                "code": "institutional",
            }]},
            "use": "claim",
            "patient": self._subject(person),
            "created": fhir_datetime(encounter.time),
            "provider": (
                {"reference": f"urn:uuid:{_organization_uuid(encounter.provider)}"}
                if getattr(encounter, 'provider', None) is not None
                else self._subject(person)
            ),
            "priority": {"coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/processpriority",
                "code": "normal",
            }]},
            "item": [{
                "sequence": 1,
                "productOrService": (
                    {"coding": codings(encounter.codes)} if encounter.codes
                    else {"text": "Encounter"}
                ),
                "encounter": [{"reference": f"urn:uuid:{encounter.id}"}],
                "net": _money(encounter.cost),
            }],
            "total": _money(encounter.cost),
        }

        coverage = getattr(encounter, 'coverage', None)
        resource["insurance"] = [{
            "sequence": 1,
            "focal": True,
            "coverage": {
                "reference": f"urn:uuid:{_coverage_uuid(person, _coverage_index(person, coverage))}"
            },
        }]
        if coverage is not None and coverage.plan is not None:
            resource["insurer"] = {
                "reference": f"urn:uuid:{_payer_uuid(coverage.plan.payer)}"
            }

        return self._entry("Claim", resource["id"], resource)

    def create_explanation_of_benefit_entry(self, encounter,
                                            person: 'Person') -> Dict[str, Any]:
        """How the claim was adjudicated between payer and patient."""
        coverage = getattr(encounter, 'coverage', None)

        resource: Dict[str, Any] = {
            "resourceType": "ExplanationOfBenefit",
            "id": _eob_uuid(encounter),
            "status": "active",
            "type": {"coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/claim-type",
                "code": "institutional",
            }]},
            "use": "claim",
            "patient": self._subject(person),
            "created": fhir_datetime(encounter.time),
            "outcome": "complete",
            "insurer": (
                {"reference": f"urn:uuid:{_payer_uuid(coverage.plan.payer)}"}
                if coverage is not None and coverage.plan is not None
                else self._subject(person)
            ),
            "provider": (
                {"reference": f"urn:uuid:{_organization_uuid(encounter.provider)}"}
                if getattr(encounter, 'provider', None) is not None
                else self._subject(person)
            ),
            "claim": {"reference": f"urn:uuid:{_claim_uuid(encounter)}"},
            "insurance": [{
                "focal": True,
                "coverage": {
                    "reference": f"urn:uuid:{_coverage_uuid(person, _coverage_index(person, coverage))}"
                },
            }],
            "item": [{
                "sequence": 1,
                "productOrService": (
                    {"coding": codings(encounter.codes)} if encounter.codes
                    else {"text": "Encounter"}
                ),
                "adjudication": [
                    _adjudication('submitted', encounter.cost),
                    _adjudication('benefit', encounter.payer_cost or 0.0),
                    _adjudication('copay', encounter.patient_cost or 0.0),
                ],
            }],
            "total": [{
                "category": {"coding": [{
                    "system": "http://terminology.hl7.org/CodeSystem/adjudication",
                    "code": "submitted",
                }]},
                "amount": _money(encounter.cost),
            }],
        }

        return self._entry("ExplanationOfBenefit", resource["id"], resource)
    def create_allergy_intolerance_entry(self, allergy,
                                         person: 'Person') -> Dict[str, Any]:
        """The patient's allergy, with whatever reaction the module recorded."""
        resource: Dict[str, Any] = {
            "resourceType": "AllergyIntolerance",
            "id": allergy.id,
            "clinicalStatus": {"coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical",
                "code": "resolved" if allergy.end_time else "active",
            }]},
            "verificationStatus": {"coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-verification",
                "code": "confirmed",
            }]},
            "type": "allergy",
            "category": [_allergy_category(allergy)],
            "code": {"coding": codings(allergy.codes)} if allergy.codes else None,
            "patient": self._subject(person),
            "recordedDate": fhir_datetime(allergy.time),
            "onsetDateTime": fhir_datetime(allergy.time),
        }

        if allergy.severity:
            resource["criticality"] = _allergy_criticality(allergy.severity)

        if allergy.reactions:
            manifestations = [
                {"coding": [coding(reaction)]} if not isinstance(reaction, str)
                else {"text": reaction}
                for reaction in allergy.reactions
            ]
            reaction: Dict[str, Any] = {"manifestation": manifestations}
            if allergy.severity in ('mild', 'moderate', 'severe'):
                reaction["severity"] = allergy.severity
            resource["reaction"] = [reaction]

        if allergy.encounter is not None:
            resource["encounter"] = {
                "reference": f"urn:uuid:{allergy.encounter.id}"}

        return self._entry("AllergyIntolerance", allergy.id, resource)

    def create_goal_entry(self, careplan, index: int, goal,
                          person: 'Person') -> Dict[str, Any]:
        """One goal of a care plan.

        The record holds goals as free text, which is what the modules write,
        so the description is a `text` rather than an invented code.
        """
        resource: Dict[str, Any] = {
            "resourceType": "Goal",
            "id": _goal_uuid(careplan, index),
            "lifecycleStatus": "completed" if careplan.end_time else "active",
            "description": (
                {"coding": [coding(goal)]} if hasattr(goal, 'code')
                else {"text": str(goal)}
            ),
            "subject": self._subject(person),
            "startDate": careplan.time.date().isoformat(),
        }
        return self._entry("Goal", resource["id"], resource)

    def create_care_team_entry(self, careplan,
                               person: 'Person') -> Dict[str, Any]:
        """Who is looking after the patient for this care plan."""
        resource: Dict[str, Any] = {
            "resourceType": "CareTeam",
            "id": _care_team_uuid(careplan),
            "status": "inactive" if careplan.end_time else "active",
            "subject": self._subject(person),
            "period": {
                "start": fhir_datetime(careplan.time),
                "end": fhir_datetime(careplan.end_time),
            },
        }

        encounter = careplan.encounter
        clinician = getattr(encounter, 'clinician', None) if encounter else None
        provider = getattr(encounter, 'provider', None) if encounter else None

        participants: List[Dict[str, Any]] = [{
            "role": [{"coding": [{
                "system": "http://snomed.info/sct",
                "code": "116154003",
                "display": "Patient",
            }]}],
            "member": self._subject(person),
        }]

        if clinician is not None:
            participants.append({
                "role": [{"coding": [{
                    "system": "http://snomed.info/sct",
                    "code": "223366009",
                    "display": "Healthcare professional",
                }]}],
                "member": {
                    "reference": f"urn:uuid:{_practitioner_uuid(clinician)}"},
            })

        if provider is not None:
            resource["managingOrganization"] = [
                {"reference": f"urn:uuid:{_organization_uuid(provider)}"}]

        resource["participant"] = participants

        if encounter is not None:
            resource["encounter"] = {"reference": f"urn:uuid:{encounter.id}"}

        return self._entry("CareTeam", resource["id"], resource)

    def create_care_plan_entry(self, careplan,
                               person: 'Person') -> Dict[str, Any]:
        """The care plan, pointing at the goals and team created alongside it."""
        resource: Dict[str, Any] = {
            "resourceType": "CarePlan",
            "id": careplan.id,
            "status": "completed" if careplan.end_time else "active",
            "intent": "plan",
            "category": [{"coding": [{
                "system": "http://hl7.org/fhir/us/core/CodeSystem/careplan-category",
                "code": "assess-plan",
            }]}],
            "subject": self._subject(person),
            "period": {
                "start": fhir_datetime(careplan.time),
                "end": fhir_datetime(careplan.end_time),
            },
            "careTeam": [
                {"reference": f"urn:uuid:{_care_team_uuid(careplan)}"}],
        }

        if careplan.codes:
            resource["category"].append({"coding": codings(careplan.codes)})

        if careplan.goals:
            resource["goal"] = [
                {"reference": f"urn:uuid:{_goal_uuid(careplan, index)}"}
                for index in range(len(careplan.goals))
            ]

        if careplan.activities:
            resource["activity"] = [
                {"detail": {
                    "status": "completed" if careplan.end_time else "in-progress",
                    "code": ({"coding": [coding(activity)]}
                             if hasattr(activity, 'code')
                             else {"text": str(activity)}),
                }}
                for activity in careplan.activities
            ]

        if careplan.encounter is not None:
            resource["encounter"] = {
                "reference": f"urn:uuid:{careplan.encounter.id}"}

        return self._entry("CarePlan", careplan.id, resource)

    def create_diagnostic_report_entry(self, report,
                                       person: 'Person') -> Dict[str, Any]:
        """A panel of results, referencing the Observations it is made of."""
        resource: Dict[str, Any] = {
            "resourceType": "DiagnosticReport",
            "id": report.id,
            "status": "final",
            "category": [{"coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/v2-0074",
                "code": "LAB",
            }]}],
            "code": {"coding": codings(report.codes)} if report.codes else None,
            "subject": self._subject(person),
            "effectiveDateTime": fhir_datetime(report.time),
            "issued": fhir_datetime(report.time),
        }

        if report.observations:
            resource["result"] = [
                {"reference": f"urn:uuid:{observation.id}"}
                for observation in report.observations
            ]

        if report.encounter is not None:
            resource["encounter"] = {
                "reference": f"urn:uuid:{report.encounter.id}"}

        provider = (getattr(report.encounter, 'provider', None)
                    if report.encounter else None)
        if provider is not None:
            resource["performer"] = [
                {"reference": f"urn:uuid:{_organization_uuid(provider)}"}]

        return self._entry("DiagnosticReport", report.id, resource)

    def create_device_entry(self, device, person: 'Person') -> Dict[str, Any]:
        """An implanted or issued device, with a UDI carrier.

        The UDI is derived from the device's own id so it is stable across a
        run, and it is not a registered issuing agency's number: these are
        synthetic devices and must not collide with a real UDI.
        """
        resource: Dict[str, Any] = {
            "resourceType": "Device",
            "id": device.id,
            "status": "inactive" if device.end_time else "active",
            "patient": self._subject(person),
            "manufactureDate": fhir_datetime(device.time),
            "type": {"coding": codings(device.codes)} if device.codes else None,
            "udiCarrier": [{
                "deviceIdentifier": _device_identifier(device),
                "carrierHRF": _device_udi(device),
            }],
        }

        if device.manufacturer:
            resource["manufacturer"] = device.manufacturer
        if device.model:
            resource["modelNumber"] = device.model
        if device.end_time:
            resource["expirationDate"] = fhir_datetime(device.end_time)

        return self._entry("Device", device.id, resource)

    def create_supply_delivery_entry(self, supply,
                                     person: 'Person') -> Dict[str, Any]:
        """Supplies handed to the patient."""
        resource: Dict[str, Any] = {
            "resourceType": "SupplyDelivery",
            "id": supply.id,
            "status": "completed",
            "patient": self._subject(person),
            "type": {"coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/supply-item-type",
                "code": "device",
            }]},
            "suppliedItem": {
                "quantity": {"value": supply.quantity},
                "itemCodeableConcept": (
                    {"coding": codings(supply.codes)} if supply.codes else None),
            },
            "occurrenceDateTime": fhir_datetime(supply.time),
        }

        provider = (getattr(supply.encounter, 'provider', None)
                    if supply.encounter else None)
        if provider is not None:
            resource["supplier"] = {
                "reference": f"urn:uuid:{_organization_uuid(provider)}"}

        return self._entry("SupplyDelivery", supply.id, resource)

    def create_provenance_entry(self, bundle: Dict[str, Any],
                                person: 'Person') -> Dict[str, Any]:
        """Says this record was generated, and by what.

        A consumer that mixes synthetic and real data needs to be able to tell
        them apart from the record itself rather than from where the file came
        from. The Provenance targets every other entry in the bundle.
        """
        targets = [
            {"reference": entry["fullUrl"]}
            for entry in bundle["entry"]
            if entry.get("fullUrl")
        ]

        resource: Dict[str, Any] = {
            "resourceType": "Provenance",
            "id": _provenance_uuid(person),
            "target": targets,
            "recorded": fhir_datetime(datetime.now(timezone.utc)),
            "activity": {"coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/v3-DataOperation",
                "code": "CREATE",
                "display": "create",
            }]},
            "agent": [{
                "type": {"coding": [{
                    "system": "http://terminology.hl7.org/CodeSystem/provenance-participant-type",
                    "code": "assembler",
                }]},
                "who": {"display": f"PySynthea {_version()}"},
            }],
        }

        return self._entry("Provenance", resource["id"], resource)

    def _map_race_code(self, race: str) -> str:
        """Map race to OMB category code."""
        race_map = {
            'white': '2106-3',
            'black': '2054-5',
            'asian': '2028-9',
            'native': '1002-5',
            'other': '2131-1'
        }
        return race_map.get(race.lower(), '2131-1')