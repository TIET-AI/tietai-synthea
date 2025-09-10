"""
Tests for the Generator engine.
"""

import pytest
from datetime import datetime
from pathlib import Path
import tempfile
import shutil

from synthea.engine.generator import Generator, GeneratorOptions
from synthea.helpers.config import Config
from synthea.world.person import Person


class TestGenerator:
    """Test Generator class."""
    
    @pytest.fixture
    def temp_output_dir(self):
        """Create a temporary output directory."""
        temp_dir = tempfile.mkdtemp()
        yield Path(temp_dir)
        # Cleanup
        shutil.rmtree(temp_dir, ignore_errors=True)
    
    def test_generator_creation(self):
        """Test creating a generator."""
        options = GeneratorOptions()
        options.population_size = 10
        
        generator = Generator(options)
        
        assert generator.options.population_size == 10
        assert generator.stats['total_generated'] == 0
        assert generator.config is not None
    
    def test_generator_options(self):
        """Test generator options."""
        options = GeneratorOptions()
        options.population_size = 5
        options.seed = 12345
        options.gender = 'F'
        options.min_age = 20
        options.max_age = 40
        options.state = 'California'
        options.city = 'San Francisco'
        
        generator = Generator(options)
        
        assert generator.options.population_size == 5
        assert generator.options.seed == 12345
        assert generator.options.gender == 'F'
        assert generator.options.min_age == 20
        assert generator.options.max_age == 40
        assert generator.options.state == 'California'
        assert generator.options.city == 'San Francisco'
    
    def test_generator_options_from_args(self):
        """Test creating options from arguments."""
        args = {
            'population': 100,
            'seed': 999,
            'gender': 'M',
            'min_age': 30,
            'max_age': 50,
            'state': 'Texas',
            'city': 'Austin',
            'threads': 4
        }
        
        options = GeneratorOptions.from_args(args)
        
        assert options.population_size == 100
        assert options.seed == 999
        assert options.gender == 'M'
        assert options.min_age == 30
        assert options.max_age == 50
        assert options.state == 'Texas'
        assert options.city == 'Austin'
        assert options.threads == 4
    
    def test_generate_person(self):
        """Test generating a single person."""
        options = GeneratorOptions()
        options.seed = 42
        options.state = 'Massachusetts'
        options.city = 'Boston'
        
        generator = Generator(options)
        person = generator.generate_person(0)
        
        assert person is not None
        assert person.alive is True
        assert person.attributes.get('state') == 'Massachusetts'
        assert person.attributes.get('city') == 'Boston'
        assert 'gender' in person.attributes
        assert 'race' in person.attributes
        assert 'birth_date' in person.attributes
    
    def test_generate_person_with_gender_filter(self):
        """Test generating a person with gender filter."""
        options = GeneratorOptions()
        options.gender = 'F'
        options.seed = 100
        
        generator = Generator(options)
        person = generator.generate_person(0)
        
        assert person is not None
        assert person.attributes['gender'] == 'F'
    
    def test_generate_person_reproducibility(self):
        """Test that same seed produces same results."""
        options1 = GeneratorOptions()
        options1.seed = 777
        generator1 = Generator(options1)
        person1 = generator1.generate_person(0)
        
        options2 = GeneratorOptions()
        options2.seed = 777
        generator2 = Generator(options2)
        person2 = generator2.generate_person(0)
        
        # Should have same attributes
        assert person1.id == person2.id
        assert person1.attributes['gender'] == person2.attributes['gender']
        assert person1.attributes['race'] == person2.attributes['race']
    
    def test_run_generation(self, temp_output_dir):
        """Test running full generation."""
        options = GeneratorOptions()
        options.population_size = 3
        options.seed = 12345
        
        config = Config()
        config.set('exporter.baseDirectory', str(temp_output_dir))
        config.set('exporter.fhir.export', False)
        config.set('exporter.json.export', True)
        
        generator = Generator(options)
        generator.config = config
        
        # Mock the module list to speed up test
        generator.module_list = []
        
        generator.run()
        
        assert generator.stats['total_generated'] == 3
        assert generator.stats['living'] + generator.stats['dead'] == 3
    
    def test_demographics_assignment(self):
        """Test demographic attribute assignment."""
        options = GeneratorOptions()
        options.seed = 555
        options.min_age = 25
        options.max_age = 25
        
        generator = Generator(options)
        person = Person()
        
        generator._set_demographics(person)
        
        assert person.attributes['gender'] in ['M', 'F']
        assert person.attributes['race'] is not None
        assert person.attributes['ethnicity'] is not None
        assert person.attributes['socioeconomic_status'] in ['low', 'middle', 'high']
        
        # Check age is approximately 25
        age = person.age_at(datetime.now())
        assert 24.5 < age < 25.5
    
    def test_location_assignment(self):
        """Test location attribute assignment."""
        options = GeneratorOptions()
        options.state = 'New York'
        options.city = 'New York'
        
        generator = Generator(options)
        person = Person()
        
        generator._set_location(person)
        
        assert person.attributes['state'] == 'New York'
        assert person.attributes['city'] == 'New York'
        assert 'zip_code' in person.attributes
        assert 'latitude' in person.attributes
        assert 'longitude' in person.attributes
    
    def test_stats_tracking(self):
        """Test statistics tracking."""
        options = GeneratorOptions()
        options.population_size = 5
        options.seed = 999
        
        generator = Generator(options)
        
        # Generate some people
        for i in range(5):
            person = generator.generate_person(i)
            if person:
                # Simulate some deaths
                if i % 2 == 0:
                    person.alive = False
                    generator.stats['dead'] += 1
                    generator.stats['living'] -= 1
        
        assert generator.stats['total_generated'] == 5
        assert generator.stats['living'] + generator.stats['dead'] == 5