# P1-01：統一來源 Adapter

本 PR 建立所有公開唯讀來源的共同介面，讓市場、事件與研究工作流不再各自處理 timeout、HTTP 錯誤、來源履歷與健康狀態。

## 契約

`src/adapters/base.py` 提供 `MarketDataAdapter`，每個來源都必須提供：

- `fetch()`：唯一允許發生網路 I/O 的方法，回傳不可變 `AdapterObservation`。
- `normalize(observation)`：純函式式正規化；不得把缺值補成即時價格。
- `health()`：回傳 `healthy`、`failed` 或 `unknown`，並保留延遲、連續失敗、最近成功時間與錯誤分類。
- `provenance(observation)`：回傳 provider、source tier、URL、抓取時間、HTTP 狀態、request ID 與 payload hash。

`AdapterError` 使用固定錯誤碼（例如 `transport_error`、`http_error`、`parse_error`、`missing_credential`），訊息不可包含 secret 或完整回應內容。

## 已登錄來源

| Provider | Source tier | 用途 |
| --- | --- | --- |
| TWSE | official | 台股公開行情／MIS |
| TAIFEX | official | 台指期與期貨公開資料 |
| TPEx | official | 櫃買市場公開資料 |
| Yahoo | public-market | 全球公開行情觀測 |
| SEC | official | 8-K 公開申報；使用可識別 GitHub User-Agent |
| FRED | official | 宏觀序列；需要 `FRED_API_KEY` |
| EIA | official | 能源資料；需要 `EIA_API_KEY` |
| Binance | public-market | BTC／ETH 公開市場行情 |
| GDELT | discovery | 事件線索，不可單獨升級高風險 |

`src/adapters/registry.py` 的 `build_default_adapters()` 每次建立全新實例，避免不同工作流共享健康計數器。測試可注入 transport，不會對外發送請求。

## 安全與失敗策略

- FRED／EIA 缺少環境變數時 fail closed，不能把缺資料當成 0 或「沒有事件」。
- HTTP 429、5xx 會分類為可重試 transient error，但本層不做密集重試；由上層排程政策控制。
- 所有來源先保存 raw observation 的 hash，再交給各領域正規化器；後續 P1-02 會把 raw payload 寫入不可變 Observation Store。
- P1-05 會在此契約上加入官方／第二來源交叉核對，本 PR 不會把單一來源直接升級為警報。

## 驗證與回滾

`tests/test_adapters.py` 完全使用假 transport，覆蓋成功、timeout、429、缺少 API key、來源履歷與健康快照。若部署後發現來源解析器問題，可回滾本 PR；既有工作流仍可使用原有來源函式，不會刪除現存資料。