# 正式回測資料就緒條件

四策略回測目前維持 `publication_state=unavailable`，不是掃描錯誤，也不是零績效。正式開放前必須完成兩個市場的 point-in-time archive audit：

- 每個固定 walk-forward window 都有當時的 OHLCV、benchmark 與成分股快照。
- 財報／配息快照標記 `point_in_time=true`，且發布日不晚於訊號日。
- 成分股包含已下市標的；不可用今日 ETF 成分回填歷史。
- 每個策略都產生 gross／net、手續費、稅、滑價、週轉與完整風險指標。
- `backtest_release_contract.publication_state=ready` 且 `publish_eligible=true` 後，才會被 Strategy Registry 與 Advice Gate 接受。

## 目前狀態

`data/backtest/{taiwan,us}/manifest.json` 或其必要檔案未齊全時，`src.run_backtest_archive_audit` 只輸出阻塞報告；workflow 不產生正式績效。UI 必須顯示「正式回測尚未發布」，候選維持研究觀察，不得顯示買進／賣出判斷。

## 建檔與驗證順序

1. 匯入已核對的歷史 bars、成分股與財報快照。
2. 執行 `python -m src.run_backtest_archive_audit --market taiwan` 及 `--market us`。
3. 兩者均 `status=ready` 後執行四策略 walk-forward workflow。
4. 檢查 release contract、Strategy Registry、Advice Gate 與公開 manifest。
5. 失敗時保留 audit JSON，禁止以部分資料覆蓋上一個正式 release。

回滾：刪除待發布回測 artifact 並保留目前 `unavailable` 狀態；不撤銷既有研究掃描或市場資料。
