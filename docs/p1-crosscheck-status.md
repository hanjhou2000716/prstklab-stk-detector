# P1 跨來源核對狀態

市場卡片的 `cross_checked` 是機器可判斷的布林欄位，`crosscheck_status` 是
顯示／診斷文字，兩者不能只靠單一語系字串互相推導。核對邏輯現在接受下列
標準狀態：

- `confirmed`
- `verified`
- `cross_checked`／`cross-checked`
- `已交叉核對`、`已核對`、`交叉核對`

其他值（例如 `pending`、`secondary_unavailable`、`discrepancy`）一律維持
未核對。這讓英文來源、繁中 UI 與歷史快照能共用同一個安全判斷，避免因
i18n／字元編碼差異錯誤放行警報。
