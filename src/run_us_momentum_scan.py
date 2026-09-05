"""Manual bounded US large-cap momentum research scan."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.batch_download import batches
from src.public_download import download_daily_batch
from src.research_scan_provenance import quote_cutoff_from_records, scan_trading_date
from src.research_scan_state import classify_scan_state
from src.taiwan_momentum_scan import rank_records
from src.us_universe import fetch_us_research_universe


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--scan-trading-date", default=None)
    args = parser.parse_args()
    target_trading_date = scan_trading_date("us", args.scan_trading_date)
    resolved_universe = fetch_us_research_universe()
    universe = resolved_universe[:args.limit] if args.limit > 0 else resolved_universe
    records, failed = [], []
    for group in batches(universe, args.batch_size):
        try:
            data = download_daily_batch([item["symbol"] for item in group])
            for item in group:
                try:
                    records.append({
                        "ticker": item["ticker"],
                        "name": item["name"],
                        "bars": data[item["symbol"]].dropna() if len(group) > 1 else data.dropna(),
                    })
                except Exception:
                    failed.append(item["ticker"])
        except Exception:
            failed.extend(item["ticker"] for item in group)
    result = rank_records(records, min_turnover=10_000_000)
    Path("data").mkdir(exist_ok=True)
    result.drop(columns=["bars"], errors="ignore").to_csv("data/us-momentum-scan.csv", index=False, encoding="utf-8-sig")
    Path("data/us-momentum-summary.json").write_text(json.dumps({"requested": len(universe), "data_complete": len(records), "candidates": len(result), "failed": len(failed), "universe_mode": "full" if args.limit <= 0 else "bounded", "universe_expected": len(resolved_universe), "universe_scanned": len(universe), "universe_completed": len(records), "universe_failed": len(failed), "scan_state": classify_scan_state(expected=len(universe), completed=len(records), failed=len(failed)), "scan_trading_date": target_trading_date, "quote_cutoff_at": quote_cutoff_from_records(records), "status": "可用" if not failed else "部分缺漏", "error_details": failed[:20]}, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
