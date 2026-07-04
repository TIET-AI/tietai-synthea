"""Locate Synthea's bundled data resources.

Resource files (disease modules, geography, names, growth charts, ...) ship as
package data under ``synthea/resources``. This resolver finds that directory
whether Synthea runs from an installed wheel or a source checkout, so the data
loaders no longer depend on the current working directory.
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path


def resources_root() -> Path:
    """Return the base directory of Synthea's bundled resources.

    Prefers the ``resources`` directory packaged inside ``synthea`` (works for
    installed wheels and editable/source checkouts); falls back to a
    ``resources`` directory in the current working directory.
    """
    try:
        packaged = Path(str(resources.files("synthea"))) / "resources"
        if packaged.is_dir():
            return packaged
    except (ModuleNotFoundError, TypeError, ValueError):
        pass
    return Path("resources")


def resource_path(*parts: str) -> Path:
    """Return the path to a bundled resource under :func:`resources_root`.

    Example::

        resource_path("modules")               # .../synthea/resources/modules
        resource_path("payers", "payers.csv")  # .../synthea/resources/payers/payers.csv
    """
    return resources_root().joinpath(*parts)
