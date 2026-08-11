# P1 Instrument Master artifact

The production evidence boundary now records the content-addressed instrument
registry used to resolve each ticker. `InstrumentMaster.artifact()` emits a
public-safe `instrument-master.schema.json` document containing market, asset
type, currency, timezone, symbol aliases and point-in-time listing dates.

Each quote includes `instrument_master_id` and `instrument_master_version`.
Unknown or ambiguous symbols remain unresolved and ineligible for alerts; the
registry identifier is evidence of which mapping was attempted, not a guess.

## Rollback

Reverting this PR removes the registry identity fields from quote evidence and
restores the prior resolver behavior. Existing market snapshots remain valid
because the new fields are additive.
