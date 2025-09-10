"""
Configuration management for Synthea.

This module handles loading and managing configuration settings from
properties files and command-line overrides.
"""

import configparser
import json
from pathlib import Path
from typing import Dict, Any, Optional, Union
import os


class Config:
    """Manages Synthea configuration settings."""
    
    def __init__(self):
        """Initialize configuration."""
        self.settings: Dict[str, Any] = {}
        self._load_defaults()
    
    def _load_defaults(self):
        """Load default configuration values."""
        self.settings = {
            # Exporter settings
            'exporter.baseDirectory': './output/',
            'exporter.use_uuid_filenames': False,
            'exporter.subfolders_by_id_substring': False,
            'exporter.years_of_history': 10,
            
            # FHIR exporter
            'exporter.fhir.export': True,
            'exporter.fhir.bulk_data': False,
            'exporter.fhir.transaction_bundle': True,
            'exporter.fhir.use_shr_extensions': False,
            'exporter.fhir.use_us_core_ig': True,
            
            # CSV exporter
            'exporter.csv.export': False,
            'exporter.csv.append_mode': False,
            'exporter.csv.folder_per_run': False,
            
            # CCDA exporter
            'exporter.ccda.export': False,
            
            # JSON exporter
            'exporter.json.export': False,
            
            # Generator settings
            'generate.default_population': 1,
            'generate.thread_pool_size': 1,
            'generate.log_patients.detail': 'simple',
            'generate.timestep': 604800000,  # 1 week in milliseconds
            'generate.database_type': 'in-memory',
            
            # Module settings
            'generate.only_dead_patients': False,
            'generate.max_attempts_to_keep_patient': 1000,
            'generate.demographics.default_file': 'geography/demographics.csv',
            
            # Lifecycle settings
            'lifecycle.death_by_natural_causes': True,
            
            # Provider settings
            'provider.default_file': 'providers/providers.csv',
            
            # Payer settings
            'payer.default_file': 'payers/payers.csv',
            
            # Costs
            'generate.costs.default_procedure_cost': 500.0,
            'generate.costs.default_medication_cost': 255.0,
            'generate.costs.default_encounter_cost': 125.0,
            'generate.costs.default_immunization_cost': 136.0,
            
            # Clinical note settings
            'generate.clinical_notes': False,
        }
    
    def load(self, filepath: Optional[str] = None):
        """
        Load configuration from a properties file.
        
        Args:
            filepath: Path to properties file (defaults to synthea.properties)
        """
        if filepath is None:
            # Search for properties file in common locations
            search_paths = [
                Path('synthea.properties'),
                Path('src/main/resources/synthea.properties'),
                Path('resources/synthea.properties'),
                Path('../synthea.properties'),
            ]
            
            for path in search_paths:
                if path.exists():
                    filepath = str(path)
                    break
        
        if filepath and Path(filepath).exists():
            self._load_properties_file(filepath)
    
    def _load_properties_file(self, filepath: str):
        """Load a Java-style properties file."""
        # Properties files are similar to INI but without sections
        # We'll read them line by line
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    
                    # Skip comments and empty lines
                    if not line or line.startswith('#') or line.startswith('!'):
                        continue
                    
                    # Handle line continuations
                    while line.endswith('\\'):
                        line = line[:-1] + next(f).strip()
                    
                    # Split on first = or :
                    if '=' in line:
                        key, value = line.split('=', 1)
                    elif ':' in line:
                        key, value = line.split(':', 1)
                    else:
                        continue
                    
                    key = key.strip()
                    value = value.strip()
                    
                    # Convert value to appropriate type
                    self.settings[key] = self._parse_value(value)
        
        except Exception as e:
            print(f"Warning: Could not load properties file {filepath}: {e}")
    
    def _parse_value(self, value: str) -> Any:
        """Parse a string value to appropriate type."""
        # Remove quotes if present
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        elif value.startswith("'") and value.endswith("'"):
            value = value[1:-1]
        
        # Try to parse as boolean
        if value.lower() == 'true':
            return True
        elif value.lower() == 'false':
            return False
        
        # Try to parse as number
        try:
            if '.' in value:
                return float(value)
            else:
                return int(value)
        except ValueError:
            pass
        
        # Return as string
        return value
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        Get a configuration value.
        
        Args:
            key: Configuration key
            default: Default value if key not found
            
        Returns:
            Configuration value or default
        """
        return self.settings.get(key, default)
    
    def set(self, key: str, value: Any):
        """
        Set a configuration value.
        
        Args:
            key: Configuration key
            value: Value to set
        """
        self.settings[key] = value
    
    def get_bool(self, key: str, default: bool = False) -> bool:
        """
        Get a boolean configuration value.
        
        Args:
            key: Configuration key
            default: Default value if key not found
            
        Returns:
            Boolean value
        """
        value = self.get(key, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ('true', 'yes', '1', 'on')
        return bool(value)
    
    def get_int(self, key: str, default: int = 0) -> int:
        """
        Get an integer configuration value.
        
        Args:
            key: Configuration key
            default: Default value if key not found
            
        Returns:
            Integer value
        """
        value = self.get(key, default)
        try:
            return int(value)
        except (ValueError, TypeError):
            return default
    
    def get_float(self, key: str, default: float = 0.0) -> float:
        """
        Get a float configuration value.
        
        Args:
            key: Configuration key
            default: Default value if key not found
            
        Returns:
            Float value
        """
        value = self.get(key, default)
        try:
            return float(value)
        except (ValueError, TypeError):
            return default
    
    def get_string(self, key: str, default: str = '') -> str:
        """
        Get a string configuration value.
        
        Args:
            key: Configuration key
            default: Default value if key not found
            
        Returns:
            String value
        """
        value = self.get(key, default)
        return str(value) if value is not None else default
    
    def override_with_args(self, args: Dict[str, Any]):
        """
        Override configuration with command-line arguments.
        
        Args:
            args: Dictionary of command-line arguments
        """
        for key, value in args.items():
            if key.startswith('--'):
                # Remove -- prefix
                key = key[2:]
                self.set(key, value)
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Get all settings as a dictionary.
        
        Returns:
            Dictionary of all settings
        """
        return self.settings.copy()
    
    def save(self, filepath: str):
        """
        Save configuration to a properties file.
        
        Args:
            filepath: Path to save properties file
        """
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write("# Synthea Configuration File\n")
            f.write("# Generated by Synthea Python\n\n")
            
            # Group settings by prefix
            grouped = {}
            for key, value in sorted(self.settings.items()):
                prefix = key.split('.')[0] if '.' in key else 'general'
                if prefix not in grouped:
                    grouped[prefix] = []
                grouped[prefix].append((key, value))
            
            # Write grouped settings
            for prefix, items in sorted(grouped.items()):
                f.write(f"\n# {prefix.title()} Settings\n")
                for key, value in items:
                    # Convert value to string
                    if isinstance(value, bool):
                        value_str = 'true' if value else 'false'
                    else:
                        value_str = str(value)
                    
                    f.write(f"{key} = {value_str}\n")