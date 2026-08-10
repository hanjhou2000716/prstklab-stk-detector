# Source health state contract

Source health exposes both a provider `status` and a user-facing `state`.
`no_event` means the source was scanned successfully and no matching event was
found. `scan_failed` means the source could not be trusted for this release;
the state must never be interpreted as a quiet market. Other modules may use
`warming`, `pending`, or `event_detected` when those states are present in the
source evidence.

The contract is fail-closed: a non-healthy provider can remain visible in the
Mini App, but it cannot qualify a high-risk alert or recommendation.

## Research scan precedence

Research rows may carry localized display text in `status`, but the machine
contract is `scan_state`.  Source Health therefore evaluates these values in
this order:

- `failed`, `scan_failed`, `data_unavailable`, or `unavailable` → `failed`
- `building`, `warming`, `partial`, or `in_progress` → `warming` (or `partial`
  when the row reports a source failure)
- `complete` with zero candidates → `healthy` plus `candidate_state=no_candidates`

This prevents a translated label change from hiding a failed scan.  A
partially completed value scan remains visible as progress, while its
candidate list stays blocked until the producer's completeness policy allows
publication.

## Observability summary

The published `source_health.observability` object is computed from the same
source rows shown in the card.  It includes `observations`, `success_rate`,
`failure_count`, `no_event_count`, `stale_count`, `degraded_count`,
`crosscheck_rate`, and `parser_error_count`.  A successful scan with no matching
event counts as a successful observation (`no_event_count`), while stale data
still keeps the aggregate in `partial` so it cannot be mistaken for a healthy
live feed.

## Published artifact validation

`schemas/source-health.schema.json` defines the canonical envelope used when a
market artifact includes the complete health record: `status`, `sources`, and
`event_scan`. `src.artifact_contract.validate_source_health` checks the
cross-field rules: a `healthy` or `no_event` row cannot carry a failed, stale,
or partial semantic state, and `event_scan=no_event` cannot coexist with a
failed core source. Legacy releases that only contain the old `data_gaps`
field remain readable; the next producer upgrades them rather than silently
treating them as a healthy scan.
