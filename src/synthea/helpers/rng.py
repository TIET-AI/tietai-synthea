"""Deterministic random-number helpers.

Synthea's output must be reproducible: the same population seed and the same
module set have to produce the same patients, on one thread or many. That only
holds if every random draw comes from a generator owned by the person being
simulated, and if each person's seed is derived from the population seed by a
pure function of ``(seed, index)``.

This module provides that derivation. It deliberately does not use Python's
``hash()`` (salted per process) or ``seed + index`` (adjacent seeds produce
correlated streams for small integers); it hashes the pair with SHA-256 and
takes 64 bits.
"""

from __future__ import annotations

import hashlib
import random
from typing import Optional

#: Width of a derived seed, in bits.
SEED_BITS = 64

#: Source of entropy for unseeded runs. Deliberately independent of the global
#: ``random`` module so that seeding ``random`` elsewhere cannot make an
#: "unseeded" run silently reproducible (or vice versa).
_SYSTEM_RANDOM = random.SystemRandom()


def derive_seed(seed: int, index: int, stream: str = "person") -> int:
    """Derive a stable child seed from a population seed and an index.

    Args:
        seed: The population-level seed.
        index: The index of the child (for example the patient number).
        stream: Name of the logical stream. Different streams derived from the
            same ``(seed, index)`` are independent, which keeps, for example,
            clinician assignment from consuming the patient's randomness.

    Returns:
        A 64-bit non-negative integer suitable for :class:`random.Random`.
    """
    payload = f"{stream}:{seed}:{index}".encode("utf-8")
    digest = hashlib.sha256(payload).digest()
    return int.from_bytes(digest[: SEED_BITS // 8], "big")


def random_seed() -> int:
    """Return a fresh, non-reproducible seed from system entropy."""
    return _SYSTEM_RANDOM.getrandbits(SEED_BITS)


def resolve_seed(seed: Optional[int], index: int, stream: str = "person") -> int:
    """Derive a child seed, or draw a random one when no seed was given.

    Args:
        seed: The population seed, or ``None`` for a non-reproducible run.
        index: The index of the child.
        stream: Logical stream name; see :func:`derive_seed`.
    """
    if seed is None:
        return random_seed()
    return derive_seed(seed, index, stream)
