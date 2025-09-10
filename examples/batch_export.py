#!/usr/bin/env python
"""
Batch export example with parallel processing.

This script demonstrates how to generate patients for multiple states
in parallel and export them in batches.

Usage:
    uv run python examples/batch_export.py
"""

import concurrent.futures
from pathlib import Path
import time
import json
from typing import Dict, List

from synthea import Generator, GeneratorOptions
from synthea.helpers.config import Config


def generate_batch(state: str, size: int, seed: int, output_base: Path) -> Dict:
    """
    Generate a batch of patients for a specific state.
    
    Args:
        state: State to generate patients for
        size: Number of patients to generate
        seed: Random seed for reproducibility
        output_base: Base output directory
    
    Returns:
        Dictionary with generation statistics
    """
    print(f"[{state}] Starting generation of {size} patients...")
    start_time = time.time()
    
    # Configure generation
    options = GeneratorOptions()
    options.population_size = size
    options.state = state
    options.seed = seed
    options.threads = 1  # Single thread per batch
    
    # Configure output
    config = Config()
    output_dir = output_base / state.lower().replace(' ', '_')
    output_dir.mkdir(parents=True, exist_ok=True)
    
    config.set('exporter.baseDirectory', str(output_dir))
    config.set('exporter.fhir.export', True)
    config.set('exporter.json.export', False)
    config.set('exporter.csv.export', False)
    
    # Generate
    generator = Generator(options)
    generator.config = config
    
    # Limit modules for faster generation in example
    generator.module_list = []
    
    try:
        generator.run()
        elapsed = time.time() - start_time
        
        result = {
            'state': state,
            'requested': size,
            'generated': generator.stats['total_generated'],
            'living': generator.stats['living'],
            'dead': generator.stats['dead'],
            'rejected': generator.stats['rejected'],
            'elapsed_time': elapsed,
            'output_dir': str(output_dir),
            'success': True,
            'error': None
        }
        
        print(f"[{state}] Completed: {result['generated']} patients in {elapsed:.2f}s")
        
    except Exception as e:
        elapsed = time.time() - start_time
        result = {
            'state': state,
            'requested': size,
            'generated': 0,
            'living': 0,
            'dead': 0,
            'rejected': 0,
            'elapsed_time': elapsed,
            'output_dir': str(output_dir),
            'success': False,
            'error': str(e)
        }
        
        print(f"[{state}] Failed: {e}")
    
    return result


def generate_summary_report(results: List[Dict], output_dir: Path):
    """
    Generate a summary report of all batches.
    
    Args:
        results: List of batch results
        output_dir: Output directory for report
    """
    report = {
        'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
        'batches': len(results),
        'successful_batches': sum(1 for r in results if r['success']),
        'failed_batches': sum(1 for r in results if not r['success']),
        'total_requested': sum(r['requested'] for r in results),
        'total_generated': sum(r['generated'] for r in results),
        'total_living': sum(r['living'] for r in results),
        'total_dead': sum(r['dead'] for r in results),
        'total_rejected': sum(r['rejected'] for r in results),
        'total_time': sum(r['elapsed_time'] for r in results),
        'batch_details': results
    }
    
    # Save report as JSON
    report_file = output_dir / 'batch_report.json'
    with open(report_file, 'w') as f:
        json.dump(report, f, indent=2)
    
    # Print summary
    print("\n" + "=" * 60)
    print("Batch Generation Summary")
    print("=" * 60)
    print(f"Timestamp: {report['timestamp']}")
    print(f"Total Batches: {report['batches']}")
    print(f"  Successful: {report['successful_batches']}")
    print(f"  Failed: {report['failed_batches']}")
    print(f"\nPatients:")
    print(f"  Requested: {report['total_requested']}")
    print(f"  Generated: {report['total_generated']}")
    print(f"    Living: {report['total_living']}")
    print(f"    Dead: {report['total_dead']}")
    print(f"  Rejected: {report['total_rejected']}")
    print(f"\nTotal Time: {report['total_time']:.2f} seconds")
    print(f"Average Time per Batch: {report['total_time']/len(results):.2f} seconds")
    
    if report['total_generated'] > 0:
        print(f"Average Time per Patient: {report['total_time']/report['total_generated']:.3f} seconds")
    
    print(f"\nReport saved to: {report_file}")
    
    return report_file


def main():
    """Main function."""
    
    print("=" * 60)
    print("Synthea Python - Batch Export Example")
    print("=" * 60)
    
    # Configuration
    batch_configs = [
        {'state': 'California', 'size': 20, 'seed': 1000},
        {'state': 'Texas', 'size': 20, 'seed': 2000},
        {'state': 'New York', 'size': 20, 'seed': 3000},
        {'state': 'Florida', 'size': 20, 'seed': 4000},
        {'state': 'Massachusetts', 'size': 20, 'seed': 5000},
    ]
    
    max_workers = 3  # Number of parallel workers
    
    # Create output directory
    output_base = Path("./output/example_batch")
    output_base.mkdir(parents=True, exist_ok=True)
    
    print(f"\nConfiguration:")
    print(f"  Batches: {len(batch_configs)}")
    print(f"  Total Patients: {sum(b['size'] for b in batch_configs)}")
    print(f"  Parallel Workers: {max_workers}")
    print(f"  Output Directory: {output_base}")
    
    print("\nStates to Process:")
    for config in batch_configs:
        print(f"  - {config['state']}: {config['size']} patients")
    
    # Process batches in parallel
    print(f"\nStarting parallel generation with {max_workers} workers...")
    print("-" * 60)
    
    start_time = time.time()
    results = []
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks
        futures = {
            executor.submit(
                generate_batch,
                config['state'],
                config['size'],
                config['seed'],
                output_base
            ): config
            for config in batch_configs
        }
        
        # Process completed tasks
        for future in concurrent.futures.as_completed(futures):
            config = futures[future]
            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                print(f"[{config['state']}] Exception: {e}")
                results.append({
                    'state': config['state'],
                    'requested': config['size'],
                    'generated': 0,
                    'living': 0,
                    'dead': 0,
                    'rejected': 0,
                    'elapsed_time': 0,
                    'output_dir': str(output_base / config['state'].lower()),
                    'success': False,
                    'error': str(e)
                })
    
    total_time = time.time() - start_time
    print("-" * 60)
    print(f"All batches completed in {total_time:.2f} seconds")
    
    # Generate summary report
    report_file = generate_summary_report(results, output_base)
    
    # Show batch details
    print("\n" + "=" * 60)
    print("Batch Details")
    print("=" * 60)
    
    for result in sorted(results, key=lambda x: x['state']):
        status = "✓" if result['success'] else "✗"
        print(f"\n[{status}] {result['state']}:")
        print(f"    Generated: {result['generated']}/{result['requested']}")
        print(f"    Living: {result['living']}, Dead: {result['dead']}")
        print(f"    Time: {result['elapsed_time']:.2f}s")
        print(f"    Output: {result['output_dir']}")
        if result['error']:
            print(f"    Error: {result['error']}")
    
    print(f"\nAll outputs saved to: {output_base}")
    
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())