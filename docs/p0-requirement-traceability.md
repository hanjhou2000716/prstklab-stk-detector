# P0 requirement traceability registry

This registry is deliberately evidence-driven. `PASS / LOCKED` is reserved for
rows with implementation, required verification, regression evidence, and
preservation evidence. A row with code or an old PR but no current objective
evidence remains `NEEDS_REVERIFY`.

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
| P0-14 market synchronization evidence | market impact and sync gates | Current evidence audit pending | no fabricated direction/percentage | NEEDS_REVERIFY |
| P0-15 release freshness and stale quote gate | freshness/release gate modules | Current evidence audit pending | stale data cannot alert | NEEDS_REVERIFY |
| P0-16 Telegram delivery receipt | Telegram client and receipt schema | Existing dry-run; production evidence pending | recipient isolation and retry | NEEDS_REVERIFY |
| P0-17 creator photo delivery | `src/creator_photo_delivery.py` | Offline contract tests; production evidence pending | media degraded never sends black card | NEEDS_REVERIFY |
| P0-18 external alert trust boundary | external alert validation | Current evidence audit pending | signature and provenance required | NEEDS_REVERIFY |
| P0-19 Gmail ingress | cursor/JWT/intelligence gateway | Existing targeted tests; current audit pending | no duplicate ingress and privacy boundary | NEEDS_REVERIFY |
| P0-20 Railway health callback | health contract/monitor | Existing tests; current audit pending | callback failure cannot crash poller | NEEDS_REVERIFY |
| P0-21 Mini App release/deep-link | public loader/deep link | Existing tests; current audit pending | release mismatch safe fallback | NEEDS_REVERIFY |
| P0-22 event timeline and feedback | timeline/feedback modules | Existing tests; current audit pending | feedback cannot mutate policy automatically | NEEDS_REVERIFY |
| P0-23 market regime/contagion | regime and cross-asset modules | Existing tests; current audit pending | missing factors remain explicit | NEEDS_REVERIFY |
| P0-24 stress scenario | stress scenario module | Existing tests; current audit pending | scenario is non-predictive | NEEDS_REVERIFY |
| P0-25 strategy registry and explainability | strategy/backtest registry | Existing tests; current audit pending | no advice before valid backtest | NEEDS_REVERIFY |
| P0-26 advice gate | `src/advice_gate.py` | Existing tests; current audit pending | fail closed with data shortage | NEEDS_REVERIFY |
| P0-27 paper portfolio | paper portfolio module | Existing tests; current audit pending | no unverified performance claims | NEEDS_REVERIFY |
| P0-28 source and release observability | source health/manifest/receipt metrics | Existing tests; current audit pending | SLO and delivery lineage preserved | NEEDS_REVERIFY |
| P0-29 backup, rollback, and disaster recovery | release branch and runbooks | P0-04/P0-06 evidence; restore drill pending | no destructive main/data deletion | NEEDS_REVERIFY |

## Gate

Rows marked `NEEDS_REVERIFY` are open completion debt. They are not a product
failure by themselves, but they block a final `COMPLETE` claim and the merge
gate until the listed evidence is captured.
