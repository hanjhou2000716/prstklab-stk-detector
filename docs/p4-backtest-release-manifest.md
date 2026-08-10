# Backtest release binding

When a research artifact carries `backtest_release_contract`, the release
manifest copies only its auditable identity fields:

- `backtest_release`
- `backtest_publication_state` (`ready`, `blocked`, or `unavailable`)
- `strategy_registry`

The manifest does not turn a blocked study into an actionable candidate.  The
Advice Gate still requires a valid release contract and keeps candidates in
`observation_only` when survivorship, point-in-time, or cost audits are not
complete.  Including this identity in the release hash prevents a market
release from silently reusing a different backtest registry.

Older research artifacts without a contract remain valid and are explicitly
marked `backtest_publication_state=unavailable`.  To roll back, restore the
previous release manifest as a whole; do not copy a backtest field between
releases.
