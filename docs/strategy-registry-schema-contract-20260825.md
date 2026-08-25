# Strategy Registry Schema Contract

本契約將策略版本、參數雜湊、研究 universe、資料版本、程式 commit 與正式回測 release 綁定為單一可驗證物件。`src.strategy_registry.validate_strategy_release` 會先執行既有欄位與型別檢查，再以 `schemas/strategy-registry.schema.json` 進行 Draft 2020-12 驗證；未知欄位或契約缺失一律 fail closed。

`schemas/backtest-release.schema.json` 透過相同 schema 限制 `strategy_registry` 陣列，避免回測 release 接受未定義或可能含私人內容的欄位。策略資料不足時仍由 Advice Gate 維持研究觀察狀態，不會解鎖買賣判斷。

## 驗證與回滾

- `tests/test_strategy_registry_validation.py` 覆蓋完整列、缺欄位、錯誤型別與未知欄位。
- `tests/test_backtest_release.py` 驗證產物仍通過回測 schema 與 registry binding。
- 若需回滾，還原本 PR 的 schema、validator、測試與文件即可；既有回測資料仍可讀取，但未通過新契約的列會被阻擋，不會被默認發布。
