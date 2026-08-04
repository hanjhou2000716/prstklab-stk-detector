# P2-02：事件聚類與版本化證據

`cluster_events()` 先使用既有的 entity／place／action 交叉核對，再以事件帳本的 canonical key 聚合。每個事件保留：

- `cluster_id`／`canonical_key`
- `first_seen`、`last_updated`
- 所有來源 URL 與網域
- `evidence_count`
- `crosscheck_status`
- `pending_reasons`（`waiting_second_source`、`waiting_market_sync`）

新聞報告與即時快訊只要描述同一人物／地點／動作，就應更新同一 cluster，而不是建立第二則獨立事件。衝突、黑天鵝與災害即使已完成來源核對，沒有至少一個相關市場同步證據仍維持等待狀態。

回滾：撤回本 PR；既有 `event_crosscheck` 與 `event_ledger` 可獨立運作。後續 P2-03 將加入總經預期／前值／公布值與市場第一反應。