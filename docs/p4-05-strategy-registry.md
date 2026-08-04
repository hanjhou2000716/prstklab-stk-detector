# P4-05 Strategy Registry

每個動能、共振、裸 K、價值策略保存 strategy ID、版本、參數 hash、宇宙、資料、程式 commit 與回測 release。沒有有效 backtest release 的策略不能進入建議閘門。

驗證：`pytest -q tests/test_strategy_registry.py`。

回滾：撤回本 PR 即可移除 registry，既有策略檔不受影響。
