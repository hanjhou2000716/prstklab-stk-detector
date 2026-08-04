# P0-01：發布產物契約

這一批建立市場、研究報表與 release manifest 的 JSON Schema，以及發送前可重複執行的跨欄位驗證器 `src/artifact_contract.py`。

## Fail-closed 規則

- `stale_used=true` 不得同時標記 `freshness=live`。
- 延遲報價 (`quote_delayed=true`) 不得成為警報可用報價。
- 官方來源標籤必須與來源網域一致；Yahoo 標籤必須來自 Yahoo 網域。
- `published_at` 不得晚於 `fetched_at`。
- 技術區間早於行情日期時，必須明確標記 `technical_context_stale=true`。
- 研究掃描的 `candidate_state`、`scan_state` 與資料缺口不可互相矛盾。
- `formal_candidates` 不得大於該來源的 `candidates`。
- manifest 指定的 market/research snapshot 必須與實際產物的 `snapshot_id` 相同。

驗證器只回傳錯誤，不會修改檔案或自行補值；呼叫端應在發布或推播前遇到非空錯誤清單時停止流程。

## 測試與失敗案例

`tests/test_artifact_contract.py` 包含：有效 release、過期資料冒充 live、來源網域矛盾、候選數矛盾，以及缺少 release envelope。這些案例會在 CI 中讓測試失敗，避免錯誤資料悄悄發布。

目前生產資料仍可能因既有來源標籤／TPEx 交叉核對格式而無法通過嚴格契約；P0-02 會先修正資料正規化，再把嚴格契約接入正式發布工作流。

## Rollback

若契約導致既有發布流程需要緊急回復，回退本 PR 即可移除新增 Schema、測試與驗證器；既有市場與研究快照不會被刪除。回退後必須重新執行完整 pytest，並記錄未通過的契約錯誤，不能以刪除驗證錯誤來放行警報。
