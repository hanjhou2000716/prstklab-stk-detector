# P1-04 Creator Consensus

`src/creator_consensus.py` 提供保守的 topic-level consensus 契約。只有兩個
以上獨立 Creator 且明確提供可比較的 `consensus_stance`（`risk_on`、
`risk_off`、`neutral`）時，才會標示 `aligned` 或 `mixed`；不會從中文或英文
評論文字猜測方向，也不會把共識轉成買進、賣出或高風險警報。

缺少第二來源時是 `insufficient_sources`，有多來源但沒有明確 stance 時是
`pending_verification`。artifact 固定保存 contributors、topic、as_of、
confidence 與 `is_investment_signal=false`，供 Mini App 顯示證據狀態。

回滾：移除本 PR 即可回到沒有 consensus 欄位的 creator artifact；核心市場、
研究與事件 release 不受影響。
