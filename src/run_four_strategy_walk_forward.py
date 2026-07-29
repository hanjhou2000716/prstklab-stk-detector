"""CLI for archived, point-in-time four-strategy walk-forward studies."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from src.four_strategy_walk_forward import run_walk_forward


def _bars(directory: Path) -> dict[str, pd.DataFrame]:
    records: dict[str, pd.DataFrame] = {}
    for path in directory.glob("*.csv"):
        frame = pd.read_csv(path, parse_dates=["Date"]).set_index("Date")
        records[path.stem] = frame
    if not records:
        raise ValueError("No OHLCV CSV files found in --bars-dir")
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description="PRStK fixed-sample walk-forward research")
    parser.add_argument("--market", choices=("taiwan", "us"), required=True)
    parser.add_argument("--bars-dir", required=True, help="Archived ticker CSVs with Date/Open/High/Low/Close/Volume")
    parser.add_argument("--universe-snapshots", required=True, help="Point-in-time membership JSON")
    parser.add_argument("--config", default="config/walk_forward_backtest.json")
    parser.add_argument("--fundamental-snapshots", help="Required to evaluate value strategy honestly")
    parser.add_argument("--benchmark-csv")
    parser.add_argument("--output", default="data/four-strategy-walk-forward.json")
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    universes = json.loads(Path(args.universe_snapshots).read_text(encoding="utf-8"))
    fundamentals = json.loads(Path(args.fundamental_snapshots).read_text(encoding="utf-8")) if args.fundamental_snapshots else []
    benchmark = pd.read_csv(args.benchmark_csv, parse_dates=["Date"]).set_index("Date") if args.benchmark_csv else None
    report = run_walk_forward(_bars(Path(args.bars_dir)), universes, market=args.market, config=config, benchmark_bars=benchmark, fundamental_snapshots=fundamentals)
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{report['status']}: {destination}")


if __name__ == "__main__":
    main()
