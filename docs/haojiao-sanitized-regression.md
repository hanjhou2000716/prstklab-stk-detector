# 財經皓角 sanitized 回歸 fixture

`tests/fixtures/haojiao-20260821-sanitized.json` 是依 2026-08-21
早晨公開節目摘要建立的最小回歸資料。它只保留主題、事實、觀點、風險與
公開時間，沒有保存寄件者、Gmail message ID、原始郵件、附件或私人 URL。

測試會把這份 fixture 送入 `src.creator_source_adapters.parse_creator_template`，
確認它能產生 `public_safe=true` 的財經皓角洞察，同時維持
`verification_state=unverified`。因此它只能作為研究觀察，不能單獨升級或觸發
高風險 Telegram 快訊；仍須通過官方來源與相關市場同步核對。

這份 fixture 不會被排程流程自動發布到 `site/data`。Railway Gmail/PubSub
尚未完成設定時，正式來源仍維持 `configuration_missing`，避免把本機回歸資料
誤當成即時郵件。

## 回滾

刪除本 fixture、測試與本文件即可回復；不影響正式 Creator release 或任何
Telegram 收件人。
