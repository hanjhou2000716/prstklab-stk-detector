# 研究發布契約與不變量

本文件記錄研究報表在加入 release manifest 前必須通過的資料語意檢查。目的
是把「掃描完成但仍有失敗／缺口」與「本輪資料不足」分開，避免 Mini App 或
通知流程把不完整結果當成正式研究資料。

## 狀態規則

- `scan_state=complete` 只代表要求的研究宇宙已完成；此狀態不得同時有
  `failed_records>0`、`data_gap_counts>0`、未完成的
  `requested_records/complete_records`，或 `candidate_state` 為
  `building`、`data_gap`、`data_unavailable`、`failed`。
- 部分完成但可用的已完成記錄使用 `scan_state=building` 與
  `candidate_state=available_from_completed_records`。
- 沒有合法候選且資料完整使用 `candidate_state=no_candidates`。
- 資料不足、來源失敗或歷史建檔未完成使用 `candidate_state=data_gap`、
  `data_unavailable` 或 `failed`，不可解釋成沒有候選。
- `formal_candidates` 與 `observation_candidates` 必須不大於
  `visible_candidates`（舊版 `candidates` 仍等同 `visible_candidates`）。

## 生產發布閘門

研究報表只有在同時具備以下條件時才可標示 `publish_eligible=true`：

1. `scan_mode=production`。
2. `scan_scope=full`。
3. 各來源通過上述完成／候選狀態檢查。

`production_eligible=true` 另外必須同時滿足 `publish_eligible=true`，且不得
使用 `research_fallback_used=true`。任何違反都會使 release audit 失敗，並
維持上一個可用版本。

## 相容與回滾

`data_gap_counts` 可是單一非負整數，也可為依來源分類的非負整數物件。舊版
摘要若宣稱有正式候選、但發布的候選列為空，release normalizer 會將計數歸零、
標記 `scan_state=building`／`candidate_state=data_gap`，並留下
`normalization_notes`；不會捏造候選。若契約仍無法通過，manifest 保持
`status=invalid`，Pages 使用上一個成功 release。

## 驗證與回滾

- 單元測試：`tests/test_artifact_contract.py`、`tests/test_release_manifest.py`。
- 若新契約造成既有資料無法發布，回滾本 PR 即可恢復原驗證器；不會修改原始
  行情、財報或事件資料。
- 發布前應檢查 manifest 的 `validation_errors` 與
  `normalization_notes`，不可用人工覆寫方式略過閘門。
