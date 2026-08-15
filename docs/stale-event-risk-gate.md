# Stale event risk gate

事件來源可以保留過期資料作為歷史上下文，但不能用它取得高風險推播資格。

`cluster_external_events` 會把觀測中的明確品質標記提升到事件群組：

- `stale_used=true`
- `quote_delayed=true`
- `freshness`／`data_status`／`quality_state` 為 `stale`、`expired`、`delayed`、`unavailable` 或 `degraded`

只要任一觀測符合上述條件，`score_prstk_risk` 會設定
`freshness_blocked=true`，最高維持 `R2`，並讓通知決策回傳
`stale_or_delayed_evidence_blocked`。因此即使事件同時帶有官方核對與市場同步旗標，過期或延遲資料仍不能升級為 R3/R4。

這個閘門不刪除歷史資料，也不把資料缺口解釋成無風險；Mini App 可以繼續顯示觀察，但 Telegram 高風險路徑會 fail closed。

回滾方式：撤回本 PR 即可移除此 freshness block；既有事件聚類欄位與資料輸出不受破壞。
