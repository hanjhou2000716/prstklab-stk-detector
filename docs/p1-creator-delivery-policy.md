# P1 Creator delivery policy

Creator 每集使用 `creator:{episode_key}:{notification_type}` 作唯一通知鍵。已成功或部分送達的同一鍵不可因 Gmail/PubSub 重試、Railway 重啟或 parser 重跑再次推送。

通知必須先通過 release gate 且 artifact 為 `public_safe`。私有摘要圖無法取得時，狀態明確為 `media_degraded`，改用受限文字模式；不會送出黑色、空白或未驗證圖卡。這個降級不會提升風險等級，也不會繞過 Telegram 收件人隔離與 delivery receipt。
