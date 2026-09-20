# README Truth Reconciliation

本文件是 README 的稽核附錄，不取代程式、Workflow、schema、部署契約或正式
production evidence。每次更新 README 前，先以最新 `main` 重跑本文件列出的對帳。

## Baseline

| 項目 | 值 | 狀態 |
|---|---|---|
| Repository | `hanjhou2000716/prstklab-stk-detector` | current |
| Audited main | `2f019db2a29620d0078ae1b5b6cc434a7585a382` | merged PR #991 |
| README baseline | 2026-09-01 | requires update |
| Latest successful Pages deploy | `b430ad7659c35212b7af1ee3732048acd768c7ee` | deployed, older than main |
| Public Pages | `https://hanjhou2000716.github.io/prstklab-stk-detector/` | reachable |
| PR #991 migration | `supabase/migrations/202609200001_financialjuice_priority_delivery.sql` | merged; apply evidence pending |
| Natural high-score FJ delivery on PR #991 | none observed | production verification pending |

## Status vocabulary

- `IMPLEMENTED`: code or configuration exists in the repository.
- `TESTED`: repository checks or isolated fixtures cover the behavior.
- `MERGED`: the change is present in `main`.
- `DEPLOYED`: the exact SHA or release is running in the named external service.
- `PRODUCTION VERIFIED`: the deployed behavior has a current, inspectable external
  acceptance record, including the required receipt where delivery is involved.
- `EXPERIMENTAL`: available behind a canary, optional path, or incomplete gate.
- `RETIRED`: no longer an active production capability; compatibility code may remain.

`MERGED` never implies `DEPLOYED`; `DEPLOYED` never implies `PRODUCTION VERIFIED`.

## Truth matrix

| Feature | README decision | Repository evidence | Workflow / runtime evidence | Production status | Decision |
|---|---|---|---|---|---|
| Market data and freshness | broadly accurate | `src/market_data.py`, source-health and market contracts | refresh, scheduled brief, official monitor | public snapshot is reachable; freshness is snapshot-specific | UPDATE |
| Scheduled four reports | present | `src/scheduled_brief.py`, `src/scheduled_delivery.py` | `scheduled-brief.yml` | historical Pages evidence; each current run requires evidence | UPDATE |
| FJ Gmail ingestion | incomplete | `railway-monitor/gmail_ingress.py`, `email_store.py` | `gmail-history-sync.yml` every five minutes | latest main sync succeeded; end-to-end delivery pending | UPDATE |
| FJ priority recovery | absent | `priority_event_refs`, pending store, delivery lifecycle in PR #991 | Gmail dispatch and official monitor consume event refs | migration and natural-event receipt pending | ADD DOC / VERIFY FIRST |
| Native market alerts | incomplete | `src/event_alerts.py`, `src/event_alert_policy.py` | `official-event-monitor.yml` every five minutes | code deployed in older Pages release; natural delivery pending | UPDATE / VERIFY FIRST |
| Public text summary | says 40 characters everywhere | `src/telegram_client.py` uses 60 for public text; photo paths retain 40 | sender and card contracts validate separately | deployed artifact uses the newer contract | UPDATE |
| Mini App bootstrap | absent | `src/bootstrap_release.py`, `site/app.js`, release gate | Pages deploy validates bootstrap and hashes | bootstrap is publicly readable and under 150 KB | ADD DOC |
| Deep-link alert loading | partial | release manifest and alert projection | monitor release gate binds alert identity | public manifest exposes release-bound alert paths | UPDATE |
| D.iNV Detector label | stale wording | Telegram inline button and site eyebrow use `D.iNV Detector` | Mini App asset tests cover the label | Pages label deployed; Telegram menu acceptance pending | UPDATE / VERIFY |
| Market observation backup | partial | migration and `src/market_backup.py` | migration/backfill workflows exist | latest backup migration evidence must be checked separately | VERIFY FIRST |
| Research strategies | broadly accurate | strategy registry and research modules | research workflows publish reports | public report may be stale or fallback-bound | UPDATE |
| Railway monitor | broadly accurate but status broad | `railway-monitor/app.py`, stores and health contract | monitor health and dispatch workflows | runtime evidence is partial and time-bound | UPDATE / VERIFY |
| Cloudflare/Supabase zero-cost path | correctly described as canary | `worker/`, `supabase/`, migration docs | worker and migration workflows | not the primary path without external evidence | KEEP / CLARIFY |

## Current architecture map

```text
public sources / Gmail / Jin10 / GDELT
        -> Actions, Railway monitor, or Worker ingress
        -> normalized observations and source health
        -> canonical events, market evidence, research outputs
        -> immutable data-release + release manifest + artifact hashes
        -> GitHub Pages Mini App
        -> release-gated Telegram sender + recipient receipt
```

FJ high-score recovery is an event-level side path, not a second sender:

```text
Gmail cursor -> priority_event_refs -> pending/ready state
             -> official monitor -> release gate -> existing sender
             -> recipient receipt -> delivered or expired
```

## README corrections required

1. Replace the 2026-09-01 current-status claim with a generated audit date and link
   to this matrix.
2. Separate 60-character public/FJ text from 40-character photo captions.
3. Document `summary_pending`, `ready`, `delivery_pending`, `delivered`, `expired`
   and `contract_failed` without claiming that migration is applied until evidence exists.
4. Document bootstrap, deferred artifacts, release identity, hash validation and
   notification-before-click-target readiness.
5. Document native market-alert triggers as implemented/tested/deployment-specific,
   not as guaranteed daily output.
6. Use the exact current brand strings and identify any Telegram menu configuration
   that still requires a separate production acceptance.
7. Replace the duplicated historical Phase sections with short summaries and links.
8. Add workflow, configuration, operations and troubleshooting tables based on the
   current YAML and source code.

## Acceptance evidence required before status promotion

- Migration apply output with schema, RLS, service-role RPC and idempotency checks.
- Exact production SHA, Pages release ID, snapshot ID and manifest hashes.
- `notify=false, force=false` replay showing zero Telegram claim, attempt and receipt.
- A fresh eligible FJ event with matching summary, Deep Link and recipient receipt.
- Reprocessing the same event with zero additional delivery.
- At least one complete observation window for the five-minute monitor.

Old FJ incidents remain regression fixtures only. They are not replayed to production
recipients and do not have their source time extended.

## A. Executive summary

本次對帳發現的主要文件技術債如下：

1. README 的日期停在 2026-09-01，沒有反映最新 `main`、PR #991 或目前公開 Pages 與 main 的版本差異。
2. `IMPLEMENTED`、`TESTED`、`MERGED`、`DEPLOYED` 與 `PRODUCTION VERIFIED` 先前混用，容易把 CI 綠燈誤讀成正式服務已修復。
3. 文字通知 60 字與照片 caption 40 字的契約曾被寫成同一個限制。
4. PR #991 的 `priority_event_refs`、FJ pending／ready／delivery lifecycle 與自然事件 receipt 尚未在 README 形成完整事件級說明。
5. Mini App 已有 bootstrap、hash、release binding 與 Deep Link 延後載入，但舊 README 只描述完整頁面，沒有說明首屏與通知前可用性閘門。
6. 原生市場速報、備援資料及來源健康已存在程式與測試，但文件容易讓讀者以為每天必然產出固定數量或所有備援值都可觸發通知。
7. Pages 的已部署 SHA 早於最新 main；README 必須把可公開讀取、已部署與最新合併程式分開記錄。
8. 舊版 Phase、近期交付與操作說明交疊；若不透過索引分流，維護者難以判斷哪一段是現況、哪一段是歷史決策。
9. Railway、Cloudflare Worker、Supabase 與 GitHub Actions 的 primary、canary、fallback 邊界需要明寫，不能用「零成本路徑」推論已完成切換。
10. 生產 migration、無通知 replay 與自然 FJ receipt 缺乏本輪證據，因此必須保留為 `VERIFY FIRST`，不能靠程式存在或 workflow 成功補足。

## B. Existing system map

### B1. Data flow

```text
TWSE / TPEx / Yahoo / Stooq / Binance / CoinGecko / official sources
  -> market/news adapters and freshness validation
  -> normalized observations + source health
  -> site/data snapshots and research artifacts
  -> immutable release manifest + hashes
  -> GitHub Pages public projection / Mini App
```

Gmail、Jin10 與 GDELT 是另外的事件入口；GDELT 只能作 discovery，不能單獨證明黑天鵝或戰爭事件。Supabase 保存服務端契約與部分持久資料；公開 Pages 不應直接暴露私有原始資料。

### B2. Signal／event flow

```text
price / official event / news / Gmail
  -> parser and source identity
  -> canonical event + material state
  -> market confirmation / source quality / freshness
  -> dedup + cooldown + priority / alert budget
  -> public-safe alert projection
```

FJ 高分事件額外保留 `priority_event_refs`，讓 Gmail cursor 前進後仍可由五分鐘 monitor 從持久集合恢復；它不建立第二套 sender。

### B3. Notification flow

```text
eligible event
  -> one-time summary / text or photo contract
  -> release + Deep Link + click_target_ready
  -> recipient-level claim
  -> Telegram attempt
  -> callback / receipt
  -> delivered, retry remaining recipients, or expired
```

沒有 `ready` 摘要、身份契約、可用 Deep Link 或有效 release 時，不應建立正式 claim、attempt 或 receipt。workflow success 只代表該階段成功，不代表收件人已看到訊息。

### B4. Release／rollback flow

```text
writers / queue
  -> snapshot
  -> manifest + schema + hash + release binding
  -> Pages publish
  -> public smoke / click-target gate
  -> sender
  -> last-known-good on failure
```

GitHub Pages 是公開靜態展示層；GitHub Actions 是主要編排與發布入口；Railway monitor 是外部來源／Gmail 監測與 dispatch 角色；Supabase 是服務端持久化與契約邊界；Cloudflare Worker 是可選的零成本 canary／替代路徑。沒有外部 evidence 時，不把 Worker 或 Supabase canary 寫成已切換的 primary。

## C. What is already accurate

以下 README 內容可保留，只需避免與新狀態表重複：

- 產品定位為公開市場資訊整理、風險觀察與量化研究，不自動交易、不要求私人帳號密碼。
- 事件需要來源品質、時間有效性、去重與市場證據，GDELT／探索來源不能單獨升格為定論。
- Telegram、Mini App、release manifest、artifact hash、last-known-good 與 receipt 必須形成同一條可追溯鏈。
- 研究分數只作各自策略內排序，不可跨策略比較，也不構成投資建議。
- 缺值、逾時與來源失敗必須被標示，不能以空白或通用文案偽裝成「本輪無事件」。
- 歷史 Phase 可保留作設計背景，但應明確標示為歷史摘要並連到深層文件，不應當成目前部署證據。

## D. Domain audit index

| Domain | 主要程式／設定 | 主要輸出 | 本輪文件判定 |
|---|---|---|---|
| Market Data | `src/market_data.py`、來源 adapters、`src/market_backup.py` | market snapshot、source health、備援狀態 | `IMPLEMENTED／TESTED`；正式回填與恢復另驗 |
| News Intelligence | `src/news_intelligence.py`、`src/news_feed_adapters.py`、provider registry | news snapshot、分類與品質 | `IMPLEMENTED`；provider 狀態依 runtime |
| Event Intelligence | `src/event_alerts.py`、`src/event_ledger.py`、canonical helpers | alert index、event ledger、material state | `IMPLEMENTED／TESTED` |
| FinancialJuice | `railway-monitor/gmail_ingress.py`、`email_store.py`、`src/official_event_monitor.py` | observation、priority refs、delivery diagnostics | PR #991 `MERGED／TESTED`；production `VERIFY FIRST` |
| Emergency／Black Swan | official monitor、disaster／geopolitical gates | gated event candidate | `IMPLEMENTED`；不以關鍵字單獨授權投遞 |
| Notification | `src/telegram_client.py`、claim／attempt／receipt、budget | Telegram text/photo、Deep Link、receipt | `IMPLEMENTED／TESTED`；自然事件需外部證據 |
| Mini App | `site/app.js`、`site/data`、`src/bootstrap_release.py` | bootstrap、deferred artifacts、公開頁面 | bootstrap contract `IMPLEMENTED／TESTED`；目前公開 SHA 需更新驗收 |
| Research | strategy registry、`src/research_report.py`、`src/pristine_value.py` | research report、candidate pools | `IMPLEMENTED／TESTED`；公開新鮮度依 snapshot |
| Taiwan Investor Intelligence | TWSE／TPEx、法人、ETF、宏觀模組 | 台股快照與 FGI | `PARTIAL／SOURCE-SPECIFIC`；不可把所有列出的標的寫成同等級即時能力 |
| Creator／External Content | Gmail／Jin10／GDELT adapters、external parsers | discovery／vendor event | parser存在；enabled、canary、retired依 workflow／env 逐項確認 |
| Release Architecture | `src/release_gate.py`、`src/pages_release.py`、manifest | immutable release、hash、last-known-good | `IMPLEMENTED／TESTED` |
| External Runtime | `.github/workflows`、`railway-monitor`、`worker`、`supabase` | schedule、dispatch、持久化 | role分層；不把 canary 宣稱 primary |
| Observability | workflow summary、source health、receipt、runtime audit | failure reason、latency、audit evidence | `IMPLEMENTED`；事件級正式證據需持續補齊 |
| Security／Privacy | secret references、public projection、RLS／service boundary | safe public artifacts、private diagnostics | `IMPLEMENTED／TESTED`；migration apply需另驗 |

## E. Outdated／incorrect content handling

| 問題 | 證據 | 處置 |
|---|---|---|
| 舊版固定 40 字總限制 | `src/telegram_client.py` 的 public text 為60；photo caption另為40 | `UPDATE`，在 README 分列兩種契約 |
| 舊品牌「稜量系統」被寫成目前按鈕 | 程式 inline button與首頁 eyebrow為 `D.iNV Detector`；menu尚無本輪正式驗收 | `UPDATE／VERIFY FIRST` |
| PR #991被視為已完成正式修復 | main有migration與測試，但無 apply／自然 receipt | `UPDATE`為 `MERGED／TESTED` |
| 研究排程 13:30 | workflow／策略文件使用台股收盤後15:30邏輯 | `UPDATE`，並保留交易日與延遲說明 |
| 所有高分 FJ 都只在 pending 集合 | PR #991已擴展 ready 與 pending 的 refs | `UPDATE`，說明相容讀取與狀態生命週期 |
| GDELT catalog／runtime狀態混為一談 | public catalog disabled 與 runtime env 是不同契約 | `UPDATE`，分開描述 |
| 歷史 Phase 當作現況 | README 有多段歷史設計與近期交付混排 | `MERGE／SPLIT`，歷史只留摘要與連結 |
| 沒有 production evidence 仍寫已驗收 | runtime audit提示 events／manifest／research snapshot缺失 | `VERIFY FIRST`，不以測試輸出補足 |

## F. Missing documentation to keep

程式已存在但舊 README不足的內容，已補入或由文件索引承接：

- FJ `priority_event_refs` 與 Gmail cursor 後的獨立恢復。
- `summary_pending` 到 `delivered／expired` 的事件狀態及 recipient-level receipt權威。
- Mini App bootstrap、指定 Deep Link、hash／release驗證與 deferred artifacts。
- `click_target_ready` 在 sender 前阻止未公開或不一致頁面。
- Market observation backup、交易日／freshness與資料不能觸發通知的邊界。
- 原生市場速報的既有能力、去重／冷卻與「不保證每日固定數量」限制。
- 通知文字60字與圖片caption 40字的分離契約。
- migration、production refresh、自然投遞與正式驗收的證據門檻。

## G. Proposed README structure

目前 README 已採漸進揭露，下一輪只需把現有章節維持在以下 22 個導覽目的，不必重複搬移所有 `docs/` 深層內容：

| # | 章節 | README應回答的問題 | 深層來源 |
|---:|---|---|---|
| 1 | What is PRStK | 這是什麼、不做什麼 | README intro |
| 2 | Quick Start | 新手如何安全啟動 | README setup |
| 3 | System Architecture | 真實資料流與角色 | README Mermaid／本文件 |
| 4 | Data Sources | 來源、更新、fallback、隱私邊界 | source modules／health docs |
| 5 | Market Intelligence | 行情、時效、風險證據 | market docs |
| 6 | Event Intelligence | canonical event、material state、dedup | event ledger docs |
| 7 | FinancialJuice Pipeline | Gmail到receipt的完整交接 | PR #991 migration／本文件 |
| 8 | Notification Intelligence | priority、budget、claim、receipt | alert／delivery docs |
| 9 | Taiwan Investor Intelligence | 台股與投資人相關能力 | Taiwan modules |
| 10 | Research System | 策略、母體、release | research docs |
| 11 | Mini App | tabs、bootstrap、Deep Link | `docs/MINI_APP_SETUP.md` |
| 12 | Release & Deployment | snapshot、manifest、Pages、rollback | release docs |
| 13 | Automation & Workflows | trigger、schedule、是否寫入／發送 | `.github/workflows` |
| 14 | Configuration | required、optional、production-only、legacy | env references |
| 15 | Operations SOP | 新增來源／市場／通知／策略與驗收 | operations docs |
| 16 | Troubleshooting | 找到 first divergence | README troubleshooting |
| 17 | Testing | unit、integration、replay、release | tests／CI |
| 18 | Security & Privacy | public／private boundary | security docs／RLS |
| 19 | Reliability Contract | fail-closed、last-known-good、status vocabulary | 本文件 |
| 20 | Current Capability Status | verified、pending、experimental、retired | README status table |
| 21 | Repository Map | 主要目錄與責任 | README code map |
| 22 | Glossary | canonical、snapshot、release、FJ等術語 | README glossary |

## H. SOP design

### New contributor

```text
Clone -> install -> configure safe/local inputs -> run read-only checks
      -> pytest / compile / runtime audit -> inspect generated artifacts
      -> understand Pages release and external acceptance boundary
```

本地流程不得要求 Telegram、Gmail、Supabase或正式 secret 才能執行純測試；需要外部服務的步驟要標示 `production-only`，並使用 `notify=false`、`force=false` 的安全模式。

### Maintainer SOP

- 新增資料來源：先加入 adapter、日期／單位／freshness契約、source health與fixture，再接入 snapshot；沒有成功 evidence 不升級為通知來源。
- 新增市場：補主檔、交易時區、完成交易日、fallback與同口徑歷史測試；備援值不得觸發即時事件。
- 新增通知：先定義 canonical identity、摘要、priority、budget、claim／attempt／receipt與 Deep Link，再加入 release gate。
- 新增研究策略：加入 registry、universe、scoring、explainability、cache與研究 release；不把候選分數寫成投資建議。
- 驗證 release：檢查 snapshot、manifest、hash、schema、bootstrap、Deep Link與 last-known-good，再做 public smoke。
- 正式 acceptance：先核對 exact SHA，再以無通知 replay；真實投遞需有 recipient receipt與可開啟 Deep Link。
- 回滾：停用新 loader／release入口，回到最後通過驗證的 artifact；不改寫歷史 ledger、claim或 receipt。

## I. Proposed change list

| Current | Problem | Evidence | Proposed change | Why | README section | Preserve | Risk | Complexity |
|---|---|---|---|---|---|---|---|---|
| README日期與近期交付混在一起 | 現況容易過期 | main SHA、Pages SHA、runtime audit | 用 baseline與status vocabulary分層 | 防止誇大部署 | 1／20 | 產品定位與免責 | Low | S |
| 文字／圖片共用40字敘述 | 讀者誤解摘要契約 | `telegram_client.py`與caption tests | 分開60／40並連到測試 | 與sender一致 | 8／11 | 現有delivery contract | Low | S |
| FJ只講來源 | 看不到游標後恢復 | PR #991 refs／migration | 加事件生命週期與待驗證證據 | 可找漏發 first divergence | 7／19 | 不新增第二sender | Medium | M |
| Mini App只講完整頁面 | 忽略bootstrap與click gate | `site/app.js`、release tests | 加兩階段載入與SHA契約 | 讓通知可用性可驗收 | 11／12 | Deep Link、last-known-good | Low | S |
| 研究時間與現況不一致 | SOP會誤導 | workflow／策略文件 | 修正為交易日與15:30邏輯 | 可重現排程 | 10／13 | 既有策略 | Low | S |
| 歷史Phase長篇混排 | 難以辨識最新真相 | README章節結構 | 改為歷史摘要＋深層連結 | 減少矛盾 | 20／21 | 有效歷史決策 | Low | M |
| Production evidence分散 | 無法證明正式驗收 | Pages／runtime audit／migration evidence缺口 | 增加 evidence checklist與待驗狀態 | 文件不超前於系統 | 12／19 | 安全邊界 | Low | S |

## J. Open questions

這些問題不會阻擋本次文件 PR，但會影響日後把狀態升級為正式 production truth：

### Q1 — PR #991 migration 的正式套用入口

- Current evidence：migration已在 main；目前沒有 dedicated FJ migration workflow或 apply record。
- Option A：由受控 Supabase release job 套用並保存 schema/RLS/RPC evidence。
- Option B：由維護者手動套用，再把匿名化結果加入 deployment evidence。
- Recommended：A；若暫時只能 B，必須保存同等級、不可含 secret的 evidence。
- Impact：未決前 README只能寫 `MERGED／TESTED`。

### Q2 — 目前正式 primary monitor

- Current evidence：GitHub Actions、Railway與Worker都有程式／契約，但沒有足夠 evidence證明外部切換角色。
- Option A：GitHub Actions primary、Railway monitor fallback。
- Option B：Railway monitor primary、Actions為 dispatch／release。
- Recommended：在外部 health、schedule與recent receipt對帳完成前保持 `role not fully verified`；不要從文件猜測。
- Impact：影響「來源失敗時誰接手」與production SOP。

### Q3 — Telegram固定選單品牌

- Current evidence：inline button與首頁是 `D.iNV Detector`；固定 menu 的實際BotFather設定沒有本輪可驗證紀錄。
- Option A：將 menu也正式改成 `📡 D.iNV Detector`並保存單收件人驗收。
- Option B：保留現有 menu設定，僅更新 inline與首頁。
- Recommended：A，但需獨立 Telegram acceptance，不在文件改名時假設已完成。
- Impact：影響 AC-18與Mini App操作SOP。

### Q4 — Public Pages release timing

- Current evidence：公開 Pages可讀且為 PR #990 SHA；最新 main含PR #991。
- Option A：文件 merge後立即部署 main，再更新 evidence。
- Option B：等待 migration與FJ production acceptance通過後一次部署。
- Recommended：A，因文件狀態可先明確標示 deployment pending，避免把程式與公開版本混為一談。
- Impact：影響 README的 `DEPLOYED`與`PRODUCTION VERIFIED`欄位。

## K. Final documentation plan

1. **Phase 1 — Truth Reconciliation**：以最新 main、workflow、runtime audit與現有 evidence更新 baseline、truth matrix及status vocabulary。
2. **Phase 2 — Architecture／Technical Whitepaper**：保留 README的流程圖與角色，將migration、事故證據及深層契約留在 `docs/`。
3. **Phase 3 — Quick Start／SOP**：補本機安全執行、外部服務界線、release與Telegram acceptance步驟。
4. **Phase 4 — Operations／Troubleshooting**：用 `Symptom → Evidence → First divergence → Safe recovery → Completion evidence` 統一排錯格式。
5. **Phase 5 — Final Consistency Audit**：檢查相對連結、workflow名稱／schedule、module path、env名稱、Mermaid、secret邊界及所有 status claim；再以 exact SHA更新 evidence。

## Acceptance gates

附件 AC-01 至 AC-16 的原則已落在本文件與 README：不把退休能力寫成 active、核心能力有文件、狀態分層、路徑／指令／workflow／env可追溯、架構與資料流一致、新手與維護者可操作、無 secret、無重複矛盾或無證據功能。實作後仍應逐項勾選，而不是以一次 Markdown 渲染成功代替驗收。

本輪新增的外部狀態門檻：

- **AC-17**：PR #991 在缺少 migration／production evidence 時不得宣稱正式修復完成。
- **AC-18**：近期功能名稱、Telegram inline button與 `D.iNV Detector` 品牌必須與正式資產一致；固定 menu若未驗收，明列待驗。
- **AC-19**：README更新不得觸發 production寫入、Telegram發送或歷史 artifact 改寫。
- **AC-20**：Truth Matrix每項重要技術主張至少指向 Code、Workflow、Config、Test、Deployment Contract 或 Production Evidence 之一。
