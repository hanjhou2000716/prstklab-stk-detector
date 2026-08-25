# FinancialJuice release-lineage contract

This contract is the final local guard for the FinancialJuice lane. The
sanitized observation set, priority decisions and eligible event rows must be
the same release-bound set before a snapshot can be written for Pages.

## Rules

- A snapshot without FinancialJuice observations is valid and remains
  unaffected by this optional lane.
- Once FinancialJuice observations exist, every observation has exactly one
  decision with an allowed status: `eligible`, `not_eligible`, or
  `already_cluster_notified`.
- Every `eligible` decision has `vendor_importance >= 8`, the priority flag,
  and a corresponding event row.
- Event rows must identify FinancialJuice, agree with their decision status,
  and explicitly preserve `vendor_importance_is_not_risk`.
- Any mismatch blocks snapshot publication. It is never converted into
  `no_event` and it cannot reach the Pages release gate or Telegram.

The contract result is stored as `financialjuice_release_contract` in the
prepared snapshot so the failure is diagnosable without exposing Gmail
transport identifiers or raw message content.

## Verification

`tests/test_financialjuice_release_contract.py` covers aligned, orphaned,
risk-mixed, and no-FinancialJuice snapshots. Scheduled preparation tests
cover the contract in the existing release path. The gate is additive and
keeps the existing vendor-priority threshold and PRStK risk separation.

## Rollback

Revert the release-contract commit. Existing parser, priority, release-gate,
and Telegram safety checks remain unchanged; the optional FinancialJuice lane
returns to the prior validation behavior.
