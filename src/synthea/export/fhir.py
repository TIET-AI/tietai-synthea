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
        
        return bundle
    
    def create_patient_entry(self, person: 'Person') -> Dict[str, Any]:
        """Create a FHIR Patient resource entry."""
        patient = {
            "resourceType": "Patient",
            "id": person.id,
            "meta": {
                "profile": ["http://hl7.org/fhir/us/core/StructureDefinition/us-core-patient"]
            } if self.use_us_core else {},
            "identifier": [
                {
                    "system": "https://synthea.mitre.org/",
                    "value": person.id
                }
            ],
            "active": person.alive,
            "name": [
                {
                    "use": "official",
                    "family": person.attributes.get('last_name', 'Unknown'),
                    "given": [person.attributes.get('first_name', 'Unknown')]
                }
            ],
            "gender": "male" if person.gender == 'M' else "female",
            "birthDate": person.birth_date.strftime('%Y-%m-%d') if person.birth_date else None,
        }
        
        # Add death information if applicable
        if not person.alive and person.death_date:
            patient["deceasedDateTime"] = person.death_date.isoformat()
        
        # Add address
        patient["address"] = [
            {
                "use": "home",
                "city": person.attributes.get('city', 'Unknown'),
                "state": person.attributes.get('state', 'Unknown'),
                "postalCode": person.attributes.get('zip_code', '00000'),
                "country": "US"
            }
        ]
        
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
    
    def create_medication_entry(self, medication: 'Medication', person: 'Person') -> Dict[str, Any]:
        """Create a FHIR MedicationRequest resource entry."""
        medication_resource = {
            "resourceType": "MedicationRequest",
            "id": medication.id,
            "status": "stopped" if medication.end_time else "active",
            "intent": "order",
            "medicationCodeableConcept": {
                "coding": [code.to_dict() for code in medication.codes]
            } if medication.codes else {},
            "subject": {
                "reference": f"urn:uuid:{person.id}"
            },
            "authoredOn": medication.time.isoformat()
        }
        
        if medication.encounter:
            medication_resource["encounter"] = {
                "reference": f"urn:uuid:{medication.encounter.id}"
            }
        
        if medication.reason:
            medication_resource["reasonCode"] = [
                {
                    "text": medication.reason
                }
            ]
        
        entry = {
            "fullUrl": f"urn:uuid:{medication.id}",
            "resource": medication_resource
        }
        
        if self.use_transaction_bundle:
            entry["request"] = {
                "method": "POST",
                "url": "MedicationRequest"
            }
        
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