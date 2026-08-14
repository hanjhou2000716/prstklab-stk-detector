# REQ-ADD-009 — Railway state schema boundary

## Scope

`railway-monitor/state_store_schema.py` is now the canonical owner of the
SQLite tables and additive migrations used by the Railway monitor's
`SeenStore`.  `railway-monitor/app.py` keeps the existing connection setup and
calls the schema boundary once during store initialization; it does not create
a second store or change the poll/delivery semantics.

The extracted boundary preserves the existing tables (`seen`, `dispatched`,
`cache`, `event_ledger`, `delivery_outbox`, `incoming_events` and
`delivery_receipts`) and the compatibility migrations used by existing Railway
volumes.  Missing columns are added only; existing rows and table data are not
rewritten or discarded.

## Verification

- `tests/test_railway_state_store_schema.py` covers a new in-memory store,
  idempotent initialization and migration of the legacy two-column/old receipt
  layouts.
- The Railway monitor and standalone health regression continue to exercise the
  real `SeenStore` startup path.
- Live Railway volume migration and delivery receipts remain an external gate;
  local SQLite tests do not claim production acceptance.

## Rollback

Revert the atomic extraction commit.  The prior `SeenStore` inline schema
creation remains behaviorally equivalent, and no destructive migration or
release data change is required.
