"""Manual bounded US large-cap momentum research scan."""
from __future__ import annotations
import argparse, json
from pathlib import Path
from src.batch_download import batches
from src.public_download import download_daily_batch
from src.taiwan_momentum_scan import rank_records
from src.us_universe import fetch_us_large_cap_universe

def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--limit", type=int, default=100); parser.add_argument("--batch-size", type=int, default=50)
    args = parser.parse_args(); universe = fetch_us_large_cap_universe()[:args.limit] if args.limit > 0 else fetch_us_large_cap_universe()
    records, failed = [], []
    for group in batches(universe, args.batch_size):
        try:
            data = download_daily_batch([item["symbol"] for item in group])
            for item in group:
                try: records.append({"ticker": item["ticker"], "name": item["name"], "bars": data[item["symbol"]].dropna() if len(group)>1 else data.dropna()})
                except Exception: failed.append(item["ticker"])
        except Exception: failed.extend(item["ticker"] for item in group)
    result = rank_records(records, min_turnover=10_000_000); Path("data").mkdir(exist_ok=True)
    result.drop(columns=["bars"], errors="ignore").to_csv("data/us-momentum-scan.csv", index=False, encoding="utf-8-sig")
    Path("data/us-momentum-summary.json").write_text(json.dumps({"requested":len(universe),"data_complete":len(records),"candidates":len(result),"failed":len(failed)}, ensure_ascii=False), encoding="utf-8")
if __name__ == "__main__": main()
