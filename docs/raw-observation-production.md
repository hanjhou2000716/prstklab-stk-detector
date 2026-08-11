# Raw observation store in production workflows

The market, emergency-alert, and unified-research workflows now set
`RAW_OBSERVATION_ROOT=data/raw-observations` and
`RAW_OBSERVATION_REQUIRED=true`. Each run restores the existing immutable
observation records from `data-release` before collecting new data, then
publishes the append-only records with the same release as `site/data`.

If recording fails, the market artifact reports `state=unavailable` and the
release contract fails closed; no alert can be promoted from that run. The
store is intentionally public metadata only (request IDs, hashes, provider
status and timestamps), not credentials or private payloads.

Rollback: revert the workflow commit and restore the previous `data-release`
manifest. Setting `RAW_OBSERVATION_REQUIRED=false` is reserved for local
fixtures and must not be used by production workflows.
