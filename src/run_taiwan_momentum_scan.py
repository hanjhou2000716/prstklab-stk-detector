"""Command-line runner for a bounded manual Taiwan momentum scan."""
from __future__ import annotations
import argparse
from pathlib import Path
import pandas as pd
import yfinance as yf
from src.taiwan_universe import fetch_taiwan_universe
from src.taiwan_momentum_scan import rank_records

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    universe = fetch_taiwan_universe()[:args.limit]
    symbols = [item["symbol"] for item in universe]
    data = yf.download(symbols, period="6mo", interval="1d", group_by="ticker", auto_adjust=False, progress=False, threads=True)
    records = []
    for item in universe:
        try:
            bars = data[item["symbol"]].dropna()
            records.append({"ticker": item["ticker"], "name": item["name"], "bars": bars})
        except Exception:
            continue
    result = rank_records(records)
    destination = Path("data/taiwan-momentum-scan.csv")
    destination.parent.mkdir(exist_ok=True)
    result.drop(columns=["bars"], errors="ignore").to_csv(destination, index=False, encoding="utf-8-sig")
    print(f"掃描 {len(universe)} 檔，研究候選 {len(result)} 檔：{destination}")

if __name__ == "__main__": main()
