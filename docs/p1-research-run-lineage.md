# P1 research run lineage

每份研究報表現在帶有 `research_run`，包括 workflow／本機 run ID、來源
commit、掃描起訖時間、掃描模式與範圍。候選列同步保存 `research_run_id`
與 `source_commit_sha`，因此不會把新行情與不明來源的舊研究結果誤組成同一
個 release。

`source_commit_sha` 由明確參數、`GITHUB_SHA` 或執行時的 Git HEAD 取得；取不
到時保留 `null`，不偽造來源。這些欄位是可追溯性資料，不會放寬任何研究或
發布閘門。

回滾：移除本 PR 後，舊報表仍可由相容讀取器載入；下次成功產生的 release
會重新建立完整 lineage。
