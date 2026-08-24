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
| Telegram photo delivery | `src/telegram_client.py`, `src/creator_photo_delivery.py`, production workflow | pass | post-release only | controlled single-recipient photo receipt verified for `release-be32bbe1a377553f` | `partially_integrated` |
| Railway outbox and receipt | `railway-monitor/delivery_store.py` | pass | health/receipt callback | same trace accepted; `delivered=1`, `failed=0`, receipt matches outbox | `partially_integrated` |

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

## Fresh external capture — 2026-08-24 22:59:54 Asia/Taipei

The redacted capture is preserved at
`docs/evidence/external-acceptance-2026-08-24T145954Z.json`. It confirms the
same release lineage is publicly available: Pages returned HTTP 200 with
`status=ready`, release `release-1df139db83e19642`, and all five declared
artifact hashes and snapshot identities verified. Railway returned HTTP 200;
the monitor heartbeat, Jin10, Gmail Watch, Creator and FinancialJuice lanes
were healthy at capture time.

The capture remains `NEEDS_REVERIFY`, not `PASS`, because GDELT returned
`HTTP_429`. No stale cache was promoted, the bounded health dispatch remained
healthy, and no Telegram or Railway write was attempted. Delivery remains
`not_checked`; this is deliberate evidence of the fail-closed boundary rather
than evidence of a successful production notification.

## Controlled production photo acceptance — 2026-08-24 23:23:45 Asia/Taipei

The controlled `production-acceptance-photo` workflow completed successfully
for the explicitly supplied single test recipient. The redacted evidence is
preserved at `docs/evidence/external-acceptance-2026-08-24T152345Z.json`.
Pages served the same ready release (`release-be32bbe1a377553f`) and all five
artifact hashes matched. The renderer produced a readable 1080×1350 PNG with
no renderer error. Telegram reported `delivered=1`, `failed=0`; Railway then
accepted the matching trace and reports `receipt_matches_last_outbox=true`.

This is scoped delivery evidence, not a broadcast acceptance and not evidence
that Creator/FinancialJuice observations have already produced a new release.
GDELT remains `HTTP_429` with no stale cache promotion, so high-risk eligibility
remains fail-closed.

## Follow-up external capture — 2026-08-24 23:12:08 Asia/Taipei

The follow-up capture is preserved at
`docs/evidence/external-acceptance-2026-08-24T151208Z.json`. Pages continued to
serve a `ready` release (`release-671d7405d51f5b08`) with all five declared
artifact hashes and snapshot identities verified. Railway remained HTTP 200
with a healthy heartbeat, active Gmail Watch, and healthy Creator and
FinancialJuice lanes.

GDELT remained `scan_failed` with `HTTP_429`; the monitor did not promote a
stale cache and remained backoff-protected. Telegram delivery is still
`not_checked`, so this capture does not claim production notification
acceptance.

## Remaining gates

1. Capture one sanitized Gmail observation on Railway and confirm the same
   observation reaches the release artifact.
2. Verify the Mini App in Telegram WebView, including the deep link and the
   degraded/fallback state.
3. Recheck the official news feed freshness after the next refresh. A failed
   provider remains a source failure; it is never converted to no event.
4. Keep GDELT rate-limit backoff bounded until an independent successful poll
   is observed.

No gate above is satisfied by a fixture, a local mock or an old release.

## Rollback

This document is audit-only. Reverting its commit changes no runtime path.
Runtime rollback remains the existing immutable `data-release` rollback and
release-gate fallback; never copy individual artifacts between releases.
