# P4-03 交易成本模型

台股明列手續費、證交稅、spread、滑價；美股明列 commission、spread、slippage 與 FX cost。模型同時提供 gross／net 計算，所有假設可由 overrides 取代且不默認為零。

驗證：`pytest -q tests/test_transaction_costs.py`。

回滾：撤回本 PR；既有回測結果不會被覆寫。
