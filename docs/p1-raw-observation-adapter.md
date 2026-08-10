# P1 raw observation adapter boundary

`build_adapter()` now honours the opt-in `RAW_OBSERVATION_ROOT` setting. When
present, every allow-listed `JsonSourceAdapter` receives a shared
`RawObservationStore`, records the provider response and payload hash before
normalization, and exposes the resulting `observation_id` in provenance.

The setting is intentionally absent by default. Local tests and dry-runs stay
read-only unless a caller explicitly supplies a store or configures the
worker environment. Raw payloads never enter a public release artifact.

## Operations

Set `RAW_OBSERVATION_ROOT` only on a writable worker (Railway or a scheduled
collector). Back up the store with the release archive. If the store cannot be
written, the adapter's existing fail-closed error path remains in effect; it
does not make an observation alertable.

## Rollback

Unset `RAW_OBSERVATION_ROOT` or revert this PR. Existing callers that inject a
store explicitly are unchanged.
