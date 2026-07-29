# PRStK Investment System

PRStK 是一套部署在 GitHub 的公開市場資訊整理、量化研究與風險監測系統。它以繁體中文提供 Apple Watch 友善的 Telegram 快報，並透過 Telegram Mini App 顯示完整儀表板。

> 本系統僅整理公開資訊、模型研究與風險觀察，不構成投資建議；不連接券商、銀行、錢包或任何私人帳戶，也不會自動交易。

## 目前可提供的服務

- **Telegram 快報**：每則訊息自動驗證在 30 字內，附有「📡 開啟稜量速報系統」Mini App 按鈕，可發送至多位已啟動 Bot 的收件人。
- **Telegram Mini App／GitHub Pages 儀表板**：呈現全球主要市場、代表標的、台美股風險、重大事件、量化觀察清單與新聞。
- **市場資料更新**：使用公開市場資料建立最新報價、交易日狀態、資料時間與可用性標示。
- **市場風險觀察**：台股 TAIEX Macro FGI 與台美波動／情緒資料；資料缺漏時會明確標示，不以舊資料偽裝即時數值。
- **量化觀察清單**：台美股動能、裸 K 價格結構、三維共振與價值覆核；僅作研究排序，不是推薦名單。
- **重大事件快訊**：官方總經事件檢查、金十 MCP 授權來源監測、HMAC 簽章驗證與事件去重。
- **外部備援**：GitHub Actions 為主排程，cron-job.org 可透過 `repository_dispatch` 作為備援觸發。
- **研究與回測工具**：提供 Price Action、主動型 ETF 配置的離線研究與回測程式；不會產生自動下單。

## 報價與研究何時更新？

所有時間均為台灣時間（UTC+8）。一般市場報價不是逐分鐘串流；每個定時快報都會先重新掃描公開市場資料、寫入 `site/data/market.json`，再發送 Telegram 並部署到 Mini App。盤中／盤前會優先採最近五分鐘報價；市場休市或資料源未提供新盤中列時，會保留最近收盤並標示為日線收盤，絕不將舊資料偽裝成即時行情。

| 類別 | 固定時間 | 更新內容 |
|---|---|---|
| 盤前晨報 | 工作日 06:00 | 隔夜市場與代表標的報價 |
| 台股盤中 | 工作日 08:45、10:00、11:45、13:15 | 台股及全球市場報價、盤勢摘要 |
| 台股盤後 | 工作日 14:45 | 台股收盤後資料與盤後摘要 |
| 美股盤前 | 工作日 21:00（台灣時間，全年固定） | 台股回顧與美股盤前公開市場資料 |
| 全市場量化研究 | 工作日 13:30 | 台美股動能、裸 K、三維共振、價值覆核，及研究清單的價格欄位；預留至 14:45 盤後快報的處理時間 |
| 官方／價格訊號監測 | 工作日每 15 分鐘 | 官方重大事件，或達門檻的台指、費半、Nasdaq、WTI／Brent 價格訊號才更新並發送一次 |
| 金十授權快訊 | Railway 每 120 秒 | 僅檢查金十官方 MCP `list_flash`，符合重大事件規則才觸發 GitHub 快訊 |

08:45、10:00、11:45、13:15 的台股時段以 TAIEX／台股盤勢為快報優先內容。單一國際商品或加密資產的價格訊號僅保留在 Mini App；只有已核對的重大政策、總經、戰爭或重要公司事件，才會在台股時段取代台股訊號進入短訊息。

因此，儀表板上的「最後更新」是**最近一次成功完成公開市場掃描並發布資料的時間**，不是交易所的逐筆即時報價時間。若有任何私人聊天室收件人尚未按 Start 或已封鎖 Bot，系統會略過該收件人並記錄原因，其他收件人、快照提交與 Pages 部署仍會繼續完成。可隨時在 GitHub Actions 手動執行 **Refresh market dashboard** 或 **Unified Taiwan-US research report** 取得一次新的快照；手動執行不代表資料來源一定提供即時行情。

cron-job.org 的備援請求只會在對應時段附近被接受，例如台股盤前為 08:15–09:15 且 payload 的 `slot` 必須為 `pre_open`。這可避免設定錯誤的提早請求先取得防重複鎖，導致正式 08:45 快報被略過；手動 GitHub Actions 測試不受此限制。

全市場研究也可用 `repository_dispatch` 備援：工作日 13:30 發送 `unified-research-report`，再由 14:45 的 `scheduled-brief`（`slot: post_close`）刷新 Mini App 並推播盤後快報。兩者均應由 cron-job.org 以 GitHub Actions 的同一個 Dispatch Token 呼叫。

## 排程與可靠性

- 每個快報時段使用唯一鍵與 GitHub Actions Cache 去重，避免 GitHub 主排程與外部 Cron 重複推播。
- 美股盤前全年固定在台灣時間 21:00；不再依紐約夏令／冬令改為 22:00。
- 資料來源請求失敗會重試一次；失敗時在儀表板呈現資料暫時無法取得。
- Railway 監測器保存已處理的金十事件 ID，GitHub 收到事件後仍會再次驗證 HMAC 簽章與去重。

### 即時速報觸發與傳送規範

速報只在「已核對的公開事件」或「達固定門檻的公開價格訊號」成立時發送；Telegram 僅傳 30 字內的事件類別與焦點，完整事件、已核對報價、可能連動市場與股市觀察放在 Mini App。

| 類別 | 觸發條件 | Mini App 優先核對 |
|---|---|---|
| 關稅／政策 | 關稅、出口管制、制裁、貿易政策等具方向性的公開快訊 | Nasdaq、費半、台股科技權值 |
| 地緣／能源 | 戰爭、停火、伊朗／中東、供應中斷，或同時具供應／地緣背景的 WTI、Brent 重大變動 | WTI、Brent、黃金、美元與主要股市 |
| 總經／Fed | FOMC、Fed、CPI、PCE、非農、就業、GDP 等官方或授權快訊 | 美債殖利率、美元、Nasdaq、費半 |
| 半導體 | 台積電、NVIDIA、AI／半導體巨頭的方向性財報、展望、出口管制或資本支出訊息 | 費半、Nasdaq、台積電與台股電子權值 |
| 價格訊號 | 台指絕對變動達 1.5%、費半達 3%、Nasdaq 達 2%、WTI／Brent 達 5%；另於盤中偵測台指／費半／Nasdaq 15 分鐘變動達 1%、油價達 2%。延遲報價不觸發 | 對應標的與兩個相關市場的最新可核對報價 |

同一外部事件依事件 ID 嚴格去重；同類後續消息預設 30 分鐘冷卻，只有內容明顯升級、官方資訊更新或市場波動擴大時才會提前再次發送。價格訊號則以「標的＋交易日＋方向／風險階段」去重：急跌由警戒升級高風險、跌幅跨過 3% 或 4% 階段、或跌深後出現達門檻的 15 分鐘快速反彈，皆視為新的公開觀察訊號。工作日 08:45–13:30 以台指為唯一價格快訊優先對象；高風險或高波動狀態持續時，最多每 60 分鐘補送一次更新，並只在有新鮮盤中報價時發送。未達上述條件的商品、加密或一般市場消息只更新儀表板，不推播 Telegram。所有文字使用「已知事實、可能影響、持續觀察」結構，不提供買賣或配置指令。

### 外部 Cron 的官方／價格訊號備援

`Official macro and price monitor` 會在工作日每 15 分鐘檢查已設定的官方總經來源與固定價格門檻。若要讓 cron-job.org 備援此檢查，可對 GitHub Repository Dispatch API 發送 `official-event-check`；完整 Header 與請求本體請見 [金十 Token 與外部快訊安全設定](docs/JIN10_RAILWAY_SETUP.md)。此備援只觸發檢查，仍由 GitHub 的事件鎖決定是否推播。

## 部署架構

| 元件 | 角色 |
|---|---|
| GitHub Actions | 主排程、資料刷新、研究計算、Pages 部署與 Telegram 推播 |
| GitHub Pages | Telegram Mini App 的 HTTPS 儀表板 |
| Telegram Bot `@PRStK_Lab_bot` | 30 字內快報、Inline Mini App 按鈕與聊天室選單 |
| Railway 金十監測器 | 使用官方 MCP 讀取授權快訊並安全觸發 GitHub |
| cron-job.org | GitHub 主排程的外部備援 |

## 本機執行

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt pytest
python -m pytest -q
```

設定 `.env` 時，請只在本機保存 `TELEGRAM_BOT_TOKEN`、`TELEGRAM_CHAT_IDS`（以逗號分隔）與 `DASHBOARD_URL`；不得提交至 Git。GitHub 部署則使用 Actions Secrets 與 Variables。每位私人聊天室收件人都必須先對 `@PRStK_Lab_bot` 按 **Start**。

## 常用操作文件

- [Telegram Mini App 設定](docs/MINI_APP_SETUP.md)
- [Railway 金十監測器部署](docs/RAILWAY_MONITOR_DEPLOY.md)
- [金十 Token 與外部快訊安全設定](docs/JIN10_RAILWAY_SETUP.md)
- [Beta 操作說明](docs/BETA_OPERATION_GUIDE.md)
- [Beta 驗收清單](docs/BETA_ACCEPTANCE.md)

## 資料與研究限制

- 僅使用公開或已授權的資料；第三方新聞／快訊須符合其 API 權限與使用條款。
- 報價可能延遲、缺漏、受市場休市影響，且不同資料提供者的時間戳可能不同。
- 價格結構、動能、情緒與價值分數都是歷史資料模型的研究輸出，非未來績效保證。
- 重大事件與市場影響採中性描述，保留已知事實、可能影響與持續觀察的界線。
