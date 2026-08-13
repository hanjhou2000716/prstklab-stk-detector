# P0-09 FinancialJuice 管線 fan-out

`build_external_events` 是單一共用事件管線的複合信件入口。每個 `items[]` 項目都會進入原有的分類、事件聚類、風險評分、通知閘門與生命週期決策，並保留 `compound_item_id` 與 `compound_event_cluster_key` 供事件帳本及 Mini App 追蹤。

`compound_unresolved` 只產生一筆 suppressed／pending 結果，不產生任何部分事件，避免錯誤資料進入 Telegram。沒有 `items[]` 的舊單項輸入仍走 `build_external_event`，維持向後相容。

驗證：`tests/test_external_event_pipeline.py`、`tests/test_intelligence_pipeline_external_risk.py`、`tests/test_external_source_parsers.py` 共 15 項 targeted tests；Ruff 與 Mypy 通過。

回滾：撤回本 PR 即可停用複合 fan-out；單項事件與既有來源核對閘門不變。
