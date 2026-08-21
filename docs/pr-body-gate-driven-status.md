## Summary

- add a requirement/evidence ledger for P0-01 through P0-29;
- distinguish local `PASS / LOCKED` from external `NEEDS_REVERIFY` states;
- record the current GDELT 429, Railway callback 403, Gmail configuration and constrained Telegram receipt debts without weakening fail-closed behavior.

## Evidence

- Main baseline: `60a2f0dc365cb19ae34ae6a689a5cfea4415154c`.
- Public Pages manifest: `release-faaa5b86acfc0db3`, `status=ready`.
- Railway `/health`: HTTP 200; monitor running; GDELT and Gmail states recorded in the ledger.
- Targeted tests: 109 passed.
- Existing full regression baseline: 1328 passed.

## Scope and rollback

Documentation-only. No runtime, schema, release artifact, secret or data change. Revert this PR to roll back.
