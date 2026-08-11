# Research report ↔ backtest release binding

The research-report producer accepts an optional `--backtest-release` path
pointing to the JSON emitted by the point-in-time walk-forward runner. Only the
auditable `backtest_release_contract` is copied into the public research
artifact; raw trades and metrics remain in the backtest artifact.

The contract is intentionally fail-closed:

- `publication_state=ready` records the release identity and strategy registry.
- `publication_state=blocked` records the blocking reasons and keeps Advice Gate
  observation-only.
- an omitted path is reported as `backtest_release_status=unavailable`.
- a missing, malformed, or contract-less file becomes `blocked`; it is never
  interpreted as a successful backtest.

The unified research workflow exposes the optional
`backtest_release_path` dispatch input. Existing scheduled scans may omit it;
this preserves backward compatibility while making a verified study available
to a release when an archived artifact is supplied.

Rollback: omit the input and remove the optional contract field from the next
research artifact. The release manifest records `unavailable` and Advice Gate
remains closed; no market or candidate data is changed.
