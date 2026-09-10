# P0-10 FinancialJuice 供應商優先通知政策

FinancialJuice 的 `vendor_importance` 是供應商標記，不是 PRStK 風險分數。只有 `9`、`10` 會標記 `vendor_priority_notification=true` 並進入獨立 `fj_priority` 投遞政策；`8` 以下（含缺值）回到一般 `material_event` 判定，不具備供應商優先資格。

此標記不會繞過來源時間、完整事實、去重、收件人投遞鎖或 release gate；它只不等待一般事件的市場同步、PRStK 風險升級、冷卻與預算。沒有必要的 FJ 公開事實或來源時間時仍抑制，不能因供應商分數單獨虛構高風險快訊。

驗證：`tests/test_financialjuice_contract.py` 覆蓋 10、8、7 與缺值邊界，並確認 vendor priority 與 PRStK risk 分離。

回滾：撤回本 PR 即可移除優先標記；既有風險分數與安全閘門不變。
