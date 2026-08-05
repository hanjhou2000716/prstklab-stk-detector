# P2 事件來源目錄契約

`src/event_source_catalog.py` 是事件收集器共用的政策登錄表。每個來源都
固定保存分類、端點、來源層級、輪詢週期、最大可接受新鮮度、保留規則與
是否可以單獨觸發警報。

## 健康狀態語意

- `healthy`：成功抓取，仍在來源的最大年齡內。
- `no_event`：成功抓取，但本輪沒有符合條件的事件；這不是掃描失敗。
- `stale`：有上次資料，但已超過該來源的 `max_age_minutes`。
- `failed`：本輪連線、HTTP 或解析失敗。
- `not_scanned`：本輪沒有任何觀測紀錄。

`catalog_health()` 會保留 `fetched_at`、計算資料年齡，並將逾時與失敗
轉成明確的 `data_gap`。通知層不得把 `stale`、`failed` 或 `not_scanned`
當成「沒有事件」；發送高風險快訊前仍須通過官方來源與市場同步閘門。

## 驗證規則

CI 透過 `validate_catalog()` 檢查：

1. key 唯一且已正規化。
2. 端點必須為 HTTPS。
3. tier 只能是 `official`、`public-market` 或 `discovery`。
4. 輪詢與最大年齡必須為正數，且最大年齡不得短於輪詢週期。
5. discovery 來源不得單獨升級為警報。

新增或修改來源時若違反上述規則，應先修正政策資料再部署，不以空結果
掩蓋來源設定錯誤。
