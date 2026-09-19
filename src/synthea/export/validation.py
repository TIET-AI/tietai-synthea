"""Validate exported bundles against the FHIR R4 specification.

The exporter hand-builds dictionaries, so nothing stopped it producing
resources that no FHIR server would accept: encounter classes that were not
ActCode values, JSON nulls where a field should be absent, dateTimes with no
timezone, quantities whose ``code`` was a display unit rather than a UCUM
symbol, and ``Coding.system`` values like ``"SNOMED-CT"`` that are not URIs.

This validates every entry in a bundle against the R4B models from
``fhir.resources`` — already a dependency — so those mistakes fail a test
instead of failing in a customer's server.

It is deliberately generic: it looks the model up by ``resourceType`` rather
than knowing the list, so a newly exported resource type is covered the moment
it appears without anyone remembering to extend this.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class ValidationIssue:
    """One resource that failed validation."""

    def __init__(self, index: int, resource_type: str, resource_id: str,
                 message: str):
        self.index = index
        self.resource_type = resource_type
        self.resource_id = resource_id
        self.message = message

    def __str__(self) -> str:
        return (f"entry[{self.index}] {self.resource_type}/{self.resource_id}: "
                f"{self.message}")

    __repr__ = __str__


def available() -> bool:
    """Whether the validation models can be imported."""
    try:
        import fhir.resources.R4B  # noqa: F401
    except ImportError:
        return False
    return True


def _model_for(resource_type: str):
    """The R4B model class for a resource type, or None if unknown."""
    import importlib

    module_name = f"fhir.resources.R4B.{resource_type.lower()}"
    try:
        module = importlib.import_module(module_name)
    except ImportError:
        return None
    return getattr(module, resource_type, None)


def validate_resource(resource: Dict[str, Any]) -> Optional[str]:
    """Validate one resource; returns an error message, or None when valid."""
    resource_type = resource.get('resourceType')
    if not resource_type:
        return "resource has no resourceType"

    model = _model_for(resource_type)
    if model is None:
        return f"unknown resource type {resource_type!r}"

    try:
        model.model_validate(resource)
    except AttributeError:  # pragma: no cover - older pydantic
        try:
            model.parse_obj(resource)
        except Exception as error:
            return str(error)
    except Exception as error:
        return str(error)

    return None


def validate_bundle(bundle: Dict[str, Any]) -> List[ValidationIssue]:
    """Validate every entry in a bundle.

    Entries are validated individually rather than as one Bundle so that a
    single bad resource reports its own position and type, instead of a single
    opaque failure for the whole bundle.
    """
    issues: List[ValidationIssue] = []

    for index, entry in enumerate(bundle.get('entry', [])):
        resource = entry.get('resource')
        if not isinstance(resource, dict):
            issues.append(ValidationIssue(index, '?', '?', "entry has no resource"))
            continue

        message = validate_resource(resource)
        if message:
            issues.append(ValidationIssue(
                index,
                resource.get('resourceType', '?'),
                resource.get('id', '?'),
                message,
            ))

    return issues


def find_nulls(node: Any, path: str = '') -> List[str]:
    """Paths of every JSON null in a structure.

    FHIR has no null: an absent value is an absent field. A null is how an
    optional period end or an unset reason used to be serialised, and it makes
    a resource invalid.
    """
    found: List[str] = []

    if isinstance(node, dict):
        for key, value in node.items():
            here = f"{path}.{key}" if path else key
            if value is None:
                found.append(here)
            else:
                found.extend(find_nulls(value, here))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            here = f"{path}[{index}]"
            if value is None:
                found.append(here)
            else:
                found.extend(find_nulls(value, here))

    return found


def check_bundle(bundle: Dict[str, Any]) -> Tuple[List[ValidationIssue], List[str]]:
    """Validate a bundle and report any nulls in it."""
    return validate_bundle(bundle), find_nulls(bundle)
