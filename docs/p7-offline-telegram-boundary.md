# P7：離線 E2E 的 Telegram mock boundary

`src.production_e2e` 的離線驗收不再讀取正式收件人設定。它使用明確的
mock delivery receipt，驗證 release gate、固定圖卡、caption 與 deep link，
同時保證不會向 Telegram 發送任何訊息。

正式 Bot／收件人設定仍由 `src.delivery_smoke_test --send` 的獨立流程驗證；
因此「離線測試可通過」不代表正式 Telegram 已送達，也不會把缺少 Secret
誤報成 renderer 或 release 失敗。
