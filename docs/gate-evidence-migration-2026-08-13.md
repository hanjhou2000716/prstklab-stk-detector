# Gate / Evidence Migration Snapshot — 2026-08-13

## Current state

- Baseline `main`: `2b05dfba79061a065bb92d374fdbe813f75e2e95`.
- Active branch: `feat/canonical-creator-provider-registry`.
- Active HEAD: `ae319fa`.
- PR: [#565](https://github.com/hanjhou2000716/prstklab-stk-detector/pull/565), open, base `main`, merge state clean.
- Working tree: tracked files clean; historical untracked test/output artifacts are preserved and intentionally not staged.
- Recovery checkpoint: the active work is fully represented by commits `af3e45c`, `68d8faf`, and `ae319fa`; no reset or destructive cleanup was performed.

## Active task

| Task | Status | Evidence |
|---|---|---|
| Canonical Creator Provider Registry | PASS / LOCKED | PR #565; targeted tests 37 passed; CI run 31693131665 passed; Ruff/Mypy/compile/release dry-runs passed |
| FinancialJuice compound envelope | PASS / LOCKED | Branch `feat/financialjuice-compound-contract`; compound fan-out, fail-closed and schema tests passed locally |
| FinancialJuice pipeline fan-out | PASS / LOCKED | Branch `feat/financialjuice-pipeline-fanout`; shared event pipeline emits one result per item and blocks unresolved envelopes |
| FinancialJuice priority policy | PASS / LOCKED | Branch `feat/financialjuice-priority-policy`; 8/9/10 priority metadata is separated from PRStK risk and covered at 7/8 boundaries |
| FinancialJuice intelligence fan-out | PASS / LOCKED | Branch `feat/financialjuice-intelligence-fanout`; all compound items remain visible in intelligence context and clusters |
| Event ledger decision provenance | PASS / LOCKED | PR #569; 25 targeted tests, Ruff, Mypy, compile and CI runs 31700567920/31700568021 passed |
| Event ledger delivery integration | IN_PROGRESS | Official monitor records release-gate and alert-budget suppression decisions before safe skip |
| Existing P0 requirements from the continuation brief | NEEDS_REVERIFY | The brief enumerates P0-01 through P0-29; this branch only addresses provider-registry scope. Each remaining DoD needs a separate evidence row before being marked PASS. |

## Verification evidence

- Targeted local suite: `37 passed in 2.45s`.
- CI: `test-and-dry-run`, `dependency-review`, `sbom`, CodeQL and codeql all passed on PR #565.
- CI gates included full unit tests, core coverage gate, Ruff, Mypy, compileall, Mini App artifact validation, Telegram configuration dry-run, offline release-to-delivery dry-run and offline production acceptance.
- `git diff --check` passed.

## Traceability

| Requirement | Task | Implementation | Verification | Evidence | Regression | Status |
|---|---|---|---|---|---|---|
| REQ-P0-01-REGISTRY | Canonical provider registry | `config/creator_providers.json`, `src/creator_provider_registry.py`, `schemas/creator-providers.schema.json` | registry, parser, routing and health tests | PR #565 + CI run above | existing creator routing preserved | PASS / LOCKED |
| REQ-P0-01-INTEGRATION | All creator consumers use registry | routing, parser, health, catalog, scheduled delivery, Railway router | 37 targeted tests + full CI | PR #565 diff | unknown provider remains fail-closed | PASS / LOCKED |
| REQ-P0-09-COMPOUND | FinancialJuice compound envelope | `src/financialjuice_contract.py`, `src/external_source_parsers.py`, `schemas/financialjuice-envelope.schema.json` | 19 targeted tests; compound fixture produces 2 independent items; unresolved item is fail-closed | local test output on `feat/financialjuice-compound-contract` | existing single-item parser preserved | PASS / LOCKED |
| REQ-P0-09-PIPELINE | Compound items reach canonical event pipeline | `src/external_event_pipeline.py`, `src/intelligence_pipeline.py` | 15 targeted tests; fan-out and unresolved-envelope regression pass | local test output on `feat/financialjuice-pipeline-fanout` | single-item external events preserved | PASS / LOCKED |
| REQ-P0-10-PRIORITY | FJ 8/10 vendor priority without risk override | `src/financialjuice_contract.py` | 14 targeted tests; 8 eligible metadata, 7 rejected, risk remains R2 | local test output on `feat/financialjuice-priority-policy` | official/market gates remain required | PASS / LOCKED |
| REQ-P0-09-INTELLIGENCE | Compound items reach Mini App intelligence payload | `src/intelligence_pipeline.py` | 23 targeted tests; two items, two clusters and item identities preserved | local test output on `feat/financialjuice-intelligence-fanout` | single-item context preserved | PASS / LOCKED |
| REQ-P0-11-LEDGER-DECISION | Event ledger preserves compound identity and notification blocking reasons | `src/event_ledger.py` | 25 targeted tests; Ruff, Mypy and compile pass | PR #569 + CI runs 31700567920/31700568021 | existing cooldown and delivery history preserved | PASS / LOCKED |
| REQ-P0-11-LEDGER-INTEGRATION | Official delivery records gate/budget suppression reasons | `src/official_event_monitor.py` | pending targeted regression and CI | pending | existing safe no-send behaviour preserved | IN_PROGRESS |
| P0-02..P0-29 | Existing continuation requirements | existing modules and prior PRs | evidence not yet reconciled against every DoD | no single current evidence artifact | open reconciliation | NEEDS_REVERIFY |

## Regression ledger

| ID | Introduced by | Symptom | Root cause | Fix | Evidence | Status |
|---|---|---|---|---|---|---|
| REG-565-001 | registry import additions | CI Ruff import ordering failure | imports were added below local imports | reordered imports; CI rerun passed | run 31693131665 | CLOSED |
| REG-565-002 | registry optional lookup | CI Mypy union-attr failure | provider lookup was called twice without narrowing | bound optional config before use; CI rerun passed | run 31693131665 | CLOSED |

## Completion-debt ledger

| Debt ID | Description | Resolution | Status |
|---|---|---|---|
| DEBT-565-001 | Historical untracked pytest/temp artifacts in working tree | preserved; never staged; cleanup requires separate approved maintenance task | OPEN (non-production workspace hygiene) |
| DEBT-565-002 | P0-02..P0-29 evidence reconciliation is incomplete | continue with evidence audit and separate atomic tasks | OPEN |

## Preservation contracts

- PC-001: existing provider routing and fail-closed unknown-source behavior preserved by targeted tests — PASS.
- PC-002: Creator content remains editorial and cannot become market-event evidence — PASS by registry policy/tests.
- PC-003: release-gate and notification code paths remain unchanged except dynamic provider inputs — PASS by CI dry-run.

## Next gate

Review/merge PR #565 only after human review. Do not merge automatically. After merge, rerun main-branch smoke and production acceptance before claiming completion.
