# Railway Gmail／GDELT 執行期韌性修復

## 問題與根因

- Gmail Pub/Sub 推送的必要驗證是 `Authorization` OIDC JWT 的 `aud` claim；`x-goog-authenticated-audience` 是可選標頭，不能視為每次推送都存在。舊邏輯在缺少該標頭時把合法推送誤判為 `GmailIngressError`。
- GDELT 的 429 冷卻原本只保存在 Railway 程序記憶體。程序重啟後會立即再次請求，可能形成重複限流。

## 修復行為

- Gmail 仍維持 service-account／JWT 驗證與設定 audience 檢查；只有在可選 audience 標頭實際存在且不一致時拒絕請求。
- Gmail ingress 將可診斷的安全錯誤碼寫入來源健康狀態，不記錄 token、郵件內容或其他敏感資料。
- GDELT 429 會寫入短期 SQLite cache，保存冷卻截止時間與失敗次數。Railway 重啟後會恢復冷卻，期間只使用符合政策的最近成功快取，不發出新的請求。
- 成功抓取後清除已過期的 GDELT 冷卻狀態；仍維持 bounded backoff、最多兩小時 stale fallback 與 fail-closed 高風險通知規則。

## 驗證

- `tests/test_railway_gmail_gateway.py`：沒有非標準 audience 標頭但帶有合法 Pub/Sub OIDC 的推送可通過 ingress。
- `tests/test_railway_monitor.py`：429 冷卻在模擬程序重啟後仍被恢復，且不會再次呼叫 GDELT。
- 針對性回歸：`21 passed, 88 deselected`。
- 外部唯讀驗證在修復部署前仍記錄 `GDELT HTTP_429` 與 `GmailIngressError`；合併部署後需重新執行外部 acceptance workflow，才能把此兩項由 `NEEDS_REVERIFY` 轉為客觀通過或保留失敗。

## 回滾

撤回本 PR 即可回到前一版本；SQLite cache 中的冷卻資料不影響事件帳本或已發布 release。若需立即停用 GDELT，沿用現有來源 feature flag，不得改用未核對資料觸發警報。
