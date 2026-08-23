# 受控單一收件人圖卡驗證

`.github/workflows/production-acceptance-photo.yml` 是唯一用於正式圖卡驗收的
手動 workflow。它不會使用 `TELEGRAM_CHAT_IDS` 廣播名單，而只接受一次輸入的
單一 `test_chat_id`，且必須明確選擇 `confirm_production=true`。

執行順序固定為：

1. 驗證 checkout 內的 ready release manifest、artifact hash 與 Pages 公開版本一致。
2. 以該 release 的 `release_id`、`market_snapshot_id` 產生 1080×1350 PNG。
3. 使用同一 release/snapshot/observation lineage 發送一則 `sendPhoto`。
4. 將不含 token、原始 chat ID 或照片內容的 delivery receipt 寫回 Railway。

只要 manifest、Pages 或 renderer 任一項失敗，流程會在 Telegram 之前停止；不會
發送黑卡，也不會改用舊 release。此 workflow 不應加入排程，也不應以正式廣播名單
取代 `test_chat_id`。

## 驗收證據

成功時需同時保存：Actions run URL、Telegram message ID（僅存於受控平台）、
release/snapshot/observation ID、Railway receipt trace，以及 Mini App deep-link
可開啟畫面。若 Railway secret 或 Gmail/GDELT 外部來源尚未配置，應標示
`NEEDS_REVERIFY`，不得把離線測試當成 production acceptance。

