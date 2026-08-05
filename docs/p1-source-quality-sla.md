# P1 來源品質 SLA

`src.data_quality.score_source` 現在會把來源健康與行情新鮮度分開評分，並
保留可追溯的 SLA 欄位：

- `data_quality_score`：可用性、新鮮度、完整度、交叉核對、解析信心與延遲
  的加權分數。
- `last_success_at`：來源最近一次成功抓取時間，不以本輪失敗時間冒充成功。
- `consecutive_failures`：連續失敗次數；即使本輪內容看似 fresh，只要仍有連續
  失敗，`alert_eligible` 就會是 false。
- `reasons`：包含 `source_unavailable`、`quote_stale_or_missing`、
  `crosscheck_missing`、`consecutive_failures` 等可供 Mini App 顯示的原因。

來源仍可在分數達到顯示門檻時呈現，但不會因顯示可用而被誤用於高風險
Telegram 警報。成功抓取後由 adapter 將連續失敗歸零，恢復警報資格仍須
同時通過新鮮度與第二來源核對。
