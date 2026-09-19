"""Modules implemented in Python rather than as JSON state machines.

The Generic Module Framework covers disease pathways well, but some things are
true of every patient regardless of illness — growing, ageing, attending
check-ups, dying — and expressing those as state machines would be contortion.
They live here instead, as ordinary Python modules that the engine runs
alongside the JSON ones.
"""
