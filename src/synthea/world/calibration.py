"""Calibration: population rates set from configuration rather than code.

Every ``calibration.<name>`` setting in ``synthea.properties`` (or a file passed
with ``-c``, which overlays it) is copied onto each patient as the attribute
``calibration.<name>`` before their life is simulated. Both kinds of module can
then read it:

- a JSON module, through an attribute-valued probability::

      "distributed_transition": [
        {"distribution": {"attribute": "calibration.pregnancy.preeclampsia",
                          "default": 0.038},
         "transition": "Develop_Pre_Eclampsia"},
        {"distribution": 1, "transition": "Week_32_Visit"}
      ]

  Probabilities are taken at face value and the last option takes the rest
  (:func:`synthea.engine.transition.select_cumulative`), so the configured
  value is exactly the probability of that branch;

- a Python core module, through :func:`calibration`.

The ``default`` in the module and the default passed to :func:`calibration`
are what applies when the setting is absent, so removing a line from the
properties file never breaks generation. Keep them equal to the bundled value.

Settings are copied per patient rather than read from a global so that a
patient carries the exact rates they were generated under, and parallel
workers need nothing but the patient.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Mapping

if TYPE_CHECKING:  # pragma: no cover - typing only
    from synthea.world.person import Person

PREFIX = 'calibration.'


def apply_calibration(person: 'Person', settings: Mapping[str, Any]) -> None:
    """Copy every ``calibration.*`` setting onto the person."""
    for key, value in settings.items():
        if isinstance(key, str) and key.startswith(PREFIX):
            person.attributes[key] = value


def calibration(person: 'Person', name: str, default: float) -> float:
    """A numeric calibration setting, ``name`` without the prefix."""
    value = person.attributes.get(PREFIX + name, default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)
