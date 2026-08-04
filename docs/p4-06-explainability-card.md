# P4-06 候選 Explainability Card

候選卡固定顯示策略、訊號日期、通過／未通過條件、資料完整度、風險因子、事件脈絡與失效條件，並明確標記不是買進訊號。缺少身份或資料品質欄位時視為不完整。

驗證：`pytest -q tests/test_strategy_explainability.py`。

回滾：撤回本 PR 即可移除候選解釋卡，不影響掃描結果。
