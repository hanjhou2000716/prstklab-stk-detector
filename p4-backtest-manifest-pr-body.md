## Bind backtest release identity into the public manifest

This stacked PR follows #415 (`feat/p2-source-health-schema`). It carries the
existing walk-forward contract into each release manifest without unlocking
advice or inventing performance data.

### Changes

- add optional `backtest_release`, `backtest_publication_state`, and
  `strategy_registry` fields to the release schema;
- copy only the auditable backtest identity from the research artifact;
- include that identity in the release hash so a registry change cannot be
  hidden behind an unchanged market snapshot;
- mark missing contracts as `unavailable` and blocked contracts as `blocked`;
- document the fail-closed Advice Gate and rollback behavior.

### Validation

- `uv run pytest -q --basetemp=.pytest-temp-backtest-manifest-2 tests/test_release_manifest.py tests/test_backtest_release.py tests/test_production_integration.py tests/test_advice_gate.py` — 28 passed
- `uv run ruff check src/release_manifest.py tests/test_release_manifest.py` — passed

### Failure cases covered

- blocked survivorship audit remains visible but non-actionable;
- absent backtest contract is explicitly unavailable;
- release identity changes when the backtest registry changes.

### Rollback

Revert this PR and restore the previous `status=ready` manifest. Existing
market, research, event, and Telegram fail-closed gates remain unchanged.
