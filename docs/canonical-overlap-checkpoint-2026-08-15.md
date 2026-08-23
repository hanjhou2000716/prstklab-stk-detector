# Canonical Creator／FinancialJuice overlap checkpoint

日期：2026-08-15  
基準：`main` @ `37b5db0feeedcdff99547446226376edef3c5bde`  
模式：Gate-driven／evidence-driven；本文件是稽核 checkpoint，不是新的資料或通知管線。

## 決策

目前不建立第二套 Creator、FinancialJuice、新聞分類或 Telegram 發送流程。唯一正式路徑維持：

```text
來源 registry／adapter
→ sanitized observation
→ domain contract／shared classifier
→ evidence、lifecycle、quality gate
→ release manifest／artifact hash
→ Pages
→ Mini App／release-gated Telegram
→ delivery receipt
```

Creator 仍是 editorial enrichment；FinancialJuice 的 vendor importance 只決定
通知優先級，不改寫 PRStK risk；官方來源與同市場同步才可提供風險證據。

## 整合矩陣（目前 main）

| 模組 | Canonical owner | 正式接入 | 狀態 | 證據／缺口 |
|---|---|---|---|---|
| Creator provider registry | `config/creator_providers.json`, `src/creator_provider_registry.py` | router、parser、health、release | `production` | registry 與 unknown-provider tests |
| Creator parser／privacy | `src/creator_source_adapters.py`, `src/creator_intelligence_pipeline.py` | sanitized creator input | `production` | parser、privacy、DLQ tests |
| Creator consensus／correlation | `src/creator_consensus.py`, `src/creator_correlation.py` | briefing／creator artifact | `production` | latest-per-creator、divergence、snapshot tests |
| Creator release lineage | `src/creator_release.py`, `src/release_manifest.py` | optional release artifacts | `production` | parent/snapshot/hash validation |
| Creator notification／receipt | `src/creator_dispatch.py`, `src/creator_delivery_store.py` | release-gated delivery | `partially_integrated` | Railway live ingress／單一收件者 receipt 尚待外部證據 |
| FinancialJuice compound parser | `src/financialjuice_contract.py`, `src/external_source_parsers.py` | sanitized external observation | `production` | compound、priority、replay tests |
| FinancialJuice scheduled ingress | `src/external_observation_input.py`, `src/scheduled_delivery.py` | release snapshot | `partially_integrated` | Railway Gmail ingress 尚為 `configuration_missing` |
| Shared event／risk path | `src/external_event_pipeline.py`, `src/intelligence_pipeline.py` | event cluster／lifecycle | `production` | creator 不計 event evidence；FJ risk 分離 tests |
| Official news registry／ranking | `src/news_intelligence.py`, `src/news_feed_adapters.py` | `news.json` | `partially_integrated` | live feed freshness 仍需現場證據；disabled provider 不得猜測 |
| Release gate | `src/release_gate.py`, `src/release_manifest.py` | Pages before notify | `production` | public smoke run passed |
| Mini App lineage | `site/app.js` | manifest-bound artifacts | `partially_integrated` | HTTP artifact verified；WebView visual evidence待補 |
| Telegram delivery | `src/telegram_client.py`, workflows | post-release send | `partially_integrated` | production photo/Creator receipt 仍需受限驗證 |

## 客觀驗證

- 本 checkpoint 的 Creator／FJ／news／release-gate focused suite：`52 passed`；測試使用工作區內獨立 `--basetemp`，避免 OneDrive 暫存權限污染結果。
- `Refresh market dashboard` Actions run `31872459722` 成功完成。
- 公開 release smoke run `31873378376` 通過；流程先還原最新 `data-release`，再驗證公開 manifest，未通過 gate 不會觸發 Telegram。
- 公開 manifest：`release-8faf8f2a2c7ef221`，狀態 `ready`，market／research／event snapshot 均存在，`validation_errors=[]`。
- Railway `/health` 顯示 monitor healthy；GDELT 的 `HTTP_429` 與 health callback `HTTP_403` 被明確記錄並 bounded retry，沒有被當成成功事件。
- Railway Gmail ingress 目前是 `configuration_missing`；因此沒有把「沒有 Creator/FJ 資料」誤報成「今日沒有內容」。

## 外部 gate 與安全邊界

以下不是本次程式稽核可自行補造的資料，未取得前維持 `NEEDS_REVERIFY`：

1. Railway Gmail OAuth／PubSub ingress 與 Creator/FJ sanitized bundle。
2. 單一測試收件者的 Creator／FinancialJuice production-safe Telegram receipt。
3. Telegram 圖卡、deep-link 與同一 release／snapshot 的 receipt 綁定。
4. Mini App Telegram WebView 的實際視覺載入確認。
5. 官方新聞 feed 的 live freshness 與市場分流證據。

不因上述缺口放寬 release gate、資料新鮮度或高風險通知條件；Creator／News
optional failure 不得拖垮 core market release，但 qualifying external event 在
release blocked 時仍必須停止 Telegram。

## 後續唯一建議路徑

本 checkpoint 後只接受兩個 canonical work items，依序而非平行重寫：

1. **Runtime evidence lane**：先補 Railway Gmail／FJ sanitized export、health 與受限 delivery receipt。
2. **WebView acceptance lane**：使用同一個 ready release 驗證 Mini App deep-link、artifact lineage 與 fallback。

兩者均應修改既有 owner，禁止在 `railway-monitor/app.py` 或 workflow 再建立第二套
classifier、provider whitelist 或 Telegram dispatcher。

## Rollback

本文件為 audit-only atomic change。回滾只需 revert 本 commit；不得藉回滾刪除
既有 release gate、privacy boundary、deduplication 或 fail-closed contract。
