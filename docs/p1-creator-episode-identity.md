# P1 Creator episode identity

Creator insight 正規化會產生穩定的 `episode_key`。若來源已提供 episode key，直接保留；否則以來源、episode/message ID、標題與發布日期建立 SHA-256 摘要。原始 email body、附件內容與私人 URL 不會參與公開輸出。

此識別可跨 Gmail Pub/Sub 重送、history cursor 重播、Railway 重啟與 parser retry 使用，作為單集 Creator 通知的去重鍵；不會把 Creator 觀點提升為事件證據，也不會繞過 release gate 或風險核對。
