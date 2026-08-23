# Gmail Watch 自動建立與續期

Railway 啟動時會檢查持久化的 Gmail Watch 租約。若沒有租約，或距離
`watch_expiration` 不足 `GMAIL_WATCH_RENEWAL_MARGIN_HOURS`（預設 6 小時），
服務會以 OAuth refresh token 取得短期 access token，呼叫 Gmail
`users.watch`，再把新的 expiration 與 history cursor 寫入
`GMAIL_STATE_PATH` 的 SQLite cursor。租約仍有效時不會重複呼叫 Gmail。

必要設定：

- `GMAIL_WATCH_TOPIC`
- `GMAIL_WATCH_LABEL_IDS`
- `GMAIL_OAUTH_STATE=configured`
- `GMAIL_PUBSUB_AUDIENCE`
- `GMAIL_PUBSUB_SERVICE_ACCOUNT`
- `GMAIL_OAUTH_CLIENT_ID`
- `GMAIL_OAUTH_CLIENT_SECRET`
- `GMAIL_REFRESH_TOKEN`

可選設定：

- `GMAIL_WATCH_RENEWAL_MARGIN_HOURS`（預設 `6`）
- `GMAIL_WATCH_RETRY_COOLDOWN_MINUTES`（預設 `60`）
- `GMAIL_WATCH_TIMEOUT_SECONDS`（預設 `15`）

OAuth client secret、refresh token 與 access token 絕不寫入 log、公開資料或
health payload。health 只回報 `healthy`、`stale`、`failed` 或
`configuration_missing`，以及脫敏錯誤類別。續期失敗不會讓 Railway worker
停止；服務會保持可探測，下一次啟動會再次嘗試。失敗期間不得把 Gmail
事件視為已接收，並應在來源健康頁顯示 Watch 未就緒。

若 Gmail 回傳權限或設定錯誤（例如 HTTP 403），系統會把脫敏錯誤與時間寫入
持久化 cursor，並在 cooldown 期間停止重複呼叫 `users.watch`；健康頁仍維持
`watch_status=failed`，所以不會把失敗誤判成「沒有郵件」。可用
`GMAIL_WATCH_RETRY_COOLDOWN_MINUTES` 調整重試間隔，手動 `force` 驗證仍可立即
重試。成功建立 Watch 後會清除上一個錯誤狀態。

Railway volume 必須掛載到 `GMAIL_STATE_PATH`（正式環境預設
`/data/gmail-ingress.sqlite3`），否則每次重啟都會遺失租約並重新建立 Watch。
SQLite migration 會保留既有 cursor，並新增續期時間與脫敏錯誤欄位。

本機驗證：

```text
python -m pytest -q --basetemp=.tmp-gmail-watch-tests \
  tests/test_railway_gmail_gateway.py tests/test_railway_gmail_runtime.py
```

測試使用假的 transport，不會呼叫 Gmail，也不會對正式信箱發送郵件。

## HTTP 403 權限排查

`http_403` 不是「本輪沒有郵件」，而是 Gmail `users.watch` 尚未取得必要
的 Pub/Sub 授權。請在與 `GMAIL_WATCH_TOPIC` 相同的 Google Cloud project
中確認：

1. Gmail API 已啟用，且 Topic 存在。
2. 將 Gmail API service agent
   `service-${PROJECT_NUMBER}@gcp-sa-gmail.iam.gserviceaccount.com` 對該
   Topic 授予 `roles/pubsub.publisher`（只授予 Topic 層級，不要擴大到整個
   project）。
3. `GMAIL_WATCH_TOPIC` 使用完整資源名稱
   `projects/<project-id>/topics/<topic-id>`。
4. OAuth refresh token 所屬帳戶與 Watch 目標信箱一致，且 OAuth scope 包含
   `https://www.googleapis.com/auth/gmail.readonly` 或更高權限的 Gmail scope。
5. 重新執行一次受控的 `force` renewal，確認 `/health` 顯示
   `watch_status=healthy`、新的 expiration 與 history cursor；不要把 token、
   message ID 或郵件內容寫入 log。

若權限尚未完成，維持 `watch_status=failed` 並停止重複重試；Railway 仍可繼續
執行其他來源輪詢。只有看到一次成功 renewal 與一次已驗證的 Pub/Sub cursor
後，才可把 Gmail ingress 標記為 production／允許進入 Creator 或
FinancialJuice 發布鏈。`roles/pubsub.publisher` 的授予屬於操作員管理的 IAM
變更，不由程式自動申請或繞過核准。
