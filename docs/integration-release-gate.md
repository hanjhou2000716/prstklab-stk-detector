# 整合發布閘門

`src/integration_release.py` 是收集、研究與推播之間的最後一層整合檢查。它會同時呼叫 artifact schema／跨欄位驗證，並拒絕失敗的事件來源健康狀態；若發布 stale 事件，必須在輸入明確設定 `allow_stale_publish=true`。只有 `allowed=true` 才能進入既有 `release_gate.py` 的公開網址驗證與 Telegram delivery。
