"""Core modules that run for every patient, before the disease modules.

The engine loads these by name (see ``Module._load_core_modules``). Order
matters: :mod:`lifecycle` sets the attributes — age, BMI, blood pressure — that
disease-module logic conditions read, so it runs first.
"""
