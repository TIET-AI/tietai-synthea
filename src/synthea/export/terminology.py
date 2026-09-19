"""Code systems and units, mapped to what FHIR requires.

The module JSON names code systems the way a person would — ``SNOMED-CT``,
``RxNorm``, ``LOINC`` — but FHIR requires ``Coding.system`` to be a URI, and a
server cannot resolve ``"SNOMED-CT"`` to anything. Exporting the short name
means every code in the bundle is uninterpretable, even though the code itself
is correct.

The same applies to units: ``Quantity.code`` is meant to be a UCUM symbol, and
the modules write display units like ``mg/dL`` or ``years``.
"""

from __future__ import annotations

import logging
from typing import Optional, Set

logger = logging.getLogger(__name__)

#: Code system names as the modules write them, mapped to their canonical URI.
CODE_SYSTEMS = {
    'snomed-ct': 'http://snomed.info/sct',
    'snomed': 'http://snomed.info/sct',
    'loinc': 'http://loinc.org',
    'rxnorm': 'http://www.nlm.nih.gov/research/umls/rxnorm',
    'cvx': 'http://hl7.org/fhir/sid/cvx',
    'nubc': 'https://www.nubc.org/CodeSystem/RevenueCodes',
    'icd10-cm': 'http://hl7.org/fhir/sid/icd-10-cm',
    'icd10': 'http://hl7.org/fhir/sid/icd-10',
    'icd9-cm': 'http://hl7.org/fhir/sid/icd-9-cm',
    'cpt': 'http://www.ama-assn.org/go/cpt',
    'ndc': 'http://hl7.org/fhir/sid/ndc',
    'dicom-dcm': 'http://dicom.nema.org/resources/ontology/DCM',
    'dicom-sop': 'urn:ietf:rfc:3986',
    'ucum': 'http://unitsofmeasure.org',
}

#: Display units as the modules write them, mapped to UCUM symbols. Units not
#: listed are passed through: many modules already use valid UCUM.
UCUM_UNITS = {
    '%': '%',
    'percent': '%',
    'mg/dl': 'mg/dL',
    'mg/dL': 'mg/dL',
    'g/dl': 'g/dL',
    'mmol/l': 'mmol/L',
    'meq/l': 'meq/L',
    'mm[hg]': 'mm[Hg]',
    'mmhg': 'mm[Hg]',
    'mm hg': 'mm[Hg]',
    'kg/m2': 'kg/m2',
    'kg/m^2': 'kg/m2',
    'kg': 'kg',
    'g': 'g',
    'lbs': '[lb_av]',
    'cm': 'cm',
    'in': '[in_i]',
    'years': 'a',
    'year': 'a',
    'months': 'mo',
    'month': 'mo',
    'weeks': 'wk',
    'week': 'wk',
    'days': 'd',
    'day': 'd',
    'hours': 'h',
    'hour': 'h',
    'minutes': 'min',
    'minute': 'min',
    '/min': '/min',
    'beats/min': '/min',
    'breaths/min': '/min',
    '{score}': '{score}',
    'ml': 'mL',
    'ml/min': 'mL/min',
    'ml/min/{1.73_m2}': 'mL/min/{1.73_m2}',
    'u/l': 'U/L',
    'k/ul': '10*3/uL',
    '10*3/ul': '10*3/uL',
    '10*6/ul': '10*6/uL',
    'fl': 'fL',
    'pg': 'pg',
    'ng/ml': 'ng/mL',
    'ug/dl': 'ug/dL',
    'iu/l': 'IU/L',
}

#: Systems already reported as unrecognised, so each is logged once.
_WARNED_SYSTEMS: Set[str] = set()


def system_uri(system: Optional[str]) -> str:
    """The canonical URI for a code system name.

    An unrecognised name is passed through when it already looks like a URI,
    and otherwise reported once and turned into a URN so the value is at least
    syntactically a URI rather than a bare word.
    """
    if not system:
        return 'http://terminology.hl7.org/CodeSystem/data-absent-reason'

    text = str(system).strip()
    known = CODE_SYSTEMS.get(text.lower())
    if known:
        return known

    if '://' in text or text.startswith('urn:'):
        return text

    if text not in _WARNED_SYSTEMS:
        _WARNED_SYSTEMS.add(text)
        logger.warning(
            "Unrecognised code system %r; exporting it as a URN. Add it to "
            "synthea.export.terminology.CODE_SYSTEMS to map it properly.", text,
        )
    return f"urn:oid:unknown:{text.replace(' ', '-').lower()}"


def ucum_code(unit: Optional[str]) -> Optional[str]:
    """The UCUM symbol for a display unit, or None when there is no unit."""
    if unit is None:
        return None
    text = str(unit).strip()
    if not text:
        return None
    return UCUM_UNITS.get(text.lower(), text)
