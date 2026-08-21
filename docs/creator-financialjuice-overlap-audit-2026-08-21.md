# Creator／FinancialJuice／News overlap audit

日期：2026-08-21（Asia/Taipei）  
稽核基準：`main` `d6caaa9`、目前公開 ready release、PR #678–#681

這份文件把目前存在的模組重新對齊到一條 canonical path，避免同一個問題
由兩套 parser、兩套通知決策或兩套 release gate 重複實作。

## Canonical path

```text
Gmail／官方新聞來源
  → provider registry／adapter
  → sanitized observation
  → provider parser
  → event／creator contract
  → dedup／consensus／market scope
  → release manifest + hash gate
  → Pages／Mini App
  → Telegram delivery + receipt
```

| 能力 | Canonical implementation | 驗證 | 目前狀態 |
|---|---|---|---|
| Creator provider registry | `config/creator_providers.json`, `src/creator_provider_registry.py` | registry／router tests | production |
| Jenny／Creator parser | `src/creator_source_adapters.py`, `src/external_source_parsers.py` | parser fixtures | production（外部 ingress 待驗證） |
| Creator morning batch | `src/creator_morning_batch.py`, `src/schedule_contract.py` | cutoff／late／idempotency tests | production |
| Creator consensus／PRStK correlation | `src/creator_consensus.py`, `src/creator_correlation.py` | multi-source／lineage tests | production |
| FinancialJuice compound parser | `src/external_source_parsers.py`, `src/financialjuice_contract.py` | compound／importance／cluster tests | production（Gmail ingress 待驗證） |
| FinancialJuice priority | `src/financialjuice_priority.py`, `src/external_event_pipeline.py` | priority／dedup／release tests | production |
| News provider registry | `src/news_intelligence.py` | provider/domain/schema tests | production |
| News market scope gate | `src/news_intelligence.py` | PR #680 targeted 48 + full 1310 | PR #680 |
| Multi-market feed routing | `src/news_feed_adapters.py` | PR #681 targeted 52 + full 1309 | PR #681 |
| Source health semantics | `src/source_health.py`, `src/health_observability.py` | no-event／failure tests | PR #678 |
| Gmail privacy observability | `railway-monitor/gmail_watch.py`, `health_contract.py` | cursor fingerprint tests | PR #679 |
| Release gate | `src/release_gate.py`, `src/release_manifest.py`, `src/pages_release.py` | immutable restore／hash tests | production |
| Telegram delivery | `src/telegram_client.py`, `src/creator_notification.py`, `src/delivery_callback.py` | dry-run／receipt tests | production code; live receipt pending |
| Mini App deep link | `site/app.js`, `src/deep_link_router.py` | router／release mismatch tests | production code; WebView evidence pending |

## PR overlap decision

- PR #678 and #679 are independent main-based fixes and can be merged in either
  order. They repair semantic health state and privacy-safe Gmail cursor
  observability; neither changes provider parsing or Telegram policy.
- PR #680 is an independent main-based market-scope gate. It prevents a US-only
  provider such as Federal Reserve from entering the Taiwan feed and records
  `market_scope_mismatch` instead of silently dropping the row.
- PR #681 is an independent main-based feed-routing fix. It preserves the full
  provider coverage list so a multi-market source is fetched for every declared
  market. It complements, rather than duplicates, #680: #681 fixes fetch-time
  selection; #680 fixes normalize/rank-time selection.

After merge, these four changes form one canonical news path; no second parser
or UI-side market classifier should be added.

## Objective evidence

- Approved `refresh-dashboard` Actions run `32435052135` succeeded.
- Public manifest returned HTTP 200 with `status=ready`; release
  `release-faaa5b86acfc0db3`, market `d244146e6209880c`, research
  `research-8b8ec8f6e5ee51aa`, event `event-a889bf10a4141a3b`.
- Current local full regression after the news-scope change: `1310 passed`.
- Current local full regression after feed-routing change: `1309 passed`.

## External gates deliberately not marked PASS

1. Railway Gmail OAuth／Pub/Sub variables remain `configuration_missing`.
2. Railway canonical shared-secret migration requires operator configuration;
   no secret is copied into source or logs.
3. GDELT live upstream remains bounded by its rate-limit/failure policy.
4. A real single-recipient Telegram receipt and Telegram WebView screenshot
   still require a controlled production-safe acceptance run.

These are external acceptance gates, not reasons to weaken fail-closed release
or notification rules.
