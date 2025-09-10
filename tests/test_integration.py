"""
Integration tests for Synthea Python.
"""

import pytest
import json
from pathlib import Path
import tempfile
import shutil
from datetime import datetime

from synthea.engine.generator import Generator, GeneratorOptions
from synthea.engine.module import Module
from synthea.helpers.config import Config
from synthea.world.person import Person
from synthea.export.fhir import FHIRExporter
from synthea.export.exporter import JSONExporter


class TestIntegration:
    """Integration tests."""
    
    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory."""
        temp_dir = tempfile.mkdtemp()
        yield Path(temp_dir)
        shutil.rmtree(temp_dir, ignore_errors=True)
    
    def test_full_generation_pipeline(self, temp_dir):
        """Test complete generation pipeline."""
        # Configure
        options = GeneratorOptions()
        options.population_size = 2
        options.seed = 12345
        options.state = 'Massachusetts'
        options.city = 'Boston'
        
        config = Config()
        config.set('exporter.baseDirectory', str(temp_dir))
        config.set('exporter.json.export', True)
        config.set('exporter.fhir.export', False)
        
        # Generate
        generator = Generator(options)
        generator.config = config
        generator.module_list = []  # Skip modules for speed
        generator.run()
        
        # Check results
        assert generator.stats['total_generated'] == 2
        
        # Check output files
        json_dir = temp_dir / 'json'
        assert json_dir.exists()
        
        json_files = list(json_dir.glob('*.json'))
        assert len(json_files) == 2
        
        # Validate JSON content
        for json_file in json_files:
            with open(json_file, 'r') as f:
                data = json.load(f)
                assert 'id' in data
                assert 'attributes' in data
                assert 'alive' in data
    
    def test_fhir_export_integration(self, temp_dir):
        """Test FHIR export integration."""
        # Create person with health record
        person = Person(seed=999)
        person.attributes['gender'] = 'M'
        person.attributes['birth_date'] = datetime(1970, 1, 1)
        person.attributes['first_name'] = 'John'
        person.attributes['last_name'] = 'Doe'
        person.init_health_record()
        
        # Add some medical data
        encounter = person.record.encounter_start(
            datetime(2023, 1, 1),
            'ambulatory'
        )
        
        condition = person.record.condition_start(
            datetime(2023, 1, 1)
        )
        
        person.record.encounter_end(encounter, datetime(2023, 1, 1))
        
        # Export to FHIR
        config = Config()
        exporter = FHIRExporter(config, temp_dir)
        output_file = exporter.export(person, 0)
        
        assert output_file is not None
        assert Path(output_file).exists()
        
        # Validate FHIR bundle
        with open(output_file, 'r') as f:
            bundle = json.load(f)
            assert bundle['resourceType'] == 'Bundle'
            assert len(bundle['entry']) > 0
            
            # Find patient resource
            patient_found = False
            for entry in bundle['entry']:
                if entry['resource']['resourceType'] == 'Patient':
                    patient_found = True
                    patient = entry['resource']
                    assert patient['name'][0]['given'][0] == 'John'
                    assert patient['name'][0]['family'] == 'Doe'
                    assert patient['gender'] == 'male'
                    break
            
            assert patient_found
    
    def test_module_loading_and_execution(self, temp_dir):
        """Test module loading and execution."""
        # Create a simple test module
        module_def = {
            "name": "test_module",
            "states": {
                "Initial": {
                    "type": "Initial",
                    "direct_transition": "SetAttribute"
                },
                "SetAttribute": {
                    "type": "SetAttribute",
                    "attribute": "test_value",
                    "value": "success",
                    "direct_transition": "Terminal"
                },
                "Terminal": {
                    "type": "Terminal"
                }
            }
        }
        
        # Save module
        module_file = temp_dir / "test_module.json"
        with open(module_file, 'w') as f:
            json.dump(module_def, f)
        
        # Load module
        Module._load_json_module(module_file)
        module = Module.get_module("test_module")
        
        assert module is not None
        assert module.name == "test_module"
        assert len(module.states) == 3
        
        # Execute module
        person = Person()
        result = module.process(person, datetime.now())
        
        assert result is True
        assert person.attributes.get('test_value') == 'success'
    
    def test_config_loading_and_override(self, temp_dir):
        """Test configuration loading and override."""
        # Create config file
        config_file = temp_dir / "test.properties"
        with open(config_file, 'w') as f:
            f.write("exporter.fhir.export = false\n")
            f.write("exporter.csv.export = true\n")
            f.write("generate.default_population = 50\n")
        
        # Load config
        config = Config()
        config.load(str(config_file))
        
        assert config.get_bool('exporter.fhir.export') is False
        assert config.get_bool('exporter.csv.export') is True
        assert config.get_int('generate.default_population') == 50
        
        # Override with args
        args = {
            '--exporter.fhir.export': 'true',
            '--generate.default_population': '100'
        }
        config.override_with_args(args)
        
        assert config.get_bool('exporter.fhir.export') is True
        assert config.get_int('generate.default_population') == 100
    
    def test_person_lifecycle_simulation(self):
        """Test simulating a person's lifecycle."""
        options = GeneratorOptions()
        options.seed = 777
        options.min_age = 30
        options.max_age = 30
        
        generator = Generator(options)
        person = Person(seed=777)
        
        # Set demographics
        generator._set_demographics(person)
        generator._set_location(person)
        
        # Initialize health record
        person.init_health_record()
        
        # Simple lifecycle simulation
        current_time = person.birth_date
        end_time = datetime.now()
        
        encounters = 0
        while current_time < end_time and person.alive:
            # Simulate annual checkup
            if current_time.month == 1:
                encounter = person.record.encounter_start(
                    current_time,
                    'wellness'
                )
                person.record.encounter_end(encounter, current_time)
                encounters += 1
            
            # Advance by month
            if current_time.month == 12:
                current_time = current_time.replace(
                    year=current_time.year + 1,
                    month=1
                )
            else:
                current_time = current_time.replace(
                    month=current_time.month + 1
                )
        
        assert encounters > 0
        assert len(person.record.encounters) == encounters
    
    def test_export_pipeline(self, temp_dir):
        """Test the complete export pipeline."""
        # Create person with data
        person = Person(seed=123)
        person.attributes.update({
            'gender': 'F',
            'first_name': 'Jane',
            'last_name': 'Smith',
            'birth_date': datetime(1990, 6, 15),
            'race': 'asian',
            'ethnicity': 'non_hispanic'
        })
        person.init_health_record()
        
        # Add medical history
        enc = person.record.encounter_start(datetime(2023, 3, 1), 'ambulatory')
        person.record.observation(
            datetime(2023, 3, 1),
            None,
            120,
            'mmHg',
            enc
        )
        person.record.encounter_end(enc, datetime(2023, 3, 1))
        
        # Configure exporters
        config = Config()
        config.set('exporter.baseDirectory', str(temp_dir))
        
        # Test JSON export
        json_exporter = JSONExporter(config, temp_dir)
        json_file = json_exporter.export(person, 0)
        
        assert json_file is not None
        assert Path(json_file).exists()
        
        with open(json_file, 'r') as f:
            data = json.load(f)
            assert data['attributes']['first_name'] == 'Jane'
            assert data['attributes']['last_name'] == 'Smith'
            assert 'health_record' in data
        
        # Test FHIR export
        fhir_exporter = FHIRExporter(config, temp_dir)
        fhir_file = fhir_exporter.export(person, 0)
        
        assert fhir_file is not None
        assert Path(fhir_file).exists()
        
        with open(fhir_file, 'r') as f:
            bundle = json.load(f)
            assert bundle['resourceType'] == 'Bundle'
            assert any(
                e['resource']['resourceType'] == 'Observation'
                for e in bundle['entry']
            )