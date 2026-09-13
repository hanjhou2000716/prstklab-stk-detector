# Telegram 訂閱入口

此 Worker 使用既有 Telegram Bot、Supabase 與發送流程。部署新版本後，依序完成一次性資料遷移與 webhook 設定：

1. 在 GitHub Actions 執行 `Migrate Telegram subscribers`。它只把 legacy 收件人及編輯者 `8869592162` 以 `ignore-duplicates` 寫入訂閱表，不發 Telegram，也不重新啟用已退訂帳號。
2. 將 `TELEGRAM_WEBHOOK_SECRET` 設為 Worker secret；不得寫入 repository。使用 `Configure Telegram subscription webhook`，並先在 repository variable 設定 `TELEGRAM_WEBHOOK_URL`，例如 `https://<worker-domain>/api/telegram-webhook`。
3. Worker 的 `TELEGRAM_SUBSCRIPTIONS_ENABLED` 維持 `true`。正式 Python workflow 會只讀取 `status=active` 的 private 訂閱；受控驗收 workflow 固定只送編輯者 `8869592162`。

私聊使用者按 `/start` 建立或恢復訂閱，`/stop` 停止後續正式速報。Webhook 必須帶 Telegram 的 secret-token header；沒有 secret 或不是 private chat 的請求不會改動訂閱資料。編輯者測試仍只允許伺服器固定的 `8869592162`，不接受一般使用者在請求中指定。
