# P0 Release Failure Semantics

## Root cause

Several Pages and notification workflows used job-level `continue-on-error` in
order to avoid repeated email alerts during a temporary Pages outage. That
scope also masked manifest, artifact, and release-gate failures. A run could
therefore appear successful even though a contract-invalid release was not
published and a notification was correctly skipped.

## Policy

- The local `deploy-pages-retry` action remains tolerant of transient Pages
  control-plane failures and exposes `available=false`.
- A missing Pages URL skips downstream delivery and records degraded
  availability.
- Manifest, schema, lineage, freshness, and release-gate failures are hard
  workflow failures.
- Telegram delivery remains conditional on `steps.release_gate.outputs.allowed`
  and is never used to hide a failed release.
- Delivery-receipt persistence may remain best effort because it occurs after a
  successful delivery decision; the receipt still records the failure through
  its callback status.

## Migration and rollback

No data migration is required. Existing workflow runs and release artifacts are
unchanged. To roll back, revert the workflow commit; do not republish an
invalid manifest or bypass the release gate.

## Verification

`tests/test_pages_deploy_retry.py` asserts that the six Pages workflows do not
mask job-level contract failures and that the release-gate steps are not
`continue-on-error`. The retry action itself keeps its bounded two-attempt
degraded-availability behavior.
