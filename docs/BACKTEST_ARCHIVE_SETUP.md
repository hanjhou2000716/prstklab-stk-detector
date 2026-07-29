# 回測歷史資料匯入與稽核

正式 walk-forward 回測只能使用「當時已知」的資料，不能以今天的 0050／0051／VOO 成分股或今日財報回推歷史。本專案先提供匯入契約與稽核器；在資料齊備前，回測輸出不得解讀為正式績效結論。

## 目錄契約

```text
data/backtest/
  taiwan/
    manifest.json
    bars/2330.TW.csv
    universe_snapshots.json
    fundamental_snapshots.json
  us/
    manifest.json
    bars/NVDA.csv
    universe_snapshots.json
    fundamental_snapshots.json
```

每個 OHLCV CSV 必須具備 `Date,Open,High,Low,Close,Volume`。成分股與基本面快照均須含 `as_of` 和 `point_in_time: true`；已下市或被剔除標的必須保留在其歷史期間的名單中。

`manifest.json` 最小範例：

```json
{
  "schema_version": "1.0",
  "market": "taiwan",
  "bars_directory": "bars",
  "universe_snapshots": "universe_snapshots.json",
  "fundamental_snapshots": "fundamental_snapshots.json",
  "delisted_symbols_included": true
}
```

## 建議資料來源與保存原則

- 台股：TWSE／TPEx 歷史日資料、0050／0051 各期公開成分資訊、MOPS 各季公告原始檔；記錄下載日期與原始 URL。
- 美股：VOO 各期持股檔案或可追溯的歷史成分資料、SEC EDGAR filing／companyfacts 的 filing 日期版本；不可用當前 VOO 成分替代。
- 基本面：每一列須保存公告可得日期，而非財報所屬年度；這會避免把後來才公布的數字帶回訊號日。

## 稽核與執行

```powershell
python -m src.run_backtest_archive_audit --market taiwan
python -m src.run_four_strategy_walk_forward --market taiwan --bars-dir data/backtest/taiwan/bars --universe-snapshots data/backtest/taiwan/universe_snapshots.json --fundamental-snapshots data/backtest/taiwan/fundamental_snapshots.json
```

第一個指令若不是 `ready` 會以非零結束，並列出阻擋原因。通過後才可執行四策略固定樣本期回測；回測仍會套用設定檔中的手續費、滑價與存活者偏差檢定。
