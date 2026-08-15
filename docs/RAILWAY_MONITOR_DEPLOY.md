# 部署 Railway 金十監測器

本服務只呼叫金十官方 MCP 的 `list_flash` 工具，不擷取網頁。它每兩分鐘讀取一次最新快訊，將已看過的事件 ID 寫入本機 SQLite，只有符合嚴格關鍵字範圍的事件才會以 HMAC 簽章觸發 GitHub。

GitHub 端會再次驗證簽章、去重、更新 Mini App，再送出 Telegram 快訊。因此 Railway 即使重啟，也不會繞過 GitHub 的安全規則。

## 1. 連接此 GitHub 儲存庫

本 PR 合併後，在既有 Railway Service：

1. 開啟 **Settings** → **Source** → **Connect Repo**。
2. 選取 `hanjhou2000716/prstklab-stk-detector`。
3. 將 **Root Directory** 設為 `railway-monitor`。
4. Railway 會使用此目錄內的 `Dockerfile`；不需要填 Build Command 或 Start Command。
5. 按 **Deploy**。

## 2. 保留既有四個 Variables

| Variable | 用途 |
|---|---|
| `JIN10_MCP_TOKEN` | 金十 MCP Token |
| `GITHUB_DISPATCH_TOKEN` | 僅限此 repository、`Contents: Read and write` 的 fine-grained PAT |
| `EXTERNAL_ALERT_SHARED_SECRET` | 與 GitHub Actions Secret 同一個高熵字串 |
| `GITHUB_REPOSITORY` | `hanjhou2000716/prstklab-stk-detector` |

可選設定：

| Variable | 預設值 | 說明 |
|---|---:|---|
| `JIN10_POLL_SECONDS` | `120` | 輪詢秒數，最低 60 秒 |
| `JIN10_FLASH_LIMIT` | `30` | 每次讀取筆數，範圍 1–100 |
| `JIN10_INITIAL_BACKFILL` | `false` | 第一次啟動只建立去重基線、不補送舊快訊；只有在確定要補送目前列表時才改 `true` |
| `JIN10_CATEGORY_COOLDOWN_SECONDS` | `1800` | 舊版相容設定；目前所有事件管線固定統一 30 分鐘，該變數不再覆蓋中央規則 |
| `MONITOR_STATE_PATH` | `/data/jin10-monitor.sqlite3` | SQLite 狀態檔路徑 |

## 3. 加上持久化 Volume（建議）

在 **Settings** → **Volumes** 新增一個 Volume，掛載路徑填 `/data`。這能讓 Railway 重啟後仍保留已看過的金十事件 ID。即使沒有 Volume，GitHub 的第二層事件鎖仍會防止重複推播。

## 4. 驗證

部署完成後：

1. 在 **Deployments** 開啟最新部署的 logs，應看到 `Health endpoint listening`，接著是 `Jin10 poll completed`。
2. 若 Token 或 MCP 權限有問題，logs 會顯示重試訊息，但不會洩漏 Token。
3. Railway 建立公開 Domain 後，可開啟 `/health`。端點維持 `status: "ok"` 供平台存活檢查，並附上不含機密的 `jin10`／`gdelt` 狀態、最近成功時間、資料筆數與錯誤類型，方便判斷「服務存活」與「來源暫時失敗」的差異。另查看 `monitor.heartbeat_status`：`healthy` 代表最近輪詢已完成，`stale` 代表 HTTP 仍可回應但輪詢超過逾時門檻，應檢查 Deploy Logs 或重啟服務；`starting` 代表尚未完成第一輪。
4. 真正觸發時，GitHub Actions 會出現 **Emergency market alert**；Mini App 會顯示已核對外部快訊，而 Telegram 僅顯示 30 字內摘要。

## 安全邊界

- 不將 Token、共享密鑰、原始授權 Header 寫入程式碼、Git 或 Mini App。
- 首次啟動預設不補發歷史快訊，避免大量舊訊息。
- 只轉發 Fed、宏觀數據、政策／關稅、戰爭衝突、半導體巨頭、極端市場事件，以及具地緣／供應／大幅變動背景的能源快訊。例行油價評論不轉發；所有內容維持公開市場教育與風險提醒，不構成投資建議。
## Phase 3 GDELT discovery settings

## Classifier packaging gate

Keep the Railway service Root Directory set to `railway-monitor`. The directory
contains `shared_event_classifier.py`, a generated copy of the canonical
`src/event_classifier.py`; CI runs
`python scripts/sync_railway_shared_classifier.py --check` to block drift.
After each deploy, inspect `/health` and require
`runtime.classifier_mode=repository-shared`. `standalone-bundled` or
`unavailable` is diagnostic-only and must remain fail-closed for dispatch.

## Health callback configuration

Use the canonical names below in the Railway service and in the GitHub Actions
environment that publishes delivery health. Never place the values in Git,
logs, artifacts, or public release data.

| Variable | Where | Required behavior |
| --- | --- | --- |
| `RAILWAY_STATUS_URL` | Railway / Actions | The HTTPS `/health` or signed status callback endpoint for the deployed service |
| `RAILWAY_STATUS_SHARED_SECRET` | Railway / Actions secret | One identical secret for HMAC verification; `canonical_name_present` must be true |
| `DELIVERY_STATUS_SHARED_SECRET` | Railway compatibility only | Legacy name retained during migration; do not add new integrations with it |

After changing either canonical variable, redeploy the Railway service and
verify that `/health` reports `runtime_config.canonical_name_present=true`.
An HTTP 403 from the callback means authentication or endpoint configuration
has not been accepted; it is not a healthy delivery and must remain visible as
`permission_denied` without restarting the monitor or sending a high-risk
notification.

The Railway monitor polls the public GDELT DOC endpoint every 15 minutes by default. A successful response is cached for 15 minutes. During a temporary failure or rate limit, the latest successful cache may be used for up to 120 minutes and is labelled with its original fetch time. Only discovery articles from the last 45 minutes are considered.

Optional Railway variables:

| Variable | Default | Meaning |
| --- | --- | --- |
| `GDELT_DISCOVERY_ENABLED` | `true` | Set `false` to pause GDELT discovery while official monitors continue. |
| `GDELT_POLL_SECONDS` | `900` | Poll interval; values below 900 seconds are clamped to 900 to respect the public endpoint. |
| `GDELT_CACHE_MINUTES` | `15` | Successful response cache window. |
| `GDELT_STALE_CACHE_MINUTES` | `120` | Maximum age of a success cache used after a transient failure. |
| `GDELT_MAX_FRESH_AGE_MINUTES` | `45` | Maximum publication age for a discovery candidate. |
| `GDELT_QUERY` | built-in query | Optional URL-encoded query override for discovery keywords. |

GDELT remains a discovery layer. A candidate needs at least two trusted publisher domains sharing the same concrete entity/place/action intersection. A black-swan or major-disaster candidate with market synchronization may produce a **警戒** alert; only a matching first-party official confirmation plus market synchronization may produce a **高風險** alert. The first successful poll establishes a baseline and does not replay historical headlines. SQLite persistence continues to provide event deduplication and cooldowns.

Current delivery policy: all event paths share a 30-minute durable cooldown. War and armed-conflict aliases are treated as black-swan candidates, but GDELT alone cannot deliver them; an official source and related-market synchronization are still required. The multilingual alias database is maintained in `config/event_keywords.json`.
