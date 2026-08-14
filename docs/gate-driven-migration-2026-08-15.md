# Gate-Driven v3 migration checkpoint — 2026-08-15

This is the authoritative reconciliation snapshot for the in-flight upgrade.
It is intentionally separate from older gate notes written before the latest
main release and does not promote historical claims to `PASS` without current
evidence.

## Repository snapshot

| Item | Evidence |
|---|---|
| Remote main at audit start | `587a27b155b92e9614fa5485d632fde28c087a64` |
| Audit branch base | `feat/publish-before-notify-contract` (`477131ce911eae76544ed36323a738a68b89410f`) |
| Current audit branch | `feat/REQ-ADD-039-gate-migration-audit` |
| Working tree policy | Only files listed in the migration PR are staged; pytest temp directories are ignored/untracked artifacts. |
| Open stacked work observed | PRs #566–#576; all were green when inspected, but remain unmerged and must be verified again after rebasing/merging. |

## Requirement traceability (migration scope)

| Requirement | Task | Implementation | Verification | Evidence | Regression | Status |
|---|---|---|---|---|---|---|
| P0-09 / P0-12 | REQ-ADD-039-T01 | Railway Gmail parses a bounded public-safe observation projection | `tests/test_railway_gmail_gateway.py` | 17 targeted tests pass; no raw body/sender/transport IDs in projection | duplicate and DLQ tests pass | PASS |
| P0-09 / P0-12 | REQ-ADD-039-T02 | Authenticated `/external-observations` export and client | `tests/test_railway_observation_client.py` | signature, status, schema and private-field rejection tests pass | missing config remains fail-closed | PASS |
| P0-09 / P0-12 | REQ-ADD-039-T03 | Scheduled delivery merges Railway and reviewed local observations | `tests/test_scheduled_delivery.py` plus external-input tests | 27 targeted/regression tests pass | local reviewed input remains usable when Railway is unavailable | PASS |
| P0-24 / P0-29 | REQ-ADD-039-T04 | Gate-driven evidence and debt ledgers | this document | branch/diff/test output captured in PR | no production release or broadcast performed | NEEDS_REVERIFY |

`PASS` above is limited to the listed implementation and tests. It is not a
claim that the entire product or all original P0 DoDs are complete.

## Integration matrix (current evidence)

| Module | Files exist | Tests | Formal pipeline | JSON | Mini App | Telegram | Status |
|---|---:|---:|---:|---:|---:|---:|---|
| Source adapters / market snapshot | yes | yes | yes | yes | yes | yes | production |
| Release manifest / release gate | yes | yes | yes | yes | yes | yes | production |
| Alert lifecycle / budget / dedup | yes | yes | yes | yes | yes | yes | production |
| Telegram delivery receipts | yes | yes | yes | yes | n/a | yes | production |
| Mini App deep links / release fallback | yes | yes | yes | yes | yes | n/a | production |
| Creator / FinancialJuice registry | yes | yes | partial | partial | partial | partial | partially_integrated |
| Railway Gmail → sanitized public observation export | yes | yes | this PR | this PR | pending deploy | pending acceptance | partially_integrated |
| Event clustering / impact graph | yes | yes | partial | partial | partial | partial | partially_integrated |
| Macro surprise / regime / contagion | yes | yes | partial | partial | partial | partial | partially_integrated |
| Strategy registry / point-in-time backtest | yes | yes | partial | partial | partial | n/a | partially_integrated |
| Private portfolio risk | yes | yes | no public pipeline | no public output | isolated | no | experimental |
| Advice gate / paper portfolio | yes | yes | partial | partial | partial | no trade action | experimental |

## Regression ledger

| ID | Symptom | Root cause / mitigation | Evidence | Status |
|---|---|---|---|---|
| REG-039-01 | OneDrive can intermittently fail raw-observation temp-file replacement | Environment/filesystem behavior; rerun on CI/Linux or a local non-synced checkout | prior baseline runs, not reproduced by targeted tests | OPEN / needs reverify |
| REG-039-02 | Railway export unavailable when URL/secret are absent | Client returns `configuration_missing`; local reviewed input remains valid and no alert is invented | client test | CLOSED |
| REG-039-03 | Invalid/private Gmail-derived row could enter release | Sanitized allowlist and SQLite privacy boundary reject it | ingress + external-input tests | CLOSED |

## Completion-debt ledger

| Debt ID | Description | Resolution / next gate | Status |
|---|---|---|---|
| DEBT-039-01 | Ruff is not installed in this local runtime | CI quality workflow must run the repository-pinned Ruff job | OPEN |
| DEBT-039-02 | Railway URL/secret and production deployment acceptance are external configuration | Configure through Railway/GitHub variables; run controlled single-recipient E2E | OPEN / external |
| DEBT-039-03 | Full repository regression and all original P0 DoDs not rerun on this checkpoint | Run after the stacked PRs are reconciled on latest main | OPEN |
| DEBT-039-04 | Existing older gate notes contain PASS claims predating this snapshot | Treat this document as current authority; reverify each mapped DoD | OPEN |

## Preservation contracts

- **PC-001** market/risk/research pipelines remain unchanged unless they consume
  the new optional observation projection.
- **PC-002** release gate and stale/fail-closed rules remain mandatory; no
  Railway failure can create a qualifying alert.
- **PC-003** Telegram delivery remains release-bound and single-recipient
  testing only; this checkpoint performs no production broadcast.
- **PC-004** raw Gmail body, sender, attachment and transport identifiers never
  enter public artifacts.
- **PC-005** local reviewed `EXTERNAL_OBSERVATIONS_PATH` remains a safe fallback
  when Railway is unavailable.

## Recovery / rollback

The branch is a recoverable checkpoint based on the existing stacked branch.
Rollback is a PR revert (or branch deletion before merge); it removes the
Railway export path while leaving prior release and Telegram gates intact.
No merge, deploy, release publication, or production notification is part of
this checkpoint.
