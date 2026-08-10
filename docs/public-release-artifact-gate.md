# 公開 Release Artifact 驗證

Pages deploy 後，`src.release_gate` 不只讀取
`data/release-manifest.json`，還會依 manifest 的 `artifact_paths` 下載
`market.json`、`research-report.json` 與 `event-ledger.json`。

每份遠端內容在解析前都會以 manifest 的 SHA-256 hash 驗證；三份 JSON 解析
成功後，再以同一份 manifest 執行 release contract、snapshot ID 與 event
ledger 驗證。遠端 artifact 缺失、跨網域、hash 不符、JSON 損壞或 snapshot
不一致時，Pages release gate 會維持封鎖，通知流程不得繼續。

驗證請求只接受與公開 Pages 相同的 HTTPS host，並使用 cache-busting query
與 no-cache headers，避免 CDN 尚未傳播完成時誤判為可發布。

## 測試與回滾

- `tests/test_release_gate.py` 覆蓋 propagation retry、遠端 hash mismatch、
  snapshot mismatch、語意驗證及本機 artifact tamper。
- 若公開 artifact 驗證失敗，保留上一個 `status=ready` release，不刪除或改寫
  目前公開資料。修復後重新部署同一 release 或回復上一個 manifest 即可。
- 這項驗證不會接觸 Secret、不會發送 Telegram，也不會修改 data-release。
