# P3 regime and contagion evidence contract

Market-regime output now includes factor contributions, expected-but-missing
factors, evidence status, factor count, data-quality score and a non-predictive
marker. A sparse input remains observable but is explicitly
`insufficient_evidence`; it is never treated as proof that risk is absent.

Cross-asset contagion output similarly reports missing required inputs,
confirmed signals, evidence sufficiency and data quality. Two independent
signals are still required before `contagion=true`.

These fields are additive and are safe for the briefing, Mini App and release
audit. They do not create a trade signal or override source freshness and
cross-check gates.

## Rollback

Revert this PR to restore the previous regime/contagion response shape. No raw
market data or user portfolio data is changed.
