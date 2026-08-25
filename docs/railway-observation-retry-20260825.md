# Railway 外部觀測匯出重試契約

`src.railway_observation_client.load_railway_observations` 對 Railway 的公開安全觀測匯出端點採用最多兩次請求：

- `429` 與 `5xx` 是可重試的暫時性失敗；若回應提供 `Retry-After`，會遵守該值並將等待時間限制在 5 秒內。
- 連線／傳輸例外可重試一次；JSON 形狀錯誤不會被重試成為成功資料。
- `401`、`403` 與其他 `4xx` 不重試，維持 fail-closed，避免把權限錯誤變成重試風暴。
- 健康結果保留 `attempts`、`retry_count`、`retryable` 與非敏感 `reason`，方便來源健康卡與 release audit 追蹤。
- 即使重試後仍失敗，排程仍可保留本地已審核觀測；失敗的 Railway 來源不可產生高風險事件或虛構行情。

## 驗證證據

- `tests/test_railway_observation_client.py` 覆蓋 `429` 遵守 `Retry-After`、`403` 不重試與既有資料清理契約。
- targeted Railway／排程／外部 acceptance：31 passed。
- 全量 pytest（隔離 basetemp）：1421 passed。
- Ruff、Mypy（client）、compileall 與 `git diff --check` 通過。

## 回滾

撤回本 PR 即可恢復單次 Railway 匯出請求；不涉及資料庫 migration、Secret 或公開 release 格式。
