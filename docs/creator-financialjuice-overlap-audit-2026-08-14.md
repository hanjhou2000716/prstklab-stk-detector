# Creator／FinancialJuice／新聞整合重疊稽核

日期：2026-08-14  
稽核基準：`feat/REQ-ADD-025-health-ui-baseline` @ `9dae11b16d392868a48f5b872fb79bc3afcec35e`  
模式：Gate-Driven／Evidence-Driven migration；本文件不是新的平行 pipeline。

## 結論

目前 repository 已有一條 canonical 外部情報路徑：

```text
來源註冊／adapter
  → sanitized observation
  → shared event／news classifier
  → evidence + lifecycle gate
  → release manifest／artifact hash
  → Mini App
  → release-gated Telegram delivery／receipt
```

Creator、FinancialJuice 與官方新聞不得各自建立通知或風險判斷。Creator 只提供
editorial enrichment；FinancialJuice 的 vendor priority 只影響通知優先級，不
改寫 PRStK risk；官方來源與同市場同步證據仍由既有 event/release gate 決定。

本次稽核沒有發現需要重寫既有 canonical pipeline 的證據。後續採「單一稽核／
必要修復 PR，依現有 stacked PR 順序合併」；不再新增第二套 Creator 或 FJ
分類器。

## Requirement traceability

| 需求族 | Canonical owner | 正式接入點 | 目前狀態 | Evidence／剩餘 gate |
|---|---|---|---|---|
| Creator provider registry | `config/creator_providers.json`, `src/creator_provider_registry.py` | parser、health、email router | `PASS / LOCKED` | registry、unknown-provider、DLQ tests |
| Creator parser／privacy boundary | `src/creator_source_adapters.py`, `src/creator_intelligence_pipeline.py` | sanitized scheduled input | `PASS / LOCKED` | parser/privacy fixtures；不得保存 raw mail/media |
| Creator consensus | `src/creator_consensus.py` | briefing／creator artifact | `PASS / LOCKED` | multi-creator、non-directional consensus tests |
| Creator ↔ PRStK correlation | `src/creator_correlation.py`, `src/briefing_cards.py` | snapshot-bound briefing | `PASS / LOCKED` | explicit ticker/sector/snapshot evidence |
| Creator release lineage | `src/creator_release.py`, `src/release_manifest.py` | optional manifest artifacts | `PASS / LOCKED` | parent release／snapshot/hash validation |
| Creator notification／receipt | `src/creator_dispatch.py`, `src/creator_notification.py`, `src/creator_delivery_store.py` | release-gated delivery | `NEEDS_REVERIFY` | local contracts pass；Railway／single-recipient receipt pending |
| FinancialJuice compound parser | `src/financialjuice_contract.py`, `src/external_source_parsers.py` | sanitized external observation | `PASS / LOCKED` | compound item、privacy、replay tests |
| FinancialJuice priority policy | `src/financialjuice_contract.py` | notification priority only | `PASS / LOCKED` | 7/8/9/10 priority boundary tests；risk unchanged |
| FinancialJuice event fan-out | `src/external_event_pipeline.py`, `src/intelligence_pipeline.py` | shared event cluster/evidence | `PASS / LOCKED` | fan-out、evidence、lifecycle tests |
| FinancialJuice scheduled ingress | `src/external_observation_input.py`, `.github/workflows/scheduled-brief.yml` | release snapshot | `PARTIALLY_INTEGRATED` | Railway sanitized bundle still required |
| FinancialJuice observability | `schemas/source-health.schema.json`, `site/app.js` | source-health artifact/UI | `NEEDS_REVERIFY` | local 52-test contract；Pages/Railway evidence pending |
| Official news provider registry | `src/news_intelligence.py`, `schemas/news-*.schema.json` | `risk_news.build_news_snapshot` | `PASS / LOCKED` | URL allowlist、provider、dedup tests |
| Official feed adapters | `src/news_feed_adapters.py`, `src/risk_news.py` | scheduled market snapshot | `PARTIALLY_INTEGRATED` | live feed/Pages evidence pending; Nasdaq remains disabled without stable endpoint |
| News release lineage | `src/release_manifest.py`, `src/release_gate.py`, `site/app.js` | `news.json` | `PASS / LOCKED` | multi-market/mixed-release/hash tests |
| Telegram photo delivery | `src/telegram_client.py`, `src/scheduled_delivery.py` | single-message sendPhoto | `NEEDS_REVERIFY` | local mock E2E pass；production receipt pending |
| Release gate | `src/release_gate.py`, `src/release_manifest.py` | pre-notify validation | `PASS / LOCKED` | local production_e2e; Pages propagation pending |

## Overlap findings

### 1. Provider identity

`config/creator_providers.json` 是唯一 Creator whitelist。`email_router.py` 只
讀 registry；任何新增 provider 必須先更新 registry、schema、parser、health 與
fixtures。不得在 `railway-monitor/app.py`、Gmail parser 或 Mini App 另放 provider
清單。

### 2. Classification and risk

Creator／FJ／news 都應把標題、摘要、來源時間與已知市場證據送進既有 shared
event／news contract。Creator opinion 與 FJ vendor importance 不得單獨產生
`confirmed`／`high-risk`。未完成官方核對或同市場同步時，狀態只能是
`observation`／`pending_confirmation`，並在 Mini App 顯示原因。

### 3. Release and delivery

所有外部情報必須進同一 `release-manifest`，以 artifact hash、snapshot ID 與
release ID 綁定。`scheduled_delivery.py` 先跑 release gate，再呼叫 Telegram。
任何附件、raw mail、私人收件者資訊都不得進 `site/data` 或公開 artifact。

### 4. Runtime extraction

目前 Railway PR stack（#580 起至 #603）是在抽取 runtime boundary，不是新增
第二套 Creator/FJ pipeline。`railway-monitor/app.py` 的相容 fallback 僅為
health 可用性保護；repository-shared classifier 才是 canonical。若 fallback
被實際用於 production，該次 delivery 必須 blocked 並寫入 health reason。

## Status and evidence rules

- `PASS / LOCKED`：程式、targeted tests、required regression 與保留性證據均在
  repository 內；後續若碰到 locked 範圍必須 REOPENED 並重跑原測試。
- `NEEDS_REVERIFY`：本地契約已通過，但仍缺 Pages、Railway 或 Telegram 的外部
  objective evidence；不可宣稱 production acceptance。
- `PARTIALLY_INTEGRATED`：程式與 workflow 已接入，但仍有明確 runtime wiring
  或 release evidence 缺口。
- 本分支目前全套本地回歸：`1207 passed`。CI 最新 test-and-dry-run 亦為
  `1207 passed`，另有 CodeQL、dependency review、SBOM 通過；這些不等於 live
  Railway、Pages 或正式 Telegram 已驗證。

### 2026-08-14 evidence capture

- 隔離系統暫存目錄的本地完整回歸：`1206 passed, 1 skipped`。
- 在 OneDrive 工作區直接使用 pytest 的 basetemp 時，raw observation 測試曾
  出現 6 個 `FileNotFoundError`；改用獨立系統暫存目錄後全部通過。這是工作區
  同步／暫存競態，不是產品 assertion，後續測試 SOP 必須指定獨立 basetemp。
- PR #603 最新 CI：test-and-dry-run `31806315184`／job `94785982441`，
  `1207 passed`、核心 coverage `90.08%`；Ruff、Mypy、runtime audit、offline
  production acceptance 均在同一 workflow 通過。
- PR #603 最新 security workflow `31806315241`：CodeQL、dependency review、
  SBOM 全部通過。
- 本機 `node --check site/app.js` 通過；本機 `src.production_e2e` 以
  `renderer_available=false` 安全阻擋送圖，沒有發出任何 Telegram；CI 的固定
  Chromium gate 才是 renderer 的客觀證據。

## Open regression／completion debt

| ID | 類型 | 內容 | 解除條件 |
|---|---|---|---|
| REG-EXT-001 | external | Railway creator/FJ ingress 與 delivery receipt 尚未取得 live evidence | sanitized bundle、health、單一收件者 receipt |
| REG-EXT-002 | external | Pages 尚未以最新 `status=ready` release 完成瀏覽器驗證 | public manifest/hash/lineage 與 Mini App browser evidence |
| REG-EXT-003 | external | Telegram production photo delivery 尚未完成限定收件者驗證 | caption、1080×1350 card、deep link、receipt 一致 |
| DEBT-NEWS-001 | completion | official feed live freshness／market split 尚待現場驗證 | TWSE/MOPS/SEC/Fed fixture + live source-health evidence |
| DEBT-FJ-001 | completion | FinancialJuice sanitized runtime bundle 尚待接入 Railway | bundle parser、priority boundary、release lineage |
| DEBT-CREATOR-001 | completion | Creator late delivery／photo receipt 仍待 production-safe test | single test recipient、retry/dedupe receipt |

上述項目是外部驗證 debt，不應用 mock 結果冒充 PASS；在解除前不得升級
高風險通知或宣稱整套 production acceptance。

## Canonical implementation decision

### REQ-ADD-027 evidence alignment lock

Creator correlation now consumes the existing market, research and event
snapshots together. Snapshot IDs and explicit entity matches are retained in
the Creator release; stale contexts are labelled `stale`, and no correlation
result is an investment signal. Legacy Creator artifacts without a research
lineage field remain readable, while newly generated artifacts bind the
declared research snapshot. This closes the local evidence-lineage gap without
creating a second classifier or delivery path.

1. 保留既有 Creator、FJ、news、release、Telegram 模組，不重寫。
2. 以本稽核文件作為後續 stacked PR 的入口；必要變更只新增到既有 canonical
   owner。
3. 若新增功能跨越兩個以上 owner，先建立 contract／schema／fixture，再接入
   workflow；不得先在 `railway-monitor/app.py` 寫另一套邏輯。
4. 下一個實作單元優先處理 `NEEDS_REVERIFY` 的最小可驗證路徑：release-ready
   Pages snapshot → Mini App lineage → 限定單一 Telegram delivery receipt。
5. 真實正式收件人不得用於測試；使用 mock 或明確限定的單一測試 chat ID。

## Rollback

本文件為 audit-only atomic change，回滾只需 revert 本 commit。任何 runtime
修復仍須保持既有 release gate、fail-closed、privacy 與 notification dedupe；
不得以回滾方式刪除已驗證的安全 contract。
