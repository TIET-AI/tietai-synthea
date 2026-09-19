"""Quality-of-life scoring (QALY / DALY).

Deliberately a placeholder. The disability weights it needs ship in
``gbd_disability_weights.csv`` but the scoring itself is not implemented; it
belongs with the population reporting work in issue #44.

It exists so the engine's core-module list loads cleanly.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from synthea.engine.module import Module

if TYPE_CHECKING:  # pragma: no cover - typing only
    from synthea.world.person import Person


class QualityOfLifeModule(Module):
    """No-op until issue #44 implements scoring."""

    def __init__(self):
        super().__init__('quality_of_life')

    def process(self, person: 'Person', time: datetime) -> bool:
        return True
