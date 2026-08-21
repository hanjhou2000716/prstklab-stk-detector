# Canonical news and source-health follow-up (2026-08-21)

This follow-up is based on `main` after the creator/news overlap audit. It
consolidates the remaining open functional work without introducing a second
Creator, FinancialJuice, or Telegram pipeline.

## Canonical ownership

| Concern | Canonical owner | Integrated behavior |
| --- | --- | --- |
| Creator identity and sanitized input | `config/creator_providers.json`, `src/creator_provider_registry.py`, `src/creator_source_adapters.py` | Unknown providers fail closed; raw mail/media never enters public artifacts. |
| Creator consensus and correlation | `src/creator_consensus.py`, `src/creator_correlation.py`, `src/creator_intelligence_pipeline.py` | Editorial context is attached to a release and never becomes market evidence by itself. |
| FinancialJuice observations | `src/financialjuice_contract.py`, `src/external_source_parsers.py`, `src/external_observation_input.py` | Vendor importance remains separate from PRStK risk; sanitized input is required. |
| News provider registry and routing | `src/news_intelligence.py`, `src/news_feed_adapters.py`, `src/risk_news.py` | Coverage is evaluated across all declared markets; unsupported providers are not guessed. |
| News interest/ranking context | `src/news_intelligence.py`, `src/risk_news.py`, `src/market_data.py` | Research tickers, active event topics, creator mentions, and current official events are explicit context signals. |
| Empty versus failed source state | `src/health_observability.py`, `src/source_health.py` | `no_new_content`/`no_event` is distinct from transport, parser, or authentication failure. |
| Release and delivery gate | `src/release_manifest.py`, `src/release_gate.py`, `src/scheduled_delivery.py` | Only a validated release can reach Telegram; source failure cannot be reclassified as no event. |

## Overlap decisions

1. The merged overlap-audit documentation remains the historical decision
   record. This document records only the functional follow-up.
2. Open branches that duplicate these changes should be treated as
   superseded after this branch is reviewed; their commits are not required
   for the canonical path.
3. Creator content is enrichment. It cannot independently confirm a market
   event, create a risk upgrade, or provide a market direction.
4. A FinancialJuice vendor-priority label cannot alter the PRStK risk level.
5. A news provider with no new content is healthy for this cycle; HTTP,
   parser, authentication, and policy failures remain visible as failures.
6. News ranking context is bounded and explainable. A matching ticker or topic
   increases relevance only; it is not a trading recommendation.

## Verification evidence

The canonical branch targeted suite covers source health, privacy-safe Gmail
cursor projection, multi-market provider routing, news interest ranking,
official-event context, risk-news snapshots, and market snapshot health:

```text
88 passed
```

Tests are offline and use fixtures; no Gmail, Railway, Telegram, broker, or
unapproved external endpoint is contacted by this verification.

## Remaining external evidence

The following require a controlled environment after merge and are not claimed
as local PASS here:

- Railway Gmail watch/ingress configuration and sanitized Creator/FJ bundle.
- A single test-recipient Telegram receipt bound to the same release/snapshot.
- Public Pages propagation and Mini App visual loading.
- Live provider freshness and cross-source delivery receipts.

These gaps keep the existing release gate and high-risk fail-closed behavior;
they do not justify lowering freshness, source, or candidate thresholds.

## Rollback

Reverting the follow-up commit(s) returns to the already merged overlap-audit
state. It does not remove the release gate, source-health distinction, or
privacy boundary introduced by earlier releases.
