"""Switch that reproduces the pre-1.4.2 engine (issue #119).

``legacy`` is ``True`` when ``generate.encounter_end_legacy_stall`` is set. It restores, together:
the EncounterEnd stall, the always-false ``PriorState`` (without ``module``) and ``is nil`` /
``is not nil`` conditions, the unlimited re-joining of a routine visit, no same-step revisit
guard, no Delay rewind, and the reference range on valueless observations.

It is **process-global**: ``Generator.__init__`` sets it from its configuration, and the last
generator constructed wins. Parallel generation (``--threads``) builds one generator per worker
process, so each worker gets the configured value (tested). Do not run two generators with
different settings concurrently in one process.
"""

legacy: bool = False
