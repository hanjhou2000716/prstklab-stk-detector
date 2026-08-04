# P4-01 Point-in-time 歷史資料庫

正式回測要求 bars、調整因子、股息、歷史成分、申報快照、下市資料與 benchmark 全部具備 `as_of`，並由 manifest 明確確認 point-in-time、存活者偏差檢核與幣別調整政策。缺一即標記 `incomplete`，不產出正式績效結論。

驗證：`pytest -q tests/test_backtest_archive_contract.py`。

回滾：撤回本 PR 不會刪除任何既有資料。
