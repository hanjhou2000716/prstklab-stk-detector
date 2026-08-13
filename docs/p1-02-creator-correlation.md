# P1-02 Creator／PRStK 交叉分析

`src/creator_correlation.py` 將已清洗的 Creator insight 與同一發布鏈上的
公開市場／研究 snapshot 做保守的可比性判斷。它只比對明確 ticker、產業與
快照時間，不從文章語氣推導漲跌，也不會產生買賣訊號。

## 狀態

- `not_comparable`：缺少兩個 snapshot，沒有足夠公開證據。
- `awaiting_market`：市場快照尚未到達，或沒有明確 entity match。
- `aligned`：至少一個明確 ticker 或產業在市場快照出現；這不是方向判斷。
- `stale`：市場快照超過預設 36 小時，不能當作目前證據。
- `divergent`：保留給後續有明確、可驗證反向證據的版本；目前不由文字推測。

每筆結果都保留 market/research snapshot ID、比對時間與 reason，並固定
`is_investment_signal=false`。缺資料時 Mini App 應顯示等待原因，而不是把
Creator 內容升級成市場快訊。

## 回滾

撤回本 PR 即可移除交叉分析欄位；Creator release 的既有 lineage 與
fail-closed parser gate 不受影響。
