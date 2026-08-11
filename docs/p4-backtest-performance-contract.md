# P4 backtest performance contract

The walk-forward release contract now carries a sanitized `performance_summary`
for each strategy and fixed window. It contains only computed net metrics such
as trade count, net return, volatility, Sharpe, Sortino, drawdown, Calmar and
turnover proxy. Private or unrecognised fields are not copied into the public
contract.

The contract also records the survivorship audit status and point-in-time
snapshot dates. A ready release remains subject to the existing audit and
Advice Gate; metrics are evidence, not a forecast or trading instruction.

## Rollback

Revert this PR to omit the additive performance fields. Existing release IDs
remain deterministic for the same input contract and no historical result is
rewritten.
