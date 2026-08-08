# PRStK stacked PR merge order

The production upgrade is intentionally delivered as stacked feature branches.
The PRs below are independent review units, but each later branch includes the
earlier branch's commits.  Merge them in order and keep all feature branches
until the final verification is complete.

| Order | PR | Branch | Depends on | Scope |
|---:|---:|---|---|---|
| 1 | #291 | `feat/t7-production-photo-delivery` | #290 | Wire release-gated scheduled delivery to one Telegram photo message per alert. |
| 2 | #292 | `feat/t8-miniapp-risk-context` | #291 | Show regime, contagion and stress context plus event timeline and feedback controls. |
| 3 | #293 | `feat/t9-source-health-slo-ui` | #292 | Distinguish source `no_events` from `scan_failed` and expose SLO evidence. |
| 4 | #294 | `feat/t10-research-explainability-contract` | #293 | Preserve and display candidate conditions, risk, invalidation and registry fields. |
| 5 | #295 | `feat/t11-macro-impact-ui` | #294 | Display Market Impact Graph paths and Macro Surprise evidence in briefings. |
| 6 | #296 | `feat/t12-offline-e2e-contract` | #295 | Extend the offline release dry-run to render and validate the 1080×1350 card. |
| 7 | #297 | `feat/t13-operations-documentation` | #296 | Align operational documentation, caption contract and post-merge runbook. |

## GitHub merge procedure

1. Merge #291, wait for its checks, then merge #292, and continue in the table
   order.
2. Select **Create a merge commit** for every PR.  Do not use **Squash and
   merge** or **Rebase and merge**; stacked commits are used to make each diff
   auditable.
3. Do not delete a branch until the next PR has been merged and its diff has
   been checked.  Delete all feature branches only after the final system test.
4. If a PR is still marked Draft, choose **Ready for review** only after its
   predecessor is merged and the checks have completed.

## Release verification after the last merge

Run the release workflow in this order:

1. `Refresh market dashboard`
2. `Unified Taiwan-US research report`
3. `Deploy dashboard to GitHub Pages`
4. `Scheduled market brief` with a dry-run/test recipient only

Confirm the same `release_id`, `snapshot_id` and `observation_id` in the
published manifest, Mini App and Railway delivery receipt.  A green Actions
run alone is not proof of Telegram delivery; the receipt must be `delivered`
for each test recipient.

## Rollback

If a release is inconsistent, stop notifications, restore the previous
successful release manifest and redeploy Pages.  Revert the affected feature
PR in reverse order; do not copy individual JSON files across releases or
force-push `main`.
