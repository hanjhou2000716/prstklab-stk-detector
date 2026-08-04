# P0-03：研究報表候選狀態契約

研究報表現在同時保存掃描狀態與候選狀態，避免把「掃描成功但沒有候選」誤報成「資料失敗」。

## 機器欄位

- `scan_state`: `complete`、`building` 或 `failed`
- `candidate_state`: `available`、`no_candidates`、`building` 或 `data_gap`
- `requested_records`、`complete_records`、`failed_records`
- `visible_candidates`：本輪實際可在 Mini App 顯示的候選數
- `candidates_definition`: 固定為 `visible_candidates`
- `formal_candidates`、`observation_candidates`
- `data_gap_counts`、`blocking_reason`

`candidates` 保留向後相容，但已明確定義為 `visible_candidates`。完整掃描零候選會是 `complete + no_candidates`；來源缺失或掃描失敗會是 `failed + data_gap`，兩者不可互換。

## 發布安全

研究載入器只會放行狀態與資料完整度允許的候選；過期、建檔中且未允許部分候選、或掃描失敗的來源不會把舊 CSV 候選帶入本輪發布。

## Rollback

回退本 PR 可恢復舊欄位輸出，但應暫停正式候選顯示並保留資料缺口。不得以刪除 `candidate_state` 或把 `data_gap` 改成 `no_candidates` 來繞過發布閘門。
