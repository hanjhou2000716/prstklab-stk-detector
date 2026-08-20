# 單一收件人圖卡 Production Smoke（2026-08-20）

## Scope

本次只使用 workflow 明確指定的單一測試收件人，沒有使用正式群發名單，
也沒有修改任何 Secret。驗證目標是 renderer、Telegram `sendPhoto`、Mini
App URL 欄位與 Railway delivery receipt 的同一條 lineage。

## Evidence

- Actions run：[32366252888](https://github.com/hanjhou2000716/prstklab-stk-detector/actions/runs/32366252888)
- Workflow：`PRStK Notification`，`photo_test=true`
- Renderer：`1080×1350` PNG，非 fallback／非空白卡
- Telegram：`delivered=1`、`failed=0`、`recipient_count=1`
- Delivery mode：`photo`
- Release／snapshot：`photo-smoke-test`／`photo-smoke-test`
- Railway trace：`photo-smoke-90c34b7733fc4eaf`
- Railway callback：accepted
- Railway `/health`：HTTP 200；`delivery_status=delivered`；receipt trace 與
  last trace 相同；`receipt_matches_last_outbox=true`

## Safety boundary

這不是廣播測試，也不代表其他收件人都已完成可達性驗證。事件、研究與市場
高風險通知仍受 release gate、來源核對、freshness 與 fail-closed 規則限制。

## Remaining external gates

目前 Railway `/health` 仍顯示 GDELT `HTTP_429`、health callback `HTTP_403`
（GDELT 健康回報，不影響本次 delivery callback）、以及 Gmail
`configuration_missing`。這些狀態仍應保留為待外部設定／重驗證，不得被本次
Telegram 成功送達覆蓋。

## Rollback

本文件只記錄驗證，不改變 runtime 或通知邏輯；回滾此文件的 commit 即可。
