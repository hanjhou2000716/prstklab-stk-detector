# Research release fallback

研究掃描任一來源失敗時，Workflow 不會把舊候選誤當成即時結果。若存在上一個成功快照，會透過 `mark_stale_research_fallback` 產生明確的降級報表：

- `availability=expired`
- `research_freshness=stale_fallback`
- `production_eligible=false`、`publish_eligible=false`
- 每個策略來源標為 `scan_state=failed`、`candidate_state=data_gap`

因此 Mini App 可以顯示上一成功版本的時間與失敗原因，但不會顯示為本輪正式候選，也不會觸發高風險通知。下一次全市場掃描成功並通過 production gate 後，才會取代降級版本。

回滾：撤回本 PR 即可恢復原 Workflow；不會刪除 data-release 上既有成功快照。
