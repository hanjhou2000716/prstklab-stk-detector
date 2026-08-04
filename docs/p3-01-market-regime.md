# P3-01：Market Regime Engine

`evaluate_regime()` 接收已正規化為 -1 到 +1 的公開因子：指數趨勢、市場寬度、波動率、信用、利率、美元、黃金、油價與加密資產。每個因子依權重計算貢獻，輸出：

- `Risk-on`
- `Neutral`
- `Risk-off`
- `Stress`
- `Crisis`

缺少資料會列在 `missing_factors`，資料品質為 complete／partial／failed。部分資料不會被當成正常市場，也不會自動觸發高風險通知；這是研究狀態，不是買賣指示。

回滾：撤回本 PR 即可移除 regime 計算器；既有 VIX 與事件警報不受影響。