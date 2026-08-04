# P1-05：官方／第二來源交叉核對

`src/source_priority.py` 集中管理各市場的來源優先順序、最大時間差與價格差門檻。它補強既有 `market_crosscheck`，輸出可以直接交給發布與警報 gate 的證據紀錄。

## 優先順序

- 台股：TWSE → TAIFEX
- TPEx：TPEx → TWSE MIS
- S&P 500／Nasdaq／DJIA／SOX：Yahoo → public-market-secondary
- BTC／ETH：Binance → CoinGecko
- WTI：Yahoo → EIA
- Brent／Gold：Yahoo → public-market-secondary
- VIX：Yahoo → official-history

每筆結果固定包含 primary／secondary source、URL、quote time、quote basis、freshness、price gap、time alignment、cross_checked 與 alert_allowed。

## Fail-closed 規則

- 第二來源缺失：可在 Mini App 顯示 primary，但 `alert_allowed=false`。
- 來源時間超過政策門檻：標為 `stale_or_unknown`，不可觸發警報。
- 價格差超過門檻或時間未對齊：`discrepancy`，不可觸發警報。
- 只有符合政策門檻且兩來源交叉核對，才可作為高風險或價格警報的市場同步證據。

這個 PR 不會自行補空白價格，也不會把 Yahoo 來源標成官方；P1-06 會把 point-in-time 基本面與公司行動接入，同一套 provenance 可沿用。

## 測試與回滾

測試使用固定時間與假行情，涵蓋官方台股來源、缺少第二來源、逾時、價格不一致與健康彙總。回滾本 PR 不影響現有原始行情函式。