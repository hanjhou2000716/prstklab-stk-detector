# REQ-ADD-011 — Railway delivery persistence boundary

## Scope

`railway-monitor/delivery_store.py` is now the single persistence boundary for
the Railway delivery outbox, retry state, delivery receipts, bounded history,
diagnostics and retention cleanup. `SeenStore` keeps the existing public API
for the monitor and health callback, but delegates all SQLite delivery queries
to this module. Transport, signing and release eligibility remain outside the
store.

## Safety contract

- Outbox rows retain a stable trace ID and replay body; retryable failures keep
  their bounded backoff state.
- Receipt callbacks accept only the existing explicit `production`, `creator`
  or scoped `photo_smoke` contracts. Unknown trace IDs or origins are rejected
  without writing a receipt.
- Recipient failures are stored as hashes only; secrets and private response
  bodies are not persisted.
- Legacy receipt rows that encoded counts in `error` remain readable.
- Retention removes only terminal `sent`/`partial` rows older than 30 days;
  pending and failed rows remain auditable and retryable.

## Verification

- `tests/test_railway_delivery_store.py` covers outbox round-trip/backoff,
  receipt origin validation, recipient failures, legacy counts, retention and
  photo-smoke registration.
- Combined delivery/classification/monitor suite: `91 passed` in an isolated
  workspace basetemp.
- Changed module Ruff check passes; `mypy src`, compileall and frontend syntax
  checks remain green. The repository's pre-existing `railway-monitor/app.py`
  lint debt is not introduced into the CI `src tests` gate.

## Rollback

Revert the extraction commit. The schema and rows are additive, so reverting
the compatibility import and wrappers restores the prior `SeenStore` query
implementation without deleting Railway data.
