# FinancialJuice 高重要度投遞政策

目前正式政策將 FinancialJuice 供應商分數與 PRStK 風險分數分開處理：

- `9/10` 以上才進入 `fj_priority` 獨立投遞政策。
- `8/10` 以下（以及 `8.x/10`）不具備優先資格，沿用一般 `material_event` 判定。
- 缺少或無法解析分數不得取得高重要度資格。

高重要度事件仍必須同時具備可信來源身份、完整公開事實、穩定
`canonical_fact_key`、來源發布時間，以及不超過 30 分鐘的 `source_published_at`
新鮮度（最多容忍五分鐘未來時鐘偏差）。它可以不等待市場同步、PRStK 風險升級、
一般事件冷卻或一般事件預算，但不能繞過 release gate、EventLedger、收件人
設定、內容品質及既有投遞結果核對。

Gmail 同步、即時監控、排程候選與 sender 必須讀取同一 `delivery_policy`。同步
只保存公開安全的診斷；`notify=false` 不取得正式 claim、不建立 Telegram attempt、
也不更新成功投遞基準。相同事實的重播可以重新喚醒尚未完成的後續處理，但最後
仍由既有 ledger／receipt 保證最多一次有效投遞。

來源健康資料中的 `importance_gte_9_*` 是目前語義；舊的 `importance_gte_8_*`
欄位只作讀取相容 alias，內容同樣只計入 `9/10` 以上，避免舊客戶端重新打開
已停用的 8/10 優先路徑。
