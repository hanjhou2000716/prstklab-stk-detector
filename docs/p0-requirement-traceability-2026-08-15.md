# P0 requirement traceability — Gate-Driven migration audit (2026-08-15)

This document is the migration-era reconciliation of the original P0-01 through
P0-29 requirements. It does not replace the canonical contracts or create a
second implementation. `PASS` means the repository has implementation,
required local/CI verification, regression coverage, and preservation evidence
for that boundary. Production acceptance is recorded separately and never
inferred from a green pull request.

## Current snapshot

| Item | Evidence |
|---|---|
| Repository checkout | `current-main`, branch `feat/REQ-ADD-045-classifier-health-provenance` |
| Migration base | `57eabb0d7369b42c519d3c6e6371fec1e8ff85a4` (`main` at migration start) |
| Recovery checkpoint | tag `migration-checkpoint-20260814-8e1ad7f` |
| Working tree | tracked files clean before this documentation change; `git diff --check` required before commit |
| Local regression | 1,246 passed, 1 skipped in an isolated system temp directory |
| Runtime audit | `ok=true`, no invariant issues; production warnings remain explicit |
| Delivery smoke | fail-closed because local `TELEGRAM_CHAT_IDS` is intentionally absent |
| Production release | public Pages manifest is `ready`; release/hash/lineage verified read-only on 2026-08-15 |

Post-PR-609 verification on this checkout: `runtime_audit` returned `ok=true`
with no invariant issues; `compileall` and `node --check site/app.js` passed.
`delivery_smoke_test` correctly returned `ok=false` with the explicit
configuration error `TELEGRAM_CHAT_IDS is empty`; no production notification was
sent. The runtime warnings (market source gaps, research building state, and
missing/not-ready production snapshots) remain visible and are not relabeled as
success.

Post-REQ-ADD-032 verification: the raw-observation retry fixture passed alongside
the production-evidence and market-refresh persistence tests (17 passed); Ruff,
Mypy, compileall and the isolated full regression all passed (1,224 passed).
The retry is bounded and only applies to transient Windows file locks and SQLite
busy/locked errors; non-retryable failures still return the existing unavailable
state and keep the alert/release gates fail-closed.

Public Pages evidence captured on 2026-08-15 (read-only):

- `https://hanjhou2000716.github.io/prstklab-stk-detector/` and `app.js` returned
  HTTP 200; the app contains manifest loading, retry and fallback paths.
- `data/release-manifest.json` returned `status=ready`, release
  `release-957714e850293f39`, market snapshot `c7466b534b3d117e`, research
  snapshot `research-8b8ec8f6e5ee51aa`, and event snapshot
  `event-f67c25c9f5e6f24d`.
- `market.json`, `research-report.json`, `event-ledger.json`, `source-health.json`,
  `creator-release.json`, and `creator-insights.json` all returned HTTP 200 and
  matched the manifest SHA-256 hashes. Their public snapshot identifiers matched
  the manifest lineage; no private fields were accessed.

Railway read-only health evidence captured on 2026-08-15:

- `/health` returned HTTP 200 with a running monitor and healthy Jin10 poller.
- The live deployment still reported `classifier_mode=standalone-bundled` and
  was based on the earlier PR #619 deployment; canonical classifier provenance
  remains pending deployment of PR #624.
- GDELT reported `HTTP_429`; the health callback reported `HTTP_403`.
- Delivery was `not_checked` with no receipt trace, and Gmail/Creator ingress
  was `configuration_missing`. No production recipient was contacted.

## Requirement / evidence matrix

`Local verdict` is the strongest evidence available in the repository. `External
gate` is deliberately separate for Pages, Railway, live feeds, and Telegram.
The final migration status cannot be `COMPLETE` while any required external gate
is pending.

| Requirement / DoD IDs | Canonical owner | Existing PR lineage | Local verification | External gate / evidence | Preservation & regression | Status |
|---|---|---|---|---|---|---|
| P0-01 / `REQ-P0-01-DOD-01..03` | `src/artifact_contract.py`, `schemas/*.schema.json` | #575 | artifact and invariant suites | ready release manifest still needs live confirmation | release-gate compatibility | PASS |
| P0-02 / `REQ-P0-02-DOD-01..03` | `src/market_data.py`, market provenance contract | #573 | provenance, stale, crosscheck tests | TWSE/TPEx live freshness pending | stale quotes remain visible but non-alertable | PASS |
| P0-03 / `REQ-P0-03-DOD-01..03` | `src/research_state.py`, research schemas | #574 | candidate-state contract tests | current public research release must be rebuilt | building/no-candidates/data-unavailable remain distinct | PASS |
| P0-04 / `REQ-P0-04-DOD-01..03` | `src/release_manifest.py`, release schema | #575 | hash, rollback, manifest tests | public Pages ready manifest, six artifact hashes and snapshot lineage verified 2026-08-15 | invalid release cannot overwrite prior good release | PASS |
| P0-05 / `REQ-P0-05-DOD-01..03` | `src/release_gate.py`, publish workflows | #576 | publish-before-notify tests | public URL propagation evidence pending | notification remains blocked before gate | PASS |
| P0-06 / `REQ-P0-06-DOD-01..03` | `src/data_release.py`, data-release workflows | #577 | branch/write-order tests | data-release deployment evidence pending | main is not used as high-frequency store | PASS |
| P0-07 / `REQ-P0-07-DOD-01..03` | `pyproject.toml`, `uv.lock`, quality/security workflows | #577, #603 | locked CI, Ruff, type/compile checks | Actions rerun on merged main pending | no mutable action tags in required workflows | PASS |
| P0-08 / `REQ-P0-08-DOD-01..03` | `src/source_health.py`, health schemas | #582, #600, #601 | source-health and gap-state suites | Railway/Pages health history pending | no-event is not scan-failed | PASS |
| P0-09 / `REQ-P0-09-DOD-01..03` | `src/external_source_parsers.py`, `src/intelligence_pipeline.py` | #566, #569, #606 | compound/event fan-out and privacy suites | sanitized runtime ingress pending | unresolved envelopes fail closed | PASS |
| P0-10 / `REQ-P0-10-DOD-01..04` | `src/financialjuice_contract.py` | #568 | 7/8/9/10 priority boundary tests | production FJ receipt pending | vendor priority cannot alter PRStK risk | PASS |
| P0-11 / `REQ-P0-11-DOD-01..03` | event ledger, `src/alert_budget.py`, `src/alert_contract.py` | #570–#572, #589 | identity, cooldown, suppression tests | live receipt lineage pending | deduplication preserved | PASS |
| P0-12 / `REQ-P0-12-DOD-01..03` | `src/event_classifier.py`, `config/event_keywords.json` | prior P0 stack | multilingual/Unicode/no-match tests | live source freshness pending | keyword match cannot bypass evidence gates | PASS |
| P0-13 / `REQ-P0-13-DOD-01..03` | `src/event_crosscheck.py`, `src/event_evidence.py` | prior P0 stack | official/independent-domain tests | live official feed confirmation pending | same-domain evidence is insufficient | PASS |
| P0-14 / `REQ-P0-14-DOD-01..03` | market-sync contract and evidence graph | prior P0 stack | 30 market-sync tests | live synchronized snapshots pending | no market sync means conditional only | PASS |
| P0-15 / `REQ-P0-15-DOD-01..03` | freshness gate in `src/market_data.py`, `src/release_gate.py` | prior P0 stack | 72 freshness tests | production quote freshness pending | stale/delayed quotes cannot alert | PASS |
| P0-16 / `REQ-P0-16-DOD-01..03` | `src/telegram_client.py`, receipt/callback modules | #571, #588, #595, #596 | 36 delivery/photo tests | one-recipient signed receipt pending | per-recipient isolation preserved | NEEDS_REVERIFY |
| P0-17 / `REQ-P0-17-DOD-01..03` | `src/creator_photo_delivery.py`, `src/alert_card_renderer.py` | prior P0 photo-delivery stack | renderer/notification fixtures | real 1080x1350 photo delivery pending | renderer failure never sends blank card | NEEDS_REVERIFY |
| P0-18 / `REQ-P0-18-DOD-01..03` | `src/external_alert.py` | prior P0 stack | signed canonical payload tests | external alert ingress evidence pending | official + market-sync high-risk gate | PASS |
| P0-19 / `REQ-P0-19-DOD-01..03` | `railway-monitor/gmail_ingress.py`, email store | prior P0 stack | authenticated cursor/replay tests | Gmail/Railway runtime evidence pending | private message content stays out of public artifacts | NEEDS_REVERIFY |
| P0-20 / `REQ-P0-20-DOD-01..03` | `src/railway_health_contract.py` | #584, #591, #601 | 401/403/429/5xx health tests | Railway callback/heartbeat evidence pending | auth failure is not restart | NEEDS_REVERIFY |
| P0-21 / `REQ-P0-21-DOD-01..03` | `src/deep_link_router.py`, `site/app.js` | #578, #579, #603 | deep-link and release mismatch tests | browser proof against current Pages release pending | old release falls back safely | NEEDS_REVERIFY |
| P0-22 / `REQ-P0-22-DOD-01..03` | `src/event_timeline.py`, `src/event_feedback.py` | #586, #587 | timeline/feedback tests | Mini App interaction evidence pending | feedback cannot mutate policy automatically | NEEDS_REVERIFY |
| P0-23 / `REQ-P0-23-DOD-01..03` | `src/market_regime.py`, `src/cross_asset_risk.py` | existing risk stack | factor/contagion tests | live multi-asset snapshot pending | missing factors remain explicit | PASS |
| P0-24 / `REQ-P0-24-DOD-01..03` | `src/stress_scenarios.py` | existing risk stack | scenario safety tests | public risk page evidence pending | scenarios are non-predictive | PASS |
| P0-25 / `REQ-P0-25-DOD-01..03` | `src/strategy_registry.py`, research provenance | #574 and research stack | strategy/explainability tests | complete point-in-time release pending | invalid provenance blocks candidates | NEEDS_REVERIFY |
| P0-26 / `REQ-P0-26-DOD-01..03` | `src/advice_gate.py` | existing advice stack | advice refusal and freshness tests | no production recommendation surface opened | no actionable output without evidence | PASS |
| P0-27 / `REQ-P0-27-DOD-01..03` | `src/paper_portfolio.py` | existing research stack | paper-tracking contract tests | point-in-time candidate release pending | unverified candidates cannot enter tracking | NEEDS_REVERIFY |
| P0-28 / `REQ-P0-28-DOD-01..03` | `src/health_observability.py`, source/release metrics | #580–#603 | observability contract and runtime audit | Pages/Railway history pending | no-event, failure, and config gaps separated | NEEDS_REVERIFY |
| P0-29 / `REQ-P0-29-DOD-01..03` | `src/data_release.py`, manifest/release gate | #575–#577 | backup/restore/hash tamper suites | restore drill on production store pending | rollback remains non-mutating | NEEDS_REVERIFY |

## Preservation contracts

The following contracts remain in scope for every subsequent PR. A change that
breaks one reopens the affected task and must rerun its original evidence.

| ID | Protected behavior | Current evidence |
|---|---|---|
| PC-001 | market collection, freshness, and fail-closed alert gates | local full regression + runtime audit |
| PC-002 | research state separation and strict value rules | research contract fixtures |
| PC-003 | release manifest/hash/rollback semantics | release gate tests |
| PC-004 | Mini App routing and release mismatch safety | deep-link contract tests; browser acceptance pending |
| PC-005 | Telegram deduplication, per-recipient isolation, and receipt lineage | mock E2E; controlled recipient pending |
| PC-006 | Railway health/auth/retry semantics | local contract tests; live callback pending |
| PC-007 | Gmail/private-source boundary and public artifact sanitization | privacy regression suites |
| PC-008 | no automated trading, no secrets in artifacts, no invented market evidence | schema/privacy/security tests |

## Open regression and completion debt

| ID | Description | Required resolution | Status |
|---|---|---|---|
| REG-EXT-001 | Railway Creator/FJ ingress and delivery receipt not proven live | controlled Railway run with sanitized bundle | OPEN / EXTERNAL |
| REG-EXT-002 | Pages ready release/hash/lineage not proven publicly | public manifest and six artifact hashes/lineage verified 2026-08-15 | CLOSED |
| REG-EXT-003 | Telegram production photo/deep-link/receipt not proven | one approved test recipient only | OPEN / EXTERNAL |
| DEBT-NEWS-001 | official feed freshness and market split live evidence | source-health capture for TWSE/MOPS/SEC/Fed | OPEN / EXTERNAL |
| DEBT-FJ-001 | FinancialJuice sanitized runtime bundle not observed in Railway | configure reviewed bundle and capture release evidence | OPEN / EXTERNAL |
| DEBT-CREATOR-001 | late Creator delivery/photo receipt not proven | controlled single-recipient retry/dedupe test | OPEN / EXTERNAL |

No debt above is hidden by changing a test, weakening a gate, or fabricating a
release. These are the remaining external acceptance steps, not reasons to
reimplement the canonical local pipeline.

## Merge and continuation policy

The existing Creator/FJ/news/release stack remains canonical. This PR is
documentation-only and intentionally does not add another classifier, source
adapter, or delivery path. Merge the existing stacked branches in their
declared dependency order; keep intermediate branches until the final main
verification. After each merge, rerun the targeted contract and preservation
tests, then capture Pages/Railway/Telegram evidence before closing the external
debt rows above.

Rollback for this PR is a single revert of the documentation commit; it has no
runtime or data-release side effect.
