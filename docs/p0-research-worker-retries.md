# P0 research worker retries

The unified research workflow runs each market/strategy worker through
`src.research_worker_runner`. A worker is attempted at most twice per run. A
successful worker exits normally and writes no failure record. When both
attempts fail, the runner appends one NDJSON record containing the market,
strategy, attempts, exit code, timestamps, and a bounded stderr summary.

The runner intentionally keeps the workflow moving after recording a failure.
`run_research_report --scan-failures` consumes the record and marks that source
as failed, blocking production publication. This means a provider outage is
visible and auditable without allowing partial or fabricated candidates into a
release. The workflow's own job timeout remains the global upper bound; no
per-worker timeout is imposed because the Taiwan MOPS value scan can be a
legitimate long-running batch.

Rollback: revert the runner/workflow commit. The existing failure-ledger
contract remains backward-compatible with the older `exit_code`-only records.
