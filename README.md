# Synthea Python - Synthetic Patient Generator

A Python implementation of Synthea™, a Synthetic Patient Population Simulator that generates realistic (but not real) patient data and associated health records.

For a formal description of the framework, design goals, architecture, and generation pipeline, see the accompanying paper: [PySynthea: A Python-Native Framework for Scalable Synthetic Healthcare Data Generation](paper.pdf).

## Features

- **Complete Patient Lifecycle**: Simulates patients from birth to death
- **231 Disease Modules**: Comprehensive set of conditions including diabetes, heart disease, COVID-19, cancer, and more
- **Modular Disease Framework**: JSON-based state machines for conditions
- **Multiple Export Formats**: FHIR R4, CSV, JSON
- **Real-World Data**: CDC growth charts, immunization schedules, provider databases, cost data
- **Demographics**: Based on real census data with geographic distributions
- **Healthcare System**: Complete with providers, payers, and cost modeling
- **Configurable**: Extensive configuration options via properties file
- **Fast**: Uses UV for blazing-fast dependency management

## Installation

### From PyPI (recommended)

```bash
pip install py-synthea
```

The distribution is published as **`py-synthea`**; the import name and CLI
command are both `synthea`:

```bash
synthea -p 10            # generate 10 patients
python -c "import synthea; print(synthea.__version__)"
```

All data resources (disease modules, demographics, growth charts, clinical
templates) are bundled with the package, so it works from any directory — no
repository checkout required.

## Prerequisites (for development)

- Python 3.9 or higher
- [UV](https://github.com/astral-sh/uv) package manager

### Installing UV

```bash
# On macOS and Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# On Windows
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

# Or with pip
pip install uv
```

### From source (development)

```bash
# Clone the repository
git clone https://github.com/TIET-AI/tietai-synthea.git
cd tietai-synthea

# Create virtual environment and install dependencies with UV
uv venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install the package in development mode
uv pip install -e .

# Or install with all development dependencies
uv pip install -e ".[dev]"

# Install additional optional dependencies
uv pip install -e ".[physiology,visualization]"
```

## Quick Start

### Generate Patients with UV

```bash
# Ensure UV environment is activated
source .venv/bin/activate

# Generate 10 patients (default)
uv run synthea -p 10

# Generate 100 patients in Massachusetts
uv run synthea -p 100 --state Massachusetts

# Generate patients with specific seed for reproducibility
uv run synthea -p 50 -s 12345

# Generate only female patients aged 20-40
uv run synthea -p 20 -g F -a 20-40

# Generate and export to specific directory
uv run synthea -p 100 -o ./my-output --state California --city "San Francisco"
```

### Using UV Scripts

```bash
# Run with UV directly (no activation needed)
uv run synthea --help

# Run tests with UV
uv run pytest

# Run with coverage
uv run pytest --cov=synthea --cov-report=html

# Format code
uv run black src/ tests/

# Lint code
uv run flake8 src/

# Type checking
uv run mypy src/
```

## Development Setup with UV

```bash
# Create fresh environment
uv venv --python 3.11

# Sync all dependencies from pyproject.toml
uv pip sync pyproject.toml

# Add new dependencies
uv pip install new-package

# Freeze dependencies
uv pip freeze > requirements.txt

# Run in isolated environment (for testing)
uv run --isolated synthea -p 10
```

## Command Line Options

```
Usage: synthea [OPTIONS] [LOCATION]...

Options:
  -p, --population INTEGER      Number of patients to generate [default: 1]
  -s, --seed INTEGER            Seed for random number generator
  --clinician-seed INTEGER      Seed for clinician random generator
  -g, --gender [M|F]            Gender of generated patients
  -a, --age TEXT                Age range (e.g., "20-40")
  -m, --module TEXT             Specific modules to run (repeatable)
  -c, --config PATH             Path to configuration file
  -d, --modules-dir PATH        Path to modules directory
  -o, --output-dir PATH         Output directory for generated files
  -r, --reference-date TEXT     Reference date (YYYYMMDD format)
  --state TEXT                  State to generate patients for
  --city TEXT                   City to generate patients for
  --threads INTEGER             Number of threads for parallel generation
  --log-level [debug|info|warning|error]
  --only-dead                   Only generate deceased patients
  --keep-patients PATH          Path to file with patient IDs to keep
  --overflow INTEGER            Overflow population
  --graphviz TEXT               Generate Graphviz for specified module
  --list-modules                List all available modules
  --version                     Show version information
  --help                        Show this message and exit

Examples:
  synthea -p 100
  synthea -p 1000 Massachusetts Boston
  synthea -s 12345 -p 50 --state California
  synthea -p 100 -g F -a 25-35 --threads 4
```

## Project Structure

```
tietai-synthea/
├── pyproject.toml        # UV-compatible project configuration
├── README.md            # This file
├── src/synthea/
│   ├── engine/          # Core simulation engine
│   │   ├── generator.py # Main generator
│   │   ├── module.py    # Module system
│   │   ├── state.py     # State machine
│   │   ├── transition.py # Transition logic
│   │   └── logic.py     # Condition evaluation
│   ├── world/           # Data models
│   │   ├── person.py    # Patient model
│   │   ├── health_record.py # Medical records
│   │   ├── demographics.py  # Demographics
│   │   ├── location.py     # Geographic data
│   │   ├── provider.py     # Healthcare providers
│   │   └── payer.py        # Insurance
│   ├── export/          # Export formats
│   │   ├── fhir.py      # FHIR R4 exporter
│   │   └── exporter.py  # Base exporter
│   ├── helpers/         # Utilities
│   │   └── config.py    # Configuration
│   └── cli.py           # Command-line interface
├── resources/           # Data files (394+ files)
│   ├── modules/         # 231 Disease modules (JSON)
│   │   ├── allergies/   # Allergy-related modules
│   │   ├── breast_cancer/ # Cancer modules
│   │   ├── covid19/     # COVID-19 modules
│   │   └── *.json       # Individual disease modules
│   ├── geography/       # Geographic and demographic data
│   ├── providers/       # Healthcare provider data (15 CSV files)
│   ├── payers/          # Insurance payer data
│   ├── costs/           # Healthcare cost data (14 CSV files)
│   ├── lookup_tables/   # Lookup tables for transitions
│   ├── export/          # Export templates
│   ├── cdc_growth_charts.json # CDC growth data
│   ├── immunization_schedule.json # Vaccine schedules
│   └── synthea.properties # Default configuration
├── tests/              # Test suite
│   ├── test_person.py
│   ├── test_state.py
│   ├── test_generator.py
│   └── test_integration.py
└── examples/           # Example scripts
    ├── basic_generation.py
    ├── custom_module.py
    └── batch_export.py
```

## Configuration

### Using Configuration Files

```bash
# Use custom configuration
uv run synthea -c my-config.properties -p 100

# Override specific settings
uv run synthea -p 100 --config my-config.properties
```

### Configuration File (synthea.properties)

```properties
# Exporter settings
exporter.fhir.export = true
exporter.csv.export = false
exporter.json.export = true
exporter.baseDirectory = ./output/
exporter.use_uuid_filenames = false

# Generator settings
generate.default_population = 10
generate.thread_pool_size = 4
generate.only_dead_patients = false
generate.max_attempts_to_keep_patient = 1000

# Module settings
generate.timestep = 604800000  # 1 week in ms

# Costs
generate.costs.default_procedure_cost = 500.0
generate.costs.default_medication_cost = 255.0
generate.costs.default_encounter_cost = 125.0
```

## Python API Usage

### Basic Generation

```python
# examples/basic_generation.py
from synthea import Generator, GeneratorOptions
from synthea.helpers.config import Config

# Configure generation
options = GeneratorOptions()
options.population_size = 100
options.state = "California"
options.city = "San Francisco"
options.seed = 12345

# Create and run generator
generator = Generator(options)
generator.run()

print(f"Generated {generator.stats['total_generated']} patients")
print(f"Living: {generator.stats['living']}")
print(f"Dead: {generator.stats['dead']}")
```

Run with UV:
```bash
uv run python examples/basic_generation.py
```

### Custom Patient Generation

```python
# examples/custom_patient.py
from datetime import datetime
from synthea.world.person import Person
from synthea.engine.generator import Generator, GeneratorOptions
from synthea.export.fhir import FHIRExporter
from pathlib import Path

# Create a specific patient
person = Person(seed=12345)
person.attributes['gender'] = 'F'
person.attributes['birth_date'] = datetime(1980, 5, 15)
person.attributes['first_name'] = 'Jane'
person.attributes['last_name'] = 'Doe'
person.attributes['race'] = 'white'
person.attributes['ethnicity'] = 'non_hispanic'

# Initialize health record
person.init_health_record()

# Run simulation
generator = Generator(GeneratorOptions())
generator._simulate_life(person)

# Export to FHIR
config = generator.config
exporter = FHIRExporter(config, Path('./output'))
output_file = exporter.export(person, 0)
print(f"Exported to: {output_file}")
```

### Batch Processing

```python
# examples/batch_export.py
from synthea import Generator, GeneratorOptions
from pathlib import Path
import concurrent.futures

def generate_batch(state: str, size: int, seed: int):
    """Generate a batch of patients for a specific state."""
    options = GeneratorOptions()
    options.population_size = size
    options.state = state
    options.seed = seed
    
    generator = Generator(options)
    generator.run()
    
    return {
        'state': state,
        'generated': generator.stats['total_generated'],
        'living': generator.stats['living'],
        'dead': generator.stats['dead']
    }

# Generate patients for multiple states in parallel
states = ['California', 'Texas', 'New York', 'Florida']
results = []

with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
    futures = [
        executor.submit(generate_batch, state, 100, i * 1000)
        for i, state in enumerate(states)
    ]
    
    for future in concurrent.futures.as_completed(futures):
        result = future.result()
        results.append(result)
        print(f"{result['state']}: Generated {result['generated']} patients")

# Summary
total = sum(r['generated'] for r in results)
print(f"\nTotal patients generated: {total}")
```

## Testing

### Run All Tests with UV

```bash
# Run all tests
uv run pytest

# Run with verbose output
uv run pytest -v

# Run specific test file
uv run pytest tests/test_person.py

# Run with coverage
uv run pytest --cov=synthea --cov-report=term-missing

# Generate HTML coverage report
uv run pytest --cov=synthea --cov-report=html
# Open htmlcov/index.html in browser

# Run tests in parallel
uv run pytest -n auto

# Run only unit tests
uv run pytest tests/unit/

# Run only integration tests
uv run pytest tests/integration/
```

### Continuous Testing

```bash
# Watch for changes and rerun tests
uv run pytest-watch

# Run tests on file save
uv run ptw -- --testmon
```

## Available Disease Modules

The Python implementation includes all 231 disease modules from the original Synthea project:

### Major Conditions
- **Cardiovascular**: Atrial Fibrillation, Heart Disease, Hypertension, Stroke
- **Cancer**: Breast Cancer, Colorectal Cancer, Lung Cancer
- **Respiratory**: Asthma, COPD, COVID-19, Pneumonia
- **Metabolic**: Diabetes, Prediabetes, Metabolic Syndrome
- **Mental Health**: Depression, Anxiety, ADHD, Dementia
- **Infectious**: COVID-19, Influenza, Ear Infections, UTIs
- **Chronic**: Chronic Kidney Disease, Rheumatoid Arthritis, Lupus
- **Pediatric**: Childhood diseases, immunizations, growth tracking

### Viewing Available Modules

```bash
# List all available modules
uv run synthea --list-modules

# Generate with specific disease modules only
uv run synthea -p 10 -m diabetes -m hypertension

# View module structure
uv run synthea --graphviz diabetes
```

## Module Development

### Creating a Custom Module

```json
{
  "name": "Simple Cold",
  "states": {
    "Initial": {
      "type": "Initial",
      "direct_transition": "Check_Cold"
    },
    "Check_Cold": {
      "type": "Simple",
      "distributed_transition": [
        {
          "distribution": 0.25,
          "transition": "Cold_Onset"
        },
        {
          "distribution": 0.75,
          "transition": "Terminal"
        }
      ]
    },
    "Cold_Onset": {
      "type": "ConditionOnset",
      "codes": [{
        "system": "SNOMED-CT",
        "code": "82272006",
        "display": "Common cold"
      }],
      "direct_transition": "Cold_Duration"
    },
    "Cold_Duration": {
      "type": "Delay",
      "range": {
        "low": 7,
        "high": 14,
        "unit": "days"
      },
      "direct_transition": "Cold_Resolves"
    },
    "Cold_Resolves": {
      "type": "ConditionEnd",
      "condition_onset": "Cold_Onset",
      "direct_transition": "Terminal"
    },
    "Terminal": {
      "type": "Terminal"
    }
  }
}
```

### Testing Custom Modules

```bash
# Validate module JSON
uv run python -m synthea.validate_module resources/modules/my_module.json

# Generate with specific module
uv run synthea -p 10 -m my_module

# Visualize module
uv run synthea --graphviz my_module
dot -Tpng my_module.dot -o my_module.png
```

## Performance Tips

### Optimizing Generation Speed

```bash
# Use multiple threads
uv run synthea -p 1000 --threads 8

# Use PyPy for better performance
uv venv --python pypy3.9
uv pip install -e .
uv run synthea -p 1000

# Profile generation
uv run python -m cProfile -o profile.stats src/synthea/cli.py -p 100
uv run python -m pstats profile.stats
```

### Memory Optimization

```python
# Use generator for large populations
from synthea import Generator, GeneratorOptions

options = GeneratorOptions()
options.population_size = 10000
options.threads = 1  # Less memory usage

# Export in batches
generator = Generator(options)
for i in range(0, 10000, 100):
    options.population_size = 100
    generator.run()
    # Files are written incrementally
```

## Troubleshooting

### Common Issues

1. **UV not found**
   ```bash
   # Reinstall UV
   curl -LsSf https://astral.sh/uv/install.sh | sh
   # Add to PATH
   export PATH="$HOME/.cargo/bin:$PATH"
   ```

2. **Module not found errors**
   ```bash
   # Ensure package is installed in editable mode
   uv pip install -e .
   ```

3. **Out of memory**
   ```bash
   # Reduce population size or use fewer threads
   uv run synthea -p 100 --threads 1
   ```

4. **Slow generation**
   ```bash
   # Use UV's compiled dependencies
   uv pip install --compile .
   ```

## Contributing

We welcome contributions! Please:

1. Fork the repository
2. Create a feature branch
3. Set up development environment with UV:
   ```bash
   uv venv
   uv pip install -e ".[dev]"
   uv run pre-commit install
   ```
4. Make changes and add tests
5. Run tests: `uv run pytest`
6. Check formatting: `uv run black --check src/ tests/`
7. Submit pull request

## License

Apache License 2.0

## How to Cite

If you use this library in academic work, research prototypes, benchmarks, or published software, please cite paper: [PySynthea: A Python-Native Framework for Scalable Synthetic Healthcare Data Generation](paper.pdf).
:

Cruz, R., & Rey-Blanco, D. (2026). *PySynthea: A Python-Native Framework for Scalable Synthetic Healthcare Data Generation*. TietAI. 2026-05-21.

BibTeX:

```bibtex
@misc{cruz2026pysynthea,
  title = {PySynthea: A Python-Native Framework for Scalable Synthetic Healthcare Data Generation},
  author = {Cruz, Roberto and Rey-Blanco, David},
  year = {2026},
  month = may,
  note = {Technical report, TietAI},
  url = {https://github.com/TIET-AI/tietai-synthea}
}
```

## Acknowledgments

This is a Python port of the original [Synthea](https://github.com/synthetichealth/synthea) project by The MITRE Corporation.

## Support

- Issues: [GitHub Issues](https://github.com/TIET-AI/tietai-synthea/issues)
- Discussions: [GitHub Discussions](https://github.com/TIET-AI/tietai-synthea/discussions)
- Documentation: [Wiki](https://github.com/TIET-AI/tietai-synthea/wiki)
