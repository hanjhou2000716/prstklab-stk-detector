# Creator Intelligence overlap audit

## Decision

The canonical provider identity is `config/creator_providers.json`, loaded by
`src/creator_provider_registry.py`. Routers, parsers, source health, event
catalogue and release preparation must consume this registry; they must not
introduce a second provider whitelist.

The three configured providers are `haojiao`, `jenny`, and `gooaye`. They are
editorial enrichment only. They cannot independently become official event
evidence, a market-synchronisation proof, or a high-risk alert.

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

## Failure and rollback

Malformed or missing registry configuration fails closed at import/load time;
unknown creators are routed to the DLQ and never published. Rollback is the
single revert of the registry integration PR; existing known-provider fixtures
remain compatible.
