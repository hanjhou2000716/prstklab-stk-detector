# Source health state contract

Source health exposes both a provider `status` and a user-facing `state`.
`no_event` means the source was scanned successfully and no matching event was
found. `scan_failed` means the source could not be trusted for this release;
the state must never be interpreted as a quiet market. Other modules may use
`warming`, `pending`, or `event_detected` when those states are present in the
source evidence.

The contract is fail-closed: a non-healthy provider can remain visible in the
Mini App, but it cannot qualify a high-risk alert or recommendation.
