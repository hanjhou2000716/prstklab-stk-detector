# P4-02 前視與存活者偏差稽核

每筆訊號要求進場日在訊號收盤日之後，財報／成分／價格 `as_of` 不得晚於訊號日；下市資料若沒有下市日期則判定失敗。稽核失敗時不產出正式績效。

驗證：`pytest -q tests/test_lookahead_audit.py`。

回滾：撤回本 PR 即可移除 row audit。
