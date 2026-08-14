# REQ-ADD-010 — Railway classification state boundary

## Scope

`railway-monitor/classification_store.py` is the single persistence boundary
for `seen` and `incoming_events` classification state. It owns recording an
incoming Jin10 item, preserving the reason a classifier path was taken,
claiming/finalising a classification, reopening a failed dispatch for retry,
and producing redacted classification diagnostics.

The canonical matching and policy implementation remains
`src/event_classifier.py` plus the Railway monitor's existing adapter. This
change only moves SQLite transitions behind injectable functions; it does not
add keywords, alter category thresholds, or create a second classifier.

## Verification

- `tests/test_railway_classification_store.py` covers first-seen state,
  retryable `unclassified` rows, invalid classifications, dispatch-failure
  reopening, and redacted diagnostics.
- The existing Railway monitor suite exercises the same `SeenStore` wrappers
  used by the poll loop and delivery gate.
- Live Railway state-volume persistence remains an external evidence gate; the
  local suite does not claim production acceptance.

## Rollback

Revert the atomic extraction commit. The previous `SeenStore` SQL transitions
remain behaviorally equivalent and no destructive migration is included.
