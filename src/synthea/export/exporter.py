"""
Base exporter module for Synthea.

This module provides the base classes and orchestration for exporting
patient data to various formats.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Any, Optional, List, TYPE_CHECKING
import json
import logging
import os

if TYPE_CHECKING:
    from synthea.world.person import Person
    from synthea.helpers.config import Config


logger = logging.getLogger(__name__)


class FHIRPushError(RuntimeError):
    """A strict FHIR push failed; never report CLI success."""


class GenomicsPackError(RuntimeError):
    """A genomics-pack failure; it must stop the run, never be swallowed."""


class PatientExporter(ABC):
    """Base class for exporters that export individual patients."""
    
    @abstractmethod
    def export(self, person: 'Person', time: int) -> Optional[str]:
        """
        Export a single patient.
        
        Args:
            person: The person to export
            time: The current simulation time
            
        Returns:
            Path to exported file, or None if not exported
        """
        pass


class PostCompletionExporter(ABC):
    """Base class for exporters that run after all patients are generated."""
    
    @abstractmethod
    def export(self, generator, stats: Dict[str, Any]):
        """
        Export aggregate data after generation completes.
        
        Args:
            generator: The generator instance
            stats: Generation statistics
        """
        pass


class Exporter:
    """Main exporter orchestrator."""
    
    def __init__(self, config: 'Config', locale=None):
        """
        Initialize the exporter.
        
        Args:
            config: Configuration object
        """
        self.config = config
        # The locale pack decides the default export profile, and whether
        # US-specific patient extensions belong at all.
        self.locale = locale
        self.base_dir = Path(config.get_string('exporter.baseDirectory', './output'))
        
        # Create output directory
        self.base_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize exporters based on configuration
        # Deceased patients are dropped at export rather than never
        # generated, so the population statistics still count them.
        self.only_living = config.get_bool('exporter.only_living', False)

        self.patient_exporters: List[PatientExporter] = []
        self.post_exporters: List[PostCompletionExporter] = []
        
        self._init_exporters()
        from synthea.export.run_output import RunOutput
        self.run_output = RunOutput(config, self.base_dir, locale)
    
    #: Exporters named in the configuration that do not exist yet, and the
    #: issue tracking each. Enabling one used to either raise an ImportError
    #: from deep inside start-up (CSV) or silently do nothing (CCDA), both of
    #: which leave the operator believing they have output they do not have.
    UNIMPLEMENTED = {
        'exporter.ccda.export': (
            'C-CDA', 'https://github.com/TIET-AI/tietai-synthea/issues/36'),
    }

    def _init_exporters(self):
        """Initialise the enabled exporters, refusing the ones that do not exist."""
        self._reject_unimplemented()

        if self.config.get_bool('exporter.fhir.export', True):
            from synthea.export.fhir import FHIRExporter
            self.patient_exporters.append(
                FHIRExporter(self.config, self.base_dir, self.locale))

        server_url = str(self.config.get('exporter.fhir.server_url', '') or '').strip()
        if server_url:
            self.patient_exporters.append(
                FHIRServerExporter(self.config, server_url))

        if self.config.get_bool('exporter.json.export', False):
            self.patient_exporters.append(JSONExporter(self.config, self.base_dir))

        if self.config.get_bool('exporter.text.export', False):
            self.patient_exporters.append(TextExporter(self.config, self.base_dir))

        # Synthetic genomics/oncology pack (GO-61). Off by default. The
        # per-person exporter only stages descriptors; the finalizer writes the
        # pack once the whole population is known.
        if self.config.get_bool('exporter.genomics.export', False):
            from synthea.export.genomics import GenomicsExporter, GenomicsPackFinalizer
            self.patient_exporters.append(
                GenomicsExporter(self.config, self.base_dir, self.locale))
            self.post_exporters.append(
                GenomicsPackFinalizer(self.config, self.base_dir))

    def _reject_unimplemented(self):
        """Fail immediately, and clearly, for an exporter that does not exist."""
        for key, (name, issue) in self.UNIMPLEMENTED.items():
            if not self.config.get_bool(key, False):
                continue
            raise NotImplementedError(
                f"{key} is set, but the {name} exporter is not implemented in "
                f"this version. Turn it off, or follow {issue}. "
                f"Available exporters: exporter.fhir.export, exporter.json.export."
            )

    def begin_run(self):
        """Called once by the parent process before generation starts."""
        self.run_output.begin()
        for exporter in self.patient_exporters:
            begin = getattr(exporter, 'begin', None)
            if begin:
                begin()

    def export(self, person: 'Person'):
        """Export a person using all enabled exporters.

        `exporter.only_living` is applied here rather than inside each
        exporter, so a new exporter cannot forget it.
        """
        exported = not (self.only_living and not getattr(person, 'alive', True))
        self.run_output.add(person, exported=exported)
        if not exported:
            return

        for exporter in self.patient_exporters:
            try:
                exporter.export(person, 0)
            except (GenomicsPackError, FHIRPushError):
                raise
            except Exception as e:
                print(f"Error exporting with {exporter.__class__.__name__}: {e}")

    def run_post_completion(self, stats: Dict[str, Any]):
        """
        Run post-completion exporters.
        
        Args:
            stats: Generation statistics
        """
        for exporter in self.post_exporters:
            try:
                exporter.export(None, stats)
            except (GenomicsPackError, FHIRPushError):
                raise
            except Exception as e:
                print(f"Error in post-completion export: {e}")
        self.run_output.finish(stats)


class JSONExporter(PatientExporter):
    """Exports patients in native Synthea JSON format."""
    
    def __init__(self, config: 'Config', base_dir: Path):
        """
        Initialize JSON exporter.
        
        Args:
            config: Configuration object
            base_dir: Base output directory
        """
        self.config = config
        self.base_dir = base_dir
        self.output_dir = base_dir / 'json'
        self.output_dir.mkdir(exist_ok=True)
    
    def export(self, person: 'Person', time: int) -> Optional[str]:
        """Export person to JSON."""
        # Create patient data structure
        patient_data = {
            'id': person.id,
            'seed': person.seed,
            'attributes': person.attributes.copy(),
            'vital_signs': person.vital_signs.copy(),
            'symptoms': person.symptoms.copy(),
            'alive': person.alive,
        }
        
        # Convert datetime objects to strings
        for key, value in patient_data['attributes'].items():
            if hasattr(value, 'isoformat'):
                patient_data['attributes'][key] = value.isoformat()
        
        # Add health record if present
        if hasattr(person, 'record') and person.record:
            patient_data['health_record'] = person.record.to_dict()
        
        # Generate filename
        if self.config.get_bool('exporter.use_uuid_filenames', False):
            filename = f"{person.id}.json"
        else:
            first_name = person.attributes.get('first_name', 'Unknown')
            last_name = person.attributes.get('last_name', 'Person')
            filename = f"{first_name}_{last_name}_{person.id[:8]}.json"
        
        filepath = self.output_dir / filename
        
        # Write JSON file
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(patient_data, f, indent=2, default=str)
        
        return str(filepath)

class TextExporter(PatientExporter):
    """Writes each patient's clinical notes as a plain text file.

    One file per patient holding every encounter note in order, which is what
    the upstream text export produces and what a reader wants when they are
    eyeballing a record rather than loading it.
    """

    def __init__(self, config: 'Config', base_dir: Path):
        self.config = config
        self.base_dir = base_dir
        self.output_dir = base_dir / 'notes'
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def export(self, person: 'Person', time: int) -> Optional[str]:
        from synthea.world.notes import NOTE_ATTRIBUTE

        record = getattr(person, 'record', None)
        if record is None:
            return None

        sections = [
            getattr(encounter, NOTE_ATTRIBUTE)
            for encounter in record.encounters
            if getattr(encounter, NOTE_ATTRIBUTE, None)
        ]
        if not sections:
            # Notes are off, or this patient never finished an encounter.
            return None

        name = ' '.join(filter(None, [
            person.attributes.get('first_name'),
            person.attributes.get('last_name'),
        ])) or person.id

        body = f"{name}\n{'=' * len(name)}\n\n" + (
            '\n\n--------------------------------------------------\n\n'
            .join(sections))

        if self.config.get_bool('exporter.use_uuid_filenames', False):
            filename = f"{person.id}.txt"
        else:
            first_name = person.attributes.get('first_name', 'Unknown')
            last_name = person.attributes.get('last_name', 'Person')
            filename = f"{first_name}_{last_name}_{person.id[:8]}.txt"

        filepath = self.output_dir / filename
        filepath.write_text(body, encoding='utf-8')

        return str(filepath)


class FHIRServerExporter(PatientExporter):
    """POSTs each patient's bundle to a FHIR server.

    `exporter.fhir.server_url` was documented and read by nothing, so bundles
    were silently only ever written to disk. This posts them.

    Failures are reported and do not stop the run: a long generation should not
    be lost because a server went away half way through. The count of failures
    is kept so the caller can tell a clean run from a partial one.
    """

    def __init__(self, config: 'Config', server_url: str):
        self.config = config
        self.server_url = server_url.rstrip('/')
        self.timeout = float(config.get('exporter.fhir.server_timeout', 30) or 30)
        self.posted = 0
        self.failed = 0

    def export(self, person: 'Person', time: int) -> Optional[str]:
        import json as _json
        import urllib.error
        import urllib.request

        from synthea.export.fhir import FHIRExporter

        from urllib.parse import urlparse
        import time as clock
        if urlparse(self.server_url).scheme not in ('http', 'https'):
            raise ValueError('FHIR server URL must use http or https')
        exporter = FHIRExporter(self.config,
                                Path(self.config.get('exporter.baseDirectory', '.')),
                                getattr(person, 'locale', None))
        exporter.use_transaction_bundle = True
        bundle = exporter.create_bundle(person)
        bundle['type'] = 'transaction'
        # A transaction is the batch boundary: splitting a patient's bundle
        # would leave its URN references unresolved. Stable PUTs make retries
        # safe for resources without conditional-create identifiers too.
        for entry in bundle['entry']:
            resource = entry['resource']
            if not entry['request'].get('ifNoneExist'):
                entry['request'] = {'method': 'PUT',
                                    'url': resource['resourceType'] + '/' + resource['id']}
        payload = _json.dumps(bundle).encode('utf-8')
        retries = max(0, int(self.config.get('exporter.fhir.server_retries', 2)))
        delay = max(0, float(self.config.get('exporter.fhir.server_retry_delay', 0.1)))
        last_error = None
        for attempt in range(retries + 1):
            request = urllib.request.Request(
                self.server_url, data=payload,
                headers={'Content-Type': 'application/fhir+json',
                         'Accept': 'application/fhir+json'}, method='POST')
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    if hasattr(response, 'read'):
                        raw = response.read()
                        if raw:
                            result = _json.loads(raw)
                            if result.get('resourceType') == 'OperationOutcome':
                                raise FHIRPushError('FHIR server returned an OperationOutcome')
                            for entry in result.get('entry', []):
                                status = str(entry.get('response', {}).get('status', ''))
                                if status and not status.startswith('2'):
                                    raise FHIRPushError('FHIR transaction entry failed: ' + status)
                    self.posted += 1
                    return f"{self.server_url} ({response.status})"
            except urllib.error.HTTPError as error:
                last_error = error
                if error.code != 429 and not 500 <= error.code < 600:
                    break
            except (OSError, FHIRPushError, ValueError) as error:
                last_error = error
                if not isinstance(error, OSError):
                    break
            if attempt < retries:
                clock.sleep(min(10, delay * 2 ** attempt))
        self.failed += 1
        logger.error("Could not post a FHIR transaction: %s", last_error)
        if self.config.get_bool('exporter.fhir.server_fail_on_error', False):
            raise FHIRPushError('FHIR transaction failed after retries') from last_error
        return None
