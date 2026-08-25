# Source-health history contract

本 PR 補上 P0-28 所需的來源健康歷史資料契約。它是目前健康快照的加法欄位，
不改變即時 `status`、`event_scan` 或任何警報門檻。

## 公開欄位

`observability.history` 最多保存 7 天、168 個樣本，並提供 `24h` 與 `7d`
兩個聚合窗口。每個樣本只包含時間、計數、成功率、核對率與語意狀態，
不保存原始回應、Gmail 游標、收件者或 Secret。

健康狀態仍分開表示：

- `no_event_count`：來源成功掃描但本輪沒有事件。
- `failure_count`：來源掃描或解析失敗。
- `stale_count`：使用過期或快取資料。
- `parser_error_count`：解析器拒絕或解析失敗的次數。

沒有歷史來源時不會由目前快照自行複製資料；`history` 只有在 producer
傳入 `history_records` 時才會出現，避免把單次觀測誤稱為 24 小時趨勢。

## 驗證與回滾

- JSON Schema 限制 retention 24–168 小時、樣本最多 168 筆，且固定要求 24h／7d 窗口。
- 無效時間戳會被排除並計入 `invalid_sample_count`。
- 目標測試：`61 passed`（observability、source-health、artifact contract）。
- 回滾：撤回本 PR；既有即時 source-health 欄位與警報閘門不受影響。

此契約本身不宣稱已有 Railway／Pages 7 天歷史資料；完整外部歷史證據仍需
由部署環境提供持久化樣本後另行驗證。
