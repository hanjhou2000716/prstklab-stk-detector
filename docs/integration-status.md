# PRStK production integration matrix

This inventory distinguishes code that exists from code that is actually
called by the release pipeline and displayed or delivered to a user.  A
module is `production` only when it has a producer, an artifact contract, a
pipeline call and a tested consumer.

| Module | File(s) | Tests | Pipeline | JSON | Mini App | Telegram | Status |
|---|---|---|---|---|---|---|---|
| Source adapters | `src/source_adapter.py`, `src/adapters/catalog.py`, `src/phase_two_sources.py` | yes | yes | yes | health | event/brief | production |
| Raw observation store | `src/raw_observation_store.py`, `src/production_evidence.py` | yes | optional market snapshot hook | quality metadata | no raw payload | no | partially_integrated |
| Instrument master | `src/instrument_master.py` | yes | partial | partial | no | no | partially_integrated |
| Data quality/SLA | `src/data_quality.py`, `src/source_health.py` | yes | yes | yes | yes | gate reason | production |
| Taiwan crosscheck | `src/taiwan_market_crosscheck.py`, `src/market_crosscheck.py` | yes | yes | yes | yes | price gate | production |
| Event source catalog | `src/event_source_catalog.py` | yes | yes | yes | health | event | production |
| Event cluster/ledger | `src/event_ledger.py`, `src/event_output.py` | yes | yes | yes | timeline | event | production |
| Event evidence state | `src/event_evidence.py`, `src/event_crosscheck.py` | yes | yes | yes | wait reason/timeline | lifecycle gate | production |
| Macro surprise | `src/surprise_engine.py`, `src/intelligence_pipeline.py` | yes | yes | yes | yes | no | production |
| Corporate events | `src/corporate_event_contract.py`, `src/official_events.py` | yes | yes | yes | yes | observe-only/event | production |
| Market impact graph | `src/market_impact_graph.py`, `src/intelligence_pipeline.py` | yes | yes | yes | briefing/event | conditional event | production |
| Alert budget/lifecycle | `src/alert_budget.py`, `src/event_alerts.py`, `src/event_ledger.py` | yes | scheduled/official/emergency | delivery history | suppression reason | all alert paths | production |
| Market regime/contagion | `src/market_regime.py`, `src/cross_asset_risk.py`, `src/intelligence_pipeline.py` | yes | yes | yes | briefing | briefing context | production |
| Stress scenarios | `src/stress_scenarios.py`, `src/intelligence_pipeline.py` | yes | yes | yes | briefing | context only | production |
| Portfolio risk | `src/portfolio_risk.py` | yes | no | no | no | no | unused |
| Paper portfolio | `src/paper_portfolio.py` | yes | yes | briefing | briefing | no | production |
| Strategy scans | `src/run_*scan.py`, `src/research_report.py` | yes | yes | yes | yes | briefing/research | production |
| Strategy registry/explainability | `src/strategy_registry.py`, `src/advice_gate.py` | yes | partial | partial | partial | no | partially_integrated |
| Backtest/cost model | `src/four_strategy_walk_forward.py`, `src/backtest_costs.py`, `src/backtest_release.py` | yes | scheduled | artifact + risk-adjusted metrics | no | no | partially_integrated |
| Release manifest/gate | `src/release_manifest.py`, `src/release_gate.py`, `src/production_e2e.py` | yes | yes | yes | loader gate | send gate | production |
| Telegram delivery | `src/telegram_client.py`, `src/scheduled_delivery.py`, `src/official_event_monitor.py`, `src/emergency_alert.py` | yes | release-gated `sendPhoto` path with shared file ID | photo receipt | alert/release deep-link button | renderer failure is fail-closed; recipient failures are isolated | production |
| Mini App deep-link/timeline | `site/app.js`, `src/event_timeline.py` | yes | Pages | yes | yes | button target | production |
| Feedback/paper portfolio | `src/event_feedback.py`, `src/production_evidence.py` | yes | briefing contract + optional endpoint/local queue | yes | feedback controls | no | partially_integrated |

## Data state contract

Market artifacts expose `overall_state` plus counts.  The aggregate is based
on each quote's classified freshness, never on fetch time alone:

- `live`: all available observations are live;
- `mixed`: live and recent-close observations coexist;
- `close_only`: only recent closes are available;
- `degraded`: stale or unavailable observations exist;
- `unavailable`: no usable observation exists.

Research artifacts expose both the legacy fields (`candidates`,
`formal_candidates`) and explicit count fields.  When a scan is still building
but has validated rows, `candidate_state=available_from_completed_records`;
when its output is missing, candidate counts are suppressed and the state is a
data gap.  This prevents a summary file from making an unavailable CSV look
like a formal candidate release.

## Production research publication gate

Production workflows invoke `src.release_manifest` with
`--require-production-research`. A report must declare
`scan_mode=production`, `scan_scope=full`, both eligibility flags, and complete
every declared universe and source before a `ready` manifest can be published.
Bounded, smoke, failed, or building scans remain diagnostic artifacts and
cannot silently become a research release. If a previously valid production
report is reused while a new scan is incomplete, the workflow may explicitly
mark `research_fallback_used=true` and `research_freshness=stale_fallback`;
legacy or contract-incomplete reports remain blocked. This prevents a market
refresh from combining a new market snapshot with an unverified historical
research file.

## Investor-facing disclosure contract

The Mini App keeps investor content and engineering evidence in separate
disclosures. `市場定時報告` is expanded on first load so the current briefing
is immediately readable. `系統分析資料` and `市場情報證據` are collapsed by
default and contain observation, snapshot, trace, provenance, regime and
cross-asset details only when a valid report provides them. Source health is
also collapsed by default; its summary uses one aggregate state (`資料正常`,
`部分資料降級`, or `核心資料不足`) and the expanded rows carry the individual
source state. VIX investor cards show the value, change, stage and an available
historical percentile without exposing fetch timestamps or unavailable-data
placeholders; raw freshness remains in the JSON provenance fields.

## Migration and rollback

The new fields are additive and readers continue to accept the legacy fields.
The release manifest normalizer converts legacy gap maps to integer counts and
backfills candidate state without inventing data.  To roll back, revert the
producer commit and restore the previous `data-release` manifest; do not copy
individual artifacts across releases.

## Current stacked integration PRs

The following changes are prepared but intentionally not merged by the agent:

- #402 public release artifact hash gate
- #403 formal point-in-time backtest publication contract
- #404 Advice Gate binding to a valid backtest release
- #405 opt-in raw observation persistence at the adapter boundary
- #406 regime and cross-asset evidence quality fields
- #407 event evidence lifecycle state contract
- #408 risk-adjusted walk-forward summary metrics
- #409 Mini App evidence wait-reason display
- #410 refresh the production integration matrix
- #411 offline production acceptance gate
- #414 source-health scan-state and observability contract
- #415 source-health schema and runtime cross-field audit
- #416 bind backtest identity to release manifests
- #417 bind backtest identity to research candidates and Actions input

Merge these in dependency order with **Create a merge commit**.  A module is
not promoted to `production` in this matrix until its PR is merged and the
release pipeline has emitted a matching manifest.  Keep the feature branches
until the complete stack is merged so each dependency remains reviewable.

## Alert contract and lifecycle

All notification paths can use the `AlertEnvelope` contract and deterministic
lifecycle engine. An observation remains `pending_confirmation` until official,
independent-source, and market-synchronisation evidence are all present.
Cooldown and hourly budgets are evaluated before delivery by scheduled briefs,
official event monitoring, and emergency alerts; suppressed records remain
auditable with a reason and budget decision in workflow outputs. The durable
event ledger keeps bounded per-delivery history so a cache eviction cannot
reset the hourly or per-event budget. `src/alert_caption.py` produces a safe
caption no longer than 40 Unicode characters above a fixed 1080x1350 photo for
every formal alert path; production captions remain limited to the existing
30-character contract.

## Production intelligence binding

`src/production_integration.py` is called by `build_briefing_snapshot` and is
the single boundary between the intelligence modules and a public briefing.
It resolves quote identities through `InstrumentMaster`, emits a mixed/live/
close-only/degraded quality summary, and records the provenance fields that
are available in the current snapshot. Missing release, snapshot, observation,
or source identifiers intentionally produce `observation_only` and keep the
advice gate closed; the binder never invents identifiers or market evidence.

Strategy metadata is likewise observation-only until a real `backtest_release`
is present. Raw observations are persisted as immutable records when
`RAW_OBSERVATION_ROOT` is configured. The market producer records one
normalized snapshot per release; local runs without that setting remain
explicitly disabled. Public output contains only safe store metadata, never
raw payloads. The store is not yet the primary historical backend.

### Raw observation configuration

Set `RAW_OBSERVATION_ROOT` only in a writable worker or scheduled job. Missing
configuration is reported as disabled, and a store error cannot make a quote
alertable. Records are content-addressed and append-only; rollback restores a
previous release manifest rather than deleting individual observations.

### Adapter quality contract

Every `SourceObservation.provenance()` now includes the shared quality fields
`data_quality_score`, `quality_freshness`, `quality_reasons`,
`display_eligible`, and `alert_eligible`. A single adapter can establish
availability, parsing, and freshness, but it cannot establish independent
market confirmation; therefore its own `alert_eligible` value remains false
until a cross-source check is recorded. A stale-cache observation is always
scored as stale with score zero, even though the fallback was fetched during
the current run. This prevents a recently-read cached payload from being
mislabelled as live.

### Feedback contract

Briefing JSON exposes an anonymous `event_feedback` contract for each displayed
event (or a briefing-level contract when this round has no event). It contains
only review labels and queue/policy flags; chat IDs, tokens, and recipient data
are never emitted. Submissions remain review-required and
`policy_update_allowed=false`, so feedback can be measured without silently
changing alert thresholds. The endpoint/local queue remains optional until a
persistent review store is provisioned.

### Rollback

The integration is additive. Reverting the binding commit restores the prior
briefing shape, while the release gate continues to validate the existing
market, research, and event artifacts. Restore the last `status=ready` manifest
as one immutable release; never mix individual files from different releases.

### Offline production acceptance

`python -m src.production_e2e` runs a deterministic release-to-delivery check
with a complete production research fixture, the release contract, the Mini App
deep-link/photo contract, and the non-network Telegram configuration check. It
never sends a message or contacts Railway. A renderer or release-contract
failure returns a non-zero status so CI cannot report a green integration gate
while delivery would be blocked in production.

## Browser contract

The investor-facing Mini App shell is covered by
`tests/test_mini_app_browser_contract.py`. The contract runs against a local
static server with a real headless Chromium instance and verifies that the
briefing is expanded by default while source health, intelligence, and
technical provenance remain opt-in. It also checks that engineering-only
freshness placeholders are not exposed in the investor surface and that the
technical drawer opens through a real click. The quality workflow provisions
the Playwright Chromium dependency before running the suite; local runs without
the browser binary skip this browser-only check rather than fabricating an
acceptance result.

## Research/backtest identity invariant

The research publisher now validates the optional `backtest_release_contract`
before a release can proceed. A ready contract must be publish-eligible and
have a release ID; blocked or unavailable contracts cannot unlock candidates.
Candidate rows must carry the same release ID and publication state as the
research-level contract. Legacy observation reports without backtest fields
remain readable, but remain research-only. See
`docs/p4-research-backtest-invariants.md` for rollback and failure rules.

## Instrument Master provenance

`InstrumentMaster.artifact()` is the deterministic public registry contract.
Production quote evidence records its `instrument_master_id` and version for
every resolution attempt, including unknown symbols. Ambiguous or unknown
symbols remain unresolved and cannot become alert evidence.

The Advice Gate also requires the structured backtest contract. A bare release
ID is treated as unverified and cannot unlock contextual decision support.
