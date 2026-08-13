# P0-14 market-synchronization evidence

## Contract

Market synchronization is an observed witness, not an inferred direction. The
event path remains conditional until a related, non-delayed quote has a
material move in the same observation window. Oil/Brent/WTI requires an
absolute daily move above 5% and both event and quote timestamps; stale or
timestamp-free quotes cannot confirm a breaking event. Impact graphs expose
`market_sync=false` and conditional direction when evidence is absent.

## Verification

`tests/test_p0_14_market_sync_contract.py` covers time alignment, fresh quote
thresholds, the oil 5% rule, and conditional graph output. Existing event-alert,
market-impact and stale-quote regressions remain required.

## Rollback and preservation

Revert the atomic P0-14 evidence/test commit if needed. Preserve fail-closed
behavior: no market witness may be replaced by a generic index move or an old
close, and no event may gain a directional percentage without confirmation.

## Traceability

- Requirement: P0-14 market synchronization evidence
- DoD: synchronized evidence is time-bounded, market-relevant and explicit;
  absent evidence remains conditional
- Evidence: targeted sync/graph tests and required PR CI
