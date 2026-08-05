# P2 總經 Surprise Engine 契約

`src/surprise_engine.py` 只計算公布值相對預期與前值的差異，並保留：

- `expected`、`actual`、`previous`
- `revision`（若來源提供修正值）
- `release_time`、`source_url`
- `surprise`、`surprise_pct_of_expected`、`surprise_z`

缺少預期值或公布值時，狀態為 `insufficient_evidence`。歷史標準差為零或
負值時不計算 z-score。`market_direction` 固定先是 `not_determined`；
Surprise Engine 不得單獨推導股市漲跌，必須由行情、利率、美元及第二來源
交叉核對後，才能進入事件影響分析。
