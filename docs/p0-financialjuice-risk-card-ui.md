# P0-13 FinancialJuice 風險卡證據

FinancialJuice 維持 `discovery`／外部快訊來源，不會取代官方核對，也不會把
`vendor_importance` 轉成 PRStK 風險等級。符合優先通知門檻的項目會沿用既有
「市場風險快訊」卡片，並在「系統分析資料」中顯示：

- 來源：FinancialJuice
- 來源重要度：`N / 10`
- PRStK Risk：事件本身的風險判定（預設仍為保守的 R2／觀察）
- Evidence：已完成來源核對或「等待第二來源」

此區只呈現可追溯證據，不新增獨立推播路徑、不繞過 release gate，也不把
供應商重要度當成高風險升級條件。缺少欄位時顯示「待核對」，維持 fail-closed。

## 驗證與回滾

UI contract 測試驗證上述欄位與來源／風險分離；撤回本 PR 即可移除新增的
證據列，既有市場風險快訊與 Telegram 發送流程不受影響。
