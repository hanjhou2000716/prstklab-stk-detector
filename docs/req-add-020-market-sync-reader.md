# REQ-ADD-020 — Market-sync snapshot reader boundary

## Scope

Extract public market-snapshot URL selection and read-only retrieval from the
Railway monitor. Missing, malformed, stale, or unavailable snapshots remain an
empty no-confirmation result; this boundary never invents a market direction.

## Verification

- Explicit `MARKET_SNAPSHOT_URL` takes precedence over the dashboard fallback.
- Dashboard fallback resolves to `/data/market.json`.
- Network access is injected in tests and never performed by the test suite.
- Targeted Railway suite: 110 passed; changed-module Ruff, compileall, and
  diff checks pass.

## Preservation and rollback

`app.fetch_market_sync_snapshot` remains as a compatibility wrapper and passes
the current environment into the reader. Reverting the atomic extraction
restores the inline HTTP reader without changing the fail-closed market-sync
confirmation gate.

Live Pages propagation and market-source freshness remain external
`NEEDS_REVERIFY` gates.
