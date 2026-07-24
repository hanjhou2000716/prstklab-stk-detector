"""Command-line runner for a bounded Taiwan Price Action research scan."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.batch_download import batches
from src.public_download import download_daily_batch
from src.taiwan_price_action_scan import rank_records
from src.taiwan_universe import load_or_fetch_taiwan_universe


def main() -> None:
    parser = argparse.ArgumentParser(description="台股裸 K 結構研究掃描")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--universe-file", default=None, help="同一次工作共用的最新公開台股清單")
    args = parser.parse_args()
    if args.offset < 0:
        raise ValueError("offset 不可小於 0")
    universe = load_or_fetch_taiwan_universe(args.universe_file)[args.offset:]
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

    result = rank_records(records)
    Path("data").mkdir(exist_ok=True)
    csv_path = Path(f"data/taiwan-price-action-scan-{args.offset}.csv")
    summary_path = Path(f"data/taiwan-price-action-summary-{args.offset}.json")
    result.to_csv(csv_path, index=False, encoding="utf-8-sig")
    summary_path.write_text(json.dumps({
        "requested": len(universe), "data_complete": len(records), "candidates": len(result),
        "failed": len(failed), "batch_size": args.batch_size, "offset": args.offset,
        "notice": "僅供公開市場結構研究，不構成買賣建議。",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"掃描 {len(universe)} 檔，資料完整 {len(records)} 檔，結構研究候選 {len(result)} 檔，失敗 {len(failed)} 檔：{csv_path}、{summary_path}")


if __name__ == "__main__":
    main()
