# P0 Event Ledger Decision Provenance

The durable event ledger now records notification decisions as well as
delivery history. Pending and suppressed events remain visible with their
explicit reason (for example `official_confirmation_missing`,
`market_sync_missing`, `cooldown`, or a quality-gate failure).

FinancialJuice compound items use their parser-owned
`compound_event_cluster_key` as the ledger identity. Distinct items therefore
cannot overwrite one another, while repeated observations of the same item
still converge after cache eviction.

This is observability only: recording a decision never bypasses the alert
budget, release gate, cross-check or fail-closed policy.

Verification: `tests/test_event_ledger.py` covers compound identity and
pending-reason persistence.
