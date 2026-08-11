# P4 回測績效摘要契約

四策略 walk-forward 現在同時輸出 gross／net 交易結果與可重現的摘要欄位：累積
淨報酬、年化報酬、年化波動、Sharpe、Sortino、最大回撤與 Calmar。計算以訊號
後的持有天數年化，且只使用已完成交易；交易數另以 `turnover_proxy` 標示，因為
沒有歷史投資組合權重時不能虛構金額週轉率。

若沒有交易，所有績效欄位保持 `null`，不把資料不足解讀成零風險或零報酬。回測
仍受 point-in-time 基本面與存活者偏差稽核約束；契約未達 `publication_state=ready`
時，Advice Gate 只能輸出 research observation。

回滾：撤回本 PR 即可恢復原有交易摘要欄位，既有成本與回測發布閘門不變。
