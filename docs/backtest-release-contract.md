# Formal backtest release contract

`run_four_strategy_walk_forward` now emits `backtest_release_contract` beside
the research-only metrics.  The contract binds each strategy to its parameter
hash, data version, point-in-time universe version and code commit.

The contract is `publication_state=ready` only when the survivorship audit
passes and every strategy has no unresolved point-in-time data gaps.  Otherwise
it is `blocked`, with explicit `blocking_reasons`; the metrics remain available
for diagnosis but are not a formal performance release and cannot open the
Advice Gate.

This is additive and backward compatible with existing walk-forward artifacts.
To roll back, stop consuming `backtest_release_contract` and restore the prior
walk-forward artifact; no market or research release is modified.
