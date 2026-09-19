"""Insurance coverage.

Deliberately a placeholder. Payer selection, coverage history, costs, claims and
explanations of benefit are tracked in issue #39, and the payer and cost
reference data they need is not bundled yet (#37).

It exists so the engine's core-module list loads cleanly and so the work has an
obvious home, rather than being silently absent as it was before.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from synthea.engine.module import Module

if TYPE_CHECKING:  # pragma: no cover - typing only
    from synthea.world.person import Person


class HealthInsuranceModule(Module):
    """No-op until issue #39 implements coverage."""

    def __init__(self):
        super().__init__('health_insurance')

    def process(self, person: 'Person', time: datetime) -> bool:
        return True
