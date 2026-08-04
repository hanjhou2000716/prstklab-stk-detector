# P1-03：Instrument Master

`src/instrument_master.py` 建立跨來源的 canonical instrument identity，避免 `2330`、`2330.TW`、`台積電`、`TSM` 或指數名稱被當成不同資產。

## 固定欄位

每筆 instrument 都包含：

- canonical `instrument_id`
- ticker／Yahoo symbol／name／aliases
- market、exchange、asset type、currency
- timezone、交易日曆
- ISIN、SEC CIK（若有）
- listed_from／listed_to（point-in-time 預留）
- source URL（若有）

`InstrumentMaster.resolve()` 對未知代碼或別名衝突會明確失敗，不會猜測。SEC CIK 會正規化成十位數字。上市期間可用於歷史回測，避免把未上市或已下市標的當成當時可選資產。

## 與既有研究宇宙的關係

本 PR 不改寫 0050／0051／VOO 的抓取器；它提供一個共同正規化邊界，後續 P1-06 可把成分快照與公司行動寫入同一主檔。`DEFAULT_INSTRUMENTS` 只放最小、透明的代表標的與指數 seed，不宣稱是完整市場名單。

## 驗證與回滾

測試涵蓋 CIK、日期、必填欄位、別名解析、衝突拒絕與 JSON round-trip。若需要回滾，移除本模組即可；既有研究 universe 與行情來源維持原狀，不會刪除資料。