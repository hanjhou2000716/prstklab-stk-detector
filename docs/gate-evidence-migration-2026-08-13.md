# Gate / Evidence Migration Snapshot — 2026-08-13

## Current state

### Migration reconciliation update (2026-08-13)

The original snapshot below records the initial registry branch. The active
stack has since advanced through the contract-hardening branches; this update
is authoritative for the Gate-Driven migration audit.

- Active branch: `feat/safe-data-publishing-contract`.
- Active HEAD: `b670051` (P0-08 source-health contract and CI lint repair).
- P0-14 implementation checkpoint: `4d71e54` (targeted market-synchronization contract tests passed; CI evidence pending).
- P0-14 gate evidence: quality run `31718964237` / job `94510770579`, security/CodeQL/SBOM passed; task is PASS / LOCKED.
- P0-15 implementation checkpoint: `tests/test_p0_15_freshness_gate_contract.py`; isolated targeted/regression suite 72 passed; CI evidence pending.
- P0-15 gate evidence: quality run `31719716607` / job `94513312331`, security/CodeQL/SBOM passed; task is PASS / LOCKED.
- P0-16 implementation checkpoint: delivery receipt lineage and recipient-isolation contract tests added; CI evidence pending.
- P0-16 gate evidence: quality run `31720218621` / job `94515038872`, security/CodeQL/SBOM passed; task is PASS / LOCKED.
- P0-17 implementation checkpoint: creator renderer/media failure contract tests added; CI evidence pending.
- P0-17 gate evidence: quality run `31720774828` / job `94516916801`, security/CodeQL/SBOM passed; task is PASS / LOCKED.
- P0-18 implementation checkpoint: external alert signature/provenance/high-risk contract tests added; targeted 19 passed.
- P0-18 verification gate: CI run `31721326422` / job `94518750439` passed; CodeQL, dependency review and SBOM also passed.
- P0-18 locked after CI evidence: external alert trust boundary now has auditable signed payload, HTTPS provenance, independent-source checks, and fail-closed high-risk gating.
- P0-19 verification gate: targeted Gmail ingress contract suite passed 20 tests; CI run `31722239089` / job `94521788534` passed with security/CodeQL/SBOM.
- P0-19 locked: authenticated, bounded and cursor-only Gmail Pub/Sub ingress is replay-safe and keeps raw mail outside Railway storage.
- P0-20 verification gate: targeted Railway health contract suite passed 7 tests with isolated basetemp; CI run `31722834875` / job `94523793185` passed with security/CodeQL/SBOM.
- P0-20 locked: callback configuration errors do not trigger restart, transient failures have bounded retry hints, and stale heartbeat remains explicit.
- Active PR: the P0-06 safe data publishing PR, stacked on PR [#576](https://github.com/hanjhou2000716/prstklab-stk-detector/pull/576).
- Previous active branch: `feat/publish-before-notify-contract` (PR [#576](https://github.com/hanjhou2000716/prstklab-stk-detector/pull/576)), now LOCKED after targeted contract tests and CI.
- Recovery checkpoint: `3c27fe6` (manifest integrity contract) and `0c1d71d`
  (portable cross-platform path validation). No reset, merge, force-push or
  destructive cleanup was performed.
- Historical untracked pytest/temp artifacts remain preserved and are not
  staged; they are tracked as completion debt rather than treated as product
  output.

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
| Event ledger delivery integration | PASS / LOCKED | PR #569; official monitor regression 27 passed; CI run 31701134871 and security run 31701134916 passed |
| Alert notification identity | PASS / LOCKED | PR #570; 34 targeted tests, Ruff, Mypy and CI run 31701759034/security run 31701759052 passed |
| Alert envelope notification contract | PASS / LOCKED | PR #571; shared AlertEnvelope/schema notification identity; CI run 31705378535 / job 94464483887 and security run 31705378337 passed |
| Intelligence notification schema | PASS / LOCKED | PR #572; unsuppressed unified events require notification identity; CI run 31706330202 / job 94467703595 and security run 31706330210 passed |
| Market provenance contract | PASS / LOCKED | PR #573; quote source/time, domain, crosscheck and technical-context freshness are schema checked; CI run 31707106925 / job 94470318661 passed |
| Research candidate-state contract | PASS / LOCKED | PR #574; available/no-candidates/building/data-unavailable states are separated; CI run 31707956986 / job 94473193712 passed |
| Release manifest integrity | PASS / LOCKED | PR #575; portable artifact paths, rollback identity and ready/rollback exclusivity; targeted artifact tests 32 passed with `-p no:tmpdir`; CI run 31709364212 / job 94478005695 and security run 31709364141 passed |
| Publish-before-notify workflow contract | PASS / LOCKED | PR #576; all production send paths require public release gate and carry release/snapshot receipt lineage; 14 targeted contract tests; CI run 31711585735 / job 94485686912 and security run 31711585721 passed |
| Safe data publishing | PASS / LOCKED | PR #577; path-restricted isolated-index publisher, serialized data writers, Pages restore-before-validation, 23 targeted tests, compileall and diff checks passed; quality run 31713173878 / job 94491106048 and security run 31713173727 passed |
| CI and reproducible environment | PASS / LOCKED | PR #577; 16 targeted CI/security/workflow tests, compileall and diff checks passed; quality run 31714087713 / job 94494236762, security run 31714087668, CodeQL 94494504242 passed |
| P0-08 source health and data gaps | PASS / LOCKED | PR #577; 50 targeted tests, compileall/diff checks, required CI run 31716430943 / job 94502215501, security/CodeQL/SBOM passed |
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
| REQ-P0-11-LEDGER-INTEGRATION | Official delivery records gate/budget suppression reasons | `src/official_event_monitor.py` | 27 targeted tests; Ruff, Mypy and compile pass | PR #569 + CI runs 31701134871/31701134916 | existing safe no-send behaviour preserved | PASS / LOCKED |
| REQ-P0-11-NOTIFICATION-ID | Budget, ledger and compound events share notification identity | `src/alert_budget.py`, `src/external_event_pipeline.py`, `src/event_ledger.py` | 34 targeted tests; Ruff, Mypy and diff checks pass | PR #570 + CI runs 31701759034/31701759052 | existing event key and cooldown preserved | PASS / LOCKED |
| REQ-P0-11-ALERT-ENVELOPE | Alert schema carries shared notification identity | `src/alert_contract.py`, `schemas/alert.schema.json` | targeted envelope/legacy-constructor tests; Ruff, Mypy, compile; PR CI | PR #571; quality run 31704162624 / job 94460383690; security run 31704162607 / job 94460383333 | legacy direct constructors preserved; provenance validation remains required | PASS / LOCKED |
| REQ-P0-11-INTELLIGENCE-SCHEMA | Intelligence schema requires notification identity for unsuppressed unified events | `schemas/intelligence.schema.json`, `src/intelligence_contract.py` | 13 targeted schema/contract/pipeline tests; compile; PR CI | PR #572; quality run 31706330202 / job 94467703595; security run 31706330210 | suppressed parse failures remain visible and non-deliverable | PASS / LOCKED |
| P0-02..P0-29 | Existing continuation requirements | existing modules and prior PRs | evidence not yet reconciled against every DoD | no single current evidence artifact | open reconciliation | NEEDS_REVERIFY |
| REQ-P0-06-DOD-01 | Generated data does not pollute `main` | `.github/workflows/*`, `src/data_release.py` | safe-data-publishing contract tests; no `HEAD:main` publisher push | existing release process preserved | PASS / LOCKED |
| REQ-P0-06-DOD-02 | Data-release writers are serialized and path restricted | `src/data_release.py`, publisher workflows | 9 runtime data-release tests + 14 workflow contract tests | partial publishers preserve parent release tree | PASS / LOCKED |
| REQ-P0-06-DOD-03 | Pages restores and validates immutable release before upload | `.github/workflows/deploy-pages.yml`, P0-06 evidence doc | Pages restore/release-gate contract checks | invalid release cannot replace public data | PASS / LOCKED |
| REQ-P0-07-DOD-01 | Locked dependencies and full quality gates | `pyproject.toml`, `uv.lock`, `.github/workflows/quality.yml` | P0-07 contract tests and CI | P0-01..P0-06 gates preserved | PASS / LOCKED |
| REQ-P0-07-DOD-02 | SHA-pinned actions and supply-chain checks | `.github/workflows/*.yml`, `.github/workflows/security.yml` | immutable-action scan, CodeQL, dependency review, SBOM | no mutable action tags accepted | PASS / LOCKED |

## Regression ledger

| ID | Introduced by | Symptom | Root cause | Fix | Evidence | Status |
|---|---|---|---|---|---|---|
| REG-565-001 | registry import additions | CI Ruff import ordering failure | imports were added below local imports | reordered imports; CI rerun passed | run 31693131665 | CLOSED |
| REG-565-002 | registry optional lookup | CI Mypy union-attr failure | provider lookup was called twice without narrowing | bound optional config before use; CI rerun passed | run 31693131665 | CLOSED |
| REG-P0-08-001 | P0-08 source-health aggregation | An optional adapter record containing only `key` and `status` crashed while building `data_gaps` | Normalize a safe label and map missing credentials to the schema-level `configuration_missing` state before aggregation | 50 targeted source-health/artifact tests; required CI run 31716430943 | CLOSED |
| REG-P0-12-001 | P0-12 multilingual classifier | Mixed-language event records could be evaluated inconsistently across title/body/market fields | Shared normalized haystack and explicit alias contract tests cover Traditional/Simplified Chinese, English, width and spacing | 41 targeted classifier/crosscheck/alert tests; required CI run 31717502438 | CLOSED |
| REG-P0-13-001 | P0-13 source crosscheck | Same-domain or provenance-free reports could be mistaken for independent confirmation | Crosscheck requires normalized anchors, source domains and official plus independent evidence; missing URLs remain pending | 14 targeted crosscheck/evidence tests; required CI run 31718107488 | CLOSED |

## Completion-debt ledger

| Debt ID | Description | Resolution | Status |
|---|---|---|---|
| DEBT-565-001 | Historical untracked pytest/temp artifacts in working tree | preserved; never staged; cleanup requires separate approved maintenance task | OPEN (non-production workspace hygiene) |
| DEBT-565-002 | P0-02..P0-29 evidence reconciliation is incomplete | continue with evidence audit and separate atomic tasks | OPEN |

| DEBT-575-001 | Full local suite cannot create pytest temporary directories because the shared Windows temp root contains permission-denied historical folders | CI Linux full suite passed 1046 tests; local targeted manifest suite used `-p no:tmpdir` and passed 32 tests | OPEN (environment-only; no product failure) |

| DEBT-576-001 | Full local suite still cannot create pytest temporary directories under the inherited Windows temp root | CI full suite and delivery dry-run passed; 14 targeted workflow-contract tests passed locally | OPEN (environment-only; no product failure) |

## Preservation contracts

- PC-001: existing provider routing and fail-closed unknown-source behavior preserved by targeted tests — PASS.
- PC-007: source-health `no_event`, `scan_failed`, and `configuration_missing` remain distinct; incomplete optional metadata cannot crash aggregation — targeted P0-08 tests and required CI run 31716430943 PASS.
- PC-008: existing event classification and strict evidence gates remain intact while multilingual aliases are audited — targeted P0-12 tests and required CI run 31717502438 PASS.
- PC-009: official-source confirmation remains provenance and domain based; same-domain duplicates and missing URLs stay non-deliverable — targeted P0-13 tests and required CI run 31718107488 PASS.
- PC-002: Creator content remains editorial and cannot become market-event evidence — PASS by registry policy/tests.
- PC-003: release-gate and notification code paths remain unchanged except dynamic provider inputs — PASS by CI dry-run.

- PC-004: manifest release/rollback integrity and fail-closed artifact path validation — PASS by PR #575 CI and targeted tests.
- PC-005: production notification cannot precede public release verification — PASS by PR #576 CI and targeted contract tests.
- PC-006: high-frequency data stays on `data-release`, while Pages and release-gated notifications consume a validated release — PASS by P0-06 targeted tests and CI.

## Next gate

Review/merge PR #565 only after human review. Do not merge automatically. After merge, rerun main-branch smoke and production acceptance before claiming completion.

## Gate-Driven P0-21 through P0-29 evidence (2026-08-14)

- P0-21 Mini App routing: 12 targeted tests passed; release, snapshot and
  observation mismatches remain archived/missing; PASS / LOCKED.
- P0-22 timeline and feedback: 12 targeted tests passed; exact event-cluster
  filtering and review-only feedback policy preserved; PASS / LOCKED.
- P0-23/P0-24/P0-26 risk, contagion, stress and advice gates: 23 targeted
  tests passed; missing factors, non-predictive scenarios and insufficient
  evidence remain fail-closed; PASS / LOCKED.
- P0-25/P0-27 research provenance and paper portfolio: 13 targeted tests
  passed; invalid strategy releases and unverified candidates remain blocked;
  PASS / LOCKED.
- P0-28 observability: 31 targeted tests passed; no-event, scan-failed,
  configuration-missing and stale states remain separate; PASS / LOCKED.
- P0-29 backup/rollback/DR: 87 targeted data, manifest, release-gate and
  recovery tests passed; dry-run is non-mutating, restore skips missing
  optional paths, hash tampering fails closed, and rollback identity is
  explicit; PASS / LOCKED.
- Required CI evidence for the atomic P0-29 checkpoint and all preceding
  branch work: quality `31724781388` / job `94530324291` passed in 2m36s;
  CodeQL, dependency review and SBOM all passed (`31724781328`).

These entries are evidence-backed locks, not claims based solely on code
existence. Main-branch post-merge verification and production acceptance
remain separate gates and are not asserted here.

## Migration audit snapshot (2026-08-14)

- Branch: `feat/safe-data-publishing-contract`
- HEAD: `e48bd66`
- Working tree: tracked files clean; pre-existing untracked pytest/temp
  artifacts preserved and not staged.
- Full local regression: `1115 passed, 1 skipped`.
- Compile and syntax: `python -m compileall -q src railway-monitor` and
  `node --check site/app.js` passed.
- Static quality: `uv run ruff check src tests` and `uv run mypy src` passed.
- Latest PR CI after evidence lock: quality run `31725272658` / job
  `94531978943` passed; CodeQL, dependency review and SBOM passed in run
  `31725272661`.
- Runtime audit (non-production mode): executable with warnings only; it
  reports six market source gaps and one building research source.
- Production acceptance: **BLOCKED / NEEDS_EXTERNAL_RELEASE**. The checked-out
  artifacts do not contain a ready event snapshot and complete production
  research release, so the fail-closed audit correctly refuses publication.
- Delivery smoke: **BLOCKED / NEEDS_RUNTIME_CONFIGURATION**. No
  `TELEGRAM_CHAT_IDS` are present in this local environment; no Telegram or
  Railway side effect was attempted.

These two blocks are environment evidence gaps, not reasons to weaken a gate
or to synthesize data. They must be cleared by a real data-release workflow
and protected runtime configuration after the PR is merged.

## Migration audit snapshot (2026-08-14, News Intelligence contract)

- Active branch: `feat/safe-data-publishing-contract`
- Recovery checkpoint: `checkpoint/migration-2026-08-14` remains available.
- Atomic commits: `fb4cd52` (canonical provider/story/interest/ranking/dedup
  contract) and `5e83ad7`/`e2351a9` (release-bound artifact and registry
  validation coverage).
- Local full regression: `1121 passed, 1 skipped`; compileall, Node syntax,
  Ruff and Mypy passed. The Windows shared temporary directory has a known
  permission-denied `build_assets` fixture failure; this is recorded as an
  environment debt and does not alter product assertions.
- Targeted News/release regression: `31 passed`; core local coverage reached
  90% before the environment-only fixture failure.
- CI evidence: PR #577 quality run `31730398078` and security run
  `31730398127` completed successfully after the News contract commits.
- News provider registry/ranking/dedup: PASS / LOCKED for the deterministic
  contract and local/CI tests. Official-feed ingestion adapters and live
  Pages rendering remain NEEDS_REVERIFY, not production acceptance.
- Production release acceptance and Telegram/Railway delivery remain
  BLOCKED until a real ready data release and protected runtime configuration
  are available. No production side effect was attempted.

## Migration audit update (2026-08-14, official news adapters)

- Atomic commit `c0b3b7c` adds isolated TWSE/MOPS/SEC/Federal Reserve feed
  adapters and wires the official-first path into `risk_news.fetch_market_news`.
- Atomic commit `707e118` resolves the CodeQL URL-taint finding in the adapter
  regression fixture; the latest head checks are all green.
- Nasdaq remains explicitly disabled because no stable documented public feed
  endpoint is configured; no undocumented endpoint is inferred.
- Provider failures, XML/JSON parse errors and HTTP 429 are captured per
  provider and do not prevent other providers or the Anue/Google fallback.
- Targeted adapter/news/release tests: `54 passed`.
- Full local regression after integration: `1128 passed, 1 skipped`.
- Full static checks: Ruff, Mypy, compileall and Mini App JavaScript syntax
  passed. Latest PR #577 quality and current security jobs passed; an older
  external CodeQL status remains visible on the PR but is not associated with
  the current commit.
- Live official feed, Pages publication, Railway and Telegram delivery remain
  `NEEDS_REVERIFY`/`BLOCKED` until a real ready release and protected runtime
  configuration are available.

## Migration audit update (2026-08-14, News release-gate lineage)

- `release_manifest` now records `news_snapshot_id` and `news_status` whenever
  the canonical News Intelligence artifact is published.
- Local and public release-gate loaders verify `news.json` hash, provider
  domains, market snapshot lineage and News snapshot identity before delivery.
- A mismatched News market snapshot is rejected by the gate; the fail-soft
  collection path remains unchanged when no News artifact is available.
- Targeted release/news gate suite: `51 passed`; full local regression:
  `1129 passed, 1 skipped`; Ruff, Mypy and Mini App syntax checks passed.
- News artifact lineage is now `PASS / LOCKED`; Mini App browser publication,
  live Pages release and protected production delivery remain external gates.
