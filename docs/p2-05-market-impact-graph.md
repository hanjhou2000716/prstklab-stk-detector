# P2-05：Market Impact Graph

`MarketImpactGraph` 將事件到市場的傳導寫成有向邊，而不是只輸出一個模糊的影響標籤。每條邊必須包含：

- `source`、`target`
- `direction`（up／down／mixed／unknown）
- `confidence`（0–1）
- `evidence`
- `horizon`
- `invalidation_condition`

預設圖包含出口管制 → AI 半導體 → 台積電／費半，以及能源供應中斷 → WTI → 通膨預期。這些是可檢驗的研究假說，不是預測；事件報告必須附同步行情與失效條件。

回滾：撤回本 PR 即可移除圖層；事件分類與來源核對仍可獨立運作。