# P2：台股／美股新聞市場歸屬與內容檢核

## 問題

新聞供應商可能把兩個分類回傳成同一份清單，或在台股頁放入 Fed／美國科技、在美股頁放入台灣政治等不相干標題。只檢查 URL 重複或信任供應商分類，會讓錯誤內容進入 Mini App。

## 已實作規則

1. 將標題、摘要、描述、來源與 URL 統一做 Unicode NFKC、大小寫折疊與空白正規化。
2. 以中／簡／英文別名群比對台灣、美國及全球事件詞。
   - 台灣：台股／台灣／台湾、台積電／台积电、TWSE、TPEx、TAIEX、TWII、0050、2330、賴清德／赖清德等。
   - 美國：美股／美國／美国、Nasdaq、S&P 500、Fed／FOMC／BLS／CPI／PCE、Trump／特朗普／川普、Nvidia、AMD 等。
   - 全球：伊朗／Iran、戰爭／war、制裁、航運、原油、Brent、WTI、黃金、地震等。
3. 只有台灣證據的文章進入台股頁；只有美國證據的文章進入美股頁。跨市場或全球事件可進入兩頁，但會保留 `market_scope` 與命中的詞作為稽核證據。
4. 沒有地域證據的文章可作為供應商故障時的可用性 fallback，但會標為 `unclassified`，不宣稱為台股或美股專屬新聞。
5. 過濾在寫入快取前執行；若清單不足，改查各自 locale 的 Google News RSS；若仍無法取得，顯示資料缺口，不把另一市場清單複製過來。

## 驗證與監控

- `tests/test_risk_news.py` 驗證 Fed 只進美股、賴清德只進台股，以及伊朗／Nasdaq／台灣半導體的跨市場稽核欄位。
- 每篇保留 `classification_status`、`market_scope`、`taiwan_matches`、`us_matches`、`global_matches`，供 Mini App 與事件稽核使用。
- 發現誤分流時，先查看 `market.json` 的 `news.source_health`、`news.diagnostics` 與文章的分類欄位，不直接以 UI 分頁判斷來源。

## 後續 P2/P3/P4/P5 待辦

- P2：加上人工抽樣檢核與錯誤分流計數；將重大事件摘要與行情證據送入同一分類器。
- P3：第二可信來源核對、官方來源與市場同步門檻、事件永久帳本及多 Workflow 寫入順序保護。
- P4：璞玉價值歷史資料完成度、新聞空結果備援、VIX 百分位新鮮度與正式 walk-forward 回測。
- P5：Railway 長輪詢健康監測、Telegram／Mini App／Actions 同一觀測 ID，以及端到端收件驗證。
