# P0 External source parsers

本 PR 將 FinancialJuice 與 Haojiao／Gooaye 的模板解析分開，並把 vendor
importance、原始標題、翻譯、分析與可能影響保留為有來源歸屬的欄位。Creator
內容的 claims 與 opinions 不混用，且 verification 預設為 `unverified`。

未知來源、缺標題或模板不符會輸出 DLQ-safe 的 `parse_status` 與
`failure_reason`；不會靜默丟棄或直接取得高風險通知資格。解析只在記憶體使用
郵件正文，回傳物件不含 raw body。

本 PR 尚未宣稱完成 Gmail Watch、事件聚類、release publication 或 Telegram
通知；那些必須等後續 cross-check 與 release gate PR。
