# P1-06 Creator runtime configuration

`CreatorRuntimeConfig` 統一 Gmail watch、Pub/Sub 驗證、媒體儲存與 dispatch
設定。啟動前可依模式檢查一般 watch、OAuth 或 dispatch 必要欄位；健康輸出只
列出缺少的變數名稱與 label 數量，不會把 secret 值寫入 log 或 JSON。

OAuth 與 dispatch secret 預設為 optional，只有真正啟用對應 runtime path 才以
`require_oauth=true` 或 `require_dispatch=true` 強制檢查，避免沒有設定時把
Creator 來源誤報為市場風險。

回滾：撤回本 PR 即可回到既有 `GmailWatchConfig`；不會改動任何 secret。
