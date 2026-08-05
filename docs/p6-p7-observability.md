# P6／P7：事件時間軸與可觀測性

`src/event_timeline.py` 提供 Mini App 可用的市場、分類與核對狀態篩選，並依發布／抓取時間排序，讓事件更新可保持同一條時間軸。

`src/health_observability.py` 將來源成功率、失敗數、stale 使用、交叉核對率與 parser error 聚合成 24 小時或 7 天摘要的基礎資料；`source_state()` 明確區分 `no_events`、`scan_failed` 與 `not_scanned`，避免空結果被誤解為成功。
