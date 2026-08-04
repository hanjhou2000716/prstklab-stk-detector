# P6 Mini App 工作台、事件時間軸與來源健康

首頁採固定八區塊順序；事件可依市場、分類、風險與確認狀態篩選，並以 cluster ID 保留版本歷史；來源健康頁統計成功率、延遲、最近成功、stale cache、交叉核對、parser error 與 rate limit。

驗證：`pytest -q tests/test_workbench_and_health.py`。

回滾：撤回本 PR 即可恢復舊頁面排序，不刪除事件紀錄。
