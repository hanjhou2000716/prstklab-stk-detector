# Alert Contract 與生命週期

`src/alert_orchestrator.py` 是通知前的唯一、無副作用決策邊界。它把事件
資料送入既有的 `AlertEnvelope`、`alert_lifecycle`、`material_change` 與
`alert_budget`，再回傳可追溯的 JSON 決策；它不直接呼叫 Telegram 或外部
服務。

## 決策順序

1. 建立事件／通知識別與 release、snapshot provenance。
2. 依資產類別及方向反轉判斷 material change。
3. 由 Alert Budget 套用品質閘門、30 分鐘冷卻及事件／小時上限。
4. 由 lifecycle engine 產生 `pending_confirmation`、`confirmed`、
   `escalated`、`resolved` 或 `suppressed`。
5. 產生不超過 40 字的 caption，並驗證 `AlertEnvelope`。

`delivery_allowed=false` 時，事件仍保留在 Mini App／ledger 的上游資料中，
但不得進入正式發送器。缺少核對證據只可停在觀察／待核對，過期或延遲資料
則由品質閘門抑制。

## 回滾

移除本模組與測試即可回到各既有入口；既有 `alert_budget`、lifecycle 與
release gate 不需停用。正式切換前應以離線 fixture 驗證所有通知入口仍使用
相同 envelope。
