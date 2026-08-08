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

## Current follow-up stack

The following PRs are the current continuation after the historical delivery
stack above.  They must be merged in this order; each base is the preceding
feature branch.  PR #300 is a standalone renderer repair and should be merged
before this stack when its checks are green.

| Order | PR | Branch | Base / dependency | Scope |
|---:|---:|---|---|---|
| 8 | #300 | `fix/full-rendered-photo-card` | `main` | Require the real browser renderer so photo cards cannot silently become blank. |
| 9 | #306 | `fix/research-candidate-state-contract` | `feat/alert-budget-lifecycle-integration` | Preserve completed research candidates while history is still building. |
| 10 | #307 | `fix/source-health-research-state` | #306 | Keep research building, no-candidate and failure states distinct in source health. |
| 11 | #308 | `fix/source-provider-classification` | #307 | Classify provider failures, fallback and degraded health without false normal status. |
| 12 | #309 | `feat/canonical-release-publisher` | `feat/telegram-card-v2` | Validate and publish one canonical release before Pages/Telegram. |
| 13 | #310 | `feat/event-impact-evidence` | `feat/source-health-class-ui` | Attach conditional market-impact evidence to event cards. |
| 14 | #311 | `feat/source-health-class-ui` | #309 | Display source-health classes and actionable diagnostics in the Mini App. |
| 15 | #312 | `feat/research-candidate-ui-state` | #310 | Keep research candidate state visible when the scan is partial. |
| 16 | #313 | `feat/raw-observation-source-provenance` | #312 | Persist raw observation provenance when Railway storage is configured. |
| 17 | #314 | `feat/full-mypy-clean` | #313 | Make the complete source tree type-safe. |
| 18 | #315 | `feat/research-explainability-advice-gate` | #314 | Bind fail-closed Advice Gate and explainability fields to candidates. |
| 19 | #316 | `feat/research-advice-gate-ui` | #315 | Render Advice Gate state and blocking reasons in the Mini App. |
| 20 | #317 | `feat/paper-portfolio-tracking` | #316 | Add public, research-only paper observations with explicit null outcomes. |
| 21 | #318 | `feat/full-offline-e2e-delivery-gate` | #317 | Verify release → renderer → Mini App link → mocked Telegram sendPhoto. |
| 22 | #319 | `fix/preserve-advice-gate-card-fields` | #318 | Preserve Advice Gate fields through the public research loader. |

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
