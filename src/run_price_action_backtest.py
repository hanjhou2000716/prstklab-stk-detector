"""Command-line runner for one public-symbol Price Action research backtest."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
import yfinance as yf

from src.price_action_backtest import walk_forward_price_action


def download_bars(symbol: str, period: str) -> pd.DataFrame:
    """Download completed daily OHLCV bars from a public source."""
    data = yf.download(symbol, period=period, interval="1d", auto_adjust=False, progress=False, threads=False)
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)
    bars = data[["Open", "High", "Low", "Close", "Volume"]].dropna()
    if bars.empty:
        raise ValueError("公開歷史資料暫時無法取得")
    return bars


def write_report(report: dict, destination: Path) -> tuple[Path, Path]:
    """Write a human-downloadable JSON summary and a tabular trade artifact."""
    destination.mkdir(parents=True, exist_ok=True)
    json_path = destination / "price-action-backtest.json"
    csv_path = destination / "price-action-backtest-trades.csv"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.DataFrame(report["trades"]).to_csv(csv_path, index=False, encoding="utf-8-sig")
    return json_path, csv_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Price Action 逐步回測研究")
    parser.add_argument("--symbol", required=True, help="Yahoo Finance 代碼，例如 2330.TW 或 NVDA")
    parser.add_argument("--market", required=True, choices=("taiwan", "us"))
    parser.add_argument("--period", default="5y", help="公開日 K 資料範圍，例如 1y、5y")
    parser.add_argument("--max-holding-days", type=int, default=60)
    args = parser.parse_args()
    report = walk_forward_price_action(
        download_bars(args.symbol, args.period), args.symbol, args.market, max_holding_days=args.max_holding_days,
    )
    json_path, csv_path = write_report(report, Path("data"))
    print(f"{report['status']}：{len(report['trades'])} 筆研究紀錄；輸出 {json_path}、{csv_path}")


if __name__ == "__main__":
    main()
