# PRStK merge order

The open production-upgrade PRs are reviewed independently and must be merged
in the order below. No PR is auto-merged by the automation. Keep each branch
until the next diff has been inspected and the post-merge checks are green.

| Order | PR | Branch | Depends on | Scope |
|---:|---:|---|---|---|
| 1 | #338 | `feat/source-adapter-catalog` | main | Publish the allow-listed source adapter catalog. |
| 2 | #339 | `feat/source-quality-contract` | #338 | Source quality scores and paper observation horizons. |
| 3 | #340 | `feat/event-feedback-contract` | #339 | Safe, anonymous event feedback contract. |
| 4 | #341 | `feat/raw-observation-release-contract` | #340 | Raw observation store health metadata. |
| 5 | #342 | `feat/research-explainability-contract` | #341 | Candidate explainability and advice-gate provenance. |
| 6 | #343 | `feat/quality-gates` | #342 | Full/core coverage gates and CI quality checks. |
| 7 | #344 | `feat/raw-observation-pipeline` | #343 | Optional immutable market snapshot persistence. |
| 8 | #345 | `feat/alert-budget-delivery` | #344 | Alert Budget enforcement in scheduled delivery. |
| 9 | #346 | `feat/production-photo-delivery` | #345 | Release-gated 1080x1350 `sendPhoto` production path. |
| 10 | #347 | `feat/photo-delivery-docs` | #346 | Production photo-delivery documentation and offline contract. |
| 11 | #348 | `feat/photo-smoke-scope` | #347 | Explicit single-recipient photo smoke-test guard. |

Use **Create a merge commit** for each PR. Do not squash or rebase stacked
work, and do not delete an earlier branch before its dependent PR is merged.

## Verification after the last merge

Run, in order:

1. `Refresh market dashboard`
2. `Unified Taiwan-US research report`
3. `Deploy dashboard to GitHub Pages`
4. the scoped photo smoke test with one explicit test chat ID
5. `Scheduled market brief` in dry-run mode

Verify the same `release_id`, `snapshot_id`, and `observation_id` in the
manifest, Mini App and delivery receipt. A green Actions run alone does not
prove Telegram delivery; the receipt must be `delivered` for the scoped test
recipient.

## Rollback

If a release is inconsistent, stop notification delivery, restore the previous
`status=ready` manifest and redeploy Pages. Revert the affected PRs in reverse
order. Never mix individual artifacts across releases or force-push `main`.
