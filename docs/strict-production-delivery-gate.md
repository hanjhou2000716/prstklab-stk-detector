# Strict production delivery gate

正式 Pages 部署、定時報告、官方事件與緊急事件通知都使用
`python -m src.release_gate --require-production-research`。

這個旗標把「可讀的回滾快照」和「可對外推播的正式發布」分開：

- 回滾／離線工具仍可讀取舊版或 legacy research artifact。
- 正式交付必須是 `scan_mode=production`、`scan_scope=full`，並通過研究血統、完整 universe、來源計數與候選狀態驗證。
- manifest 必須標示 `research_freshness=fresh`；`stale`、`unknown` 或缺漏一律 fail closed。
- gate 失敗時不送 Telegram，也不把失敗的 release 當成已發布版本。

## 驗證

`tests/test_release_gate.py` 覆蓋 strict mode 對 legacy research 與 stale freshness marker 的阻擋；Pages workflow contract test 確認部署使用 strict flag。

## 回滾

若需要暫時回到上一個已驗證版本，應回復 `data-release` 上一個 `status=ready` 且
`research_freshness=fresh` 的 immutable release；不可移除 strict flag，也不可把 legacy
或 bounded artifact 標成正式可推播版本。
