# P0-09 FinancialJuice Intelligence fan-out

複合 FinancialJuice envelope 在進入 `build_intelligence_context` 時會先展開 `items[]`，再交由同一套事件分類、跨來源聚類、風險評分、Market Impact 與 Advice Gate。Mini App 可取得全部項目的 `item_id`、`event_cluster_key`、標題與供應商重要性，不再只保留第一則。

每個項目仍受 PRStK 官方核對、相關市場同步、資料品質、Alert Budget 與 release gate 約束。未核對項目只會顯示 pending／observation，不能因 FinancialJuice 分數變成高風險快訊。

驗證：`tests/test_intelligence_pipeline_external_risk.py`、`tests/test_external_event_pipeline.py`、`tests/test_external_source_parsers.py`、`tests/test_financialjuice_contract.py` 共 23 項 targeted tests；Ruff 與 Mypy 通過。

回滾：撤回本 PR 即可停止複合 envelope 在 intelligence context 的展開；既有單項 external event 行為保留。
