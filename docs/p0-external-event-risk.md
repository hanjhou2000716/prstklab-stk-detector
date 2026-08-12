# P0 External event risk engine

本 PR 將 FinancialJuice／Jin10／GDELT／可信媒體／官方觀測聚成同一事件，並
把人物、動作、地點、事件類型與時間窗納入 identity。Haojiao／Gooaye 等
EDITORIAL 內容只保留為 Creator Intelligence，不可作為事件核對來源。

## R0–R4

- R0：非重大或未分類。
- R1：編輯／創作者內容，不是事件證據。
- R2：單一來源觀察，等待交叉核對。
- R3：官方確認或至少兩個獨立證據來源。
- R4：官方確認且至少一個相關市場同步確認。

FinancialJuice 10/10 只是 vendor metadata，不能單獨升級為 R4。所有未達門檻
的結果都保留 `pending` 原因，不靜默丟棄。
