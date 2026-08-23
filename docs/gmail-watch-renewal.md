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
- `GMAIL_WATCH_TIMEOUT_SECONDS`（預設 `15`）

OAuth client secret、refresh token 與 access token 絕不寫入 log、公開資料或
health payload。health 只回報 `healthy`、`stale`、`failed` 或
`configuration_missing`，以及脫敏錯誤類別。續期失敗不會讓 Railway worker
停止；服務會保持可探測，下一次啟動會再次嘗試。失敗期間不得把 Gmail
事件視為已接收，並應在來源健康頁顯示 Watch 未就緒。

Railway volume 必須掛載到 `GMAIL_STATE_PATH`（正式環境預設
`/data/gmail-ingress.sqlite3`），否則每次重啟都會遺失租約並重新建立 Watch。
SQLite migration 會保留既有 cursor，並新增續期時間與脫敏錯誤欄位。

本機驗證：

```text
python -m pytest -q --basetemp=.tmp-gmail-watch-tests \
  tests/test_railway_gmail_gateway.py tests/test_railway_gmail_runtime.py
```

測試使用假的 transport，不會呼叫 Gmail，也不會對正式信箱發送郵件。
