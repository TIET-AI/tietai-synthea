"""Export profiles: which implementation guide a bundle is shaped for.

Profiling used to be a single boolean, `exporter.fhir.use_us_core_ig`. That is
fine while the only audience is American, and useless the moment it is not:
a bundle for a cross-border summary needs IPS, and an EHDS consumer wants the
priority categories as separate documents.

A profile answers four questions about a bundle:

  which `meta.profile` URI each resource type carries
  whether US-specific extensions (race, ethnicity, birth sex) belong
  what shape the bundle takes - a plain collection, or a Composition-led
  document with ordered sections
  which resources are included at all

Profiles are selected in order of specificity: `exporter.fhir.profile` if set,
otherwise the locale pack's `export_profile`, otherwise US Core. That ordering
matters - a Spanish locale should produce IPS by default without the operator
having to know to ask, but an operator who does ask must win.

`none` is a real choice, not an absence: it emits valid R4 with no profile
claims at all, which is what you want when the consumer has its own.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

US_CORE = 'http://hl7.org/fhir/us/core/StructureDefinition/'
IPS = 'http://hl7.org/fhir/uv/ips/StructureDefinition/'

#: The vital signs profile is core FHIR, not US Core, and applies under any
#: profile that profiles observations at all.
VITAL_SIGNS = 'http://hl7.org/fhir/StructureDefinition/vitalsigns'


@dataclass(frozen=True)
class ExportProfile:
    """How a bundle is shaped for one implementation guide."""

    code: str
    name: str

    profiles: Dict[str, str] = field(default_factory=dict)
    """Resource type -> `meta.profile` URI."""

    vital_signs_profile: Optional[str] = None

    us_extensions: bool = False
    """Whether US Core race, ethnicity and birth-sex extensions belong.

    Off for everything except US Core. Emitting OMB race categories in a
    bundle for a country that does not record race is inventing data.
    """

    composition: bool = False
    """Whether the bundle is a document led by a Composition."""

    composition_sections: Sequence[tuple] = ()
    """`(title, loinc_code, [resource types])`, in the order they appear."""

    bundle_type: Optional[str] = None
    """Overrides the configured bundle type. A document must say `document`."""

    def profile_for(self, resource_type: str, vital_signs: bool = False
                    ) -> Optional[str]:
        """The profile URI for one resource, or None."""
        if vital_signs and self.vital_signs_profile:
            return self.vital_signs_profile
        return self.profiles.get(resource_type)


# ----------------------------------------------------------------------
# US Core - the default, and what every previous release produced
# ----------------------------------------------------------------------

US_CORE_PROFILE = ExportProfile(
    code='us-core',
    name='US Core',
    profiles={
        'Patient': US_CORE + 'us-core-patient',
        'Encounter': US_CORE + 'us-core-encounter',
        'Condition': US_CORE + 'us-core-condition-problems-health-concerns',
        'Observation': US_CORE + 'us-core-observation-lab',
        'Procedure': US_CORE + 'us-core-procedure',
        'MedicationRequest': US_CORE + 'us-core-medicationrequest',
        'Immunization': US_CORE + 'us-core-immunization',
        'Organization': US_CORE + 'us-core-organization',
        'Practitioner': US_CORE + 'us-core-practitioner',
        'PractitionerRole': US_CORE + 'us-core-practitionerrole',
        'Location': US_CORE + 'us-core-location',
        'AllergyIntolerance': US_CORE + 'us-core-allergyintolerance',
        'CarePlan': US_CORE + 'us-core-careplan',
        'CareTeam': US_CORE + 'us-core-careteam',
        'DiagnosticReport': US_CORE + 'us-core-diagnosticreport-lab',
        'Goal': US_CORE + 'us-core-goal',
        'Provenance': US_CORE + 'us-core-provenance',
        'DocumentReference': US_CORE + 'us-core-documentreference',
    },
    vital_signs_profile=VITAL_SIGNS,
    us_extensions=True,
)


# ----------------------------------------------------------------------
# International Patient Summary
# ----------------------------------------------------------------------

#: The three sections IPS requires. A summary without them is not a summary:
#: "no known allergies" is clinically meaningful and must be stated, which is
#: why these sections are emitted even when the patient has nothing in them.
IPS_REQUIRED_SECTIONS = (
    ('Problems', '11450-4', ['Condition']),
    ('Medication Summary', '10160-0',
     ['MedicationRequest', 'MedicationStatement', 'MedicationAdministration']),
    ('Allergies and Intolerances', '48765-2', ['AllergyIntolerance']),
)

IPS_OPTIONAL_SECTIONS = (
    ('Immunizations', '11369-6', ['Immunization']),
    ('Results', '30954-2', ['Observation', 'DiagnosticReport']),
    ('Procedures', '47519-4', ['Procedure']),
    ('Medical Devices', '46264-8', ['Device']),
    ('Plan of Care', '18776-5', ['CarePlan']),
)

IPS_PROFILE = ExportProfile(
    code='ips',
    name='International Patient Summary',
    profiles={
        'Patient': IPS + 'Patient-uv-ips',
        'Condition': IPS + 'Condition-uv-ips',
        'AllergyIntolerance': IPS + 'AllergyIntolerance-uv-ips',
        'MedicationRequest': IPS + 'MedicationRequest-uv-ips',
        'MedicationStatement': IPS + 'MedicationStatement-uv-ips',
        'Immunization': IPS + 'Immunization-uv-ips',
        'Procedure': IPS + 'Procedure-uv-ips',
        'DiagnosticReport': IPS + 'DiagnosticReport-uv-ips',
        'Device': IPS + 'Device-uv-ips',
        'Organization': IPS + 'Organization-uv-ips',
        'Practitioner': IPS + 'Practitioner-uv-ips',
        'PractitionerRole': IPS + 'PractitionerRole-uv-ips',
        'Composition': IPS + 'Composition-uv-ips',
    },
    vital_signs_profile=VITAL_SIGNS,
    us_extensions=False,
    composition=True,
    composition_sections=IPS_REQUIRED_SECTIONS + IPS_OPTIONAL_SECTIONS,
    bundle_type='document',
)


# ----------------------------------------------------------------------
# EHDS priority categories
# ----------------------------------------------------------------------

#: The five categories the European Health Data Space names. A consumer asks
#: for one of them, not for "a patient", so each is its own document.
EHDS_CATEGORIES = (
    ('patient-summary', 'Patient Summary', '60591-5',
     IPS_REQUIRED_SECTIONS + IPS_OPTIONAL_SECTIONS),
    ('eprescription', 'ePrescription', '57833-6',
     (('Prescriptions', '10160-0', ['MedicationRequest']),)),
    ('laboratory-result', 'Laboratory Result Report', '11502-2',
     (('Results', '30954-2', ['Observation', 'DiagnosticReport']),)),
    ('medical-imaging', 'Medical Imaging Report', '18748-4',
     (('Imaging', '18748-4', ['ImagingStudy']),)),
    ('discharge-report', 'Discharge Report', '18842-5',
     (('Hospital Course', '8648-8', ['Encounter', 'Condition', 'Procedure']),)),
)

EHDS_PROFILE = ExportProfile(
    code='ehds',
    name='EHDS priority categories',
    # EHDS builds on IPS, so the resource profiles are the same. What differs
    # is that one patient produces five documents rather than one bundle.
    profiles=dict(IPS_PROFILE.profiles),
    vital_signs_profile=VITAL_SIGNS,
    us_extensions=False,
    composition=True,
    composition_sections=IPS_REQUIRED_SECTIONS + IPS_OPTIONAL_SECTIONS,
    bundle_type='document',
)


NO_PROFILE = ExportProfile(
    code='none',
    name='Plain FHIR R4',
    profiles={},
    us_extensions=False,
)


_PROFILES = {
    profile.code: profile
    for profile in (US_CORE_PROFILE, IPS_PROFILE, EHDS_PROFILE, NO_PROFILE)
}

DEFAULT_PROFILE = 'us-core'


def get(code: Optional[str] = None) -> ExportProfile:
    """The profile for a code.

    An unknown profile falls back to US Core with a warning rather than
    raising: a typo in a config file should not lose a long generation, and
    the bundle is still valid FHIR either way. That is the opposite of the
    locale decision, where the wrong answer is silently plausible data.
    """
    if not code:
        return _PROFILES[DEFAULT_PROFILE]

    wanted = str(code).strip().lower()
    profile = _PROFILES.get(wanted)
    if profile is not None:
        return profile

    logger.warning(
        "Unknown export profile %r; using %s. Available: %s",
        code, DEFAULT_PROFILE, ', '.join(sorted(_PROFILES)),
    )
    return _PROFILES[DEFAULT_PROFILE]


def available() -> List[ExportProfile]:
    return [_PROFILES[code] for code in sorted(_PROFILES)]


def resolve(config, locale_pack=None) -> ExportProfile:
    """Which profile to use, in order of specificity.

    An explicit setting beats the locale's default, which beats US Core. A
    Spanish locale should produce IPS without the operator having to know to
    ask, but an operator who does ask must win.

    `exporter.fhir.use_us_core_ig = false` is still honoured, because it is
    what every existing configuration file says. It means "no profile", which
    is what it always meant.
    """
    explicit = config.get('exporter.fhir.profile')
    if explicit:
        return get(explicit)

    if not config.get_bool('exporter.fhir.use_us_core_ig', True):
        return NO_PROFILE

    if locale_pack is not None and getattr(locale_pack, 'export_profile', None):
        return get(locale_pack.export_profile)

    return _PROFILES[DEFAULT_PROFILE]
