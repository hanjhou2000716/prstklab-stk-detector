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

## 價格結構研究引擎

`src/price_action.py` 是研究用途的四大裸 K 結構掃描器：撐壓互換回踩、雙底右腳確認、假跌破收復、訂單塊回踩。它以最新完成日 K、歷史結構點、成交金額排序與 ATR 風險邊界產生研究候選清單，最多 5 檔。

輸出欄位是市場結構與參考風險資訊，並不代表買賣訊號、部位建議或自動下單。儀表板目前會掃描 7 檔代表觀測池並展示最多 5 檔研究候選；後續再擴大公開市場範圍與建立可重現的回測驗證。

## 主動型 ETF 研究配置

`src/active_etf_research.py` 會讀取價格結構研究候選的「參考價格」與「結構風險邊界」，以反向風險比例產生一份可重現的**研究配置草案**。單一候選預設上限為 45%；僅有 1 或 2 檔候選時，自動改為 100% 或各 50%，避免研究計算出現無法分配的餘額。

這個模組不會連接券商、不會計算下單股數、不會發出交易指令；每日收盤後只提供下一交易日可供人工檢視的風險配置草案。

儀表板會在裸 K 結構研究有候選時，同步顯示其研究配置比例與結構風險百分比；沒有候選或資料缺漏時會明確留白，不會以舊資料代替。

## 回測成本模型

`src/research_backtest.py` 提供假設性的進出價格回測計算，會在每一筆研究紀錄同時扣除進、出兩側的手續費與滑價：台股預設單邊手續費 0.1425%、美股預設單邊手續費 0.005%，兩者預設單邊滑價 0.5%。成本假設會連同結果輸出，方便日後比較不同情境，且不會默認成本為零。

此模組只評估已提供的歷史研究紀錄，並不預測未來、不產生下單指令或連接任何帳戶。

## Price Action 逐步回測研究

`src/price_action_backtest.py` 以逐根 K 線方式重播裸 K 結構掃描：訊號只看當時已完成的歷史資料，並從下一根 K 線開盤開始評估結構風險邊界與 10R 研究目標。若同一根 K 線同時觸及停損與 10R，OHLCV 無法判斷先後順序，系統會標示「順序不明」並採保守的風險邊界結果，而不假設獲利。

在 **Actions → Price Action walk-forward backtest → Run workflow** 可選擇公開 Yahoo Finance 代碼（例如 `2330.TW` 或 `NVDA`）、市場成本模型與歷史區間，下載 JSON 與 CSV 研究報表。這是手動驗證工具，不會納入正式快報排程。

回測工作流程也可選擇 **Free Roll** 研究模式：達 5R 時以半數比例記錄、其餘半數的研究風險邊界改為成本價，並繼續檢視 10R。日 K 若無法判斷同日高低點的先後順序，報表會直接標示「順序不明」而不假設較有利的結果。

## 再平衡研究檢視

`src/rebalance_research.py` 只接受使用者手動提供的現有權重與系統的研究目標權重；每日收盤後，當任一權重漂移達 10%、ATR 比率達 1.5 倍，或平均相關性變化達 0.2 時，才會標記為「需人工再平衡檢視」。它不會讀取券商帳戶，也不會產生或執行調整指令。

## 台股裸 K 結構全市場研究

在 **Actions → Manual Taiwan Price Action scan → Run workflow** 可分批掃描公開台股清單。工作流程使用公開日 K、四大裸 K 結構與最低成交金額篩選，按最新成交金額排序最多 5 檔研究候選，並將 CSV／JSON 作為可下載 Artifact。這是手動研究工具，不會納入快報或自動交易流程。

**Actions → Manual US Price Action scan → Run workflow** 提供對應的美股大型股掃描；資料來源為公開 S&P 500 成分表作為大型股研究樣本，而非宣稱為 VOO 的精確成分股。結果同樣僅供研究，並輸出可下載 Artifact。

## 跨市場研究摘要格式

`src/research_report.py` 將台股／美股的動能與裸 K 結構掃描 CSV 轉為共同欄位（市場、策略、排序、標的、成交金額、參考價格、結構風險邊界與資料狀態）。不同策略的分數不會被混為同一排名；缺少或空白的來源會明確標記，而不使用舊資料補足。

在 **Actions → Unified Taiwan-US research report → Run workflow** 可一鍵執行台股與美股的動能、裸 K 結構掃描，更新代表標的資料，將統一研究摘要部署到 GitHub Pages，並保留所有 CSV／JSON 為可下載 Artifact。這個工作流程是手動研究工具，不會推播 Telegram 或執行任何交易。

每次成功完成的統一研究摘要與代表標的資料會保存為公開的 GitHub Pages 資料檔。這可避免後續一般儀表板部署覆蓋掉最新研究摘要；內容只包含公開市場研究結果，不包含帳戶、持倉或任何機敏資料。

研究摘要會附帶健康度：來源暫時無法取得、報表超過 180 分鐘或產生時間缺失時，儀表板會顯示「需留意」與具體原因；資料健康時也會明確標示，避免把缺漏誤認為無候選。

全市場掃描的公開資料批次會設定 8 秒逾時，若出現暫時失敗會重試一次；仍失敗的批次會被統計為失敗並在摘要中揭露，不會讓單一來源無限卡住整份研究流程。

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
