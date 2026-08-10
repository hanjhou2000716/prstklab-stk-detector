# Producer contract cleanup

This release hardens two producer boundaries that previously relied on the
release-time normalizer to repair artifacts:

- Research reports now emit integer formal/observation counts even when an
  older scan row has no `list_type`. Structured per-domain gaps are collapsed
  into the public `data_gap_counts` integer without losing the blocking state.
- TPEx official, TWSE MIS, and Yahoo fallback records emit an explicit source
  label. The Taiwan merge path derives the label from the selected fallback,
  so a stale Yahoo label cannot remain beside an official TPEx URL.

The release normalizer remains as backward-compatible defense in depth, but a
new producer should not need it to repair these fields. A release with no
verified production research still fails closed and keeps the last successful
data-release snapshot.

Validation:

- focused research/market tests: 40 passed
- full suite: 706 passed, 1 skipped
- coverage: 80.54%
- Ruff and Mypy: clean
- latest `origin/data-release` snapshot: release gate allowed

Rollback: revert this PR. Existing release-gate and data-release safeguards
remain active; no production artifact is deleted.
