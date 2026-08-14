# REQ-ADD-018 — Railway delivery retry boundary

## Scope

Extract the durable outbox replay loop from `railway-monitor/app.py` without
changing its public `retry_due_outbox` API or the existing fail-closed delivery
behaviour. The extracted boundary must reuse the persisted signed payload,
apply the bounded `OUTBOX_RETRY_BATCH` setting, mark each recipient-independent
dispatch independently, and publish delivery diagnostics only after a
successful replay.

## Verification

- `tests/test_railway_delivery_retry.py` covers persisted-payload reuse,
  bounded batch selection, success health projection, and failure continuation.
- `tests/test_railway_monitor.py` preserves the compatibility wrapper and
  existing outbox state assertions.
- Targeted Railway suite: 106 passed.
- Changed-module Ruff, compileall, and `git diff --check` pass.

## Preservation and rollback

The wrapper remains in `app.py`, so existing monitor callers and monkeypatch
seams remain stable. Reverting the atomic extraction commit restores the
inline implementation without touching persisted outbox rows or delivery
receipts.

## Evidence status

Local targeted evidence is PASS for this boundary. Live Railway restart
continuity, signed callback delivery, and production Telegram receipt remain
external `NEEDS_REVERIFY` gates.
