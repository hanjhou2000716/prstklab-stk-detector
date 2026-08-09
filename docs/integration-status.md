# PRStK production integration matrix

This inventory distinguishes code that exists from code that is actually
called by the release pipeline and displayed or delivered to a user.  A
module is `production` only when it has a producer, an artifact contract, a
pipeline call and a tested consumer.

| Module | File(s) | Tests | Pipeline | JSON | Mini App | Telegram | Status |
|---|---|---|---|---|---|---|---|
| Source adapters | `src/source_adapter.py`, `src/phase_two_sources.py` | yes | yes | yes | health | event/brief | partially_integrated |
| Raw observation store | `src/raw_observation_store.py` | yes | no | no | no | no | experimental |
| Instrument master | `src/instrument_master.py` | yes | partial | partial | no | no | partially_integrated |
| Data quality/SLA | `src/data_quality.py`, `src/source_health.py` | yes | yes | yes | yes | gate reason | production |
| Taiwan crosscheck | `src/taiwan_market_crosscheck.py`, `src/market_crosscheck.py` | yes | yes | yes | yes | price gate | production |
| Event source catalog | `src/event_source_catalog.py` | yes | yes | yes | health | event | production |
| Event cluster/ledger | `src/event_ledger.py`, `src/event_output.py` | yes | yes | yes | timeline | event | production |
| Macro surprise | `src/surprise_engine.py` | yes | partial | partial | partial | no | partially_integrated |
| Corporate events | `src/corporate_event_contract.py`, `src/official_events.py` | yes | yes | yes | yes | observe-only/event | production |
| Market impact graph | `src/market_impact_graph.py`, `src/intelligence_pipeline.py` | yes | yes | yes | briefing/event | conditional event | production |
| Alert budget/lifecycle | `src/alert_budget.py`, `src/event_alerts.py` | yes | partial | partial | partial | partial | partially_integrated |
| Market regime/contagion | `src/market_regime.py`, `src/cross_asset_risk.py`, `src/intelligence_pipeline.py` | yes | yes | yes | briefing | briefing context | production |
| Stress scenarios | `src/stress_scenarios.py`, `src/intelligence_pipeline.py` | yes | yes | yes | briefing | context only | production |
| Portfolio risk | `src/portfolio_risk.py` | yes | no | no | no | no | unused |
| Paper portfolio | `src/paper_portfolio.py` | yes | yes | briefing | briefing | no | production |
| Strategy scans | `src/run_*scan.py`, `src/research_report.py` | yes | yes | yes | yes | briefing/research | production |
| Strategy registry/explainability | `src/strategy_registry.py`, `src/advice_gate.py` | yes | partial | partial | partial | no | partially_integrated |
| Backtest/cost model | `src/four_strategy_walk_forward.py`, `src/backtest_costs.py` | yes | scheduled | artifact | no | no | partially_integrated |
| Release manifest/gate | `src/release_manifest.py`, `src/release_gate.py` | yes | yes | yes | loader gate | send gate | production |
| Telegram delivery | `src/telegram_client.py`, `src/scheduled_delivery.py` | yes | yes | receipt | no | yes | production |
| Mini App deep-link/timeline | `site/app.js`, `src/event_timeline.py` | yes | Pages | yes | yes | button target | production |
| Feedback/paper portfolio | `src/event_feedback.py`, `src/production_evidence.py` | yes | optional endpoint/local queue | no | feedback controls | no | partially_integrated |

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

## Migration and rollback

The new fields are additive and readers continue to accept the legacy fields.
The release manifest normalizer converts legacy gap maps to integer counts and
backfills candidate state without inventing data.  To roll back, revert the
producer commit and restore the previous `data-release` manifest; do not copy
individual artifacts across releases.

## Alert contract and lifecycle

All notification paths can use the `AlertEnvelope` contract and deterministic
lifecycle engine. An observation remains `pending_confirmation` until official,
independent-source, and market-synchronisation evidence are all present.
Cooldown and hourly budgets are evaluated before delivery; suppressed records
remain auditable. `src/alert_caption.py` produces a safe caption no longer than
40 Unicode characters.

## Production intelligence binding

`src/production_integration.py` is called by `build_briefing_snapshot` and is
the single boundary between the intelligence modules and a public briefing.
It resolves quote identities through `InstrumentMaster`, emits a mixed/live/
close-only/degraded quality summary, and records the provenance fields that
are available in the current snapshot. Missing release, snapshot, observation,
or source identifiers intentionally produce `observation_only` and keep the
advice gate closed; the binder never invents identifiers or market evidence.

Strategy metadata is likewise observation-only until a real `backtest_release`
is present. Raw observations remain an optional local append-only store and are
represented in public output only by quality metadata, not by raw payloads.

### Rollback

The integration is additive. Reverting the binding commit restores the prior
briefing shape, while the release gate continues to validate the existing
market, research, and event artifacts. Restore the last `status=ready` manifest
as one immutable release; never mix individual files from different releases.
