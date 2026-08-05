# P3：市場 regime 與跨資產風險

`src/market_regime.py` 將趨勢、波動、信用等公開因子拆成可讀的貢獻，輸出 Risk-on、Neutral、Risk-off、Stress 或 Crisis；因子不足時會保留 `evidence_sufficient=false`，不把缺資料當作低風險。

`src/cross_asset_risk.py` 提供完整窗口的 rolling correlation，以及股市下跌、VIX 上升、美元急升等同步條件。至少兩個獨立條件成立才標為 `contagion=true`，並只描述已觀測的同步現象，不預測未來行情。
