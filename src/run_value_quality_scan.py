"""Run bounded value-quality review after the full-universe technical scans."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from src.value_review import review_candidates


def _scan_paths(market: str, data_dir: Path) -> list[Path]:
    suffix = "-0" if market == "taiwan" else ""
    return [data_dir / f"{market}-{strategy}-scan{suffix}.csv" for strategy in ("momentum", "price-action", "resonance")]


def load_upstream_candidates(market: str, data_dir: Path, universe_file: str | None) -> list[dict[str, str]]:
    symbols = {}
    if market == "taiwan" and universe_file:
        try:
            symbols = {item["ticker"]: item["symbol"] for item in json.loads(Path(universe_file).read_text(encoding="utf-8"))}
        except (OSError, json.JSONDecodeError, KeyError):
            symbols = {}
    candidates: dict[str, dict[str, str]] = {}
    for path in _scan_paths(market, data_dir):
        try:
            frame = pd.read_csv(path)
        except (OSError, pd.errors.EmptyDataError):
            continue
        for _, row in frame.iterrows():
            ticker = str(row.get("ticker", "")).strip()
            if not ticker:
                continue
            symbol = symbols.get(ticker, f"{ticker}.TW" if market == "taiwan" else ticker)
            candidates.setdefault(ticker, {"ticker": ticker, "name": str(row.get("name", ticker)), "symbol": symbol})
    return list(candidates.values())


def main() -> None:
    parser = argparse.ArgumentParser(description="Public value-quality review")
    parser.add_argument("--market", choices=("taiwan", "us"), required=True)
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--universe-file", default=None)
    args = parser.parse_args()
    data_dir = Path(args.data_dir)
    candidates = load_upstream_candidates(args.market, data_dir, args.universe_file)
    import yfinance as yf
    rows, failed = review_candidates(candidates, lambda symbol: yf.Ticker(symbol).info)
    destination = data_dir / f"{args.market}-value-scan.csv"
    summary = data_dir / f"{args.market}-value-summary.json"
    pd.DataFrame(rows).to_csv(destination, index=False, encoding="utf-8-sig")
    summary.write_text(json.dumps({"requested": len(candidates), "data_complete": len(rows) + len(failed), "candidates": len(rows), "failed": len(failed)}, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
