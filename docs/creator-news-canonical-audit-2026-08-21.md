# Creator Intelligence／FinancialJuice／News canonical integration audit

Date: 2026-08-21 (Asia/Taipei)

This is an evidence checkpoint against `origin/main` at
`7d294269ffc09bc6ac1a2b52f9020360a64283f8`. It is intentionally a
documentation-only audit. It does not promote optional connectors to production
and does not replace the release gate.

## Canonical path

All three domains must converge on one release-bound path:

```text
ingress
  -> provider adapter / parser
  -> sanitized observation
  -> domain contract
  -> interest / relevance classification
  -> event-cluster deduplication and consensus
  -> release manifest + artifact hash gate
  -> Pages / Mini App
  -> Telegram delivery + receipt
```

The producer is authoritative. A UI fallback, a stale cache, or a release-time
normalizer cannot create a new event, candidate, risk direction, or delivery.

## Overlap findings and decisions

| Capability | Canonical owner | Duplicate or overlapping path | Decision | Evidence |
|---|---|---|---|---|
| Creator provider registry | `src/creator_provider_registry.py` + `config/creator_providers.json` | Railway registry adapters | Keep one shared provider configuration; Railway only transports sanitized observations | `tests/test_creator_provider_registry.py`, `tests/test_creator_config.py` |
| Creator consensus | `src/creator_consensus.py` and `src/creator_intelligence_pipeline.py` | UI-only aggregation in `site/app.js` | UI consumes the release artifact; it must not recompute consensus | `tests/test_creator_consensus.py`, `tests/test_creator_insight_ui_contract.py` |
| FinancialJuice priority | `src/financialjuice_priority.py` | Generic risk classifier / emergency alert | Vendor priority is a routing hint only; it cannot change PRStK risk or bypass evidence gates | `tests/test_financialjuice_priority.py`, `tests/test_external_event_pipeline.py` |
| News provider routing | `src/news_feed_adapters.py` and `src/risk_news.py` | Direct provider calls in UI | Keep provider calls in the producer; Mini App only reads `data/news.json` bound to the manifest | `tests/test_news_feed_adapters.py`, `tests/test_release_manifest.py` |
| News relevance | `src/news_intelligence.py` | Market-specific ad-hoc keyword filtering | Use the canonical interest context and explicit relevance reasons; do not silently reuse another market's stories | `tests/test_news_intelligence.py`, `tests/test_news_market_scope.py` |
| Cross-provider event identity | `src/news_intelligence.py` | Per-provider headline-only deduplication | Use deterministic `event_cluster_key`; preserve source evidence and never merge unrelated generic ticker stories | `tests/test_news_intelligence.py` |
| Release binding | `src/release_manifest.py` + `src/release_gate.py` | Pages deploy or Telegram code paths | Publish and notify only after the same release/snapshot/hash passes validation | `tests/test_release_gate.py`, `tests/test_pages_release.py` |
| Mini App presentation | `site/app.js` | Producer-side HTML or Telegram-only summaries | Mini App renders release data and explains source state; it never invents missing data | `tests/test_news_empty_state_ui.py`, `tests/test_news_badges_ui.py` |
| Telegram delivery | `src/telegram_client.py` + `src/scheduled_delivery.py` | Creator-specific delivery wrappers | Keep one release-gated delivery path; creator/news context remains evidence attached to the same release | `tests/test_telegram_photo_delivery.py`, `tests/test_scheduled_delivery.py` |

## Current integration status

| Area | Implementation | Pipeline | JSON / release | Mini App | Telegram | Status |
|---|---|---|---|---|---|---|
| Creator registry/adapters | yes | yes | yes | yes | bounded/partial | production |
| Creator consensus and correlation | yes | yes | yes | yes | context only | production |
| Creator morning batch | yes | scheduled slot | yes | yes | opt-in/release-gated | partially_integrated |
| FinancialJuice parser/priority | yes | sanitized bundle path | yes | yes | priority routing | production |
| FinancialJuice Gmail ingress | yes | Railway-only | sanitized only | health/pending state | no raw mail | partially_integrated |
| News provider registry/routing | yes | market snapshot | yes | yes | context only | production |
| News relevance/ranking | yes | market snapshot | yes | badges/reasons | context only | production |
| Cross-provider event clustering | yes | release producer | yes | event identity | lifecycle gate | production |
| Empty/no-event/source-failure UI state | yes | release health | yes | explicit state | no false alert | production |
| Release manifest/hash gate | yes | Pages + notify gate | yes | loader verification | send gate | production |
| Railway health/receipts | yes | monitor boundary | redacted | health panel | receipt contract | partially_integrated |

`partially_integrated` is deliberate: it means the code and contract exist but
live external configuration or post-merge evidence is still required. It is not
equivalent to a failed release and must not be silently promoted to `production`.

## Evidence captured on current main

- `origin/main` HEAD: `7d294269ffc09bc6ac1a2b52f9020360a64283f8`.
- Refresh dashboard run `32435052135` completed successfully.
- Public manifest returned HTTP 200 with `status=ready` and
  `creator_public_status=ready`, `news_status=ready`.
- Public release lineage is internally bound by `release_id`, market/research/
  event snapshot IDs and artifact hashes; a consumer must reject mixed releases.
- The open follow-up PRs #683, #684, #685 and #686 are each green and
  mergeable, but are not treated as present in `main` until merged.
- Offline production E2E on this checkout passed all gates: release contract,
  Creator release/delivery contract, `1080x1350` photo contract, renderer
  availability and mocked single-recipient Telegram boundary.
- `python -m src.runtime_audit` returned `ok=true` with explicit warnings for
  the checked-in diagnostic artifacts (missing event/research release fields and
  six local market gaps). Those warnings are not converted into a public
  `status=ready` claim; the public manifest remains the authoritative evidence.

## External acceptance gates still open

These are not claims of failure; they are evidence still required before the
corresponding row can be locked as production:

1. Railway Gmail OAuth/Pub/Sub configuration and a live sanitized ingress receipt.
2. Operator-managed Railway shared-secret migration; no secret value belongs in
   source, artifacts, or logs.
3. A real, single-recipient Telegram receipt tied to the same release and
   snapshot IDs, after the dry-run path passes.
4. Mini App WebView evidence that the deep link opens the requested release and
   safely falls back when that release is archived.
5. A current GDELT success or bounded stale-cache evidence; HTTP 429 must never
   become a live event or high-risk confirmation.

## Required next implementation order

1. Merge and re-verify the green news PRs in dependency order: interest context,
   event-cluster identity, badges, then empty-state handling.
2. Run one release-bound production smoke using the refreshed manifest.
3. Capture Railway health and delivery receipt evidence without exposing private
   identifiers.
4. Only then implement any remaining P0 item whose acceptance test is still
   absent. Do not create a second parser, classifier, release gate, or Telegram
   notification path.

## Rollback

Revert this document-only PR if the audit is superseded. Runtime rollback remains
the existing release-manifest rollback: restore the last `status=ready` release
and do not copy individual market, research, event, or creator artifacts across
release IDs.
