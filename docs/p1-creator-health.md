# P1-05 Creator health observability

`build_creator_health` 將 Gmail watch、parser/DLQ、release、media 與 delivery
的狀態整理成單一、可供 Railway／Mini App 使用的健康契約。`healthy`、
`no_new_content`、`stale`、`parse_failed`、`media_degraded`、
`configuration_missing` 與 `failed` 分開處理，不會把「沒有新內容」誤報成故障。

輸出只保留 watch expiration、history ID、時間戳與 DLQ 數量等非敏感欄位；
token、原始郵件、附件與完整 response 永遠不會進入 health payload。

回滾：撤回本 PR 即可停用聚合器；Railway 現有 `/health` 行為不受破壞。
