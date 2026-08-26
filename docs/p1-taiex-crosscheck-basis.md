# P1-05 TAIEX／TAIFEX 交叉核對基準

TAIEX（現貨加權指數）與 TAIFEX TXF（台指期貨）是不同的金融工具，兩者
的點位不能直接相除或比較價差。來源政策現在只把 TXF 作為獨立的方向與
時間證據：

- 顯示價格與漲跌數值由 TWSE 現貨觀測擁有。
- 兩筆觀測必須有變動方向與可比較時間；時間差超過政策門檻時維持未核對。
- 同向只能表示「方向已由第二來源核對」，不代表兩個點位相等。
- 反向或缺資料時，仍保留現貨卡片，但不得取得高風險／即時價格警報資格。

`src.source_policy.evaluate_crosscheck("TAIEX", ...)` 會回傳
`comparison_basis=direction_only`、`price_comparable=false`，避免通用點位
比較器將現貨與期貨誤判為價差異常。其他同一資產的來源仍使用價格與時間
對齊規則。

每筆行情的 `quote_provenance` 也會帶出 `crosscheck_policy`（主來源、第二
來源、時間／價格門檻）與 `comparison_basis`。因此 Mini App、release audit
及警報決策讀取的是同一份版本化政策；`TPEx` 等大小寫變體也會正確套用
政策，不會因標籤格式而退回未知來源。

## 回滾

撤回本次變更即可恢復原來源政策；不會刪除既有行情或事件資料，也不會改變
TWSE 現貨顯示值。
