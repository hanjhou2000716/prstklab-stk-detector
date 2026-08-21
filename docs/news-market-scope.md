# 市場新聞範圍閘門

市場新聞在進入台股或美股分頁前，會先以 canonical provider registry 檢查來源覆蓋範圍。

- 只支援美股的來源（例如 Federal Reserve、SEC）不得出現在台股分頁。
- 只支援台股的來源（例如 TWSE、MOPS）不得出現在美股分頁。
- Google News、Anue 等明確標記為跨市場的來源可以進入兩個分頁，但仍須有標題、主題或標的的相關性證據。
- `market_scope_mismatch` 會計入 `excluded_count` 與 `exclusion_reasons`，不會被靜默當成「本輪沒有新聞」。

若所有候選都因範圍不符被排除，輸出狀態為 `no_event`，並保留排除統計供 Mini App／來源健康狀態稽核；這與來源抓取失敗不同。
