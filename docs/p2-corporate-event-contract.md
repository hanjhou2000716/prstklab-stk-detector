# P2-04 企業事件資料契約

企業重大訊息與市場事件共用來源、時間與交叉核對欄位，但會額外保留
`issuer_ticker`、`corporate_scope`、`corporate_candidate_eligible` 與
`corporate_data_gaps`。MOPS／TWSE 公告屬 `core_observation`，SEC 觀察池申報
屬 `sec_watchlist`。

候選資格採 fail-closed：缺少發行人代碼、發布時間或來源 URL 時，事件仍可在
Mini App 顯示並供人工追查，但 `corporate_candidate_eligible=false`，且不會被
當作完整企業事件候選或高風險警報證據。事件的 `source_url`、`source_domain`、
`fetched_at` 與 `published_at` 均由共用事件契約保存。
