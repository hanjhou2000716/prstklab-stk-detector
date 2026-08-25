# Gate-driven continuation status — 2026-08-25

## Task

`REQ-ADD-041`: normalize Railway external-observation status aliases before
they enter the release-bound source-health contract.

## Evidence

| Check | Result |
|---|---|
| External observation + Railway client tests | 18 passed |
| Scheduled delivery regression | 17 passed |
| Full repository pytest | 1419 passed |
| Mypy (changed source) | pass |
| Compileall | pass |
| Git diff check | pass |
| GitHub test-and-dry-run | pass (run 32806946634) |
| GitHub CodeQL / dependency review / SBOM | pass |

The change keeps provider status raw for diagnostics while mapping completed
empty scans to `no_event`. Unknown statuses remain `failed` (or `partial`
when a local fallback is present), so the fail-closed notification boundary is
preserved.

## Regression / debt

- No new open regression.
- Existing external Railway/Pages/Telegram acceptance debts remain external;
  this PR does not claim live production acceptance.

## Rollback

Revert PR #764. No data migration or public artifact rewrite is required.
