"""
Synthea - Synthetic Patient Population Simulator.

A Python implementation of the Synthea patient generator, which creates
synthetic, realistic (but not real) patient data and associated health records.
"""

__version__ = "1.0.0"
__author__ = "TietAI and PySynthea project contributors"

from synthea.engine.generator import Generator
from synthea.world.person import Person
from synthea.engine.module import Module

__all__ = [
    "Generator",
    "Person",
    "Module",
]