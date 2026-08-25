# P0 requirement traceability registry

This registry is deliberately evidence-driven. `PASS / LOCKED` is reserved for
rows with implementation, required verification, regression evidence, and
preservation evidence. A row with code or an old PR but no current objective
evidence remains `NEEDS_REVERIFY`.

The machine-readable counterpart is [`config/gate_evidence.json`](../config/gate_evidence.json),
validated by [`scripts/verify_gate_evidence.py`](../scripts/verify_gate_evidence.py).
It keeps local contract locks separate from the external completion-debt ledger;
the default audit therefore reports `needs_reverify` while Gmail, Railway,
Pages or Telegram evidence is still open. `--strict` is reserved for the final
production/merge gate and fails closed until both ledgers contain no `OPEN`
entries.

| Requirement | Task / implementation | Verification and evidence | Regression / preservation | Status |
|---|---|---|---|---|
| P0-01 artifact schema and cross-field invariants | `src/artifact_contract.py`, `schemas/*.schema.json` | PR #575 targeted artifact suite 32; CI quality/security | release gate and legacy artifact compatibility | PASS / LOCKED |
| P0-02 market provenance semantics | `src/market_data.py`, market provenance contract | PR #573 targeted + CI 31707106925 | TAIEX/TPEx stale and crosscheck behavior | PASS / LOCKED |
| P0-03 research candidate state | `src/research_state.py`, research schemas | PR #574 targeted + CI 31707956986 | building/no-candidates/data-unavailable separation | PASS / LOCKED |
| P0-04 release manifest | `src/release_manifest.py`, release schema | PR #575 targeted + CI 31709364212 | rollback identity and hash validation | PASS / LOCKED |
| P0-05 publish before notify | workflow contracts and `src/release_gate.py` | PR #576 targeted + CI 31714451717 | no delivery before public release | PASS / LOCKED |
| P0-06 safe data publishing | `src/data_release.py`, data writer workflows | PR #577 targeted 23; CI 31714451717 | data stays off main; Pages restore | PASS / LOCKED |
| P0-07 reproducible CI and security | `pyproject.toml`, `uv.lock`, quality/security workflows | PR #577 targeted 16; CI quality/security/CodeQL/SBOM | no mutable actions, locked dependencies | PASS / LOCKED |
| P0-08 source health and data gaps | `src/source_health.py`, `src/artifact_contract.py`, health schemas | 50 targeted source-health/artifact tests; caught and fixed missing-label aggregation crash; compileall/diff checks passed; required CI 31716430943, security/CodeQL/SBOM passed | source failure vs no-event separation; configuration gap remains distinct | PASS / LOCKED |
| P0-09 event source and intelligence fan-out | external parsers/pipeline/intelligence | FinancialJuice targeted suites and PR history | unresolved envelopes remain fail-closed | PASS / LOCKED |
| P0-10 vendor priority boundary | `src/financialjuice_contract.py` | 8/10 and 7/10 targeted policy tests | vendor priority cannot alter PRStK risk | PASS / LOCKED |
| P0-11 event ledger and notification identity | ledger, budget, alert envelope | PR #569–#572 targeted + CI | cooldown/suppression lineage preserved | PASS / LOCKED |
| P0-12 multilingual event matching | `src/event_classifier.py`, `config/event_keywords.json` | 41 targeted classifier/crosscheck/alert tests; multilingual, Unicode and explicit no-match contract passed; required CI 31717502438, security/CodeQL/SBOM passed | keyword match cannot bypass official or market-sync gates | PASS / LOCKED |
| P0-13 official/source crosscheck | `src/event_crosscheck.py`, `src/event_evidence.py` | 14 targeted crosscheck/evidence tests; official plus independent domain, same-domain and missing provenance cases passed; required CI 31718107488, security/CodeQL/SBOM passed | fail closed without required evidence | PASS / LOCKED |
| P0-14 market synchronization evidence | `tests/test_p0_14_market_sync_contract.py` | `4d71e54`; targeted 30 passed; required CI quality run 31718964237 / job 94510770579; security/CodeQL/SBOM passed | fresh timestamp-aligned market evidence is required; oil/Brent/WTI uses the 5% threshold; graph remains conditional without sync | PASS / LOCKED |
| P0-15 release freshness and stale quote gate | `src/market_data.py`, `src/release_gate.py`, `tests/test_p0_15_freshness_gate_contract.py` | targeted 72 passed with isolated basetemp; quality run 31719716607 / job 94513312331; security/CodeQL/SBOM passed | stale/recent-close data remains visible but cannot alert; non-fresh research cannot pass strict release gate | PASS / LOCKED |
| P0-16 Telegram delivery receipt | `src/telegram_client.py`, `src/creator_photo_delivery.py`, `src/delivery_callback.py`, `tests/test_p0_16_delivery_receipt_contract.py` | 36 targeted delivery/photo/Telegram tests; quality run 31720218621 / job 94515038872; security/CodeQL/SBOM passed | release/snapshot/alert lineage; hashed recipients; per-recipient isolation | PASS / LOCKED |
| P0-17 creator photo delivery | `src/creator_photo_delivery.py`, `src/creator_notification.py`, `src/alert_card_renderer.py`, `tests/test_p0_17_creator_photo_contract.py` | 24 targeted photo/renderer/notification tests; quality run 31720774828 / job 94516916801; security/CodeQL/SBOM passed | renderer/media failure is explicit and never sends a blank/black photo; text degradation keeps lineage | PASS / LOCKED |
| P0-18 external alert trust boundary | `src/external_alert.py`, `tests/test_p0_18_external_alert_contract.py` | CI run `31721326422` / job `94518750439` green; targeted 19 passed | signed canonical payload; HTTPS provenance; official/market-sync high-risk gate | PASS → LOCKED |
| P0-19 Gmail ingress | `railway-monitor/gmail_ingress.py`, `railway-monitor/email_store.py`, `tests/test_p0_19_gmail_ingress_contract.py` | targeted 20 passed; CI run `31722239089` / job `94521788534` green; security/CodeQL/SBOM passed | authenticated bounded Pub/Sub; cursor-only persistence; replay-safe dedupe; malformed/configuration failures fail closed | PASS → LOCKED |
| P0-20 Railway health callback | `src/railway_health_contract.py`, `tests/test_p0_20_railway_health_contract.py` | targeted 7 passed with isolated basetemp; CI run `31722834875` / job `94523793185` green; security/CodeQL/SBOM passed | 401/403 configuration is not restart; 429/5xx are bounded retry; stale heartbeat is explicit | PASS → LOCKED |
| P0-21 Mini App release/deep-link | `src/deep_link_router.py`, public loader | `tests/test_p0_21_mini_app_routing_contract.py`; 12 targeted; CI run 31724781388 / job 94530324291 | release mismatch and missing alerts stay archived/missing | PASS / LOCKED |
| P0-22 event timeline and feedback | `src/event_timeline.py`, `src/event_feedback.py` | `tests/test_p0_22_timeline_feedback_contract.py`; 12 targeted; CI run 31724781388 / job 94530324291 | feedback cannot mutate policy automatically | PASS / LOCKED |
| P0-23 market regime/contagion | `src/market_regime.py`, `src/cross_asset_risk.py` | `tests/test_p0_23_26_risk_advice_contract.py`; 23 targeted; CI run 31724781388 / job 94530324291 | missing factors and stale contagion remain explicit | PASS / LOCKED |
| P0-24 stress scenario | `src/stress_scenarios.py` | same 23-test risk/advice contract suite; CI run 31724781388 / job 94530324291 | scenarios remain non-predictive | PASS / LOCKED |
| P0-25 strategy registry and explainability | `src/strategy_registry.py`, production provenance | `tests/test_p0_25_27_research_contract.py`; 13 targeted; CI run 31724781388 / job 94530324291 | invalid strategy provenance remains blocked | PASS / LOCKED |
| P0-26 advice gate | `src/advice_gate.py` | same 23-test risk/advice contract suite; CI run 31724781388 / job 94530324291 | no actionable output without fresh evidence/backtest | PASS / LOCKED |
| P0-27 paper portfolio | `src/paper_portfolio.py` | same 13-test research contract suite; CI run 31724781388 / job 94530324291 | unverified candidates cannot enter paper tracking | PASS / LOCKED |
| P0-28 source and release observability | `src/health_observability.py`, source-health/release metrics | `tests/test_p0_28_observability_contract.py`; 31 targeted; CI run 31724781388 / job 94530324291 | no-event, scan-failed and configuration gaps remain distinct | PASS / LOCKED |
| P0-29 backup, rollback, and disaster recovery | `src/data_release.py`, manifest/release gate | `tests/test_p0_29_backup_rollback_contract.py` plus data/release suites; 87 targeted; CI run 31724781388 / job 94530324291 | non-mutating dry-run, restore drill, hash tamper detection and rollback identity | PASS / LOCKED |

## Gate

Rows marked `NEEDS_REVERIFY` are open completion debt. They are not a product
failure by themselves, but they block a final `COMPLETE` claim and the merge
gate until the listed evidence is captured.

## Current external-gate debt

All P0 rows above have implementation and branch-level verification evidence.
The final migration audit is nevertheless **INCOMPLETE** until these external
gates are cleared:

| Debt | Evidence | Status |
|---|---|---|
| Production release acceptance | Public Pages manifest `release-957714e850293f39` is `ready`; six declared public artifact hashes matched | NEEDS_REVERIFY on latest main; post-merge Mini App visual acceptance remains |
| Telegram/Railway delivery acceptance | Actions photo smoke run `31839093636` / job `94891873503`; one scoped recipient; Railway receipt `delivered`, `receipt_matches=true` | NEEDS_REVERIFY on latest main; Railway GDELT `HTTP_429` and dispatch `HTTP_403` remain open runtime issues |

No production notification, secret access, or data fabrication was used to
make these checks green.

## 2026-08-25 continuation evidence

The canonical overlap checkpoint is documented in
`docs/canonical-overlap-checkpoint-20260825.md`. PRs #757–#761 form one
stacked architecture: shared classification is used by both news and live
events, while the external acceptance probe now verifies that the reviewed
Railway observation set is the same set represented by the public release
manifest. This is still local/branch evidence; the external rows above remain
`NEEDS_REVERIFY` until a controlled post-merge Railway, Pages and
single-recipient Telegram run is captured.

### 2026-08-25 Railway health-history durability evidence

The bounded source-health projection is now durable across Railway monitor
restarts. `railway-monitor/health_history_store.py` persists only aggregate
states, counters and component labels in the existing SQLite state volume;
`health_state.restore_health_history()` restores at most 168 chronological
samples before the first health response. Schema migration is additive for
existing volumes and SQLite write failures remain non-fatal to polling.

Verification on the continuation branch:

- health-history/store/monitor targeted suite: **104 passed**;
- full repository regression: **1444 passed**;
- Ruff, compileall, mypy and the offline production E2E gate: **passed**;
- the latest manual Quality and Security Actions runs on commit `9310614`:
  [Quality run 32824397226](https://github.com/hanjhou2000716/prstklab-stk-detector/actions/runs/32824397226),
  [Security run 32824401282](https://github.com/hanjhou2000716/prstklab-stk-detector/actions/runs/32824401282).

This is branch-level evidence only. Live Railway volume continuity and the
post-merge Pages/Mini App/Telegram acceptance gates remain `NEEDS_REVERIFY`.

### 2026-08-25 read-only external acceptance refresh

The public Railway health endpoint and Pages release were probed again after
the durable health-history change. The redacted capture is retained at
[`docs/evidence/external-acceptance-2026-08-25T0820Z.json`](evidence/external-acceptance-2026-08-25T0820Z.json).
Railway returned HTTP 200 with a running monitor, healthy heartbeat, healthy
Jin10 and Gmail Watch, and the canonical shared-secret name active without
exposing values. Pages returned `status=ready`; all five declared artifact
hashes and market/research/event snapshot bindings matched.

This evidence does **not** close the external gate: GDELT remained explicitly
`HTTP_429`, the last aggregate delivery receipt was partial (4 of 7), and the
public health projection cannot prove durable Railway volume continuity. No
Telegram message, Railway write, configuration change, or credential access
was performed by this probe.
