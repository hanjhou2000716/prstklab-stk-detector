# P1：資料平台基礎

本階段新增兩個可獨立使用的基礎元件：

## 統一來源 Adapter

`src/source_adapter.py` 的 `JsonSourceAdapter` 統一處理公開 JSON 來源的：

- timeout、可重試 HTTP 狀態與退避
- 最小請求間隔（rate limit）
- parser version 與來源 tier
- request ID、抓取時間、HTTP 狀態、延遲與 payload hash
- source health（最近成功／失敗、連續失敗與錯誤類別）
- 明確選擇才可使用的 stale cache

stale cache 永遠標記 `stale_used=true` 與 `freshness=stale`，不能被誤當成
live 行情或高風險警報證據。各 provider 只需提供 endpoint 與 parser，後續
可逐步將 TWSE、TAIFEX、TPEx、Yahoo、SEC、FRED、EIA、Binance、GDELT
接到相同介面。

## Raw Observation Store

`src/raw_observation_store.py` 以標準函式庫 SQLite 建立不可變索引，並把原始
payload 存成 content-addressed JSON 檔。每筆觀測保留：

- provider、endpoint、request ID、fetched_at
- HTTP status、payload hash、raw payload location
- parser version、parsing status、observation ID

相同 request/payload 會冪等回傳既有觀測；不同 payload 不會覆寫舊資料。這
讓後續 parser 重播、來源品質稽核、事件與行情追溯可以使用同一份原始證據。

目前預設路徑是 `data/raw_observations/`；Railway 可把它指向持久化 volume，
GitHub Actions 則可把短期內容上傳為 artifact。正式接入各來源前，仍必須
由呼叫端檢查 freshness 與 cross-check 狀態，資料不足時 fail closed。
