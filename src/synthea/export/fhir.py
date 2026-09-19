"""
FHIR exporter for Synthea.

This module exports patient data in FHIR R4 format.
"""

from pathlib import Path
from typing import Dict, Any, Optional, List, TYPE_CHECKING
from datetime import datetime
import json
import uuid

from synthea.export.exporter import PatientExporter

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


def _coding(raw: Any) -> Dict[str, Any]:
    """A FHIR coding from a Code object or a raw dict."""
    if hasattr(raw, 'to_dict'):
        return raw.to_dict()
    if isinstance(raw, dict):
        return {
            'system': raw.get('system', ''),
            'code': str(raw.get('code', '')),
            'display': raw.get('display', ''),
        }
    return {'text': str(raw)}


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

        return bundle
    
    def create_patient_entry(self, person: 'Person') -> Dict[str, Any]:
        """Create a FHIR Patient resource entry."""
        patient = {
            "resourceType": "Patient",
            "id": person.id,
            "meta": {
                "profile": ["http://hl7.org/fhir/us/core/StructureDefinition/us-core-patient"]
            } if self.use_us_core else {},
            "identifier": self._identifiers(person),
            "active": person.alive,
            "name": self._names(person),
            "gender": "male" if person.gender == 'M' else "female",
            "birthDate": person.birth_date.strftime('%Y-%m-%d') if person.birth_date else None,
        }
        
        # Add death information if applicable
        if not person.alive and person.death_date:
            patient["deceasedDateTime"] = person.death_date.isoformat()
        
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
        
        entry = {
            "fullUrl": f"urn:uuid:{person.id}",
            "resource": patient
        }
        
        if self.use_transaction_bundle:
            entry["request"] = {
                "method": "POST",
                "url": "Patient"
            }
        
        return entry
    
    def create_encounter_entry(self, encounter: 'Encounter', person: 'Person') -> Dict[str, Any]:
        """Create a FHIR Encounter resource entry."""
        encounter_resource = {
            "resourceType": "Encounter",
            "id": encounter.id,
            "status": "finished" if encounter.end_time else "in-progress",
            "class": {
                "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
                "code": encounter.encounter_class.value.upper(),
                "display": encounter.encounter_class.value.title()
            },
            "type": [
                {
                    "coding": [code.to_dict() for code in encounter.codes]
                }
            ] if encounter.codes else [],
            "subject": {
                "reference": f"urn:uuid:{person.id}",
                "display": f"{person.attributes.get('first_name', '')} {person.attributes.get('last_name', '')}"
            },
            "period": {
                "start": encounter.time.isoformat(),
                "end": encounter.end_time.isoformat() if encounter.end_time else None
            }
        }
        
        if encounter.reason:
            encounter_resource["reasonCode"] = [
                {
                    "text": encounter.reason
                }
            ]
        
        entry = {
            "fullUrl": f"urn:uuid:{encounter.id}",
            "resource": encounter_resource
        }
        
        if self.use_transaction_bundle:
            entry["request"] = {
                "method": "POST",
                "url": "Encounter"
            }
        
        return entry
    
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
            "code": {
                "coding": [code.to_dict() for code in condition.codes]
            } if condition.codes else {},
            "subject": {
                "reference": f"urn:uuid:{person.id}"
            },
            "onsetDateTime": condition.time.isoformat()
        }
        
        if condition.end_time:
            condition_resource["abatementDateTime"] = condition.end_time.isoformat()
        
        if condition.encounter:
            condition_resource["encounter"] = {
                "reference": f"urn:uuid:{condition.encounter.id}"
            }
        
        entry = {
            "fullUrl": f"urn:uuid:{condition.id}",
            "resource": condition_resource
        }
        
        if self.use_transaction_bundle:
            entry["request"] = {
                "method": "POST",
                "url": "Condition"
            }
        
        return entry
    
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
                "coding": [code.to_dict() for code in medication.codes]
            } if medication.codes else {},
            "subject": {"reference": f"urn:uuid:{person.id}"},
            "authoredOn": medication.time.isoformat(),
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

        entry = {
            "fullUrl": f"urn:uuid:{medication.id}",
            "resource": resource,
        }
        if self.use_transaction_bundle:
            entry["request"] = {"method": "POST", "url": "MedicationRequest"}
        return entry

    def _medication_administration(self, medication, person) -> Dict[str, Any]:
        resource = {
            "resourceType": "MedicationAdministration",
            "id": medication.id,
            "status": "completed",
            "medicationCodeableConcept": {
                "coding": [code.to_dict() for code in medication.codes]
            } if medication.codes else {},
            "subject": {"reference": f"urn:uuid:{person.id}"},
            "effectiveDateTime": medication.time.isoformat(),
        }

        if medication.encounter:
            resource["context"] = {
                "reference": f"urn:uuid:{medication.encounter.id}"
            }

        self._add_reason(resource, medication)

        entry = {
            "fullUrl": f"urn:uuid:{medication.id}",
            "resource": resource,
        }
        if self.use_transaction_bundle:
            entry["request"] = {"method": "POST", "url": "MedicationAdministration"}
        return entry

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
                {"coding": [_coding(instruction)]} for instruction in instructions
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
                entry_series["modality"] = _coding(definition['modality'])
            if definition.get('body_site') is not None:
                entry_series["bodySite"] = _coding(definition['body_site'])

            entry_series["instance"] = [
                {
                    "uid": instance.get('uid'),
                    "number": position,
                    "title": instance.get('title'),
                    "sopClass": _coding(instance.get('sop_class')),
                }
                for position, instance in enumerate(instances, start=1)
                if instance.get('sop_class') is not None
            ]
            series.append(entry_series)

        resource = {
            "resourceType": "ImagingStudy",
            "id": study.id,
            "status": "available",
            "subject": {"reference": f"urn:uuid:{person.id}"},
            "started": study.time.isoformat(),
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
            resource["procedureCode"] = [{"coding": [study.procedure_code.to_dict()]}]

        entry = {
            "fullUrl": f"urn:uuid:{study.id}",
            "resource": resource,
        }
        if self.use_transaction_bundle:
            entry["request"] = {"method": "POST", "url": "ImagingStudy"}
        return entry

    def create_procedure_entry(self, procedure: 'Procedure', person: 'Person') -> Dict[str, Any]:
        """Create a FHIR Procedure resource entry."""
        procedure_resource = {
            "resourceType": "Procedure",
            "id": procedure.id,
            "status": "completed",
            "code": {
                "coding": [code.to_dict() for code in procedure.codes]
            } if procedure.codes else {},
            "subject": {
                "reference": f"urn:uuid:{person.id}"
            },
            "performedDateTime": procedure.time.isoformat()
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
        
        entry = {
            "fullUrl": f"urn:uuid:{procedure.id}",
            "resource": procedure_resource
        }
        
        if self.use_transaction_bundle:
            entry["request"] = {
                "method": "POST",
                "url": "Procedure"
            }
        
        return entry
    
    def create_observation_entry(self, observation: 'Observation', person: 'Person') -> Dict[str, Any]:
        """Create a FHIR Observation resource entry."""
        observation_resource = {
            "resourceType": "Observation",
            "id": observation.id,
            "status": "final",
            "category": [
                {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                            "code": observation.category,
                            "display": observation.category.title()
                        }
                    ]
                }
            ],
            "code": {
                "coding": [code.to_dict() for code in observation.codes]
            } if observation.codes else {},
            "subject": {
                "reference": f"urn:uuid:{person.id}"
            },
            "effectiveDateTime": observation.time.isoformat()
        }
        
        # Panels (blood pressure) carry their parts as components rather than
        # a single value.
        components = getattr(observation, 'components', None)
        if components:
            observation_resource["component"] = [
                {
                    "code": {"coding": [code.to_dict()]},
                    "valueQuantity": {
                        "value": value,
                        "unit": unit or "",
                        "system": "http://unitsofmeasure.org",
                        "code": unit or "",
                    },
                }
                for code, value, unit in components
            ]

        # Add value based on type
        if observation.value is not None:
            if isinstance(observation.value, (int, float)):
                observation_resource["valueQuantity"] = {
                    "value": observation.value,
                    "unit": observation.unit or "",
                    "system": "http://unitsofmeasure.org",
                    "code": observation.unit or ""
                }
            elif isinstance(observation.value, str):
                observation_resource["valueString"] = observation.value
            elif isinstance(observation.value, dict):
                observation_resource["valueCodeableConcept"] = observation.value
        
        if observation.encounter:
            observation_resource["encounter"] = {
                "reference": f"urn:uuid:{observation.encounter.id}"
            }
        
        entry = {
            "fullUrl": f"urn:uuid:{observation.id}",
            "resource": observation_resource
        }
        
        if self.use_transaction_bundle:
            entry["request"] = {
                "method": "POST",
                "url": "Observation"
            }
        
        return entry
    
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
                "coding": [code.to_dict() for code in immunization.codes]
            } if immunization.codes else {},
            "patient": {"reference": f"urn:uuid:{person.id}"},
            "occurrenceDateTime": immunization.time.isoformat(),
            "primarySource": True,
        }

        if immunization.encounter:
            resource["encounter"] = {
                "reference": f"urn:uuid:{immunization.encounter.id}"
            }

        entry = {
            "fullUrl": f"urn:uuid:{immunization.id}",
            "resource": resource,
        }
        if self.use_transaction_bundle:
            entry["request"] = {"method": "POST", "url": "Immunization"}
        return entry

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