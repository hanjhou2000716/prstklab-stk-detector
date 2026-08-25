# P4 回測發布契約一致性

研究報表若帶有 `backtest_release_status` 或候選的回測識別，發布稽核會把研究層、候選層與回測契約視為同一個不可分割的版本。這避免候選卡片引用另一個 walk-forward 研究，或在資料不足時誤解鎖 Advice Gate。

## 規則

- `ready` 必須有 `backtest_release_contract`、非空 `backtest_release`，且 `publish_eligible=true`。
- `blocked`／`unavailable` 不得宣稱 `publish_eligible=true`。
- 研究層的 `backtest_release_status` 與契約 `publication_state` 必須一致；為了讀取舊的 blocked release，未提供研究層 status 仍可相容。
- 候選的 `backtest_release` 與候選契約必須和研究層的 release ID、狀態一致。
- 沒有回測欄位的舊觀察報表維持可讀，但不會因此取得正式建議資格。
- 每個正式回測契約會輸出 `strategy_registry_validation`；所有策略列必須通過完整 provenance 欄位檢查，缺欄位時契約會保持 `blocked`。

## 失敗處理與回滾

任何不一致都會在 `validate_research`／release gate 失敗，發布與通知流程維持 fail-closed。回滾本 PR 即可移除新增 invariant；既有回測 JSON 與候選資料不會被改寫。

