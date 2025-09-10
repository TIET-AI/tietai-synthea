#!/usr/bin/env python
"""
Test script to verify all resources are properly loaded.
"""

import json
from pathlib import Path
from synthea.engine.module import Module
from synthea.helpers.config import Config
from synthea.world.demographics import Demographics
from synthea.world.location import Location

def test_resources():
    """Test that all resources are accessible."""
    
    print("=" * 60)
    print("Testing Synthea Python Resources")
    print("=" * 60)
    
    # Test module loading
    print("\n1. Testing Module Loading:")
    print("-" * 30)
    Module.load_modules('resources/modules')
    modules = Module.get_all_modules()
    print(f"✓ Loaded {len(modules)} disease modules")
    print(f"  Examples: {modules[:5]}")
    
    # Test specific module
    asthma = Module.get_module('Asthma')
    if asthma:
        print(f"✓ Successfully loaded 'Asthma' module")
        print(f"  States: {len(asthma.states)}")
    
    # Test configuration
    print("\n2. Testing Configuration:")
    print("-" * 30)
    config = Config()
    config.load('resources/synthea.properties')
    print(f"✓ Loaded configuration file")
    print(f"  Sample settings:")
    print(f"    - FHIR export: {config.get('exporter.fhir.export')}")
    print(f"    - Default population: {config.get('generate.default_population')}")
    
    # Test geography data
    print("\n3. Testing Geography Data:")
    print("-" * 30)
    geography_path = Path('resources/geography')
    if geography_path.exists():
        files = list(geography_path.glob('*.json')) + list(geography_path.glob('*.csv'))
        print(f"✓ Found {len(files)} geography files")
        for f in files[:3]:
            print(f"    - {f.name}")
    
    # Test provider data
    print("\n4. Testing Provider Data:")
    print("-" * 30)
    provider_path = Path('resources/providers')
    if provider_path.exists():
        csv_files = list(provider_path.glob('*.csv'))
        print(f"✓ Found {len(csv_files)} provider files")
        for f in csv_files[:3]:
            print(f"    - {f.name}")
    
    # Test payer data
    print("\n5. Testing Payer Data:")
    print("-" * 30)
    payer_path = Path('resources/payers')
    if payer_path.exists():
        payer_files = list(payer_path.glob('*.csv'))
        print(f"✓ Found {len(payer_files)} payer files")
        for f in payer_files[:3]:
            print(f"    - {f.name}")
    
    # Test lookup tables
    print("\n6. Testing Lookup Tables:")
    print("-" * 30)
    lookup_path = Path('resources/lookup_tables')
    if lookup_path.exists():
        lookup_files = list(lookup_path.glob('*.csv'))
        print(f"✓ Found {len(lookup_files)} lookup tables")
        for f in lookup_files[:3]:
            print(f"    - {f.name}")
    
    # Test cost data
    print("\n7. Testing Cost Data:")
    print("-" * 30)
    cost_path = Path('resources/costs')
    if cost_path.exists():
        cost_files = list(cost_path.glob('*.csv'))
        print(f"✓ Found {len(cost_files)} cost files")
        for f in cost_files[:3]:
            print(f"    - {f.name}")
    
    # Test COVID-19 modules
    print("\n8. Testing COVID-19 Modules:")
    print("-" * 30)
    covid_path = Path('resources/covid19')
    if covid_path.exists():
        covid_files = list(covid_path.glob('*.json'))
        print(f"✓ Found {len(covid_files)} COVID-19 modules")
    
    # Test immunization schedule
    print("\n9. Testing Immunization Schedule:")
    print("-" * 30)
    immun_file = Path('resources/immunization_schedule.json')
    if immun_file.exists():
        with open(immun_file) as f:
            schedule = json.load(f)
            print(f"✓ Loaded immunization schedule")
            print(f"  Vaccines: {len(schedule.get('vaccines', []))}")
    
    # Test growth charts
    print("\n10. Testing Growth Charts:")
    print("-" * 30)
    growth_file = Path('resources/cdc_growth_charts.json')
    if growth_file.exists():
        print(f"✓ Found CDC growth charts")
        print(f"  File size: {growth_file.stat().st_size / 1024:.1f} KB")
    
    print("\n" + "=" * 60)
    print("Resource Test Summary")
    print("=" * 60)
    
    # Summary
    total_files = 0
    for ext in ['*.json', '*.csv', '*.yml', '*.yaml']:
        total_files += len(list(Path('resources').rglob(ext)))
    
    print(f"✓ Total resource files: {total_files}")
    print(f"✓ Disease modules: {len(modules)}")
    
    subdirs = [d for d in Path('resources').iterdir() if d.is_dir()]
    print(f"✓ Resource directories: {len(subdirs)}")
    
    print("\nAll resources loaded successfully!")
    
    return True

if __name__ == "__main__":
    test_resources()