# P4-04 Walk-forward 指標

提供 CAGR、波動度、Sharpe、Sortino、最大回撤、Calmar、勝率、換手率、最差期間、恢復期與相對 benchmark 的觀測 alpha。空資料明確回報 `insufficient_data`，不以零績效冒充正式結果。

驗證：`pytest -q tests/test_backtest_metrics.py`。

回滾：撤回本 PR，不影響原始交易紀錄。
