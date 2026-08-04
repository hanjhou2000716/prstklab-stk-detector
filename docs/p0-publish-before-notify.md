# P0-05：發布成功後才推播

通知工作流現在採兩階段流程：

1. 建立市場 snapshot、研究資料與事件資料。
2. 產生 `release-manifest.json`，執行 schema／invariant 與 SHA-256 檢核。
3. 發布不可變檔案並部署 GitHub Pages。
4. 以 `src.release_gate` 核對本地與公開網址的 `release_id`、市場 `snapshot_id` 及所有 artifact hash。
5. 只有 gate 通過才呼叫 Telegram；未通過會輸出 `release_gate_blocked`，不發送、不建立事件冷卻鎖。
6. 成功後以 `trace_id`、`release_id`、`snapshot_id` 建立 Railway delivery receipt。

排程速報使用 `src.scheduled_delivery` 的 `--prepare-only`／`--send-only`。這避免
「先送舊資料、後發布新資料」或將新市場資料與舊研究資料混在同一則通知中。公開
manifest 不可讀、狀態不是 `ready`、hash 不符、snapshot 不一致或 Pages 尚未反映
該 release 時，系統採 fail closed，Mini App 仍可顯示資料不完整原因。
