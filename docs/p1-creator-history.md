# P1-03 Creator history backend

`CreatorHistoryStore` 使用私有 SQLite 保存已正規化的 Creator episode snapshot，
以內容雜湊去重並保留 episode 演化。只接受 `public_safe=true` 的欄位，原始
email body、附件、私人 URL 與本機路徑會直接拒絕；因此這個資料庫不能替代
公開 release，也不能把評論升格成市場事實。

歷史保留至少 30 天，`list_recent` 可供後端顯示每位 Creator 最近內容；公共
artifact 仍由 release contract 控制最多展示數量。Pipeline 可傳入
`history_store` 進行持久化，未提供時保持純函式離線模式。

回滾：撤回本 PR 即可停用歷史寫入；既有 creator release 與核心市場資料不受影響。
