#!/usr/bin/env python
"""
Basic patient generation example.

This script demonstrates how to use the Synthea Python API to generate
synthetic patients programmatically.

Usage:
    uv run python examples/basic_generation.py
"""

from synthea import Generator, GeneratorOptions
from synthea.helpers.config import Config
from pathlib import Path
import sys


def main():
    """Generate synthetic patients with basic configuration."""
    
    print("=" * 60)
    print("Synthea Python - Basic Generation Example")
    print("=" * 60)
    
    # Configure generation options
    options = GeneratorOptions()
    options.population_size = 10
    options.state = "California"
    options.city = "San Francisco"
    options.seed = 12345  # For reproducibility
    options.threads = 2  # Use 2 threads for parallel generation
    
    print(f"\nConfiguration:")
    print(f"  Population Size: {options.population_size}")
    print(f"  Location: {options.city}, {options.state}")
    print(f"  Seed: {options.seed}")
    print(f"  Threads: {options.threads}")
    
    # Configure output
    config = Config()
    output_dir = Path("./output/example_basic")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    config.set('exporter.baseDirectory', str(output_dir))
    config.set('exporter.fhir.export', True)
    config.set('exporter.json.export', True)
    config.set('exporter.csv.export', False)
    
    print(f"  Output Directory: {output_dir}")
    print(f"  Export Formats: FHIR, JSON")
    
    # Create and configure generator
    print("\nInitializing generator...")
    generator = Generator(options)
    generator.config = config
    
    # Run generation
    print("Generating patients...")
    try:
        generator.run()
    except KeyboardInterrupt:
        print("\nGeneration interrupted by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\nError during generation: {e}")
        sys.exit(1)
    
    # Print results
    print("\n" + "=" * 60)
    print("Generation Complete!")
    print("=" * 60)
    print(f"Total Generated: {generator.stats['total_generated']}")
    print(f"  Living: {generator.stats['living']}")
    print(f"  Dead: {generator.stats['dead']}")
    print(f"  Rejected: {generator.stats['rejected']}")
    
    print(f"\nOutput files saved to: {output_dir}")
    
    # List generated files
    fhir_files = list((output_dir / 'fhir').glob('*.json')) if (output_dir / 'fhir').exists() else []
    json_files = list((output_dir / 'json').glob('*.json')) if (output_dir / 'json').exists() else []
    
    if fhir_files:
        print(f"  FHIR files: {len(fhir_files)}")
    if json_files:
        print(f"  JSON files: {len(json_files)}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())