# P0-09 FinancialJuice 複合信件契約

FinancialJuice 一封信可能包含多個獨立新聞項目。系統以明確的 `Item N`、`News Item N` 或 `Story N` 標記分段；沒有明確分段時維持既有單項解析，不把段落猜成事件。

每個項目會產生獨立的 `item_id`、`content_hash`、`event_cluster_key`、候選事件分類、供應商重要性與來源欄位。供應商重要性只表示 FinancialJuice 的優先級，不會改寫 PRStK 風險等級。

若複合信件任一項缺少標題，整封信標記 `compound_unresolved` 並輸出空 `items`，避免部分解析資料進入正式事件與通知管線。此狀態需在來源健康與事件帳本中保留，等待下一次完整內容。

驗證：`tests/test_external_source_parsers.py` 覆蓋兩項 fan-out、缺標題 fail-closed、單項向後相容與 JSON Schema。

回滾：撤回本 PR 即可回到單項解析；既有 FinancialJuice 風險閘門與 notification policy 不變。
