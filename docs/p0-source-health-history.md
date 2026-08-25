# P0-28 Railway source-health history

Railway now records one privacy-safe sample after each completed monitor cycle.
The history is bounded to 168 samples (the configured seven-day ceiling) and is
exposed by `/health` as `observability.history`. Each sample contains only the
overall state, aggregate failure/no-event counters, and per-component status
labels. Credentials, message content, Gmail identifiers, Telegram identifiers,
and transport payloads are never copied into the history.

The endpoint also reports 24-hour and seven-day sample/failure/healthy counts.
An empty history means the monitor has not completed a cycle yet; it is not
interpreted as a healthy source. This is an in-memory operational view and is
deliberately not a substitute for the durable release snapshots used by the
public Mini App.

## Verification

- `tests/test_railway_health_state.py` covers privacy filtering, bounded
  retention, and window counts.
- The cycle-end hook records a sample only after the monitor marks the cycle
  complete, so a partially executed cycle cannot be reported as successful.

## Rollback

Revert the atomic commit for this change. The existing `/health` fields and
source-health fail-closed behavior remain available without the history block.
