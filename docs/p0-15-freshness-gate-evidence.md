# P0-15 freshness and stale-quote gate

## Contract

- Old daily observations remain visible for transparency but are classified as
  `stale` and cannot be alert eligible.
- A recent close is explicitly classified as `recent_close`; it is not promoted
  to a live quote and cannot trigger a high-risk alert.
- A release gate rejects a ready manifest whose research freshness is not
  `fresh` in strict mode.

## Verification

`tests/test_p0_15_freshness_gate_contract.py` covers stale, recent-close and
strict release-gate cases. The existing market-data, data-quality, release
manifest and release-gate suites are run as regression tests.

## Failure and rollback

If a provider timestamp is missing or too old, the card remains visible with an
explicit freshness state and delivery is fail-closed. Reverting this atomic
test/documentation change restores the previous branch without changing stored
market observations.
