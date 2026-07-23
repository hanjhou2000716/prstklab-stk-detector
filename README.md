# PRStK Investment System

第一階段目標：從 GitHub Actions 安全地發出一則 Telegram 測試快報。

## 目前已完成的功能

- 30 字內快報驗證
- Telegram Inline Button（完整儀表板連結）
- 預設模擬模式，避免誤發送
- 可由 GitHub Actions 手動執行的測試工作流程
- 機敏資料使用 GitHub Secrets，不寫入程式碼

## 本機測試（不會發送）

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt pytest
python -m src.main
pytest -q
```

## 首次發送前的 Telegram 設定

1. 在 Telegram 開啟 `@PRStK_Lab_bot`，按下 **Start**，或傳送任意文字。
2. 取得 Bot Token：向 `@BotFather` 建立或管理 Bot 後複製 Token。
3. 取得 Chat ID：使用 Telegram Bot API 的 `getUpdates` 查詢；程式不會保存它。
4. 複製 `.env.example` 為 `.env`，填入 Token、Chat ID 與暫時的儀表板網址。
5. 執行下列指令才會真的發送：

```powershell
python -m src.main --send
```

## GitHub 設定

建立 GitHub repository 後，在 **Settings → Secrets and variables → Actions** 設定：

| 類型 | 名稱 | 內容 |
|---|---|---|
| Secret | `TELEGRAM_BOT_TOKEN` | BotFather 提供的 Token |
| Secret | `TELEGRAM_CHAT_ID` | 要接收快報的聊天 ID |
| Variable | `DASHBOARD_URL` | GitHub Pages 儀表板網址；第一階段可先填暫時網址 |

接著從 **Actions → PRStK Notification → Run workflow** 手動執行，即可發送第一則測試訊息。

## 儀表板

`site/` 包含 GitHub Pages 儀表板。第一次部署後，將 GitHub Pages 網址填入 `DASHBOARD_URL` 變數，Telegram 按鈕便會開啟儀表板。

## 市場資料更新

從 **Actions → Refresh market dashboard → Run workflow** 可手動更新代表標的收盤價、漲跌幅與台／美交易日狀態，並重新部署儀表板。系統僅使用公開資料；若個別報價來源暫時無法取得，頁面會明確顯示部分缺漏。

## 新聞與風險觀察

儀表板會另外呈現以下公開資訊，僅作為市場教育與風險觀察，不產生買賣建議：

- 台／美持股關聯新聞：從鉅亨網分類頁篩選與觀察池關鍵字相關的內容，最多各 3 則；沒有相關新聞時會留白，不以無關新聞補足。
- 美股風險：CNN Fear & Greed 與 CBOE VIX 最新讀值。
- 台股風險：嘗試取得台指 VIX；若公開來源沒有可用最新數值，會明確標示「暫時無法取得」，不會沿用舊資料。

## 正式快報排程

`Scheduled market brief` 會在下列台灣時間的週一至週五執行：06:00、08:45、10:00、11:45、13:15、14:10，以及美股盤前時段。美股盤前會依 `America/New_York` 時區自動二選一：美國夏令時間使用 21:00，冬令時間使用 22:00；兩者皆為美東 09:00、開盤前 30 分鐘。每次執行都會更新儀表板，並發送一則小於 30 字的 Telegram 快報。

同一日期與時段僅會推播一次。需要人工驗證時，可在 Actions 手動執行並勾選 `force`。

### 重大事件與快報規則

系統只會將下列公開新聞標記為「重大市場事件」：Fed／FOMC 與利率決策、CPI／PCE／非農等重要經濟數據、關稅／出口管制等重大政策、地緣軍事衝突，以及台積電或 NVIDIA 的方向性財報與展望。代表標的單日漲跌幅達 3% 以上時，也會標示為顯著波動。

Telegram 快報一律小於 30 字；有重大事件時會優先顯示事件類別，例如：`盤中｜關稅／政策｜2330📈+1.2%`。無符合門檻的事件則顯示代表標的的漲跌，完整標題、來源與背景只放在儀表板。

### 外部 Cron 備援

工作流程支援 GitHub `repository_dispatch` 事件 `scheduled-brief`。外部 Cron 必須使用專屬、最小權限的 GitHub Fine-grained PAT，並在確認 GitHub 排程漏跑時才觸發：

```json
{"event_type":"scheduled-brief","client_payload":{"slot":"intraday"}}
```

系統會用日期加時段的紀錄避免重複推播。外部 Cron 的實際帳號與 Token 將於下一階段設定，不能寫入 Repository 或對話內容。外部 Cron 的美股盤前備援只需建立一個：時區選 `America/New_York`、時間設 `09:00`、週一至週五，並以 `us_premarket` 作為 slot；cron-job.org 會自動處理夏令／冬令時間。

## 安全提醒

- `.env` 已被排除，不會提交至 Git。
- Token 一旦外流，請立即到 BotFather 撤銷並重新產生。
- 系統目前不會連接券商、錢包或帳戶，也不會自動下單。
