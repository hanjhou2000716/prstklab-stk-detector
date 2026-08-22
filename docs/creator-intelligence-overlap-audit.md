# Creator Intelligence overlap audit

## Decision

The canonical provider identity is `config/creator_providers.json`, loaded by
`src/creator_provider_registry.py`. Routers, parsers, source health, event
catalogue and release preparation must consume this registry; they must not
introduce a second provider whitelist.

The three configured providers are `haojiao`, `jenny`, and `gooaye`. They are
editorial enrichment only. They cannot independently become official event
evidence, a market-synchronisation proof, or a high-risk alert.

## Current canonical checkpoint (2026-08-22)

The active continuation branch is `feat/external-acceptance-evidence`, stacked
after PRs #703–#706. It does not introduce a second Creator, FinancialJuice,
News, or Telegram pipeline. The latest local checkpoint is:

- full repository regression: `1350 passed`;
- full Ruff, Mypy (177 source files), Python compilation and Mini App syntax
  checks: passed;
- canonical overlap and generated-bundle provenance audit: passed;
- PR #707 quality and security checks: passed after commit `e5a6a90`.

The latest redacted read-only external capture is
`docs/evidence/external-acceptance-2026-08-22T1300.json` (the earlier
`1215` and `1230` captures remain retained). Pages serves a
`ready` manifest and Railway is running, but Gmail remains
`configuration_missing`, GDELT returned `invalid_json`, and the health
callback is `HTTP_403`. These are intentionally recorded as
`NEEDS_REVERIFY`; they are not converted to `no_new_content`, healthy, or a
production Telegram acceptance. No external write or production broadcast
was performed by this checkpoint.

## Latest production evidence (2026-08-21)

The post-refresh acceptance evidence supersedes the older checkpoint notes
below.  Main is now at `657c3e3` (PR #668).  The latest successful refresh
(`32417964673`) published release `release-e43a55e29d580bc1` with market
snapshot `389b72b2fb5ff27`, research snapshot `research-8b8ec8f6e5ee51aa`,
and event snapshot `event-a889bf10a4141a3b`.  The manifest is `ready`, Creator
and News are `ready`, research is explicitly `stale_fallback`, and all seven
manifest artifacts passed the public SHA-256 audit.  The preceding Pages
fallback run (`32417839816`) found no valid production release and preserved
the currently published version without notifying anyone.

The public Mini App was then checked from the published bundle: the Creator
Intelligence panel and Taiwan/US News panel were both present, release-bound,
and rendered at a 390px viewport without horizontal overflow.  A scoped photo
smoke (`32418325859`) to test recipient `8869592162` produced a 1080x1350
card, delivered one message, and recorded a matching Railway receipt with
trace `photo-smoke-34fc671f8bc341f5`.

These checks lock Pages release integrity, Creator/News public rendering, and
the single-recipient delivery path.  They do not claim that external sources
are healthy: Railway still reports GDELT `HTTP_429` and Gmail
`configuration_missing`, and the research artifact remains an explicitly
labelled stale fallback.

## Current checkpoint (2026-08-15)

The overlap audit is now evaluated against main after PR #636. The sanitized
Railway observation export remains on the existing scheduled release path; no
second Creator or FinancialJuice pipeline was introduced.

The focused Creator, FinancialJuice, shared-event, release-gate, news, and
Telegram contract suite passes locally (`72 passed`) when run with an explicit
workspace `--basetemp`; the default OneDrive pytest temp root is not reliable
enough for evidence because it can retain locked directories. Remote quality
and security checks for the checkpoint are green. Pages artifact integrity and
a scoped single-recipient Telegram receipt are now evidenced below; post-merge
main acceptance and Mini App WebView visual confirmation remain open gates.

### Public Pages evidence captured (superseded by the latest evidence above)

Read-only HTTP verification of the currently published Pages bundle found:

- release `release-12ff05f51e4ea353` with `status=ready`
- Creator artifact `creator-e0c589f4b010dac5` with `status=ready`
- Creator public artifact with one sanitized creator record
- Source-health artifact schema `1.0`
- all six manifest-declared artifact SHA-256 hashes matched the downloaded
  public files

This proves public artifact integrity at the captured release. It does not
replace Mini App WebView visual confirmation or live Railway Gmail evidence.

### FinancialJuice Gmail HTML replay (2026-08-20)

A read-only Gmail inspection of a current FinancialJuice relay confirmed that
the transport is an HTML-only message: the vendor importance score and the
Traditional-Chinese translation are rendered in sibling HTML elements rather
than plain `Label: value` lines.  The canonical parser now converts that HTML
to bounded text before classification, recognizes `重要性評分`,
`繁體中文翻譯` and `AI 評論`, and uses the translation as a headline fallback
when the relay does not expose a separate original-headline field.  The
derived projection remains public-safe; no Gmail message IDs, raw body,
recipients or transport headers are persisted.

Sanitized regression evidence: the parser, shared external-event path,
privacy boundary and Railway Gmail gateway passed 41 tests; the relevant
source/contract/release suite passed 147 tests.  The live Railway source is
still `configuration_missing`, so this proves parser compatibility and not
live Gmail watch delivery.

### Runtime and delivery evidence captured

- Railway `/health` reports the monitor `running/healthy`.
- GDELT is explicitly `HTTP_429` and the GitHub dispatch callback is explicitly
  `HTTP_403`; neither failure is hidden or treated as a successful event scan.
- Scoped photo smoke Actions run `31882734841` delivered
  one test message; the Railway projection reports `last_outbox_status=delivered`,
  `last_receipt_status=delivered`, `receipt_matches_last_outbox=true`, one
  delivered, zero failed, and trace `photo-smoke-b09bb97240c54a9f`.
- Runtime boundary regression suite: `97 passed` across GDELT fetch/backoff,
  stale-cache projection, health callback 403/429 handling and repository
  dispatch transport. The live 429/403 therefore represents external runtime
  configuration/provider state, not an untested repository path.

### Post-merge refresh verification (PR #636)

Actions run [31886831364](https://github.com/hanjhou2000716/prstklab-stk-detector/actions/runs/31886831364)
completed successfully from main commit `46f0fae`. The public manifest returned
`status=ready` with release `release-12ff05f51e4ea353`, market snapshot
`92dcb8d32908d715`, research snapshot `research-8b8ec8f6e5ee51aa`, event
snapshot `event-f67c25c9f5e6f24d`, and Creator snapshot
`creator-e0c589f4b010dac5`. This refresh updates public market data and Pages;
it intentionally does not constitute a Telegram delivery receipt.

## Gate-driven migration reconciliation (2026-08-14)

The current branch is a continuation of the existing production stack, not a
new parallel implementation.  The attachment requirements map as follows:

| Requirement family | Canonical implementation | Verification | Status |
|---|---|---|---|
| Creator registry, identity and unknown-provider DLQ | `config/creator_providers.json`, `src/creator_provider_registry.py`, parser/health routers | registry, parser, scheduled-input and DLQ tests | PASS / LOCKED |
| Creator normalization, public artifact and release lineage | `src/creator_intelligence_pipeline.py`, `src/creator_artifact.py`, `src/creator_release.py` | creator artifact/release and briefing tests | PASS / LOCKED |
| FinancialJuice compound parsing and vendor-priority boundary | `src/financialjuice_contract.py`, `src/external_source_parsers.py` | compound, 7/8/9/10 priority and replay tests | PASS / LOCKED |
| FinancialJuice sanitized scheduled ingress | `src/external_observation_input.py`, `src/railway_observation_client.py`, `src/scheduled_delivery.py`, `.github/workflows/scheduled-brief.yml` | privacy rejection, remote/local fallback, source-health and snapshot-binding tests | NEEDS_REVERIFY (live Railway bundle evidence pending) |
| FinancialJuice operational observability | `src/external_observation_input.py`, `schemas/source-health.schema.json`, `site/app.js` | receive/parse/error/importance/pending metrics and UI contract (`52 passed`) | NEEDS_REVERIFY (Railway + Pages evidence pending) |
| Creator operational observability | `src/creator_source_health.py`, `schemas/source-health.schema.json`, `site/app.js` | receive/parse/error/delivery metrics and UI contract (`91 targeted`, `1147 full`), plus public Creator panel evidence | NEEDS_REVERIFY (live Railway ingress remains external) |
| Official News adapter observability | `src/news_feed_adapters.py`, `tests/test_news_feed_adapters.py` | per-provider checked/parsed/error/latency metrics (`45 targeted`, `1147 full`) | NEEDS_REVERIFY (live feed + Pages evidence pending) |
| Gmail watch observability | `railway-monitor/gmail_watch.py`, `tests/test_railway_gmail_gateway.py` | receive/parse/error/delivery metrics with cursor privacy boundary (`12 targeted`) | NEEDS_REVERIFY (Railway OAuth/PubSub evidence pending) |
| FinancialJuice release lineage and Mini App panel | `src/release_manifest.py`, `src/release_gate.py`, `site/index.html`, `site/app.js` | count/hash/source mismatch fixtures; public ready release, seven matching hashes, and browser DOM evidence | NEEDS_REVERIFY (Railway FinancialJuice source remains external) |
| FinancialJuice + news event unification | `src/external_event_pipeline.py`, `src/intelligence_pipeline.py` | event fan-out, evidence and lifecycle tests; public News/Creator projections present | PASS / LOCKED |
| Market News provider registry and URL contract | `src/news_intelligence.py`, `schemas/news-story.schema.json`, `schemas/news-intelligence.schema.json` | provider/domain, unknown URL, schema and dedup tests | PASS / LOCKED |
| Official news-feed adapters (TWSE/MOPS/SEC/Fed/Nasdaq) | `src/news_feed_adapters.py`; isolated TWSE/MOPS/SEC/Fed adapters; Nasdaq remains explicitly disabled until a stable documented endpoint is configured | parser, timeout/429 isolation and catalog tests; live feed evidence pending | partially_integrated |
| News interest graph, ranking and dedup | `src/news_intelligence.py`, `risk_news.build_news_snapshot` | ticker/sector reasons, authority ordering and supporting-source tests | PASS / LOCKED |
| News Mini App rendering | `site/app.js` release-provided provider allowlist and `news.json` lineage loader | Mini App asset, URL-safety, release-loader contract tests, and public browser evidence | PASS / LOCKED |
| News artifact in release lineage | `src/release_manifest.py`, `src/release_gate.py`, `src/artifact_contract.py`, `site/app.js` | manifest/hash, multi-market release, release-gate lineage and mixed-release tests (`52 passed` in targeted release/news gate suite) | PASS / LOCKED |
| Production release and Telegram acceptance | `src/release_gate.py`, workflows, delivery receipts | public ready release, 7/7 hash audit, Pages fallback, and scoped single-recipient receipt from main | PASS for scoped acceptance; broad production remains NEEDS_REVERIFY |

The legacy Anue/Google arrays remain compatibility fields.  The canonical
`news.intelligence` object is the only new consumer contract; it is additive
and fail-soft, so an optional news outage cannot invalidate core market,
research or event artifacts.  The UI uses the release provider registry for
URL validation rather than a hard-coded domain list.

## Evidence boundaries

`PASS / LOCKED` means implementation, targeted verification and preservation
tests are present on this branch.  The remaining `NEEDS_REVERIFY` row requires
a full Pages release and browser verification after the next manifest is built;
it is not claimed as production acceptance.  Production acceptance remains
open until the same evidence is repeated from the merged `main` release and
the Mini App WebView is visually confirmed.

## Rollback

Revert the atomic News Intelligence commit and restore the previous
`data-release` manifest.  Legacy `news.taiwan`/`news.us` arrays remain readable;
no individual artifact should be copied between releases.

## Existing implementation retained

The existing Creator normalizer, artifact/release contracts, source-health
rows, delivery receipts, privacy filter and release gate remain the production
pipeline. This change supplies identity metadata and routing policy to those
modules; it does not create a parallel Creator pipeline.

## Overlap reconciliation

Open Creator/Gmail/FinancialJuice PR chains must be reviewed against this
registry before merge. Any branch that adds another hard-coded provider list is
superseded or must be retargeted to the registry. The expected integration
order is registry/schema first, provider adapters second, then delivery and UI.

The News Intelligence contract was added in the earlier stack and is already
an ancestor of `main`; PR #618 is the current continuation branch. A Pages
release and scoped receipt are evidenced, while browser verification and
post-merge main verification are still required before the remaining
`NEEDS_REVERIFY` rows can be locked.

Sanitized FinancialJuice observations are now bound to the same release
manifest as market/research/event artifacts. The Mini App shows their source
and whether official confirmation or market synchronization is still pending.
This is a release-bound contract; a live Railway source bundle remains an
external configuration gate, while Telegram delivery has a scoped receipt.

The source-health row now also carries privacy-safe operational observability
for the sanitized ingress: last receive/parse timestamps, parser errors,
vendor-importance >=8 count, pending cluster count and notification decision.
It deliberately excludes observation IDs, mail transport identifiers, raw
content and recipients. The Mini App renders this state without upgrading a
pending item to a confirmed alert. A live Railway bundle and ready Pages
release are still required before this row can be locked as production.

### Canonical Railway provider bundle (2026-08-15)

The standalone Railway image now ships `railway-monitor/creator_providers.json`
as an exact JSON-equivalent copy of `config/creator_providers.json`.
`tests/test_railway_gmail_gateway.py::test_standalone_creator_bundle_matches_canonical_registry`
fails if the bundle drifts. The Railway root fallback retains only
FinancialJuice aliases; Creator identity matching continues to use the same
registry as the repository runtime, so the monitor cannot silently reintroduce
a second Creator whitelist. This is local integration evidence; live Railway
packaging still must prove `classifier_mode=repository-shared` before a
production lock.

### Mini App public-artifact preference (2026-08-15)

The Mini App now prefers the bounded `creator-insights.json` projection over
the internal `creator-release.json` envelope when both are present. This keeps
the UI from rendering an empty internal envelope while a valid public insight
projection contains sanitized episodes. The loader still verifies release,
market, research, event, creator release and creator snapshot bindings before
rendering either artifact. Targeted UI/fallback verification: `4 passed`; the
full repository regression remains `1231 passed, 1 skipped` at the prior
checkpoint. The change is committed as `a09bb30` on PR #618; the latest quality
and security checks are green.

### Railway runtime boundary reconciliation

The open stacked Railway work is an extraction of runtime boundaries, not a
second Creator or FinancialJuice pipeline:

| Runtime concern | Canonical owner | Compatibility owner | Duplicate risk | Gate state |
|---|---|---|---|---|
| Runtime secrets and feature flags | `railway-monitor/runtime_config.py` | `railway-monitor/app.py` lookup wrapper | legacy variable names only | local PASS / external NEEDS_REVERIFY |
| Health projection and heartbeat | `railway-monitor/health_contract.py` | `railway-monitor/app.py` HTTP handler | no provider classifier | local PASS / external NEEDS_REVERIFY |
| Gmail runtime construction | `railway-monitor/gmail_runtime.py` | `railway-monitor/app.py` factory alias | no parser duplication | local PASS / external NEEDS_REVERIFY |
| Repository dispatch transport | `railway-monitor/dispatch_transport.py` | `railway-monitor/app.py` async wrapper | no event classification | local PASS / external NEEDS_REVERIFY |
| Jin10/GDELT poll settings | `railway-monitor/poll_config.py` | `railway-monitor/app.py` loop | no source or alert policy | local PASS / external NEEDS_REVERIFY |
| Event classification | `src/event_classifier.py` when repository package is present | bundled Railway fallback only when the root-only image cannot import `src` | **known compatibility risk**; fallback is health-visible and must not be treated as canonical | NEEDS_REVERIFY |

The last row is intentionally not marked production: the root-only Railway
image still has a compatibility classifier. The fallback is retained only to
keep `/health` available during a misconfigured deployment; production
acceptance must prove the repository-shared classifier is active (or the
deployment packaging must be changed before high-risk delivery is enabled).
No Creator provider list, FinancialJuice parser, event cluster, release gate,
or Telegram policy is reimplemented in `railway-monitor/app.py`.

### Current stacked PR evidence

Historical stack reference: PR #584 (`feat/railway-runtime-config-boundary`)
was an earlier continuation. The current continuation is PR #618
(`feat/REQ-ADD-039-gate-migration-audit`).
of PRs #580–#583. Its local atomic extractions are covered by the migration
state ledger; the remote quality/security checks are green. It must not be
treated as fully accepted until Railway source configuration, post-merge main
verification and the Mini App WebView gate are captured.

## Failure and rollback

Malformed or missing registry configuration fails closed at import/load time;
unknown creators are routed to the DLQ and never published. Rollback is the
single revert of the registry integration PR; existing known-provider fixtures
remain compatible.
The P0-24 observability contract is implemented in the merged stack and the
remote quality/security checks pass; the remaining external gates are Railway
source configuration and post-merge acceptance.

### Canonical email routing continuation (2026-08-15)

`src/email_intelligence.py` now routes Creator identities exclusively through
`creator_provider_registry.py`; its fallback table contains only the
FinancialJuice aliases. This removes the second source whitelist that could
silently diverge from `config/creator_providers.json`. The routing regression
also proves a canonical 財經皓角 marker still resolves to `haojiao`, while
unknown sources remain DLQ-safe. This is local evidence and does not claim live
Gmail/Railway delivery.

### Canonical template adapter continuation (2026-08-15)

`src/creator_source_adapters.py` now derives its provider dispatch map from
`creator_provider_registry.creator_ids()` and keeps only one shared labelled
template vocabulary. A registry provider using `creator-template-v2` therefore
cannot be silently rejected because a second parser whitelist was not updated.
The parser remains fail-closed for unknown providers and unlabelled prose. The
registry-wide adapter regression covers every currently enabled provider.

The adapter validates the registry `parser` field before parsing. An unknown
or future parser version returns `unsupported_parser` rather than silently
using the v2 template, keeping parser configuration and runtime behavior
aligned without weakening the DLQ boundary.

### Canonical news feed adapter contract (follow-up)

`src/news_feed_adapters.py` now derives its official feed catalog from the
canonical `src.news_intelligence.PROVIDER_REGISTRY`. Endpoint URL, parser kind,
market, authority tier, timeout and disabled-source reason therefore have one
owner. Discovery sources such as Google News and Anue cannot enter the
official-evidence fetch path merely because they appear in the public provider
registry. Adapter tests verify the registry projection and preserve
per-provider failure isolation, rate-limit classification and no-event versus
failed semantics. This is local/CI evidence; live source freshness remains an
external acceptance gate.

The release validator also checks optional feed metadata: configured endpoints
must be HTTPS and remain inside the provider's canonical domain, while a
disabled provider may explicitly retain an empty endpoint for diagnostics.

### Railway keyword bundle contract (REQ-ADD-043)

The standalone Railway image now carries the exact canonical
`config/event_keywords.json` payload. A reduced or separately edited keyword
table could classify the same Jin10/GDELT item differently from the
repository-shared classifier; this is a policy drift defect, not an allowed
fallback. `tests/test_railway_monitor.py` compares the parsed bundle structure
with the canonical payload. Dispatch remains fail-closed when the shared classifier is
not packaged, and live Railway `classifier_mode=repository-shared` evidence is
still required before production acceptance.

### Repository-shared classifier packaging (REQ-ADD-044)

The standalone image now includes a generated copy of the canonical event
classifier. `scripts/sync_railway_shared_classifier.py` is the only producer;
CI fails when the tracked bundle differs from `src/event_classifier.py`.
Root-only import isolation therefore exercises the same multilingual policy
and keyword bundle as the repository pipeline. This is local/CI evidence only;
the Railway `/health` mode and a controlled delivery receipt remain external
`NEEDS_REVERIFY` gates.

### Actionable Gmail configuration diagnostics (2026-08-20)

The Railway Gmail health projection now exposes only the names of missing
configuration keys when the watch is `configuration_missing`. It deliberately
does not expose OAuth values, Pub/Sub credentials, mailbox identifiers, or
message cursors. This makes the operator action explicit while preserving the
privacy boundary. Live Gmail watch delivery remains `NEEDS_REVERIFY` until the
Railway environment is configured and a controlled receipt is captured.

### Post-merge release and Railway evidence (2026-08-20)

The Gmail diagnostics change is now on `main` at `d279a9b` (merge of PR
#653). Main-branch quality and security workflows completed successfully,
and the targeted Railway health-contract/runtime regression suite passed
(`98 passed`). The approved `refresh-dashboard` run `32385839035` then
published the following coherent Pages release:

The full repository regression also passed (`1266 passed, 1 skipped`) when
run with an ASCII temporary directory. The default workspace-local temp path
is under a non-ASCII OneDrive directory and produced only a local Windows
permission/encoding warning; it is not a repository test failure.

| Artifact | ID |
|---|---|
| Release | `release-d7831aa2cce8bd35` |
| Market snapshot | `d2ea6264dc43aad2` |
| Research snapshot | `research-8b8ec8f6e5ee51aa` |
| Event snapshot | `event-ed531dee05c7de49` |

The same public manifest's Creator and news artifacts are also present and
release-bound: Creator release `creator-9d88617b6fd60ed6` reports
`status=ready`, `public_safe=true`, coverage `1/1` (Haojiao) and zero
validation errors; news snapshot `news-cc4794ea205628ee` reports
`status=ready`. The single-creator coverage is explicit and is not presented
as a two-source consensus.

The public manifest reports `status=ready` and those IDs are mutually
consistent. No Telegram notification was emitted by this refresh because the
run produced no qualifying alert.

The Railway monitor has since rolled to the merged diagnostics build. Its
read-only health response reports `status=ok`, a running/healthy monitor and
the Gmail projection now includes the redacted missing-key list. Gmail is
still intentionally `configuration_missing` (OAuth/Pub/Sub variables are not
configured), so this is deployment evidence—not evidence of live Gmail watch
delivery. GDELT remains fail-closed after `invalid_json`, and the health
callback remains permission-denied (`HTTP_403`); neither condition is treated
as a successful event or as a reason to publish a high-risk alert.

The remaining production gates are explicit: configure and verify Gmail
OAuth/Pub/Sub, restore a successful GDELT response or bounded cache, and
capture one controlled Telegram delivery receipt linked to a ready release.
Until those observations exist, the related rows remain `NEEDS_REVERIFY`.

### Controlled Telegram photo acceptance (2026-08-20)

The scoped `PRStK Notification` workflow run `32388111469` completed
successfully with `photo_test=true` and one explicitly supplied recipient.
The renderer installed Chromium, the photo smoke step succeeded, and the
Railway receipt projection matched the outbox:

- trace: `photo-smoke-09b44a04039f482c`
- outbox: `delivered`
- receipt: `delivered`
- delivered / failed / recipients: `1 / 0 / 1`
- `receipt_matches_last_outbox=true`

This is a controlled single-recipient acceptance, not a broadcast or proof of
every subscriber's delivery. The remaining external gates are Gmail OAuth /
Pub/Sub ingress and a qualifying live FinancialJuice receipt.

### Latest approved refresh rerun (2026-08-21 Asia/Taipei)

The approved `refresh-dashboard` dispatch from the merged `main` commit
`d279a9b24f325913567a55d4706bfc65158b867c` completed successfully in Actions
run [32389687042](https://github.com/hanjhou2000716/prstklab-stk-detector/actions/runs/32389687042).
The public manifest was re-read after Pages deployment and returned
`status=ready`; its release-bound artifact set is:

| Artifact | ID |
|---|---|
| Release | `release-24bbf60f03850ca5` |
| Market snapshot | `40f6d61f5886c7c8` |
| Research snapshot | `research-8b8ec8f6e5ee51aa` |
| Event snapshot | `event-ed531dee05c7de49` |
| Creator snapshot | `creator-c11ad4250540693f` |
| News snapshot | `news-ae8520aae4d776ae` |

The manifest declares `creator_public_status=ready`, `news_status=ready`,
zero validation errors and matching artifact hashes. Research remains
explicitly `stale_fallback` as a data-freshness state; it is not relabelled as
live merely because the market refresh succeeded. No Telegram notification was
emitted because this refresh produced no qualifying alert.

### Latest read-only Railway health (2026-08-21 00:08 Asia/Taipei)

The post-refresh health read returned `status=ok`. The monitor completed its
latest cycle with `heartbeat_status=healthy`, and the deployed classifier was
`repository-shared`. The delivery projection still reports the prior
controlled photo smoke as `delivered` with
`receipt_matches_last_outbox=true`; no new broadcast was created by the
dashboard refresh.

The same response keeps the external gates explicit and fail-closed:

- Gmail is `configuration_missing`; only the missing variable names are
  exposed (`GMAIL_WATCH_TOPIC`, `GMAIL_WATCH_LABEL_IDS`, `GMAIL_OAUTH_STATE`,
  `GMAIL_PUBSUB_AUDIENCE`, `GMAIL_PUBSUB_SERVICE_ACCOUNT`).
- GDELT is `HTTP_429`, with no stale cache promoted to live evidence.
- The non-fatal health callback is `HTTP_403` and is scheduled for bounded
  retry; it does not change the local Railway health result.

This read is operational evidence only. It does not claim live Gmail ingress,
a successful GDELT poll, or a new FinancialJuice qualifying receipt.

### Approved refresh-dashboard run (2026-08-21 12:09 Asia/Taipei)

The user-approved `refresh-dashboard` dispatch from `main` commit
`6a8849676fbd859447ece0b725d7a363d80ef361` completed successfully in Actions
run [32412415883](https://github.com/hanjhou2000716/prstklab-stk-detector/actions/runs/32412415883).
The run completed market refresh, immutable data-release publication, asset
build, Pages deployment and public artifact upload without bypassing the
release gate.

The public manifest was re-read after deployment and returned `status=ready`:

| Artifact | ID |
|---|---|
| Release | `release-f9c4dba0b0ede6c5` |
| Market snapshot | `b6353a161a9bc86a` |
| Research snapshot | `research-8b8ec8f6e5ee51aa` |
| Event snapshot | `event-a889bf10a4141a3b` |
| Creator snapshot | `creator-c1a6ab872c820f3d` |
| News snapshot | `news-f8623518ad0441d9` |

All manifest-declared artifact hashes matched the public downloads at the
time of capture; Creator and News artifacts were `ready`. Research remained
`stale_fallback` because the bounded MOPS research gate was not complete. The
refresh therefore updated the public market/creator/news release but did not
pretend that the research scan was current and did not emit a Telegram alert.
This is the expected fail-closed behavior while the incremental MOPS cache is
being filled by the bounded research workflow.

### Canonical release correlation repair (2026-08-21)

The release-manifest producer now passes the actual release-bound market,
research and event artifacts into the existing Creator correlation function.
Previously the manifest path passed only snapshot IDs, so the public episode
could be lineage-labelled while reporting `market_snapshot_missing` and could
not match an explicit ticker or sector.  The correlation time parser also
accepts the immutable artifact field `generated_at` in addition to runtime
`as_of`/`fetched_at` timestamps.  This is a producer wiring correction, not a
new classifier or a second pipeline.

Targeted regression evidence: `21 passed` across release-manifest Creator
artifact, correlation and intelligence-pipeline tests.  The test proves an
explicit `2330.TW` match carries the release market/event snapshot IDs and
returns `aligned` when the bound market snapshot is fresh.

### FinancialJuice priority visibility (2026-08-21)

The existing `外部財經快訊` panel now renders release-bound
`financialjuice_priority_decisions` beside each sanitized observation. It
shows whether an item is eligible for vendor-priority handling, below the
8/10 threshold, or already covered by the same event cluster. This is display
and audit metadata only: FinancialJuice remains discovery-only, does not
upgrade PRStK risk, and does not bypass official confirmation, market-sync,
Alert Budget, or the release gate.
