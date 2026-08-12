# P0 Creator release contract

Creator Intelligence 是核心市場 release 的附加 artifact，不會覆寫市場、研究或事件資料。每份 artifact 都綁定 `parent_release_id`、`market_snapshot_id` 與 `event_snapshot_id`，並保留自己的 hash。

若 claims/opinions、驗證狀態或私有欄位不符合契約，artifact 狀態為 `unavailable`；父 release 仍可正常發布，Mini App 顯示來源不可用而不是混用新舊版本。

## Rollback

刪除 creator artifact 的發布指標即可回退到 parent release；核心市場、研究與事件 snapshot 不受影響。
