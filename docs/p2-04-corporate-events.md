# P2-04：企業事件引擎

`normalize_corporate_event()` 接收 SEC／MOPS／公司 IR 的公開資料，保存：

- EPS、營收的 actual／expected 與 beat／miss／in-line；
- 財測、毛利率、資本支出、受影響產業；
- SEC form 或 MOPS 類型、來源 URL、source tier、published_at、fetched_at；
- `point_in_time=true` 與 `directional_claim=false`。

`corporate_event_summary()` 只產生證據與後續核對項目，不把申報自動定性為利多、利空或買賣訊號。事件仍需交給共用分類器、來源核對與市場同步閘門。

回滾：撤回本 PR 即可移除正規化層；既有 SEC／MOPS 抓取器仍可輸出原始記錄。