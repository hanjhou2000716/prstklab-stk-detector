# P3 策略可解釋性與 Advice Gate

研究候選現在會在公開研究產物中保留可追溯的證據維度：通過／未通過條件、資料完整度、流動性、近期事件、估值／動能／品質位置、訊號日期、失效條件與來源證據。

每一筆候選都會經過 `Advice Gate`。缺少新鮮行情、交叉核對、完整資料、有效策略登錄或正式回測發布契約時，候選仍可作為研究觀察，但狀態固定為 `observation_only`，不會產生買進／賣出指令或保證式語句。

策略登錄只有在 `strategy_version`、`data_version`、`backtest_release` 與完整 registry row 均可核對時才會標為 `production`。僅有裸 release ID 不足以開啟 Advice Gate；回測契約必須是 `publication_state=ready` 且 `publish_eligible=true`。

這些欄位是證據欄位，不是新的綜合評分，也不會放寬既有選股條件。若資料缺漏，系統維持 fail-closed。

## 回滾

撤回本 PR 即可移除新增的 Explainability 維度與欄位映射；既有候選條件、研究逾時門檻與 Advice Gate 的保守阻擋不受影響。
