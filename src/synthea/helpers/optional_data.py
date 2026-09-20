"""Reference datasets that are fetched on demand rather than bundled.

Four upstream datasets are large enough that bundling them would grow the wheel
by an order of magnitude for data most runs never touch: per-city census
demographics, veteran demographics, county FIPS codes, and the facility types a
generated patient cannot currently be sent to.

Rather than ship them or pretend they do not exist, they are declared here and
downloaded on request into a user cache:

    synthea fetch-data              # everything optional
    synthea fetch-data demographics # one dataset
    synthea fetch-data --list

Loaders look in the cache first and fall back to the bundled resources, so a
run works without the download and improves with it. Nothing downloads
implicitly: a generator run never reaches the network.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import pathlib
import urllib.request
from typing import Dict, Iterable, List, NamedTuple, Optional

logger = logging.getLogger(__name__)

#: Upstream project and the revision the bundled data was taken from. Kept in
#: step with PROVENANCE.json so fetched files match what is already bundled.
UPSTREAM_REPO = "synthetichealth/synthea"
UPSTREAM_ROOT = "src/main/resources"

#: Environment variable overriding where fetched data is cached.
CACHE_ENV = "SYNTHEA_DATA_DIR"


class Dataset(NamedTuple):
    """An optional dataset: what it is, and what it unlocks."""
    name: str
    files: List[str]
    approx_bytes: int
    purpose: str


#: The optional datasets, keyed by the name `fetch-data` accepts.
DATASETS: Dict[str, Dataset] = {
    'demographics': Dataset(
        'demographics',
        ['geography/demographics.csv'],
        25_870_455,
        'Per-city census age, sex, race and income distributions. Without it '
        'ages come from a built-in national distribution.',
    ),
    'veteran-demographics': Dataset(
        'veteran-demographics',
        ['geography/veteran_demographics.csv'],
        19_453_779,
        'Veteran population distributions, used only by the veterans modules.',
    ),
    'fipscodes': Dataset(
        'fipscodes',
        ['geography/fipscodes.csv'],
        2_984_322,
        'County FIPS codes, for linking a patient to a county.',
    ),
    'facilities': Dataset(
        'facilities',
        [
            'providers/nursing.csv',
            'providers/rehab.csv',
            'providers/home_health_agencies.csv',
            'providers/dialysis.csv',
            'providers/hospice.csv',
            'providers/ambulatory_surgical_center.csv',
            'providers/primary_care_facilities_women.csv',
        ],
        9_913_000,
        'Specialist facilities: nursing, rehabilitation, home health, dialysis, '
        'hospice and surgical centres. Hospitals, primary care and urgent care '
        'are already bundled.',
    ),
}


def cache_dir() -> pathlib.Path:
    """Where fetched datasets are stored.

    Honours ``SYNTHEA_DATA_DIR``, then ``XDG_DATA_HOME``, then the platform
    default, so a shared or read-only install still works.
    """
    override = os.environ.get(CACHE_ENV)
    if override:
        return pathlib.Path(override)

    xdg = os.environ.get('XDG_DATA_HOME')
    if xdg:
        return pathlib.Path(xdg) / 'synthea'

    if os.name == 'nt':
        base = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~')
        return pathlib.Path(base) / 'synthea' / 'data'

    return pathlib.Path(os.path.expanduser('~')) / '.local' / 'share' / 'synthea'


def cached_path(relative: str) -> Optional[pathlib.Path]:
    """The cached copy of a resource, if it has been fetched."""
    candidate = cache_dir() / relative
    return candidate if candidate.is_file() else None


def is_available(name: str) -> bool:
    """Whether every file of a dataset is present in the cache."""
    dataset = DATASETS.get(name)
    if dataset is None:
        return False
    return all(cached_path(f) is not None for f in dataset.files)


def status() -> List[tuple]:
    """(name, available, approx_bytes, purpose) for every optional dataset."""
    return [
        (d.name, is_available(d.name), d.approx_bytes, d.purpose)
        for d in DATASETS.values()
    ]


def fetch(names: Optional[Iterable[str]] = None, revision: str = 'master',
          progress=None) -> List[pathlib.Path]:
    """Download optional datasets into the cache.

    Args:
        names: Dataset names, or None for all of them.
        revision: Upstream revision to fetch from.
        progress: Optional callable taking a status string.

    Returns:
        The paths written.
    """
    wanted = list(names) if names else list(DATASETS)
    unknown = [n for n in wanted if n not in DATASETS]
    if unknown:
        raise ValueError(
            f"Unknown dataset(s): {', '.join(unknown)}. "
            f"Available: {', '.join(DATASETS)}"
        )

    target_root = cache_dir()
    written: List[pathlib.Path] = []

    for name in wanted:
        dataset = DATASETS[name]
        for relative in dataset.files:
            destination = target_root / relative
            if destination.is_file():
                if progress:
                    progress(f"  {relative} already present")
                continue

            url = (f"https://raw.githubusercontent.com/{UPSTREAM_REPO}/"
                   f"{revision}/{UPSTREAM_ROOT}/{relative}")
            if progress:
                progress(f"  fetching {relative} ...")

            destination.parent.mkdir(parents=True, exist_ok=True)
            with urllib.request.urlopen(url, timeout=300) as response:
                payload = response.read()

            # Write via a temporary file so an interrupted download never
            # leaves a truncated file that later looks cached.
            temporary = destination.with_suffix(destination.suffix + '.part')
            temporary.write_bytes(payload)
            temporary.replace(destination)

            written.append(destination)
            if progress:
                digest = hashlib.sha256(payload).hexdigest()[:12]
                progress(f"    {len(payload):,} bytes, sha256 {digest}")

    if written:
        (target_root / 'FETCHED.json').write_text(
            json.dumps({
                'source_repository': f"https://github.com/{UPSTREAM_REPO}",
                'revision': revision,
                'licence': 'Apache-2.0',
                'files': sorted(str(p.relative_to(target_root)).replace('\\', '/')
                                for p in target_root.rglob('*.csv')),
            }, indent=2) + "\n",
            encoding='utf-8',
        )

    return written
