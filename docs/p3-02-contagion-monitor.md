# P3-02 跨資產傳染監測

以可追溯的日變動與 rolling correlation 觀測股債同跌、美元急升、黃金與 VIX 同升、亞洲／半導體同步轉弱及加密風險轉折。任何必要欄位缺失都回報 `data_gap`，不把缺資料當成正常，也不單獨升級高風險通知。

驗證：`pytest -q tests/test_contagion_monitor.py`。

回滾：撤回本 PR 即可移除傳染監測器，不影響既有行情與事件資料。
