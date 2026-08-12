# P4 研究回測版本綁定

研究候選只有在同時具備可發布的 `backtest_release_contract` 與完整
`strategy_registry` 時，才會進入 production binding。回測合約必須是
`publication_state=ready` 且 `publish_eligible=true`，並與候選上的 release ID
一致；缺漏、阻擋或不一致一律保留為 `observation_only`。

這讓研究頁、建議閘門與候選解釋卡使用同一個回測證據，不會因為只有一個
看似有效的 release ID 就誤開啟正式決策狀態。

## 測試與回滾

- 測試涵蓋阻擋合約、release ID 不一致與完整 registry 綁定。
- 回滾本 PR 即可恢復原本只檢查候選欄位的行為；既有回測產物不會被修改。
