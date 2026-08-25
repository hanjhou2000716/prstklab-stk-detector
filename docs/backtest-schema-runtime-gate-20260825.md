# Backtest schema runtime gate

`validate_research` now validates every present `backtest_release_contract`
against `schemas/backtest-release.schema.json` before the manual compatibility
checks run. This closes the gap where a producer could emit a structurally
valid-looking contract with unknown fields that were never checked at the
release boundary.

The manual checks remain intentionally in place so legacy callers receive
stable, actionable errors (for example a missing `strategy_registry` field),
while the formal schema rejects unknown fields, invalid release identifiers,
and malformed strategy registry rows. Any schema load or parse failure is
fail-closed and prevents publication.

Verification: targeted artifact/backtest/advice tests and the full repository
regression suite. Rollback is an atomic revert of the runtime gate and its
test/documentation; the producer schema from PR #780 remains available for
future re-enablement.
