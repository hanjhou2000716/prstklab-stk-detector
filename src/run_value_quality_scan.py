"""Run the independent public value-investing research pool."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from src.batch_download import batches
from src.public_download import download_daily_batch
from src.pristine_value import heat_metrics, review_pristine_pool
from src.research_contract import latest_quote_context
from src.value_fundamentals import sec_fundamentals, twse_financial_snapshot
from src.value_review import review_public_pool
from src.value_universe import (
    fetch_taiwan_value_universe,
    fetch_us_value_universe,
    universe_snapshot,
)


def load_upstream_candidates(market: str, data_dir: Path, universe_file: str | None) -> list[dict[str, str]]:
    """Legacy compatibility helper; the production value scan no longer calls it."""
    symbols = {}
    if market == "taiwan" and universe_file:
        try:
            symbols = {item["ticker"]: item["symbol"] for item in json.loads(Path(universe_file).read_text(encoding="utf-8"))}
        except (OSError, json.JSONDecodeError, KeyError):
            symbols = {}
    candidates: dict[str, dict[str, str]] = {}
    suffix = "-0" if market == "taiwan" else ""
    for strategy in ("momentum", "price-action", "resonance"):
        try:
            frame = pd.read_csv(data_dir / f"{market}-{strategy}-scan{suffix}.csv")
        except (OSError, pd.errors.EmptyDataError):
            continue
        for _, row in frame.iterrows():
            ticker = str(row.get("ticker", "")).strip()
            if ticker:
                candidates.setdefault(ticker, {
                    "ticker": ticker,
                    "name": str(row.get("name", ticker)),
                    "symbol": symbols.get(ticker, f"{ticker}.TW" if market == "taiwan" else ticker),
                })
    return list(candidates.values())


def public_quotes(candidates: list[dict[str, str]], batch_size: int = 50) -> tuple[dict[str, dict[str, float | str]], list[str]]:
    """Return latest quote plus three-month heat observations for each symbol."""
    quotes: dict[str, dict[str, float | str]] = {}
    errors: list[str] = []
    for group in batches(candidates, batch_size):
        try:
            downloaded = download_daily_batch([item["symbol"] for item in group])
            for item in group:
                try:
                    bars = downloaded[item["symbol"]].dropna() if len(group) > 1 else downloaded.dropna()
                    context = latest_quote_context(bars)
                    if context:
                        quotes[item["symbol"]] = {**context, **heat_metrics(bars)}
                    else:
                        errors.append(f"{item['ticker']} 報價資料不足")
                except (KeyError, TypeError, ValueError):
                    errors.append(f"{item['ticker']} 報價暫時無法取得")
        except Exception:
            errors.extend(f"{item['ticker']} 報價暫時無法取得" for item in group)
    return quotes, errors


def main() -> None:
    parser = argparse.ArgumentParser(description="Independent public value-investing research")
    parser.add_argument("--market", choices=("taiwan", "us"), required=True)
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--batch-size", type=int, default=50)
    args = parser.parse_args()
    data_dir = Path(args.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    candidates, universe_errors = (
        fetch_taiwan_value_universe() if args.market == "taiwan" else fetch_us_value_universe()
    )
    (data_dir / f"runtime-value-{args.market}-universe.json").write_text(
        json.dumps(universe_snapshot(args.market, candidates, universe_errors), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if args.market == "taiwan":
        fundamentals, fundamental_errors = twse_financial_snapshot([item["ticker"] for item in candidates])
    else:
        fundamentals, fundamental_errors = sec_fundamentals([item["ticker"] for item in candidates])
    quotes, quote_errors = public_quotes(candidates, args.batch_size)
    base_rows = review_public_pool(candidates, fundamentals, quotes, args.market, limit=None)
    rows = review_pristine_pool(base_rows, args.market)

    pd.DataFrame(rows).to_csv(data_dir / f"{args.market}-value-scan.csv", index=False, encoding="utf-8-sig")
    summary = {
        "requested": len(candidates),
        "data_complete": len(fundamentals),
        "candidates": len(rows),
        "failed": len(universe_errors) + len(fundamental_errors) + len(quote_errors),
        "universe_source": "Yuanta 0050+0051 PCF" if args.market == "taiwan" else "Vanguard VOO holdings",
        "financial_source": "TWSE OpenAPI" if args.market == "taiwan" else "SEC EDGAR CompanyFacts",
        "errors": universe_errors + fundamental_errors + quote_errors,
        "notice": "價值投資池獨立於技術策略；僅提供公開財務觀察，不構成投資建議。",
    }
    (data_dir / f"{args.market}-value-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
