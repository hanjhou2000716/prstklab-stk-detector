# P7-03 SLO 與 P7-04 備份恢復

SLO 統計來源成功率、報價新鮮度、交叉核對、Telegram 送達、stale 比率與研究完成率。備份 manifest 保存檔案大小與 SHA-256，restore verification 會檢查檔案遺失或內容變動；每月可將驗證結果寫入維運摘要。

驗證：`pytest -q tests/test_slo_backup.py`。

回滾：撤回本 PR 即可移除 SLO／備份檢核，不刪除任何備份檔。
