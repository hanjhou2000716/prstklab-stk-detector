# P4：回測成本與策略版本

`src/backtest_costs.py` 以市場為單位明確列出手續費、交易稅、滑價與匯兌成本，所有績效可同時保存 gross／net。成本不是隱含假設，若市場不支援會直接拒絕。

`src/strategy_registry.py` 登錄策略版本、參數雜湊、股票池版本、資料版本、程式 commit 與回測 release，避免不同版本結果被混用。正式回測仍需先通過 point-in-time 與 survivorship audit。
