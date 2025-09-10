"""
Command-line interface for Synthea.

This module provides the main entry point for running Synthea from the command line.
"""

import click
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional

from synthea.engine.generator import Generator, GeneratorOptions
from synthea.helpers.config import Config
from synthea.engine.module import Module


@click.command()
@click.option('-p', '--population', type=int, default=1,
              help='Number of patients to generate')
@click.option('-s', '--seed', type=int, default=None,
              help='Seed for random number generator')
@click.option('--clinician-seed', type=int, default=None,
              help='Seed for clinician random number generator')
@click.option('-g', '--gender', type=click.Choice(['M', 'F'], case_sensitive=False),
              help='Gender of generated patients')
@click.option('-a', '--age', type=str, default=None,
              help='Age range (e.g., "20-40")')
@click.option('-m', '--module', type=str, multiple=True,
              help='Specific modules to run (can be specified multiple times)')
@click.option('-c', '--config', type=click.Path(exists=True),
              help='Path to configuration file')
@click.option('-d', '--modules-dir', type=click.Path(exists=True),
              help='Path to modules directory')
@click.option('-o', '--output-dir', type=click.Path(),
              help='Output directory for generated files')
@click.option('-r', '--reference-date', type=str,
              help='Reference date (YYYYMMDD format)')
@click.option('--state', type=str, default=None,
              help='State to generate patients for')
@click.option('--city', type=str, default=None,
              help='City to generate patients for')
@click.option('--threads', type=int, default=1,
              help='Number of threads to use for generation')
@click.option('--log-level', type=click.Choice(['debug', 'info', 'warning', 'error']),
              default='info', help='Logging level')
@click.option('--only-dead', is_flag=True,
              help='Only generate deceased patients')
@click.option('--keep-patients', type=click.Path(),
              help='Path to file with patient IDs to keep')
@click.option('--overflow', type=int, default=0,
              help='Overflow population')
@click.option('--graphviz', type=str,
              help='Generate Graphviz visualization for specified module')
@click.option('--list-modules', is_flag=True,
              help='List all available modules')
@click.option('--version', is_flag=True,
              help='Show version information')
@click.argument('location', nargs=-1)
def main(population, seed, clinician_seed, gender, age, module, config, modules_dir,
         output_dir, reference_date, state, city, threads, log_level, only_dead,
         keep_patients, overflow, graphviz, list_modules, version, location):
    """
    Synthea Patient Generator
    
    Generate synthetic patient data and health records.
    
    Examples:
    
        synthea -p 100
        
        synthea -p 1000 Massachusetts Boston
        
        synthea -s 12345 -p 50 --state California
    """
    
    # Handle version flag
    if version:
        from synthea import __version__
        click.echo(f"Synthea Python v{__version__}")
        sys.exit(0)
    
    # Handle list modules flag
    if list_modules:
        list_available_modules(modules_dir)
        sys.exit(0)
    
    # Handle graphviz flag
    if graphviz:
        generate_graphviz(graphviz, modules_dir)
        sys.exit(0)
    
    # Parse location arguments
    if location:
        if len(location) >= 1:
            state = location[0]
        if len(location) >= 2:
            city = location[1]
    
    # Create generator options
    options = GeneratorOptions()
    options.population_size = population
    options.seed = seed
    options.clinician_seed = clinician_seed
    options.gender = gender
    options.state = state
    options.city = city
    options.threads = threads
    options.only_dead_patients = only_dead
    options.overflow_population = overflow
    
    # Parse age range
    if age:
        if '-' in age:
            min_age, max_age = age.split('-')
            options.min_age = int(min_age)
            options.max_age = int(max_age)
        else:
            options.min_age = int(age)
            options.max_age = int(age)
    
    # Parse reference date
    if reference_date:
        try:
            options.reference_date = datetime.strptime(reference_date, '%Y%m%d')
            options.end_date = options.reference_date
        except ValueError:
            click.echo(f"Error: Invalid date format '{reference_date}'. Use YYYYMMDD.", err=True)
            sys.exit(1)
    
    if keep_patients:
        options.keep_patients_path = keep_patients
    
    # Load configuration
    config_obj = Config()
    if config:
        config_obj.load(config)
    else:
        config_obj.load()  # Load default
    
    # Override with command-line settings
    if output_dir:
        config_obj.set('exporter.baseDirectory', output_dir)
    
    if module:
        # Enable only specified modules
        for mod in Module.get_all_modules():
            config_obj.set(f'generate.{mod}', mod in module)
    
    # Create and run generator
    click.echo("=" * 50)
    click.echo("Synthea Patient Generator")
    click.echo("=" * 50)
    click.echo(f"Population: {options.population_size}")
    if options.seed:
        click.echo(f"Seed: {options.seed}")
    if state:
        click.echo(f"Location: {state}" + (f", {city}" if city else ""))
    click.echo("")
    
    try:
        generator = Generator(options)
        generator.config = config_obj
        
        # Override modules directory if specified
        if modules_dir:
            Module.load_modules(modules_dir)
        
        generator.run()
        
    except KeyboardInterrupt:
        click.echo("\nGeneration interrupted by user.", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        if log_level == 'debug':
            import traceback
            traceback.print_exc()
        sys.exit(1)


def list_available_modules(modules_dir: Optional[str] = None):
    """List all available modules."""
    click.echo("Available Modules:")
    click.echo("-" * 30)
    
    # Load modules
    if modules_dir:
        modules = Module.load_modules(modules_dir)
    else:
        modules = Module.load_modules()
    
    # Get all module names
    module_names = Module.get_all_modules()
    
    # Group by type
    core_modules = []
    disease_modules = []
    
    for name in sorted(module_names):
        if name in ['lifecycle', 'encounter', 'health_insurance', 'death', 'quality_of_life']:
            core_modules.append(name)
        else:
            disease_modules.append(name)
    
    if core_modules:
        click.echo("\nCore Modules:")
        for name in core_modules:
            click.echo(f"  - {name}")
    
    if disease_modules:
        click.echo("\nDisease/Condition Modules:")
        for name in disease_modules:
            click.echo(f"  - {name}")
    
    click.echo(f"\nTotal: {len(module_names)} modules")


def generate_graphviz(module_name: str, modules_dir: Optional[str] = None):
    """Generate Graphviz visualization for a module."""
    click.echo(f"Generating Graphviz for module: {module_name}")
    
    # Load modules
    if modules_dir:
        Module.load_modules(modules_dir)
    else:
        Module.load_modules()
    
    # Get the module
    module = Module.get_module(module_name)
    if not module:
        click.echo(f"Error: Module '{module_name}' not found.", err=True)
        sys.exit(1)
    
    # Generate DOT format
    dot = generate_module_dot(module)
    
    # Write to file
    output_file = f"{module_name}.dot"
    with open(output_file, 'w') as f:
        f.write(dot)
    
    click.echo(f"Graphviz DOT file written to: {output_file}")
    click.echo(f"To generate image: dot -Tpng {output_file} -o {module_name}.png")


def generate_module_dot(module: Module) -> str:
    """Generate DOT format for a module."""
    lines = []
    lines.append("digraph G {")
    lines.append('  rankdir=TB;')
    lines.append('  node [shape=box];')
    
    # Add states
    for state_name, state in module.states.items():
        state_type = state.definition.get('type', 'Simple')
        
        # Style based on state type
        if state_type == 'Initial':
            style = 'style=filled,fillcolor=green'
        elif state_type == 'Terminal':
            style = 'style=filled,fillcolor=red'
        elif state_type == 'Encounter':
            style = 'style=filled,fillcolor=lightblue'
        elif state_type == 'ConditionOnset':
            style = 'style=filled,fillcolor=yellow'
        else:
            style = ''
        
        label = f"{state_name}\\n[{state_type}]"
        lines.append(f'  "{state_name}" [label="{label}"{", " + style if style else ""}];')
    
    # Add transitions
    for state_name, state in module.states.items():
        transitions = module._get_possible_transitions(state.definition)
        for target in transitions:
            if target and target in module.states:
                lines.append(f'  "{state_name}" -> "{target}";')
    
    lines.append("}")
    
    return '\n'.join(lines)


if __name__ == '__main__':
    main()