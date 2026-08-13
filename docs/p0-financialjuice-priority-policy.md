# P0-10 FinancialJuice 供應商優先通知政策

FinancialJuice 的 `vendor_importance` 是供應商標記，不是 PRStK 風險分數。`8`、`9`、`10` 會標記 `vendor_priority_notification=true`，提供通知編排器作優先處理；`7` 或缺值不具備供應商優先資格。

此標記不會繞過官方核對、第二來源、相關市場同步、Alert Budget 或 release gate。沒有 PRStK 證據時，仍維持 R2／pending，不能因供應商分數單獨發出高風險快訊。

驗證：`tests/test_financialjuice_contract.py` 覆蓋 10、8、7 與缺值邊界，並確認 vendor priority 與 PRStK risk 分離。

回滾：撤回本 PR 即可移除優先標記；既有風險分數與安全閘門不變。
