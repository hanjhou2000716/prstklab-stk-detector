# Creator Intelligence overlap audit

## Decision

The canonical provider identity is `config/creator_providers.json`, loaded by
`src/creator_provider_registry.py`. Routers, parsers, source health, event
catalogue and release preparation must consume this registry; they must not
introduce a second provider whitelist.

The three configured providers are `haojiao`, `jenny`, and `gooaye`. They are
editorial enrichment only. They cannot independently become official event
evidence, a market-synchronisation proof, or a high-risk alert.

## Gate-driven migration reconciliation (2026-08-14)

The current branch is a continuation of the existing production stack, not a
new parallel implementation.  The attachment requirements map as follows:

| Requirement family | Canonical implementation | Verification | Status |
|---|---|---|---|
| Creator registry, identity and unknown-provider DLQ | `config/creator_providers.json`, `src/creator_provider_registry.py`, parser/health routers | registry, parser, scheduled-input and DLQ tests | PASS / LOCKED |
| Creator normalization, public artifact and release lineage | `src/creator_intelligence_pipeline.py`, `src/creator_artifact.py`, `src/creator_release.py` | creator artifact/release and briefing tests | PASS / LOCKED |
| FinancialJuice compound parsing and vendor-priority boundary | `src/financialjuice_contract.py`, `src/external_source_parsers.py` | compound, 7/8/9/10 priority and replay tests | PASS / LOCKED |
| FinancialJuice + news event unification | `src/external_event_pipeline.py`, `src/intelligence_pipeline.py` | event fan-out, evidence and lifecycle tests | PASS / LOCKED |
| Market News provider registry and URL contract | `src/news_intelligence.py`, `schemas/news-story.schema.json`, `schemas/news-intelligence.schema.json` | provider/domain, unknown URL, schema and dedup tests | PASS / LOCKED |
| Official news-feed adapters (TWSE/MOPS/SEC/Fed/Nasdaq) | registry metadata only; ingestion remains in existing source adapters | registry and URL-contract tests; live feed evidence pending | NEEDS_REVERIFY |
| News interest graph, ranking and dedup | `src/news_intelligence.py`, `risk_news.build_news_snapshot` | ticker/sector reasons, authority ordering and supporting-source tests | PASS / LOCKED |
| News Mini App rendering | `site/app.js` release-provided provider allowlist | Mini App asset and URL-safety tests | NEEDS_REVERIFY |
| News artifact in release lineage | `src/release_manifest.py`, `src/artifact_contract.py` | manifest/hash and mixed-release tests | NEEDS_REVERIFY |
| Production release and Telegram acceptance | `src/release_gate.py`, workflows, delivery receipts | local contracts pass; production credentials/release evidence required | BLOCKED (external) |

The legacy Anue/Google arrays remain compatibility fields.  The canonical
`news.intelligence` object is the only new consumer contract; it is additive
and fail-soft, so an optional news outage cannot invalidate core market,
research or event artifacts.  The UI uses the release provider registry for
URL validation rather than a hard-coded domain list.

## Evidence boundaries

`PASS / LOCKED` means implementation, targeted verification and preservation
tests are present on this branch.  The two `NEEDS_REVERIFY` rows require a
full Pages release and browser verification after the next manifest is built;
they are not claimed as production acceptance.  Production acceptance remains
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

## Failure and rollback

Malformed or missing registry configuration fails closed at import/load time;
unknown creators are routed to the DLQ and never published. Rollback is the
single revert of the registry integration PR; existing known-provider fixtures
remain compatible.
