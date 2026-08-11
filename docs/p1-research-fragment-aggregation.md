# P1 Research Fragment Aggregation

台股分批 worker 會以 offset 寫出 `*-scan-<offset>.csv` 與對應摘要。統一研究報表在建立前會合併所有 offset，依 ticker 去重並按分數排序，摘要則聚合完成、失敗與 universe 計數。

只有單一 `scan-0` 時不會改寫檔案；分段缺失或失敗會保留 `building` 狀態，不能被誤判成完整掃描。回滾方式為撤回本 PR，既有 canonical artifact 不受影響。
