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
and security checks for the checkpoint are green. Pages artifact integrity and
a scoped single-recipient Telegram receipt are now evidenced below; post-merge
main acceptance and Mini App WebView visual confirmation remain open gates.

### Public Pages evidence captured

Read-only HTTP verification of the currently published Pages bundle found:

- release `release-957714e850293f39` with `status=ready`
- Creator artifact `creator-86a5ed7f74464baa` with `status=ready`
- Creator public artifact with one sanitized creator record
- Source-health artifact schema `1.0`
- all six manifest-declared artifact SHA-256 hashes matched the downloaded
  public files

This proves public artifact integrity at the captured release. It does not
replace post-merge main verification or Mini App WebView visual confirmation.

### Runtime and delivery evidence captured

- Railway `/health` reports the monitor `running/healthy`.
- GDELT is explicitly `HTTP_429` and the GitHub dispatch callback is explicitly
  `HTTP_403`; neither failure is hidden or treated as a successful event scan.
- Scoped photo smoke Actions run `31839093636` / job `94891873503` delivered
  one test message; the Railway projection reports `last_outbox_status=delivered`,
  `last_receipt_status=delivered`, `receipt_matches_last_outbox=true`, one
  delivered, zero failed, and trace `photo-smoke-b09bb97240c54a9f`.
- Runtime boundary regression suite: `97 passed` across GDELT fetch/backoff,
  stale-cache projection, health callback 403/429 handling and repository
  dispatch transport. The live 429/403 therefore represents external runtime
  configuration/provider state, not an untested repository path.

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
| Creator operational observability | `src/creator_source_health.py`, `schemas/source-health.schema.json`, `site/app.js` | receive/parse/error/delivery metrics and UI contract (`91 targeted`, `1147 full`) | NEEDS_REVERIFY (Railway + Pages evidence pending) |
| Official News adapter observability | `src/news_feed_adapters.py`, `tests/test_news_feed_adapters.py` | per-provider checked/parsed/error/latency metrics (`45 targeted`, `1147 full`) | NEEDS_REVERIFY (live feed + Pages evidence pending) |
| Gmail watch observability | `railway-monitor/gmail_watch.py`, `tests/test_railway_gmail_gateway.py` | receive/parse/error/delivery metrics with cursor privacy boundary (`12 targeted`) | NEEDS_REVERIFY (Railway OAuth/PubSub evidence pending) |
| FinancialJuice release lineage and Mini App panel | `src/release_manifest.py`, `src/release_gate.py`, `site/index.html`, `site/app.js` | count/hash/source mismatch fixtures; public ready release and six matching hashes | NEEDS_REVERIFY (post-merge WebView evidence pending) |
| FinancialJuice + news event unification | `src/external_event_pipeline.py`, `src/intelligence_pipeline.py` | event fan-out, evidence and lifecycle tests | PASS / LOCKED |
| Market News provider registry and URL contract | `src/news_intelligence.py`, `schemas/news-story.schema.json`, `schemas/news-intelligence.schema.json` | provider/domain, unknown URL, schema and dedup tests | PASS / LOCKED |
| Official news-feed adapters (TWSE/MOPS/SEC/Fed/Nasdaq) | `src/news_feed_adapters.py`; isolated TWSE/MOPS/SEC/Fed adapters; Nasdaq remains explicitly disabled until a stable documented endpoint is configured | parser, timeout/429 isolation and catalog tests; live feed evidence pending | partially_integrated |
| News interest graph, ranking and dedup | `src/news_intelligence.py`, `risk_news.build_news_snapshot` | ticker/sector reasons, authority ordering and supporting-source tests | PASS / LOCKED |
| News Mini App rendering | `site/app.js` release-provided provider allowlist and `news.json` lineage loader | Mini App asset, URL-safety, and release-loader contract tests | NEEDS_REVERIFY |
| News artifact in release lineage | `src/release_manifest.py`, `src/release_gate.py`, `src/artifact_contract.py`, `site/app.js` | manifest/hash, multi-market release, release-gate lineage and mixed-release tests (`52 passed` in targeted release/news gate suite) | PASS / LOCKED |
| Production release and Telegram acceptance | `src/release_gate.py`, workflows, delivery receipts | public ready release plus scoped receipt evidenced; post-merge main acceptance pending | NEEDS_REVERIFY |

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
