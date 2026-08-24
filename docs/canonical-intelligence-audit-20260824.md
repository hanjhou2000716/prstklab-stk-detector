# Canonical intelligence integration audit — 2026-08-24

## Scope and decision

This audit starts from `main` after PR #749. It reconciles the existing
Creator, FinancialJuice, Gmail, News, Release Gate, Mini App and Telegram
owners; it does not introduce a second classifier, provider registry, release
builder or dispatcher.

The canonical path remains:

```text
Gmail / official feeds / discovery feeds
→ sanitized observation
→ canonical provider/parser contract
→ shared event/news classification
→ evidence, freshness and lifecycle gates
→ immutable release manifest
→ Pages / Mini App
→ release-gated Telegram
→ Railway delivery receipt
```

Creator material is editorial enrichment only. FinancialJuice importance is a
notification-priority signal only. Neither can independently create official
market evidence or a high-risk alert.

## Integration matrix

| Capability | Canonical owner | Local contract | Main integration | External evidence | Status |
|---|---|---:|---:|---:|---|
| Creator registry and parser | `config/creator_providers.json`, `src/creator_provider_registry.py`, `src/creator_source_adapters.py` | pass | release/health/Mini App | Railway currently `no_new_content` | `partially_integrated` |
| Creator consensus and lineage | `src/creator_consensus.py`, `src/creator_correlation.py`, `src/creator_release.py` | pass | release-bound artifact | no current creator artifact in public release | `partially_integrated` |
| FinancialJuice compound parser and priority | `src/financialjuice_contract.py`, `src/financialjuice_priority.py`, `src/external_source_parsers.py` | pass | sanitized ingress and release projection | Railway currently `no_new_content` | `partially_integrated` |
| Gmail Watch and history sync | `railway-monitor/gmail_watch_service.py`, `railway-monitor/gmail_history_sync.py` | pass | Railway `/health` | Watch healthy, cursor present, no new observation | `partially_integrated` |
| Official and discovery news | `src/news_intelligence.py`, `src/news_feed_adapters.py` | pass | `news.json` and Mini App | Taiwan/US split is ready; one US official feed failed | `partially_integrated` |
| Release manifest and hash gate | `src/release_manifest.py`, `src/release_gate.py`, `src/external_acceptance.py` | pass | Pages before notification | public `status=ready`, artifact hashes verified at capture | `production` |
| Mini App release routing | `site/app.js` | pass | manifest-bound loader and health panel | public release loads; WebView visual gate remains | `partially_integrated` |
| Telegram photo delivery | `src/telegram_client.py`, `src/creator_photo_delivery.py`, production workflow | pass | post-release only | controlled receipt exists historically; no current run | `partially_integrated` |
| Railway outbox and receipt | `railway-monitor/delivery_store.py` | pass | health/receipt callback | current delivery `not_checked` | `partially_integrated` |

`partially_integrated` is intentional: local tests prove the contract, while
the external column records whether the same release and source have been
observed in production. It must not be promoted to `production` from mocks.

## Captured public evidence

The read-only capture used for this audit was taken on 2026-08-24 Asia/Taipei:

- Pages manifest: `release-05bc2e16716a3be7`, `status=ready`.
- Market snapshot: `632c92828b4c27a7`.
- Research snapshot: `research-8b8ec8f6e5ee51aa`, explicitly
  `research_freshness=stale_fallback`; it is not presented as fresh research.
- Event snapshot: `event-a889bf10a4141a3b`.
- News snapshot: `news-2840126ba7c8d4c5`, `status=ready`, with separate Taiwan
  and US views and source-health rows.
- Railway monitor: HTTP 200, heartbeat healthy, repository-shared classifier
  active, Gmail Watch healthy through 2026-08-31, history cursor present.
- GDELT: `HTTP_429`, `scan_failed`, no stale cache promoted to live evidence.
- Railway delivery: `not_checked`; no production delivery is inferred.

This evidence is diagnostic only. It does not claim a new Telegram send or a
live Creator/FinancialJuice message unless a matching receipt is present.

## Remaining gates

1. Capture one sanitized Gmail observation on Railway and confirm the same
   observation reaches the release artifact.
2. Capture one controlled, single-recipient Telegram receipt bound to that
   release, snapshot and observation.
3. Verify the Mini App in Telegram WebView, including the deep link and the
   degraded/fallback state.
4. Recheck the official news feed freshness after the next refresh. A failed
   provider remains a source failure; it is never converted to no event.
5. Keep GDELT rate-limit backoff bounded until an independent successful poll
   is observed.

No gate above is satisfied by a fixture, a local mock or an old release.

## Rollback

This document is audit-only. Reverting its commit changes no runtime path.
Runtime rollback remains the existing immutable `data-release` rollback and
release-gate fallback; never copy individual artifacts between releases.
