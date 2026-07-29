"""Run public three-dimensional resonance research over one configured universe."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.batch_download import batches
from src.public_download import download_daily_batch
from src.resonance_universe import rank_records
from src.taiwan_universe import load_or_fetch_taiwan_universe
from src.us_universe import fetch_us_research_universe


def universe_for(market: str, cache_path: str | None) -> list[dict[str, str]]:
    return load_or_fetch_taiwan_universe(cache_path) if market == "taiwan" else fetch_us_research_universe()


def latest_batch_bars(data, symbol: str):
    """Extract a completed single-symbol frame from the public batch response."""
    columns = getattr(data, "columns", None)
    return data[symbol].dropna() if getattr(columns, "nlevels", 1) > 1 else data.dropna()


def main() -> None:
    parser = argparse.ArgumentParser(description="Public full-universe resonance research")
    parser.add_argument("--market", choices=("taiwan", "us"), required=True)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--universe-file", default=None)
    args = parser.parse_args()
    universe = universe_for(args.market, args.universe_file)[args.offset:]
    if args.limit > 0:
        universe = universe[:args.limit]

    records, failed = [], []
    for group in batches(universe, args.batch_size):
        try:
            data = download_daily_batch([item["symbol"] for item in group], period="1y")
            for item in group:
                try:
                    bars = data[item["symbol"]].dropna() if len(group) > 1 else data.dropna()
                    records.append({"ticker": item["ticker"], "name": item["name"], "bars": bars})
                except Exception:
                    failed.append(item["ticker"])
        except Exception:
            failed.extend(item["ticker"] for item in group)

    threshold = 5_000_000 if args.market == "taiwan" else 10_000_000
    benchmark_symbol = "^TWII" if args.market == "taiwan" else "^GSPC"
    benchmark_bars = None
    try:
        benchmark_bars = latest_batch_bars(download_daily_batch([benchmark_symbol], period="1y"), benchmark_symbol)
    except Exception:
        pass
    result = rank_records(records, min_turnover=threshold, benchmark_bars=benchmark_bars)
    directory = Path("data"); directory.mkdir(exist_ok=True)
    suffix = f"-{args.offset}" if args.market == "taiwan" else ""
    scan_path = directory / f"{args.market}-resonance-scan{suffix}.csv"
    summary_path = directory / f"{args.market}-resonance-summary{suffix}.json"
    result.to_csv(scan_path, index=False, encoding="utf-8-sig")
    summary_path.write_text(json.dumps({
        "requested": len(universe), "data_complete": len(records), "candidates": len(result),
        "failed": len(failed), "batch_size": args.batch_size, "offset": args.offset,
        "benchmark": benchmark_symbol, "benchmark_available": benchmark_bars is not None,
        "minimum_conditions": 3, "priority": "四項共振優先；無四項時顯示三項備選",
    }, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
