# P2 News empty-state contract

The Mini App keeps a zero-story result fail-closed and explains why the list
is empty.  It uses the release-bound `source_health` row for each market:

- `no_event`: the source scan completed and found no matching public story.
- `failed`: the source failed, so the empty result is not treated as evidence
  that no market risk exists.
- `stale`: a recent successful cache is being used and its last success time is
  shown.
- `pending`: the current scan has not finished.

Raw provider error strings and data-gap codes are not displayed verbatim.  The
UI exposes a stable explanation, while full diagnostics remain in the release
artifact and source-health evidence.  The behavior is presentation-only and
does not change provider scope, alert eligibility, release gates or fallback
policy.

Rollback: revert this PR; the previous generic empty message remains safe and
release JSON is unchanged.
