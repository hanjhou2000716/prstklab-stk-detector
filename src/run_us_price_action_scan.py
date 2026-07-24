"""Command-line runner for a bounded US large-cap Price Action scan."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.batch_download import batches
from src.public_download import download_daily_batch
from src.taiwan_price_action_scan import rank_records
from src.us_universe import fetch_us_large_cap_universe


def main() -> None:
    parser = argparse.ArgumentParser(description="美股大型股裸 K 結構研究掃描")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--batch-size", type=int, default=50)
    args = parser.parse_args()
    universe = fetch_us_large_cap_universe()
    if args.limit > 0:
        universe = universe[:args.limit]

    records, failed = [], []
    for group in batches(universe, args.batch_size):
        try:
            data = download_daily_batch([item["symbol"] for item in group])
            for item in group:
                try:
                    bars = data[item["symbol"]].dropna() if len(group) > 1 else data.dropna()
                    records.append({"ticker": item["ticker"], "name": item["name"], "bars": bars})
                except Exception:
                    failed.append(item["ticker"])
        except Exception:
            failed.extend(item["ticker"] for item in group)

    result = rank_records(records, min_turnover=10_000_000)
    Path("data").mkdir(exist_ok=True)
    csv_path = Path("data/us-price-action-scan.csv")
    summary_path = Path("data/us-price-action-summary.json")
    result.to_csv(csv_path, index=False, encoding="utf-8-sig")
    summary_path.write_text(json.dumps({
        "requested": len(universe), "data_complete": len(records), "candidates": len(result),
        "failed": len(failed), "batch_size": args.batch_size,
        "notice": "美股大型股公開資料研究，不等同 VOO 精確成分股，也不構成買賣建議。",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"掃描 {len(universe)} 檔，資料完整 {len(records)} 檔，結構研究候選 {len(result)} 檔，失敗 {len(failed)} 檔：{csv_path}、{summary_path}")


if __name__ == "__main__":
    main()
