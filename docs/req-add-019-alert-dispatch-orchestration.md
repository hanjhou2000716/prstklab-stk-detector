# REQ-ADD-019 — Alert dispatch orchestration boundary

## Scope

Extract the small orchestration that derives an alert trace ID, builds the
canonical payload, signs it, and invokes the existing repository-dispatch
transport. The application wrapper and payload contracts remain unchanged.

## Verification

- `tests/test_railway_alert_dispatch.py` asserts exactly one build, sign, and
  dispatch call with the same trace ID.
- Existing dispatch payload, outbox, monitor, and retry tests remain in the
  targeted Railway suite.
- Targeted suite: 107 passed; changed-module Ruff, compileall, and diff checks
  pass.

## Preservation and rollback

The public `app.dispatch_alert` wrapper remains in place and injects the same
callbacks. Reverting the atomic extraction commit restores the inline
orchestration without changing stored payloads, signatures, or outbox rows.

Live signed callback and Telegram receipt delivery remain external
`NEEDS_REVERIFY` gates.
