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
| 台股盤後 | 工作日 14:25 | 台股收盤後資料與盤後摘要 |
| 美股盤前 | 工作日 21:00（美國夏令）或 22:00（美國冬令） | 台股回顧與美股盤前資料；兩個時間只會擇一發送 |
| 全市場量化研究 | 工作日 13:30 | 台美股動能、裸 K、三維共振、價值覆核，及研究清單的價格欄位；預留至 14:25 盤後快報的處理時間 |
| 官方重大總經事件 | 工作日每 15 分鐘 | 僅在符合官方事件條件時更新並發送一次 |
| 金十授權快訊 | Railway 每 120 秒 | 僅檢查金十官方 MCP `list_flash`，符合重大事件規則才觸發 GitHub 快訊 |

因此，儀表板上的「最後更新」是**最近一次成功完成公開市場掃描並發布資料的時間**，不是交易所的逐筆即時報價時間。若有任何私人聊天室收件人尚未按 Start 或已封鎖 Bot，系統會略過該收件人並記錄原因，其他收件人、快照提交與 Pages 部署仍會繼續完成。可隨時在 GitHub Actions 手動執行 **Refresh market dashboard** 或 **Unified Taiwan-US research report** 取得一次新的快照；手動執行不代表資料來源一定提供即時行情。

cron-job.org 的備援請求只會在對應時段附近被接受，例如台股盤前為 08:15–09:15 且 payload 的 `slot` 必須為 `pre_open`。這可避免設定錯誤的提早請求先取得防重複鎖，導致正式 08:45 快報被略過；手動 GitHub Actions 測試不受此限制。

## 排程與可靠性

- 每個快報時段使用唯一鍵與 GitHub Actions Cache 去重，避免 GitHub 主排程與外部 Cron 重複推播。
- 21:00／22:00 的美股盤前時段會依 `America/New_York` 夏令時間自動選擇一個有效時段。
- 資料來源請求失敗會重試一次；失敗時在儀表板呈現資料暫時無法取得。
- Railway 監測器保存已處理的金十事件 ID，GitHub 收到事件後仍會再次驗證 HMAC 簽章與去重。

### 外部 Cron 的官方事件備援

`Official macro event monitor` 會在工作日每 15 分鐘檢查已設定的官方總經來源。若要讓 cron-job.org 備援此檢查，可對 GitHub Repository Dispatch API 發送 `official-event-check`；完整 Header 與請求本體請見 [金十 Token 與外部快訊安全設定](docs/JIN10_RAILWAY_SETUP.md)。此備援只觸發檢查，仍由 GitHub 的事件鎖決定是否推播。

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
