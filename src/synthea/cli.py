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
        generator = Generator(options, config=config_obj)

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


@click.command('fetch-data')
@click.argument('datasets', nargs=-1)
@click.option('--list', 'show_list', is_flag=True,
              help='Show the optional datasets and whether they are present')
@click.option('--revision', default='master',
              help='Upstream revision to fetch from')
def fetch_data(datasets, show_list, revision):
    """Download optional reference data.

    Four upstream datasets are too large to bundle for data most runs never
    touch. They are downloaded into a local cache on request; loaders look
    there first and fall back to the bundled resources, so a run works without
    them and improves with them.

    Nothing is downloaded implicitly: generating patients never reaches the
    network.

    \b
    Examples:
        synthea fetch-data --list
        synthea fetch-data
        synthea fetch-data demographics facilities
    """
    from synthea.helpers import optional_data

    if show_list:
        click.echo(f"Cache: {optional_data.cache_dir()}")
        click.echo("")
        for name, available, size, purpose in optional_data.status():
            mark = "present" if available else "not fetched"
            click.echo(f"  {name:22s} {size/1024/1024:6.1f} MB  [{mark}]")
            for line in _wrap(purpose, 74):
                click.echo(f"      {line}")
            click.echo("")
        return

    try:
        written = optional_data.fetch(
            datasets or None, revision=revision, progress=click.echo)
    except ValueError as error:
        click.echo(f"Error: {error}", err=True)
        sys.exit(1)
    except Exception as error:
        click.echo(f"Error: download failed: {error}", err=True)
        sys.exit(1)

    if written:
        click.echo(f"\nFetched {len(written)} file(s) into "
                   f"{optional_data.cache_dir()}")
    else:
        click.echo("Everything requested is already present.")


def _wrap(text: str, width: int):
    """Wrap text to a width, for the dataset listing."""
    import textwrap
    return textwrap.wrap(text, width)


class _GenerateByDefault(click.Group):
    """A group whose default command is generation.

    `synthea` has always been a single command: `synthea -p 100`,
    `synthea --version`, `synthea Massachusetts Boston`. Turning it into a
    plain group would break every one of those, so anything that is not a
    known sub-command is handed to the generator instead.
    """

    def parse_args(self, ctx, args):
        if args and args[0] not in self.commands:
            args = ['generate'] + list(args)
        elif not args:
            args = ['generate']
        return super().parse_args(ctx, args)

    def format_help(self, ctx, formatter):
        # Show the generator's own options, since that is what most people
        # invoke, then list the sub-commands.
        main.format_help(ctx, formatter)
        formatter.write_paragraph()
        with formatter.section('Commands'):
            formatter.write_dl([
                (name, (command.get_short_help_str() or ''))
                for name, command in sorted(self.commands.items())
                if name != 'generate'
            ])


@click.group(cls=_GenerateByDefault)
def cli():
    """Synthea Patient Generator."""


cli.add_command(main, name='generate')
cli.add_command(fetch_data)


if __name__ == '__main__':
    cli()