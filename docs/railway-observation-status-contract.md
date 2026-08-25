# Railway 外部觀測狀態契約

`src.external_observation_input.external_source_health_from_remote` 是
Railway `/external-observations` 回應進入公開 release 前的唯一狀態映射點。

| Railway 回傳 | 公開狀態 | 是否成功掃描 | 說明 |
|---|---|---:|---|
| `ready`、`healthy`、`ok`、`success` | `healthy`（有資料）／`no_event`（空結果） | 是 | 本輪完成，空結果不代表來源失敗 |
| `no_event`、`no_new_content`、`scan_complete`、`empty`、`idle` | `no_event`（無資料） | 是 | 保留原始 `provider_status` 供稽核 |
| `configuration_missing`、`configuration_required`、`not_configured` | `configuration_missing` | 否 | 缺少 URL／Secret，不得解釋為無事件 |
| 其他失敗狀態 | `failed`（有 fallback 時為 `partial`） | 否 | fail-closed，不能觸發高風險通知 |

`last_success_at` 只在完成掃描的狀態寫入；未設定或失敗狀態固定輸出
`null`，避免舊資料被誤讀成最近成功。

## Migration / rollback

這是向後相容的狀態投影變更，不改 Railway 原始 payload，也不改警報門檻。
回滾本 PR 即可恢復舊映射；公開 release 的來源與事件資料不需 migration。

## Verification

- `tests/test_external_observation_input.py`
- `tests/test_railway_observation_client.py`
- `tests/test_scheduled_delivery.py`

驗收重點：空掃描與來源失敗在 source-health、Mini App 與 release gate 中保持不同狀態。
