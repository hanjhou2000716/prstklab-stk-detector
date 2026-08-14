# Creator Intelligence overlap audit

## Decision

The canonical provider identity is `config/creator_providers.json`, loaded by
`src/creator_provider_registry.py`. Routers, parsers, source health, event
catalogue and release preparation must consume this registry; they must not
introduce a second provider whitelist.

The three configured providers are `haojiao`, `jenny`, and `gooaye`. They are
editorial enrichment only. They cannot independently become official event
evidence, a market-synchronisation proof, or a high-risk alert.

## Current checkpoint (2026-08-15)

The overlap audit is being continued on PR [#618](https://github.com/hanjhou2000716/prstklab-stk-detector/pull/618),
which is based on `main` and wires the sanitized Railway observation export into
the existing scheduled release. This is an integration continuation, not a
second Creator or FinancialJuice pipeline.

The focused Creator, FinancialJuice, shared-event, release-gate, news, and
Telegram contract suite passes locally (`72 passed`) when run with an explicit
workspace `--basetemp`; the default OneDrive pytest temp root is not reliable
enough for evidence because it can retain locked directories. Remote quality
and security checks for the checkpoint are green. Live Railway, Pages, and
single-recipient Telegram acceptance remain external gates and are therefore
not marked production-ready here.

### Public Pages evidence captured

Read-only HTTP verification of the currently published Pages bundle found:

- release `release-957714e850293f39` with `status=ready`
- Creator artifact `creator-86a5ed7f74464baa` with `status=ready`
- Creator public artifact with one sanitized creator record
- Source-health artifact schema `1.0`
- all six manifest-declared artifact SHA-256 hashes matched the downloaded
  public files

This proves public artifact integrity at the captured release, but does not
replace a post-merge browser, Railway, or Telegram acceptance test.

## Gate-driven migration reconciliation (2026-08-14)

The current branch is a continuation of the existing production stack, not a
new parallel implementation.  The attachment requirements map as follows:

| Requirement family | Canonical implementation | Verification | Status |
|---|---|---|---|
| Creator registry, identity and unknown-provider DLQ | `config/creator_providers.json`, `src/creator_provider_registry.py`, parser/health routers | registry, parser, scheduled-input and DLQ tests | PASS / LOCKED |
| Creator normalization, public artifact and release lineage | `src/creator_intelligence_pipeline.py`, `src/creator_artifact.py`, `src/creator_release.py` | creator artifact/release and briefing tests | PASS / LOCKED |
| FinancialJuice compound parsing and vendor-priority boundary | `src/financialjuice_contract.py`, `src/external_source_parsers.py` | compound, 7/8/9/10 priority and replay tests | PASS / LOCKED |
| FinancialJuice sanitized scheduled ingress | `src/external_observation_input.py`, `src/scheduled_delivery.py`, `.github/workflows/scheduled-brief.yml` | privacy rejection, source-health and snapshot-binding tests | partially_integrated (Railway bundle evidence pending) |
| FinancialJuice operational observability | `src/external_observation_input.py`, `schemas/source-health.schema.json`, `site/app.js` | receive/parse/error/importance/pending metrics and UI contract (`52 passed`) | NEEDS_REVERIFY (Railway + Pages evidence pending) |
| Creator operational observability | `src/creator_source_health.py`, `schemas/source-health.schema.json`, `site/app.js` | receive/parse/error/delivery metrics and UI contract (`91 targeted`, `1147 full`) | NEEDS_REVERIFY (Railway + Pages evidence pending) |
| Official News adapter observability | `src/news_feed_adapters.py`, `tests/test_news_feed_adapters.py` | per-provider checked/parsed/error/latency metrics (`45 targeted`, `1147 full`) | NEEDS_REVERIFY (live feed + Pages evidence pending) |
| Gmail watch observability | `railway-monitor/gmail_watch.py`, `tests/test_railway_gmail_gateway.py` | receive/parse/error/delivery metrics with cursor privacy boundary (`12 targeted`) | NEEDS_REVERIFY (Railway OAuth/PubSub evidence pending) |
| FinancialJuice release lineage and Mini App panel | `src/release_manifest.py`, `src/release_gate.py`, `site/index.html`, `site/app.js` | count/hash/source mismatch fixtures; 78 targeted and 1144 full local regression | NEEDS_REVERIFY (Pages browser evidence pending) |
| FinancialJuice + news event unification | `src/external_event_pipeline.py`, `src/intelligence_pipeline.py` | event fan-out, evidence and lifecycle tests | PASS / LOCKED |
| Market News provider registry and URL contract | `src/news_intelligence.py`, `schemas/news-story.schema.json`, `schemas/news-intelligence.schema.json` | provider/domain, unknown URL, schema and dedup tests | PASS / LOCKED |
| Official news-feed adapters (TWSE/MOPS/SEC/Fed/Nasdaq) | `src/news_feed_adapters.py`; isolated TWSE/MOPS/SEC/Fed adapters; Nasdaq remains explicitly disabled until a stable documented endpoint is configured | parser, timeout/429 isolation and catalog tests; live feed evidence pending | partially_integrated |
| News interest graph, ranking and dedup | `src/news_intelligence.py`, `risk_news.build_news_snapshot` | ticker/sector reasons, authority ordering and supporting-source tests | PASS / LOCKED |
| News Mini App rendering | `site/app.js` release-provided provider allowlist and `news.json` lineage loader | Mini App asset, URL-safety, and release-loader contract tests | NEEDS_REVERIFY |
| News artifact in release lineage | `src/release_manifest.py`, `src/release_gate.py`, `src/artifact_contract.py`, `site/app.js` | manifest/hash, multi-market release, release-gate lineage and mixed-release tests (`52 passed` in targeted release/news gate suite) | PASS / LOCKED |
| Production release and Telegram acceptance | `src/release_gate.py`, workflows, delivery receipts | local contracts pass; production credentials/release evidence required | BLOCKED (external) |

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
blocked when no ready release or Telegram delivery configuration is available.

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

The News Intelligence contract was added in PR #577's continuation branch;
the branch-level CI gate passed. A Pages release and browser verification are
still required before the two `NEEDS_REVERIFY` rows can be locked.

Sanitized FinancialJuice observations are now bound to the same release
manifest as market/research/event artifacts. The Mini App shows their source
and whether official confirmation or market synchronization is still pending.
This is a local contract lock only; Railway bundle and Telegram acceptance
remain external gates.

The source-health row now also carries privacy-safe operational observability
for the sanitized ingress: last receive/parse timestamps, parser errors,
vendor-importance >=8 count, pending cluster count and notification decision.
It deliberately excludes observation IDs, mail transport identifiers, raw
content and recipients. The Mini App renders this state without upgrading a
pending item to a confirmed alert. A live Railway bundle and ready Pages
release are still required before this row can be locked as production.

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

PR #584 (`feat/railway-runtime-config-boundary`) is the current continuation
of PRs #580–#583. Its local atomic extractions are covered by the migration
state ledger; the remote quality/security checks are green. It must not be
treated as production-ready until Railway health, a ready Pages release and a
single-recipient Telegram delivery receipt are captured after merge.

## Failure and rollback

Malformed or missing registry configuration fails closed at import/load time;
unknown creators are routed to the DLQ and never published. Rollback is the
single revert of the registry integration PR; existing known-provider fixtures
remain compatible.
The P0-24 observability contract is implemented in stacked PR #580. Its
remote quality/security checks pass, while Railway source-health evidence and
a ready Pages release remain external verification gates.
