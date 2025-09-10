#!/usr/bin/env python
"""
Custom patient generation example.

This script demonstrates how to create and simulate specific patients
with custom attributes.

Usage:
    uv run python examples/custom_patient.py
"""

from datetime import datetime, timedelta
from pathlib import Path
import json

from synthea.world.person import Person
from synthea.world.health_record import EncounterClass
from synthea.engine.generator import Generator, GeneratorOptions
from synthea.export.fhir import FHIRExporter
from synthea.export.exporter import JSONExporter
from synthea.helpers.config import Config


def create_custom_patient():
    """Create a patient with specific characteristics."""
    
    print("Creating custom patient...")
    
    # Create person with specific seed for reproducibility
    person = Person(seed=12345)
    
    # Set demographics
    person.attributes['gender'] = 'F'
    person.attributes['first_name'] = 'Alice'
    person.attributes['last_name'] = 'Johnson'
    person.attributes['birth_date'] = datetime(1985, 3, 15)
    person.attributes['race'] = 'white'
    person.attributes['ethnicity'] = 'non_hispanic'
    person.attributes['socioeconomic_status'] = 'middle'
    
    # Set location
    person.attributes['state'] = 'Massachusetts'
    person.attributes['city'] = 'Boston'
    person.attributes['zip_code'] = '02108'
    person.attributes['latitude'] = 42.3601
    person.attributes['longitude'] = -71.0589
    
    # Set vital signs
    person.set_vital_sign('height', 165, 'cm', datetime.now())
    person.set_vital_sign('weight', 65, 'kg', datetime.now())
    person.set_vital_sign('bmi', 23.9, 'kg/m2', datetime.now())
    
    print(f"  Name: {person.attributes['first_name']} {person.attributes['last_name']}")
    print(f"  Gender: {person.attributes['gender']}")
    print(f"  Birth Date: {person.attributes['birth_date'].strftime('%Y-%m-%d')}")
    print(f"  Age: {person.age:.1f} years")
    
    return person


def add_medical_history(person):
    """Add medical history to the patient."""
    
    print("\nAdding medical history...")
    
    # Initialize health record
    person.init_health_record()
    
    # Add childhood vaccination
    vaccination_date = person.birth_date + timedelta(days=60)
    enc1 = person.record.encounter_start(
        vaccination_date,
        EncounterClass.WELLNESS
    )
    
    # Add immunization procedure
    proc1 = person.record.procedure(vaccination_date, None, enc1)
    proc1.name = "Childhood immunization"
    
    person.record.encounter_end(enc1, vaccination_date)
    print(f"  Added childhood vaccination at age {person.age_at(vaccination_date):.1f}")
    
    # Add annual checkup at age 30
    checkup_date = person.birth_date.replace(year=person.birth_date.year + 30)
    enc2 = person.record.encounter_start(
        checkup_date,
        EncounterClass.AMBULATORY
    )
    
    # Add vital signs observations
    person.record.observation(checkup_date, None, 120, 'mmHg', enc2).name = "Systolic BP"
    person.record.observation(checkup_date, None, 80, 'mmHg', enc2).name = "Diastolic BP"
    person.record.observation(checkup_date, None, 72, 'bpm', enc2).name = "Heart rate"
    person.record.observation(checkup_date, None, 98.6, 'F', enc2).name = "Temperature"
    
    person.record.encounter_end(enc2, checkup_date)
    print(f"  Added annual checkup at age {person.age_at(checkup_date):.1f}")
    
    # Add a condition (common cold)
    cold_date = person.birth_date.replace(year=person.birth_date.year + 35)
    enc3 = person.record.encounter_start(
        cold_date,
        EncounterClass.AMBULATORY
    )
    
    condition = person.record.condition_start(cold_date)
    condition.name = "Common cold"
    
    # Prescribe medication
    medication = person.record.medication_start(cold_date, None, enc3)
    medication.name = "Acetaminophen"
    medication.reason = "Common cold symptoms"
    
    person.record.encounter_end(enc3, cold_date + timedelta(hours=1))
    
    # Resolve condition after 7 days
    person.record.condition_end(condition, cold_date + timedelta(days=7))
    person.record.medication_end(medication, cold_date + timedelta(days=7))
    
    print(f"  Added common cold episode at age {person.age_at(cold_date):.1f}")
    
    # Add recent checkup
    recent_date = datetime.now() - timedelta(days=30)
    enc4 = person.record.encounter_start(
        recent_date,
        EncounterClass.WELLNESS
    )
    
    # Add lab results
    person.record.observation(recent_date, None, 95, 'mg/dL', enc4).name = "Glucose"
    person.record.observation(recent_date, None, 180, 'mg/dL', enc4).name = "Cholesterol"
    person.record.observation(recent_date, None, 14.5, 'g/dL', enc4).name = "Hemoglobin"
    
    person.record.encounter_end(enc4, recent_date)
    print(f"  Added recent checkup with lab results")
    
    print(f"\nMedical Record Summary:")
    print(f"  Total Encounters: {len(person.record.encounters)}")
    print(f"  Total Conditions: {len(person.record.conditions)}")
    print(f"  Total Medications: {len(person.record.medications)}")
    print(f"  Total Observations: {len(person.record.observations)}")
    print(f"  Total Procedures: {len(person.record.procedures)}")


def export_patient(person, output_dir):
    """Export patient data to various formats."""
    
    print(f"\nExporting patient data to {output_dir}...")
    
    config = Config()
    
    # Export to JSON
    json_exporter = JSONExporter(config, output_dir)
    json_file = json_exporter.export(person, 0)
    print(f"  JSON: {json_file}")
    
    # Export to FHIR
    fhir_exporter = FHIRExporter(config, output_dir)
    fhir_file = fhir_exporter.export(person, 0)
    print(f"  FHIR: {fhir_file}")
    
    return json_file, fhir_file


def main():
    """Main function."""
    
    print("=" * 60)
    print("Synthea Python - Custom Patient Example")
    print("=" * 60)
    
    # Create output directory
    output_dir = Path("./output/example_custom")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Create custom patient
    person = create_custom_patient()
    
    # Add medical history
    add_medical_history(person)
    
    # Export patient data
    json_file, fhir_file = export_patient(person, output_dir)
    
    # Display sample of exported data
    print("\n" + "=" * 60)
    print("Sample of Exported Data")
    print("=" * 60)
    
    # Show JSON structure
    with open(json_file, 'r') as f:
        data = json.load(f)
        print("\nJSON Structure:")
        print(f"  ID: {data['id']}")
        print(f"  Name: {data['attributes']['first_name']} {data['attributes']['last_name']}")
        print(f"  Alive: {data['alive']}")
        if 'health_record' in data:
            print(f"  Encounters: {len(data['health_record']['encounters'])}")
    
    # Show FHIR bundle
    with open(fhir_file, 'r') as f:
        bundle = json.load(f)
        print("\nFHIR Bundle:")
        print(f"  Type: {bundle['type']}")
        print(f"  Total Entries: {len(bundle['entry'])}")
        
        # Count resource types
        resource_types = {}
        for entry in bundle['entry']:
            rtype = entry['resource']['resourceType']
            resource_types[rtype] = resource_types.get(rtype, 0) + 1
        
        print("  Resource Types:")
        for rtype, count in sorted(resource_types.items()):
            print(f"    {rtype}: {count}")
    
    print(f"\nAll files exported to: {output_dir}")
    
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())