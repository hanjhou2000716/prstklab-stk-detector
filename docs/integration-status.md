# PRStK production integration matrix

This inventory distinguishes code that exists from code that is actually
called by the release pipeline and displayed or delivered to a user.  A
module is `production` only when it has a producer, an artifact contract, a
pipeline call and a tested consumer.

| Module | File(s) | Tests | Pipeline | JSON | Mini App | Telegram | Status |
|---|---|---|---|---|---|---|---|
| Source adapters | `src/source_adapter.py`, `src/adapters/catalog.py`, `src/phase_two_sources.py` | yes | yes | yes | health | event/brief | production |
| Raw observation store | `src/raw_observation_store.py`, `src/production_evidence.py` | yes | market/research/brief workflows persist immutable records | quality metadata + observation envelope | no raw payload | no | production |
| Instrument master | `src/instrument_master.py` | yes | research + market producers | candidate/quote lineage | no | no | production |
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
| Portfolio risk | `src/portfolio_risk.py`, `src/private_portfolio.py` | yes | local-only adapter | private payload | private local view | prohibited | partially_integrated |
| Paper portfolio | `src/paper_portfolio.py` | yes | yes | briefing | briefing | no | production |
| Strategy scans | `src/run_*scan.py`, `src/research_report.py` | yes | yes | yes | yes | briefing/research | production |
| Strategy registry/explainability | `src/strategy_registry.py`, `src/advice_gate.py` | yes | partial | partial | partial | no | partially_integrated |
| Backtest/cost model | `src/four_strategy_walk_forward.py`, `src/backtest_costs.py`, `src/backtest_release.py` | yes | scheduled | artifact + risk-adjusted metrics | no | no | partially_integrated |
| Release manifest/gate | `src/release_manifest.py`, `src/release_gate.py`, `src/production_e2e.py` | yes | yes | yes | loader gate | send gate | production |
| Telegram delivery | `src/telegram_client.py`, `src/scheduled_delivery.py`, `src/official_event_monitor.py`, `src/emergency_alert.py` | yes | release-gated `sendPhoto` path with shared file ID | photo receipt | alert/release deep-link button | renderer failure is fail-closed; recipient failures are isolated | production |
| Source-health release artifact | `src/release_manifest.py`, `src/release_gate.py`, `site/app.js` | yes | manifest/release gate | `data/source-health.json` | release-bound health view | gate evidence only | production |
| Mini App deep-link/timeline | `site/app.js`, `src/event_timeline.py` | yes | Pages | yes | yes | button target | production |
| External source email contract | `src/email_intelligence.py`, `src/gmail_ingress.py`, `src/external_source_parsers.py`, `src/creator_source_adapters.py`, `railway-monitor/gmail_ingress.py`, `railway-monitor/gmail_watch.py`, `railway-monitor/email_store.py`, `railway-monitor/email_router.py` | yes | bounded Railway ingress + parser/DLQ boundary | sanitized EmailObservation + private cursor/DLQ | source health/pending reasons | no raw mail | partially_integrated |
| External event risk | `src/external_event_risk.py`, `src/intelligence_pipeline.py` | yes | intelligence context | external risk status + pending reasons | event trace/pending path | eligible only after evidence gates | production |
| Creator media boundary | `src/creator_media.py`, `src/creator_photo_delivery.py` | yes | private attachment boundary + transport-neutral plan | hash + private availability only | no raw media | bounded photo/text plan; receipt contract | partially_integrated |
| Creator release lineage | `src/creator_release.py`, `src/creator_intelligence_pipeline.py`, `src/release_manifest.py` | yes | scheduled input + optional manifest artifact | parent release/hash/status | release-bound creator drawer | no raw creator media | production |
| Creator/PRStK correlation | `src/creator_correlation.py`, `src/creator_intelligence_pipeline.py`, `src/briefing_cards.py` | yes | briefing creator binding | explicit entity matches + snapshot IDs | creator correlation state/reason | never a standalone signal | production |
| Railway health contract | `src/railway_health_contract.py`, `railway-monitor/app.py`, `railway-monitor/runtime_config.py`, `railway-monitor/health_contract.py` | yes | monitor health boundary + standalone heartbeat/Gmail projection + redacted runtime configuration | bounded status/retry/heartbeat/configuration state | source health | observability only | partially_integrated |
| Railway Gmail runtime wiring | `railway-monitor/gmail_runtime.py`, `railway-monitor/gmail_ingress.py`, `railway-monitor/gmail_watch.py`, `railway-monitor/email_store.py` | yes | standalone configuration-to-ingress boundary | redacted Gmail watch health | source health | not directly | partially_integrated |
| Railway dispatch transport | `railway-monitor/dispatch_transport.py`, `railway-monitor/app.py` | yes | bounded repository-dispatch HTTP transport with compatibility wrapper | no payload persistence | no | repository dispatch only; no Telegram path | partially_integrated |
| Railway delivery retry orchestration | `railway-monitor/delivery_retry.py`, `railway-monitor/app.py` | yes | bounded durable outbox replay with injected transport and health projection | retry status remains in delivery outbox | source health delivery diagnostics | repository dispatch retry only; no direct Telegram path | partially_integrated |
| Railway alert dispatch orchestration | `railway-monitor/alert_dispatch.py`, `railway-monitor/app.py` | yes | trace/payload/sign/dispatch seam with compatibility wrapper | signed repository-dispatch payload | no | repository dispatch only; no direct Telegram path | partially_integrated |
| Railway market-sync reader | `railway-monitor/market_sync.py`, `railway-monitor/app.py` | yes | read-only public snapshot retrieval with fail-closed fallback | market snapshot used for confirmation only | source evidence indirectly | no direct delivery | partially_integrated |
| Gate-driven traceability ledgers | `docs/gate-ledgers-2026-08-14.md`, `docs/gate-driven-state-2026-08-14.md` | yes | requirement, regression, and debt evidence | documentation only | no direct UI | no direct delivery | production |
| Railway poll configuration | `railway-monitor/poll_config.py`, `railway-monitor/app.py` | yes | bounded Jin10/GDELT environment projection | redacted runtime settings only | source health indirectly | no direct delivery | partially_integrated |
| Railway state schema/migrations | `railway-monitor/state_store_schema.py`, `railway-monitor/app.py` | yes | SeenStore startup boundary | SQLite tables, additive migrations and outbox/receipt lineage | source health indirectly | delivery receipt persistence | partially_integrated |
| Railway classification state | `railway-monitor/classification_store.py`, `railway-monitor/app.py`, `src/event_classifier.py` | yes | incoming-event and retry state boundary | classification reason/count diagnostics | pending/blocked reason | dispatch gate input only | partially_integrated |
| Railway classifier delivery gate | `railway-monitor/app.py`, `src/event_classifier.py` | yes | canonical classifier required for Jin10 dispatch; root-only fallback is diagnostics-only | classifier mode and blocked reason | source health | blocked until repository-shared mode | partially_integrated |
| Creator scheduled input | `src/scheduled_delivery.py`, `.github/workflows/scheduled-brief.yml` | yes | optional sanitized `CREATOR_RECORDS_PATH` | same market/creator release lineage | creator release | no raw creator media | production |
| FinancialJuice sanitized external input | `src/external_observation_input.py`, `src/scheduled_delivery.py`, `.github/workflows/scheduled-brief.yml` | yes | opt-in `EXTERNAL_OBSERVATIONS_PATH` | same market/event/briefing snapshot | external intelligence | raw Gmail rejected; Railway bundle still required | partially_integrated |
| Creator delivery runtime | `src/creator_dispatch.py`, `src/creator_notification.py`, `src/creator_photo_delivery.py`, `src/creator_delivery_store.py`, `railway-monitor/app.py` | yes | release-gated scheduled dispatch + signed Railway history | private receipt lineage only | release-bound Creator view | one initial episode notification; duplicate-safe | production |
| Creator provider health | `src/creator_source_health.py`, `src/creator_health.py`, `src/scheduled_delivery.py` | yes | scheduled source-health merge | provider state without raw content | healthy/no-content/stale/failure states | gate evidence only | production |
| External event unification | `src/external_event_pipeline.py`, `src/financialjuice_contract.py`, `src/intelligence_pipeline.py` | yes | shared classification and evidence gate | event cluster/evidence state | pending reason and source evidence | only policy-eligible events | production |
| News provider registry | `src/news_intelligence.py`, `schemas/news-story.schema.json` | yes | `risk_news.build_news_snapshot` | provider/domain contract | release-provided URL allowlist | no direct alert | production |
| Official news feed adapters | `src/news_feed_adapters.py`, `src/risk_news.py` | yes | official-first, fail-soft fallback | provider health + NewsStory | provider/status badges | context only | partially_integrated |
| News interest/ranking/dedup | `src/news_intelligence.py`, `src/risk_news.py` | yes | market snapshot | `news.intelligence` | badges/relevance reasons | context only | production |
| News artifact/release binding | `src/release_manifest.py`, `src/artifact_contract.py`, `site/app.js` | yes | multi-market release envelope with lineage and browser verification | `data/news.json` | release-bound and loaded by manifest | release gate and Mini App | production |
| Creator source health runtime | `src/creator_source_health.py`, `src/scheduled_delivery.py`, `site/app.js` | yes | scheduled snapshot preparation | `source_health` + `creator_source_health` | optional source rows and no-event/failed distinction | observability only | production |
| Creator delivery lineage | `src/creator_delivery_store.py`, `src/delivery_callback.py`, `railway-monitor/app.py` | yes | signed Creator callback + history read | private Railway receipt metadata | no raw receipt data | dedupe evidence | production |
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
Strict delivery also requires the complete eight-entry matrix: Taiwan and US
for momentum, price action, resonance, and value. Missing, duplicated, or
unknown market/strategy rows fail closed even when aggregate universe counts
look complete.
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

## Historical stacked integration PRs

The numbered stack above is historical context, not an outstanding merge
queue.  The current `main` already contains the merged production changes;
do not merge or resurrect those branches.  The authoritative state is the
current `main` commit, its generated release manifest, and the latest
successful production workflow.  Any new work must branch from the latest
`main`, include its own tests and release evidence, and be reviewed as a new
PR.

### Last verified production release

This section is updated only from the public manifest and the latest successful
main-branch workflows. It is evidence of the deployed release, not a claim
that every optional provider or historical backtest is available.

- Main commit: `6b3efac8b666ebcfb87337fec68e6b7536e65c37`
- Pages deployment: [31567941161](https://github.com/hanjhou2000716/prstklab-stk-detector/actions/runs/31567941161)
- Quality/delivery workflow: [31567941144](https://github.com/hanjhou2000716/prstklab-stk-detector/actions/runs/31567941144)
- Official macro/price workflow: [31567991408](https://github.com/hanjhou2000716/prstklab-stk-detector/actions/runs/31567991408)
- Release: `release-9f742bf9a0c579e4`
- Market snapshot: `e5a30f1e6aee3c23`
- Research snapshot: `research-acddbf45ffd6e4db`
- Event snapshot: `event-1c1c81d0f4e30a41`
- Manifest status: `ready`; research mode/scope: `production` / `full`
- Source health is now also emitted as a release-bound `data/source-health.json`
  artifact when the producer has the canonical health envelope. The legacy
  embedded `market.source_health` remains for compatibility; older releases
  without the optional artifact remain readable.
- Research universe: `7772 / 7772` completed; 40 visible candidates
- Formal backtest: `unavailable`; Advice Gate therefore remains observation-only

The public source of truth is
[`release-manifest.json`](https://hanjhou2000716.github.io/prstklab-stk-detector/data/release-manifest.json).
If this section and the manifest disagree, the manifest and its artifact
hashes take precedence and this document must be corrected before claiming a
new production verification.

The photo smoke receipt is intentionally a single-recipient diagnostic and
uses a synthetic smoke alert identity.  It proves renderer, sendPhoto and
receipt plumbing, not the content of a live event.  A release-gated production
delivery must use the release identifiers above.

### Creator delivery durability

Creator dispatch first combines the bounded runner-local receipt file with the
optional signed Railway `/creator-delivery-history` response.  Railway stores
only notification keys, release/snapshot lineage, status and aggregate counts;
it does not receive raw episode text, media, Telegram IDs or tokens.  A Railway
outage is reported as `remote_history_status=unavailable` and is not treated as
an empty history.  This keeps the dispatch fail-closed for release readiness
while making the operational limitation explicit.

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
40-character photo-caption contract.  The legacy text-only helper remains
30-character limited and is not used by production photo delivery.

## Production intelligence binding

`src/production_integration.py` is called by `build_briefing_snapshot` and is
the single boundary between the intelligence modules and a public briefing.
It resolves quote identities through `InstrumentMaster`, emits a mixed/live/
close-only/degraded quality summary, and records the provenance fields that
are available in the current snapshot. Missing release, snapshot, observation,
or source identifiers intentionally produce `observation_only` and keep the
advice gate closed; the binder never invents identifiers or market evidence.

Strategy metadata is likewise observation-only until a real `backtest_release`
is present. Raw observations are persisted as immutable records by the market,
research and briefing workflows when `RAW_OBSERVATION_ROOT=data/raw-observations`
is configured. Those jobs also set `RAW_OBSERVATION_REQUIRED=true`, so a failed
capture blocks publication rather than silently producing a partial release.
Local runs without that setting remain explicitly disabled. Public output
contains only safe store metadata, never raw payloads. The store is an
immutable release evidence layer; it is not yet the primary historical
analytics backend.

### Raw observation configuration

Set `RAW_OBSERVATION_ROOT` only in a writable worker or scheduled job. Missing
configuration is reported as `state=disabled`, and a store error is reported
as `state=unavailable`; neither state can make a quote alertable. Records are
content-addressed and append-only; rollback restores a previous release
manifest rather than deleting individual observations.

For a production worker that must prove raw capture before publishing, set
`RAW_OBSERVATION_REQUIRED=true` together with a writable
`RAW_OBSERVATION_ROOT`. The market artifact then carries an explicit
`raw_observation` envelope (`required`, `state`, `recorded`, and
`observation_id`). The release validator rejects `required=true` unless the
snapshot was recorded successfully. The default remains optional so local
development and legacy replay jobs do not silently become unpublishable.

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
symbols remain unresolved and cannot become alert evidence. Research reports
extend the compact headline registry from explicit public-universe rows
(ticker, issuer name and market) without fuzzy matching, giving ordinary
production candidates deterministic IDs while malformed or ambiguous rows
remain unresolved.

The Advice Gate also requires the structured backtest contract. A bare release
ID is treated as unverified and cannot unlock contextual decision support.

Walk-forward contracts now expose sanitized net performance metrics and the
survivorship audit snapshot dates. These are research evidence only and do not
unlock trading language or create a performance forecast.

Market news routing is fail-closed for unclassified headlines. Only explicit
regional evidence or an auditable global/cross-market classification can reach
a tab; empty scans and provider failures remain separate source-health states.

Candidate explainability is an additive machine-readable contract. When a
candidate emits `explainability`, release validation requires passed and
failed conditions, data completeness, risk factors, evidence, signal date,
and an invalidation condition. Legacy rows remain readable but do not gain
advice permissions merely by having a score or ticker.

When a candidate includes a `strategy_registry` entry, the production binder
compares the strategy ID, version, data version and backtest release, and
requires all seven string identity fields (including parameter hash, universe
version and code commit). A partial, non-string, or mismatched row is reported
as `observation_only` with `invalid_strategy_registry`; a complete match is
marked `registry_state=verified`. Candidates without the optional entry retain
the legacy observation-only compatibility path.

## Private portfolio boundary

`src/private_portfolio.py` is the only supported adapter for an optional
personal risk view. It accepts caller-owned in-memory positions, delegates to
`portfolio_risk_snapshot`, and annotates the result as
`private_local_only`/`caller_memory_only`. The payload is never a release
artifact, never enters Telegram delivery, and cannot access a broker account
or place an order. This keeps portfolio risk isolated from the public Pages
and data-release pipeline.

## Intelligence evidence contract

`src/intelligence_contract.py` validates the cross-field meaning of the
briefing intelligence payload before a market artifact can be released. A
confirmed market sync must have a synchronized impact-graph path with explicit
market evidence; a high-confidence conditional path without that evidence is
rejected. Regime factor counts, contagion signal counts, non-predictive stress
scenarios, and fail-closed advice bindings are checked as well. This keeps the
Mini App's conditional transmission hypotheses from becoming directional
claims during serialization or release publication.

The contract is additive and accepts older market snapshots without an
`intelligence` block. To roll back, remove the producer's briefing intelligence
block or revert the validation commit; the existing market, release, and
Telegram gates remain fail-closed.

## Telegram observation traceability

Photo delivery receipts now carry the source `observation_id` in addition to
the alert, release and snapshot IDs. Every scheduled brief and official event
photo call passes the same observation ID that produced the published artifact.
The Mini App button target includes `alert`, `release`, `snapshot`, and (when
available) `observation`, so a receipt can be traced to one immutable source
observation without exposing recipient identifiers or Telegram file IDs.
The backend and browser router reject a snapshot or observation mismatch rather
than opening an unrelated current event.
Legacy callers may omit the optional observation ID; such receipts remain
valid but are explicitly unbound rather than guessed. Rollback is safe because
the field is additive and defaults to an empty string.

Cross-asset contagion evidence is also freshness-gated: stale, delayed,
unavailable, or non-alertable quotes remain visible in the context but cannot
confirm synchronised stress. The output records `signal_evidence`,
`unusable_inputs`, and a conservative quality score so the Mini App can explain
why a market-sync confirmation is still pending.

## Research worker state integrity

All five market research workers use the shared
`src.research_scan_state.classify_scan_state` helper. A batch failure is
reported as `building` when some rows completed, or `failed` when none did;
only a run with zero failures and all requested rows completed is `complete`.
The report normalizer applies the same correction to legacy summaries that
incorrectly wrote `complete` alongside failed rows. A provider outage can
therefore never become a successful empty candidate list or a publishable
research snapshot.

The current reliability stack continues from that contract:

- #433 records worker exits in a machine-readable failure ledger.
- #434 makes the investor-facing source-gap count deterministic from
  `source_health.sources[]`.
- #435 removes hidden worker-step `continue-on-error`; isolation is retained by
  the explicit ledger path, and publication remains fail-closed.
- The next contract also validates that `missing_source_count` equals the
  number of degraded semantic source rows; stale backend aggregates are now a
  release validation error rather than an investor-facing mismatch.

Research workflow lineage is explicit as well: the unified report producer
receives the GitHub run ID/attempt and checkout SHA, then stamps both onto the
research report and visible candidates. This prevents a released scan from
being mistaken for a later rerun or an untracked local artifact.

The offline production E2E now uses an explicit mocked Telegram boundary. It
does not require `TELEGRAM_CHAT_IDS` or a bot token and cannot contact real
recipients; renderer, release, deep-link and photo-contract gates remain
strict. Real delivery configuration is checked only by the separate delivery
smoke test.

## Research worker failure ledger

The unified research workflow keeps worker isolation while making each
non-zero worker exit explicit in a failure ledger. Each worker failure is written
to `research-artifacts/scan-failures.ndjson` with its market and strategy, then
passed to `run_research_report --scan-failures`. The report marks that source
`scan_state=failed`, `candidate_state=data_gap`, and blocks publication while
preserving the last successful release. This distinguishes a failed scan from
a successful scan with no candidates and prevents an empty strategy drawer from
being mistaken for a healthy result. The ledger is diagnostic-only and is not
used to fabricate rows or scores. Rollback is additive: remove the option and
ledger step to restore legacy worker behaviour.

## Production research semantic gate

The production acceptance gate rejects research artifacts whose timestamps,
provider state, and candidate state contradict one another. A source cannot be
`complete` while claiming an unavailable provider or a `data_unavailable`,
`failed`, or `building` candidate state; `no_candidates` must have zero visible
rows. The report generation time may not be materially later than its recorded
run finish time. These checks prevent a partial or stale research artifact from
being repackaged into a ready market release.

## Source-health aggregate contract

Source rows use `semantic_state` as the machine-readable authority. The public
aggregate keeps three separate concepts:

- `missing_source_count`: every degraded row, including an unconfigured
  optional provider;
- `runtime_failure_count`: providers that failed, are stale, partial, or
  otherwise unavailable during this scan;
- `configuration_missing_count`: providers waiting for an operator-managed
  credential or setting, such as optional FRED/EIA enrichment.

An absent optional credential is visible to engineering users but is not
reported as a runtime outage. `investor_status` is `資料正常` when all required
runtime sources are healthy, `部分資料降級` when an optional/runtime source is
degraded, and `核心資料不足` when a core source is unavailable. The release
contract validates both counts against `sources[].semantic_state`, so the Mini
App cannot invent a divergent gap count.

## Railway delivery persistence

`railway-monitor/delivery_store.py` is the canonical SQLite boundary for
delivery outbox rows, retry backoff, receipt registration, bounded diagnostics
and retention. `SeenStore` delegates to it for backward compatibility. The
boundary is **partially_integrated** until the stacked PR is merged and live
Railway volume/receipt continuity is reverified; local contract tests are
green, while production acceptance remains an external gate.

## Railway event-ledger persistence

`railway-monitor/ledger_store.py` owns canonical event-ledger observations,
source merging, category cooldowns and retention. `SeenStore` delegates to it
for compatibility. Status is **partially_integrated** pending stacked PR and
live restart/volume continuity evidence; no release or notification policy is
implemented in this store.

## Railway source-cache persistence

`railway-monitor/cache_store.py` is the canonical SQLite boundary for bounded
source-cache reads and writes used by GDELT fallback. It rejects malformed JSON,
non-list payloads and entries older than the caller's freshness window, while
preserving UTF-8 content and atomic replacement semantics. `SeenStore` keeps
the compatibility methods and delegates to this module. Status is
**partially_integrated** until the stacked PR is merged and live restart/cache
continuity is reverified.

## Railway health-dispatch boundary

`railway-monitor/health_dispatch.py` owns the non-fatal GitHub health callback
payload, retry/backoff handling and 401/403/429/5xx classification. The monitor
keeps the public compatibility function and its bounded state, while the
extracted boundary receives an explicit health updater and HTTP client factory
for deterministic tests. Status is **partially_integrated** until the stacked
PR is merged and live Railway callback behaviour is reverified.

## Railway dispatch-payload boundary

`railway-monitor/dispatch_payload.py` owns canonical repository-dispatch body
construction and HMAC signing. The monitor keeps compatibility wrappers while
injecting canonical-key, trace and source-normalization callbacks. Status is
**partially_integrated** until the stacked PR is merged and a live signed
dispatch receipt is reverified.

## Jin10 source adapter

`railway-monitor/jin10_source.py` owns the official MCP `list_flash` call and
schema-aware argument negotiation. The monitor retains compatibility parsing
into canonical `Flash` records; no HTML/feed scraping or alternate endpoint is
introduced. Status is **partially_integrated** until the stacked PR is merged
and live Jin10 source health is reverified.

## Creator delivery receipt projection

`railway-monitor/creator_delivery.py` owns the bounded, non-secret projection
of creator notification keys used by the creator-history endpoint. It filters
receipt category, deduplicates and truncates keys without exposing message
bodies or recipient identifiers. Status is **partially_integrated** pending
stacked PR and live creator receipt verification.
