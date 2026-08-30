# 舊圖卡驗收入口（已退役）

本文件保留作為歷史說明。現行正式驗收已改為
`.github/workflows/production-acceptance-photo.yml` 的 release-gated 純文字
流程；非 Creator 路徑不得呼叫 Telegram photo API。Creator 圖片僅能由已核驗的
Gmail 原始附件路徑送出。

舊版 workflow 不再產生或上傳 PNG，只接受一次輸入的單一 `test_chat_id`，且必須
明確選擇 `confirm_production=true`。

執行順序固定為：

1. 驗證 checkout 內的 ready release manifest、artifact hash 與 Pages 公開版本一致。
2. 以該 release 的 `release_id`、`market_snapshot_id` 產生一則 canonical text。
3. 使用同一 release/snapshot/observation lineage 發送一則 `sendMessage`。
4. 將不含 token、原始 chat ID 或照片內容的 delivery receipt 寫回 Railway。

只要 manifest、Pages 或 renderer 任一項失敗，流程會在 Telegram 之前停止；不會
發送黑卡，也不會改用舊 release。此 workflow 不應加入排程，也不應以正式廣播名單
取代 `test_chat_id`。

## 驗收證據

成功時需同時保存：Actions run URL、Telegram message ID（僅存於受控平台）、
release/snapshot/observation ID、Railway receipt trace，以及 Mini App deep-link
可開啟畫面。若 Railway secret 或 Gmail/GDELT 外部來源尚未配置，應標示
`NEEDS_REVERIFY`，不得把離線測試當成 production acceptance。

