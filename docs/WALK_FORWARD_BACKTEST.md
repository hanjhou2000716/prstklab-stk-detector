# 四策略固定樣本期 Walk-forward 回測

這是研究驗證工具，不會產生下單、部位或交易指令。所有報酬都必須扣除雙邊手續費與滑價，且不得使用今天的成分股或今天的基本面回推歷史。

## 固定研究期

設定檔 [`config/walk_forward_backtest.json`](../config/walk_forward_backtest.json) 預設將樣本切為：

| 階段 | 期間 | 用途 |
| --- | --- | --- |
| Training | 2021-01-01 至 2022-12-31 | 僅用來固定策略參數 |
| Validation | 2023-01-01 至 2023-12-31 | 檢查是否只是在訓練期過度擬合 |
| Test | 2024-01-01 至 2025-12-31 | 不可再依結果調參的最終樣本外驗證 |

每月最後一個可得交易日以收盤資料形成訊號，下一個交易日開盤進入假設路徑，持有 20 根完成日 K 後以收盤結束。這個規則避免把收盤後才知道的價格當成可成交價。

## 四個策略

- 動能狙擊：僅保留站上 5 日均線、且台股日成交額至少 3,000 萬元的標的；以七項原有百分位權重做橫斷面排序。
- 三維共振：個股 FGI 小於 56，並優先四項 Smart Money 全符合；若沒有，才採三項符合。排序為爆量吸收／長下影、假跌破收回、Alpha、TR 大於 1.1 ATR。
- 裸 K 結構：使用既有四型態與嚴格訂單塊掃描器，僅用訊號當日之前已完成、已確認的 K 線結構。
- 價值投資：只能讀取日期不晚於訊號日、並標示 `point_in_time: true` 的 TWSE／MOPS／SEC 歷史基本面快照；缺資料時會列為資料缺口，不能拿今天的基本面補回去。

## 存活者偏差防線

選股池 JSON 的每一筆快照都要有 `as_of`、`market`、`tickers`、`source` 和 `point_in_time: true`。來源文字若標成 `current` 或未標記 point-in-time，研究會被標示 `blocked_by_survivorship_audit`。已知下市／下櫃標的必須保留在其當時的快照內。

範例：

```json
[{"as_of":"2023-06-30","market":"taiwan","tickers":["2330.TW","2317.TW"],"source":"TWSE archived constituent file","point_in_time":true}]
```

## 執行方式

OHLCV 要存成每檔一個 CSV，欄位為 `Date,Open,High,Low,Close,Volume`；基本面快照另存 JSON。以下是本機或 GitHub Actions 的等價指令：

```powershell
python -m src.run_four_strategy_walk_forward `
  --market taiwan `
  --bars-dir data/backtest/taiwan/bars `
  --benchmark-csv data/backtest/taiwan/benchmark.csv `
  --universe-snapshots data/backtest/taiwan/universe_snapshots.json `
  --fundamental-snapshots data/backtest/taiwan/fundamental_snapshots.json
```

輸出 JSON 包含每筆訊號日期、次日開盤假設、離場日期、毛／淨報酬、成本拖累、每階段勝率與最大回撤，以及獨立的存活者偏差稽核結果。
