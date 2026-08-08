# PRStK production integration matrix

Last audited against the current stacked release branches: 2026-08-08.
`production` means the module is called by a production workflow, contributes
to a validated artifact, has a tested consumer, and is fail-closed when its
evidence is unavailable. A file existing by itself is never sufficient.

This inventory distinguishes code that exists from code that is actually
called by the release pipeline and displayed or delivered to a user.  A
module is `production` only when it has a producer, an artifact contract, a
pipeline call and a tested consumer.

| Module | File(s) | Tests | Pipeline | JSON | Mini App | Telegram | Status |
|---|---|---|---|---|---|---|---|
| Source adapters | `src/source_adapter.py`, `src/phase_two_sources.py` | yes | yes | yes | health | event/brief | partially_integrated |
| Raw observation store | `src/raw_observation_store.py`, `src/phase_two_sources.py` | yes | optional Railway runtime | health provenance | source diagnostics | no | partially_integrated |
| Instrument master | `src/instrument_master.py` | yes | partial | partial | no | no | partially_integrated |
| Data quality/SLA | `src/data_quality.py`, `src/source_health.py` | yes | yes | yes | yes | gate reason | production |
| Taiwan crosscheck | `src/taiwan_market_crosscheck.py`, `src/market_crosscheck.py` | yes | yes | yes | yes | price gate | production |
| Event source catalog | `src/event_source_catalog.py` | yes | yes | yes | health | event | production |
| Event cluster/ledger | `src/event_ledger.py`, `src/event_output.py` | yes | yes | yes | timeline | event | production |
| Macro surprise | `src/surprise_engine.py` | yes | partial | partial | partial | no | partially_integrated |
| Corporate events | `src/corporate_event_contract.py`, `src/official_events.py` | yes | yes | yes | yes | observe-only/event | production |
| Market impact graph | `src/market_impact_graph.py`, `src/intelligence_pipeline.py` | yes | yes | yes | briefing/event | conditional event | production |
| Alert budget/lifecycle | `src/alert_budget.py`, `src/alert_dispatch.py`, `src/event_alerts.py` | yes | yes | yes | yes | yes | production |
| Market regime/contagion | `src/market_regime.py`, `src/cross_asset_risk.py`, `src/intelligence_pipeline.py` | yes | yes | yes | briefing | briefing context | production |
| Stress scenarios | `src/stress_scenarios.py`, `src/intelligence_pipeline.py` | yes | yes | yes | briefing | context only | production |
| Portfolio risk | `src/portfolio_risk.py` | yes | no | no | no | no | unused |
| Strategy scans | `src/run_*scan.py`, `src/research_report.py` | yes | yes | yes | yes | briefing/research | production |
| Strategy registry/explainability | `src/strategy_registry.py`, `src/advice_gate.py` | yes | partial | partial | partial | no | partially_integrated |
| Backtest/cost model | `src/four_strategy_walk_forward.py`, `src/backtest_costs.py` | yes | scheduled | artifact | no | no | partially_integrated |
| Release manifest/gate | `src/release_manifest.py`, `src/release_gate.py`, `src/canonical_release_publisher.py` | yes | yes | yes | loader gate | send gate | production |
| Telegram delivery/card renderer | `src/telegram_client.py`, `src/alert_card_renderer.py`, `src/scheduled_delivery.py` | yes | yes | receipt | deep-link button | yes | production |
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

## Raw observation persistence

Phase-two provider results can be retained in the append-only raw observation
store when the Railway service sets `PRSTK_RAW_OBSERVATION_ROOT` to a
persistent volume.  Each normalized provider result receives an
`observation_id` and `raw_payload_location` in source health; the immutable
SQLite index and content-addressed JSON payload remain outside the public
`data-release` branch.  GitHub Actions intentionally leaves this variable
unset, so a transient scan cannot accidentally publish raw provider payloads.
Storage failures are recorded as a provider diagnostic and never turn a
successful market fetch into an alert-eligible result.  The next rollout can
promote this row to production only after a Railway backup/restore check is
available.

## Alert contract and lifecycle

All notification paths can use the `AlertEnvelope` contract and deterministic
lifecycle engine. An observation remains `pending_confirmation` until official,
independent-source, and market-synchronisation evidence are all present.
Cooldown and hourly budgets are evaluated before delivery; suppressed records
remain auditable. `src/alert_caption.py` produces a safe caption no longer than
40 Unicode characters.
