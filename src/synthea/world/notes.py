"""Clinical notes for finished encounters.

`templates/notes/note.ftl` shipped from the Java port and was never used, so
generated records had no free text at all. Every real encounter leaves a note
behind, and the platform's consult, report and document-parsing flows are all
fed by free text, so a record without notes cannot exercise any of them.

The FreeMarker template is ported to Jinja2 (already a dependency). The port is
not mechanical: FreeMarker's built-ins have no Jinja equivalents, so the
sentence-level decisions — how an age reads, which social-history clauses
apply — are made here in Python and the template is left to do layout. That
also makes those decisions testable without rendering.

Notes are written once per finished encounter, after the simulation has ended,
so that "active at the time of the visit" can be resolved against the finished
record rather than guessed at export time.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

from synthea.helpers.resources import resource_path

logger = logging.getLogger(__name__)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from synthea.world.health_record import Encounter
    from synthea.world.person import Person

#: LOINC code for a note written at a visit. The same code the FHIR
#: DocumentReference and the text export both use.
NOTE_CODE = '34117-2'
NOTE_DISPLAY = 'History and physical note'

#: Attribute on an Encounter holding the rendered note.
NOTE_ATTRIBUTE = 'note_text'

_TEMPLATE_NAME = 'note.md.j2'

#: Set by :func:`set_post_processor`. An integration can replace the rendered
#: text — a language model rewriting it in a clinician's voice, say — without
#: this package taking a dependency on whatever does it.
_post_processor: Optional[Callable[[str, 'Person', 'Encounter'], str]] = None


def set_post_processor(
        processor: Optional[Callable[[str, 'Person', 'Encounter'], str]]) -> None:
    """Install a hook that rewrites each note after it is rendered.

    The hook receives the rendered text, the patient and the encounter, and
    returns replacement text. Nothing in this repository calls out to such a
    service; this is the seam for something that does.
    """
    global _post_processor
    _post_processor = processor


def _environment():
    """The Jinja environment, built once."""
    global _env
    if _env is None:
        from jinja2 import Environment, FileSystemLoader, select_autoescape

        _env = Environment(
            loader=FileSystemLoader(str(resource_path('templates', 'notes'))),
            autoescape=select_autoescape(enabled_extensions=(), default=False),
            trim_blocks=True,
            lstrip_blocks=False,
            keep_trailing_newline=True,
        )
    return _env


_env = None


# ----------------------------------------------------------------------
# Writing
# ----------------------------------------------------------------------

def write_notes(person: 'Person') -> int:
    """Write a note onto every finished encounter. Returns how many."""
    written = 0
    for encounter in person.record.encounters:
        if encounter.end_time is None:
            continue
        text = note_for(person, encounter)
        if text:
            setattr(encounter, NOTE_ATTRIBUTE, text)
            written += 1
    return written


def note_for(person: 'Person', encounter: 'Encounter') -> Optional[str]:
    """Render one encounter's note, or None if it could not be rendered."""
    try:
        template = _environment().get_template(_TEMPLATE_NAME)
        text = template.render(**context_for(person, encounter))
    except Exception:  # pragma: no cover - never fail a run over a note
        logger.warning("Could not render a clinical note", exc_info=True)
        return None

    text = _tidy(text)

    if _post_processor is not None:
        try:
            text = _post_processor(text, person, encounter)
        except Exception:  # pragma: no cover - a bad hook must not lose the note
            logger.warning("Note post-processor failed; keeping the rendered "
                           "note", exc_info=True)

    return text


def _tidy(text: str) -> str:
    """Collapse the blank lines a conditional template inevitably leaves."""
    lines = [line.rstrip() for line in text.splitlines()]
    tidied: List[str] = []
    for line in lines:
        if not line and tidied and not tidied[-1]:
            continue
        tidied.append(line)
    return '\n'.join(tidied).strip() + '\n'


# ----------------------------------------------------------------------
# Context
# ----------------------------------------------------------------------

def context_for(person: 'Person', encounter: 'Encounter') -> Dict[str, Any]:
    """Everything the template needs, decided here rather than in markup."""
    time = encounter.time
    age = person.age_at(time)

    return {
        'date': time.strftime('%Y-%m-%d'),
        'history_of_present_illness': history_of_present_illness(person, time),
        'social_history': social_history(person, age),
        'complaints': _displays(encounter.conditions),
        'active_allergies': _active_displays(person.record.allergies, time),
        'active_medications': _active_displays(person.record.medications, time),
        'vitals': _vitals(encounter),
        'conditions': _displays(encounter.conditions),
        # Allergies are not bucketed onto an Encounter, so the ones newly
        # recorded at this visit are found by their onset time.
        'allergies': _displays(_started_at(person.record.allergies, encounter)),
        'immunizations': _displays(encounter.immunizations),
        'procedures': _displays(encounter.procedures),
        'reports': _displays(encounter.reports),
        'medications': _displays(encounter.medications),
        'careplans': _displays(encounter.careplans),
    }


def history_of_present_illness(person: 'Person', time: datetime) -> str:
    """The opening sentence, and the problem list behind it."""
    who = person.attributes.get('first_name') or 'The patient'
    ethnicity = _humanise(person.attributes.get('ethnicity', ''))
    race = _humanise(person.attributes.get('race', ''))
    sex = 'female' if _gender(person) == 'F' else 'male'

    descriptors = ' '.join(filter(None, [ethnicity, race, sex]))
    sentence = f"{who} is a {age_phrase(person, time)} {descriptors}."

    active = _active_displays(person.record.conditions, time)
    if active:
        sentence += f" Patient has a history of {_join(active)}."

    return sentence


def social_history(person: 'Person', age: float) -> List[str]:
    """The social-history sentences that apply to this patient."""
    sentences = [
        _marital_sentence(person, age),
        _smoking_sentence(person, age),
        _socioeconomic_sentence(person),
        _education_sentence(person, age),
        f"Patient currently has {_insurance(person)}.",
    ]
    return [sentence for sentence in sentences if sentence]


def _join(items: List[str]) -> str:
    """A comma list an English reader would accept."""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ', '.join(items[:-1]) + f" and {items[-1]}"


def age_phrase(person: 'Person', time: datetime) -> str:
    """How a clinician would write the age: years, else months, else newborn.

    Calendar arithmetic, not `age_at`: that divides days by 365.25, so a
    patient on their first birthday comes out at 0.9993 years and would be
    written up as eleven months old.
    """
    born = person.attributes.get('birth_date')
    if born is None:
        return 'patient of unknown age'
    if isinstance(born, str):
        born = datetime.fromisoformat(born)

    years = time.year - born.year - (
        (time.month, time.day) < (born.month, born.day))
    if years >= 1:
        return f"{years} year-old"

    months = (time.year - born.year) * 12 + time.month - born.month
    if time.day < born.day:
        months -= 1
    if months >= 1:
        return f"{months} month-old"

    return "newborn"


def _gender(person: 'Person') -> str:
    return str(person.attributes.get('gender', '')).strip().upper()[:1]


def _humanise(value: Any) -> str:
    return str(value or '').replace('_', ' ').strip()


def _displays(entries) -> List[str]:
    """The display text of each entry's first code, lower-cased and unique."""
    seen: List[str] = []
    for entry in entries or []:
        if not entry.codes:
            continue
        display = (entry.codes[0].display or '').strip().lower()
        if display and display not in seen:
            seen.append(display)
    return seen


def _active_displays(entries, time: datetime) -> List[str]:
    """Entries that had started and had not ended at the time of the visit."""
    active = [
        entry for entry in entries or []
        if entry.time <= time
        and (getattr(entry, 'end_time', None) is None or entry.end_time > time)
    ]
    return _displays(active)


def _started_at(entries, encounter: 'Encounter') -> List[Any]:
    """Entries that began during this visit."""
    end = encounter.end_time or encounter.time
    return [entry for entry in entries or []
            if encounter.time <= entry.time <= end]


def _vitals(encounter: 'Encounter') -> List[str]:
    """The vital signs recorded at this visit, one finished line each.

    A visit can record the same vital more than once — a repeat blood pressure,
    or a panel recorded alongside its components — and a note that lists height
    twice reads like a bug. The last value for each code wins, which is what a
    clinician would have written down.
    """
    from synthea.world.vitals import VITAL_CODES

    wanted = {spec['code'].code for spec in VITAL_CODES.values()}
    latest: Dict[str, str] = {}

    for observation in encounter.observations or []:
        if not observation.codes or observation.codes[0].code not in wanted:
            continue
        value = getattr(observation, 'value', None)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue

        code = observation.codes[0]
        unit = getattr(observation, 'unit', None) or ''
        latest[code.code] = (
            f"{code.display}: {round(float(value), 1)}"
            + (f" {unit}" if unit else ''))

    return list(latest.values())


# ----------------------------------------------------------------------
# Social history
# ----------------------------------------------------------------------

def _marital_sentence(person: 'Person', age: float) -> str:
    if age <= 18:
        return ''
    status = person.attributes.get('marital_status')
    if isinstance(status, dict):
        status = status.get('code')
    if not status:
        return ''
    return ('Patient is married.' if str(status).upper().startswith('M')
            else 'Patient is single.')


def _smoking_sentence(person: 'Person', age: float) -> str:
    if age <= 16:
        return ''

    alcoholic = bool(person.attributes.get('alcoholic'))
    if person.attributes.get('smoker'):
        clause = 'Patient is an active smoker'
    elif person.attributes.get('quit_smoking_age') is not None:
        clause = ("Patient quit smoking at age "
                  f"{person.attributes['quit_smoking_age']}")
    else:
        clause = 'Patient has never smoked'

    return clause + (' and is an alcoholic.' if alcoholic else '.')


def _socioeconomic_sentence(person: 'Person') -> str:
    status = person.attributes.get('socioeconomic_status')
    if not status:
        return ''
    return (f"Patient comes from a {_humanise(status).lower()} socioeconomic "
            "background.")


#: How the education attribute reads in a note.
_EDUCATION = {
    'less_than_hs': 'Patient did not finish high school.',
    'hs_degree': 'Patient has a high school education.',
    'some_college': 'Patient has completed some college courses.',
    'bs_degree': 'Patient is a college graduate.',
}


def _education_sentence(person: 'Person', age: float) -> str:
    if age < 18:
        return ''
    return _EDUCATION.get(str(person.attributes.get('education', '')), '')


def _insurance(person: 'Person') -> str:
    """How the patient's cover reads in a note."""
    coverage = person.attributes.get('current_coverage')
    if coverage is None:
        return 'no insurance'
    if getattr(coverage, 'plan', None) is None:
        return 'no insurance'
    return coverage.plan.payer.name
