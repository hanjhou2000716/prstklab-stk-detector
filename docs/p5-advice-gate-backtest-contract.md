# P5 Advice Gate backtest contract

Decision-support context now requires the structured `backtest_release_contract`
to be ready and publish-eligible. A bare `backtest_release` string is not
enough evidence: it cannot prove publication state, eligibility or the
identity of the study attached to the candidate.

This remains a research-only safety gate. It never creates a buy/sell command;
missing or stale contract metadata returns `invalid_backtest_release` and the
candidate remains observation-only.

## Rollback

Reverting this PR restores the previous compatibility behavior for bare IDs;
the structured contract path and existing fail-closed checks remain unchanged.
