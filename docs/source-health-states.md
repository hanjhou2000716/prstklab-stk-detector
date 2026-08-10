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
