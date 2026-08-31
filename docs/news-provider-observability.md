# News provider observability

每個 release-bound `news.intelligence.<market>` 物件現在會輸出
`observability`，並把同一組數據投影到 `source_health`：

- `stories_ingested`：正規化後收到的故事數；不代表已通過公開來源與市場範圍閘門。
- `stories_deduped`：依 canonical headline／event cluster 合併後的故事數。
- `ranked_count`：實際進入本市場前五名排序的故事數。
- `relevance_distribution`：由明確 relevance reason 前綴統計（例如
  `tracked_ticker`、`research_candidate`、`active_event`）。
- `providers[]`：每個 provider 的 `status`、最後成功／失敗檢查時間，以及上述三種計數。
- `scan_summary`：彙總 provider 數量、成功／失敗／停用數、被市場語意篩除的故事數，
  以及最終排序可用數量；Mini App 以此顯示美股來源漏掃的實際範圍。

美股的 SEC／Federal Reserve 官方來源與 Yahoo Finance／Google News／鉅亨公開來源
分開記錄 funnel（取得、正規化、市場相容、可公開、去重、排名）。公開來源故事的
`evidence_state` 固定為 `observation` 並標記 `confirmation_required=true`，不能單獨
升級為 confirmed、escalated 或高風險警報。官方來源失敗但公開來源成功時，市場狀態
為 `degraded`；只有所有啟用來源均失敗且沒有有效快取時才是 `source_failed`。

`healthy`、`no_event`、`stale` 與 `rate_limited`／`failed` 保持不同語意。來源
失敗不會被空結果覆蓋，也不會阻擋核心市場 release；但它會保留在健康卡與
release artifact，讓 Mini App 能區分「本輪無事件」和「掃描失敗」。這些欄位
只保存計數、時間與狀態，不保存 response body、header、token 或私人識別資訊。

驗證：`python -m pytest -q tests/test_news_intelligence.py tests/test_release_manifest.py`

回滾：撤回本 PR 即可移除新增的 observability 欄位；既有 `stories`、來源路由與
fail-closed 行為不變。
