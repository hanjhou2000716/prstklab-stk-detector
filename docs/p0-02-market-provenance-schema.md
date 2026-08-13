# P0-02 market provenance schema

Market quote artifacts now declare the additive provenance fields used by the
producer and audit layer: quote source/domain/time, cross-check source records,
and technical context freshness. Runtime validation accepts the nested
`technical_context_stale` marker so historical technical ranges cannot be
mistaken for current support/resistance evidence.

Verification: 60 market/artifact/cross-check tests passed, compilation and
diff checks passed. The existing fail-closed stale/live and source-domain
invariants remain unchanged.

Rollback: revert this PR to restore the previous permissive schema; no market
data is deleted and the existing source safety checks remain independently
available.
