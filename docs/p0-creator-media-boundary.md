# P0 Creator media boundary

創作者郵件中的摘要圖或音訊只在私有儲存範圍處理。邊界會檢查檔名、MIME、magic bytes、大小上限與 SHA-256；失敗時標記 `unavailable`，不會把附件內容、路徑或私有 URL 寫入公開 insight、release manifest、Mini App 或 Telegram。

公開資料只可攜帶 `media_id`、`mime_type`、`byte_size`、`sha256`、`availability` 與 `storage_scope=private`。任何驗證錯誤均 fail closed，並保留可供私有稽核的錯誤類別。

## Rollback

移除媒體摘要的 pipeline 綁定即可回到只有文字 claims/opinions 的 creator insight；既有公開事件與市場資料不受影響。
