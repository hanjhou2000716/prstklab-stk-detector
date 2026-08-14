# Gate-Driven v3 migration checkpoint — 2026-08-15

This is the authoritative reconciliation snapshot for the in-flight upgrade.
It is intentionally separate from older gate notes written before the latest
main release and does not promote historical claims to `PASS` without current
evidence.

## Repository snapshot

| Item | Evidence |
|---|---|
| Remote main at audit start | `587a27b155b92e9614fa5485d632fde28c087a64` |
| Audit branch base | `main` (reconciled with merge commit `420e53f`) |
| Current audit branch | `feat/REQ-ADD-039-gate-migration-audit` |
| Current HEAD | `9bc16a3c19677687959350f01f1252e2640aaa82` (`test(REQ-ADD-039): record full regression evidence`) |
| Working tree | Clean at the snapshot; no uncommitted or untracked product changes. |
| Historical stack observed | PRs #566–#617 are already ancestors of current `main`; they are historical context, not an outstanding merge queue. |

Local full-regression evidence at this checkpoint: `python -m pytest -q
--basetemp=.pytest-full` completed with **1231 passed, 1 skipped** in 50.55s.
The workspace basetemp was removed after the run; no production data or
notification was touched.

## Requirement traceability (migration scope)

| Requirement | Task | Implementation | Verification | Evidence | Regression | Status |
|---|---|---|---|---|---|---|
| P0-09 / P0-12 | REQ-ADD-039-T01 | Railway Gmail parses a bounded public-safe observation projection | `tests/test_railway_gmail_gateway.py` | 17 targeted tests pass; no raw body/sender/transport IDs in projection | duplicate and DLQ tests pass | PASS |
| P0-09 / P0-12 | REQ-ADD-039-T02 | Authenticated `/external-observations` export and client | `tests/test_railway_observation_client.py` | signature, status, schema and private-field rejection tests pass | missing config remains fail-closed | PASS |
| P0-09 / P0-12 | REQ-ADD-039-T03 | Scheduled delivery merges Railway and reviewed local observations | `tests/test_scheduled_delivery.py` plus external-input tests | 27 targeted/regression tests pass | local reviewed input remains usable when Railway is unavailable | PASS |
| P0-24 / P0-29 | REQ-ADD-039-T04 | Gate-driven evidence and debt ledgers | this document and canonical `docs/p0-requirement-traceability.md` | PR #618 at HEAD `9bc16a3`: quality run `31837821774` and security run `31837821805` passed (CodeQL, dependency review, SBOM, full test-and-dry-run) | no production release or broadcast performed | PASS / LOCKED |

`PASS` above is limited to the listed implementation and tests. It is not a
claim that the entire product or all original P0 DoDs are complete.

The full P0-01..P0-29 requirement index and its current external-gate debt are
maintained in the canonical `docs/p0-requirement-traceability.md` registry and
covered by `tests/test_p0_traceability_registry.py`; this checkpoint does not
create a second registry.

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
| DEBT-039-01 | Ruff is not installed in this local runtime | Remote CI Ruff gate passed; local environment remains unable to reproduce it without network/cache access | CLOSED (CI evidence) |
| DEBT-039-02 | Railway URL/secret and production deployment acceptance are external configuration | Configure through Railway/GitHub variables; run controlled single-recipient E2E | OPEN / external |
| DEBT-039-03 | Full repository regression and all original P0 DoDs not rerun on this checkpoint | Run after the stacked PRs are reconciled on latest main; current matrix is explicit in canonical `docs/p0-requirement-traceability.md` and `tests/test_p0_traceability_registry.py` | OPEN |
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

The branch is a recoverable checkpoint merged non-destructively with the latest
`main` (`420e53f`). Rollback is a PR revert (or branch deletion before merge);
it removes the Railway export path while leaving prior release and Telegram
gates intact.
No merge, deploy, release publication, or production notification is part of
this checkpoint.
