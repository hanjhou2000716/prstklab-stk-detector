"""Command-line runner for a production Taiwan momentum scan."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.batch_download import batches
from src.public_download import download_daily_batch
from src.taiwan_momentum_scan import TAIWAN_MIN_TURNOVER, rank_records
from src.taiwan_universe import load_or_fetch_taiwan_universe


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="0 scans the complete resolved universe")
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--universe-file", default=None, help="同一次工作共用的最新公開台股清單")
    args = parser.parse_args()
    resolved_universe = load_or_fetch_taiwan_universe(args.universe_file)
    if args.offset < 0:
        raise ValueError("offset 不可小於 0")
    universe = resolved_universe[args.offset:]
    if args.limit > 0:
        universe = universe[:args.limit]
    records = []
    failed = []
    for group in batches(universe, args.batch_size):
        symbols = [item["symbol"] for item in group]
        try:
            data = download_daily_batch(symbols)
            for item in group:
                try:
                    bars = data[item["symbol"]].dropna() if len(group) > 1 else data.dropna()
                    records.append({"ticker": item["ticker"], "name": item["name"], "bars": bars})
                except Exception:
                    failed.append(item["ticker"])
        except Exception:
            failed.extend(item["ticker"] for item in group)
    result = rank_records(records)
    destination = Path(f"data/taiwan-momentum-scan-{args.offset}.csv")
    destination.parent.mkdir(exist_ok=True)
    result.drop(columns=["bars"], errors="ignore").to_csv(destination, index=False, encoding="utf-8-sig")
    summary_path = Path(f"data/taiwan-momentum-summary-{args.offset}.json")
    summary_path.write_text(json.dumps({
        "requested": len(universe), "data_complete": len(records), "candidates": len(result),
        "universe_mode": "full" if args.limit <= 0 else "bounded",
        "universe_expected": len(resolved_universe), "universe_scanned": len(universe),
        "universe_completed": len(records), "universe_failed": len(failed),
        "failed": len(failed), "batch_size": args.batch_size, "offset": args.offset,
        "min_turnover": TAIWAN_MIN_TURNOVER, "candidate_limit": 5,
        "scan_state": "complete",
        "status": "可用" if not failed else "部分缺漏",
        "error_details": failed[:20],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"掃描 {len(universe)} 檔，資料完整 {len(records)} 檔，研究候選 {len(result)} 檔，失敗 {len(failed)} 檔：{destination}、{summary_path}")

if __name__ == "__main__":
    main()
