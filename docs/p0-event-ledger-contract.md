# P0 事件帳本發布契約

事件帳本是通知決策的輸入，不再只由檔案存在與否判斷可發布。每次 release
建立 manifest 時，`event-ledger.json` 會先通過
`schemas/event-ledger.schema.json` 與 `src/artifact_contract.py` 的跨欄位檢查。

## 必要檢查

- 根節點必須包含 `schema_version`、`retention_days` 與 `events`。
- 每個事件的 map key 必須等於 `canonical_key`，避免去重索引與內容分離。
- `source_url` 與 `verified_sources` 必須是可追溯的 HTTPS URL；
  `source_domain` 必須與主要來源 URL 的網域一致。
- `updated_at` 不得早於 `first_discovered_at`。`last_reminded_at` 是送達冷卻
  的獨立欄位，不會被誤當成事件內容更新時間。
- 若事件本身帶有 `snapshot_id`，必須與 manifest 的 `event_snapshot_id` 相符。

任何一項失敗都會使 manifest 成為 `invalid`，後續 release gate 不會放行
Telegram 推播。事件檔案仍可保留在 Pages 供診斷，但不會被當作已發布的完整
事件快照。

## 測試與回滾

`tests/test_artifact_contract.py` 覆蓋有效帳本、網域不一致與時間倒序案例；
`tests/test_release_manifest.py` 覆蓋空事件帳本、缺檔與 hash 篡改。若發布失敗，
保留上一個 `ready` manifest，不推送新 release；修正資料後重新執行 manifest
建置即可恢復。
