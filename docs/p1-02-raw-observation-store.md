# P1-02：不可變 Raw Observation Store

本 PR 新增 `src/observation_store.py`，以 SQLite metadata index 加上 hash-addressed JSON raw body 儲存每次公開來源抓取結果。它是 P1-01 Adapter 與後續正規化／交叉核對之間的證據層。

## 寫入契約

`RawObservationStore.append(observation, parser_version=...)` 會：

1. 以 payload SHA-256 驗證 Adapter observation，hash 不一致就 fail closed。
2. 將原始 payload 寫入 `data/raw-observations/<provider>/<UTC-date>/<payload_hash>.json`。
3. 以 `open(..., "xb")` 建立檔案；相同 hash 重送只回傳既有紀錄，不覆寫原始內容。
4. 將 provider、endpoint、source tier、fetched time、request ID、HTTP status、parser version、parse status、payload location 寫入 SQLite index。

資料庫會保留 `payload_hash` 唯一索引，因此工作流重試不會產生重複觀測。所有 request headers、API key 與 response cookies 都不會被保存。

## 使用方式

```python
from src.adapters import build_default_adapters
from src.observation_store import RawObservationStore

adapter = build_default_adapters()["twse"]
observation = adapter.fetch()
record = RawObservationStore().append(observation, parser_version="twse-v1")
```

FRED／EIA 若缺少環境變數會在 Adapter 層先失敗，不會寫入假造的 raw record。Store 本身不做網路重試或事件判斷；這些責任由來源 Adapter 與上層政策管理。

## 部署與回滾

- 本地與 GitHub Actions 可使用 `data/raw-observations` 作短期 artifact；Railway 應將 root 指到持久化 volume。
- 下一步可將 SQLite index 轉換為 DuckDB／Parquet 或 PostgreSQL，但保留相同欄位與 hash 契約。
- 回滾本 PR 不會刪除既有 market、event 或 research 資料；只需停用新 store 呼叫即可。
- 若資料庫損壞，raw JSON 仍可讀取；可重建 index（後續 migration 任務）而不改變 payload。

## 測試

`tests/test_observation_store.py` 覆蓋 idempotent append、不同 payload 查詢、hash mismatch fail closed、provider／日期分區與 raw payload 讀回。測試完全使用暫存目錄，不連線外部來源。