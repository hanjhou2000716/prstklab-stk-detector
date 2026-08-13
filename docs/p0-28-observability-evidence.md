# P0-28 source/release observability evidence

Source health distinguishes `no_events`, `scan_failed`, configuration gaps and
stale observations. Aggregates report success, failure, stale, cross-check and
parser-error counts. Production bindings expose mixed/degraded freshness and a
conservative quality score rather than treating missing evidence as safety.

Rollback is the atomic commit revert; health endpoints remain read-only.
