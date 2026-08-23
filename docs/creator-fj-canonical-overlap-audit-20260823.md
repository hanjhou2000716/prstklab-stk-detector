# Creator／FinancialJuice／News canonical overlap audit — 2026-08-23

## Scope and checkpoint

This audit starts from the current `main` checkpoint (`92f8907`, PR #725),
not from an historical Creator or FinancialJuice branch.  The working tree was
clean before this change.  Existing provider registries, event classification,
release gate, Mini App loader, Telegram delivery and Railway ingress remain the
canonical owners; this change does not introduce a parallel pipeline.

## Integration matrix (current evidence)

| Capability | Canonical owner | Local contract tests | Current status | Remaining evidence |
|---|---|---:|---|---|
| Creator provider registry and parser boundary | `src/creator_provider_registry.py`, `src/creator_source_adapters.py` | pass | production | live Railway sanitized input |
| Creator consensus/correlation/lineage | `src/creator_consensus.py`, `src/creator_correlation.py`, `src/creator_release.py` | pass | production | Pages release verification |
| Creator morning batch and dedupe | `src/creator_morning_batch.py`, `src/creator_dispatch.py` | pass | partially_integrated | one-recipient receipt |
| FinancialJuice compound parsing and priority | `src/financialjuice_contract.py`, `src/financialjuice_priority.py` | pass | production | live sanitized Railway bundle |
| Shared external observation ingress | `src/external_observation_input.py`, `src/railway_observation_client.py` | pass | partially_integrated | Railway endpoint health/receipt |
| Official/news routing | `src/news_intelligence.py`, `src/news_feed_adapters.py` | pass | partially_integrated | live provider freshness and market split |
| Release manifest and Pages gate | `src/release_manifest.py`, `src/release_gate.py` | pass | production | public release/hash evidence |
| Telegram photo delivery | `src/telegram_client.py`, `src/creator_photo_delivery.py` | pass | needs reverify | single-recipient production-safe receipt |

The local verification command for this checkpoint is:

```text
python -m pytest -q --basetemp=<isolated-temp>
1360 passed
```

This is local evidence only; it does not claim live Railway, Pages or Telegram
acceptance.

## Overlap decision

1. Creator editorial content remains non-evidence and cannot become a market
   risk signal by itself.
2. FinancialJuice vendor importance remains separate from PRStK risk.  A score
   of 8 or higher may enter the vendor-priority lane, but it cannot bypass the
   official-source and market-synchronization gates.
3. Creator, FinancialJuice and official news observations enter the existing
   shared event/news contracts.  They do not get provider-specific classifiers
   in `railway-monitor/app.py`.
4. Release, hash, snapshot and delivery identity remain the single lineage
   boundary for Pages, Mini App and Telegram.

## Reconciled publication gap

The scheduled workflow previously required both `status=ready` and
`research_freshness=fresh` before publishing anything.  That coupled an
explicit, safe research fallback to unrelated market/event/creator publication
and left the Mini App on an old release.  The workflow now uses:

- **Publication gate:** manifest `status=ready`.
- **Research delivery gate:** `research_freshness=fresh`.

Therefore a release with `research_freshness=stale_fallback` can publish its
market, event and creator artifacts with the stale label intact, while Telegram
research delivery remains blocked.  An `invalid` or non-ready manifest still
fails closed and preserves the previous immutable release.

## Open external evidence debt

- Railway Gmail/FinancialJuice sanitized export and health projection.
- Public Pages manifest/hash and Mini App release lineage.
- One-recipient Telegram photo/card/deep-link delivery receipt.
- Live official news-feed freshness and Taiwan/US market separation.

These remain `NEEDS_REVERIFY`; mocks and local tests must not be reported as
production acceptance.  Rollback is a revert of this atomic workflow/docs
change, followed by restoring the last successful immutable `data-release`.
