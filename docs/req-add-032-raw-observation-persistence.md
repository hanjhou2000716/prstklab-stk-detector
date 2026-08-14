# REQ-ADD-032：raw observation 持久化韌性

## 目的

避免 Windows／OneDrive 或防毒軟體短暫鎖定 raw payload 時，正式市場快照被
誤判為來源失敗。這項修復只處理可辨識的短暫檔案鎖與 SQLite busy/locked；
真正的權限、磁碟或資料庫錯誤仍會 fail closed，不會被吞掉。

## 行為

- payload 仍以暫存檔寫入，再以原子替換發布。
- `EACCES`、`EBUSY`、`EPERM`、`ETXTBSY` 最多重試三次，退避 50/100/200 ms。
- SQLite 使用 5 秒 busy timeout，並對 `busy`／`locked` 最多重試三次。
- 超過上限或非重試錯誤會回傳 `unavailable`，維持既有 fail-closed 閘門。
- 不修改 raw payload schema、觀測 ID 或不可變保存語意。

## 驗證與回滾

`tests/test_raw_observation_store.py` 以一次暫時性 `PermissionError` 驗證檔案
鎖重試；完整回歸需再執行。回滾本 PR 即可移除重試，不會修改既有 raw store
資料或公開 release。
