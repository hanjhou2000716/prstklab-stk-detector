# P0-28 Railway source-health history

Railway records one privacy-safe sample after each completed monitor cycle.
The history is bounded to 168 samples (the configured seven-day ceiling),
persisted in the existing Railway SQLite state volume, and exposed by
`/health` as `observability.history`. On restart, the redacted samples are
restored before the first health response, so a process restart cannot erase
the evidence needed to distinguish a fresh deployment from a source outage.

Each sample contains only the overall state, aggregate failure/no-event
counters, and per-component status labels. Credentials, message content,
Gmail identifiers, Telegram identifiers, and transport payloads are never
copied into the history. This remains an operational view, not a raw event or
delivery database, and is not a substitute for durable release snapshots used
by the public Mini App.

The endpoint also reports 24-hour and seven-day sample/failure/healthy counts.
An empty history means the monitor has not completed a cycle yet; it is not
interpreted as a healthy source.

## Verification

- `tests/test_railway_health_state.py` covers privacy filtering, bounded
  retention, restore filtering, and window counts.
- `tests/test_railway_health_history_store.py` covers SQLite retention and
  redaction.
- `tests/test_railway_monitor.py` covers persistence across a store reopen.
- The cycle-end hook records a sample only after the monitor marks the cycle
  complete, so a partially executed cycle cannot be reported as successful.

## Rollback

Revert the atomic commit for this change. Existing `/health` fields and
source-health fail-closed behavior remain available; the additive
`health_samples` table is harmless on older volumes and can be removed only by
the normal additive migration process.
