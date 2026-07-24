"""Command-line runner for a bounded manual Taiwan momentum scan."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import pandas as pd
import yfinance as yf
from src.batch_download import batches
from src.taiwan_universe import fetch_taiwan_universe
from src.taiwan_momentum_scan import rank_records

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--offset", type=int, default=0)
    args = parser.parse_args()
    universe = fetch_taiwan_universe()
    if args.offset < 0:
        raise ValueError("offset 不可小於 0")
    universe = universe[args.offset:]
    if args.limit > 0:
        universe = universe[:args.limit]
    records = []
    failed = []
    for group in batches(universe, args.batch_size):
        symbols = [item["symbol"] for item in group]
        try:
            data = yf.download(symbols, period="6mo", interval="1d", group_by="ticker", auto_adjust=False, progress=False, threads=True)
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
        "failed": len(failed), "batch_size": args.batch_size, "offset": args.offset,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"掃描 {len(universe)} 檔，資料完整 {len(records)} 檔，研究候選 {len(result)} 檔，失敗 {len(failed)} 檔：{destination}、{summary_path}")

if __name__ == "__main__": main()
