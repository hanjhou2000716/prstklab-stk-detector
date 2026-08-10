"""Run the independent public value-investing research pool."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import pandas as pd

from src.batch_download import batches
from src.mops_history import mops_pristine_history
from src.pristine_value import (
    heat_metrics,
    pristine_selection_diagnostics,
    review_pristine_observation_pool,
    review_pristine_pool,
)
from src.public_download import download_daily_batch
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


def public_share_counts(candidates: list[dict[str, str]]) -> dict[str, float]:
    """Read a bounded public share-count proxy for turnover-rate screening.

    Yahoo's public ``floatShares`` field is preferred; ``shares`` is the
    disclosed outstanding-share fallback.  The result is used only to derive
    a transparent turnover proxy when TWSE free-float data is unavailable.
    """
    try:
        import yfinance as yf
    except ImportError:
        return {}
    output: dict[str, float] = {}
    for item in candidates:
        symbol = item["symbol"]
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info
            shares = info.get("floatShares") or info.get("sharesOutstanding")
            if shares is None:
                shares = dict(ticker.fast_info).get("shares")
            if isinstance(shares, (int, float)) and float(shares) > 0:
                output[symbol] = float(shares)
        except Exception:
            continue
    return output


def public_quotes(
    candidates: list[dict[str, str]], batch_size: int = 50,
    share_counts: dict[str, float] | None = None,
) -> tuple[dict[str, dict[str, float | str]], list[str]]:
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
                        shares = (share_counts or {}).get(item["symbol"])
                        quote: dict[str, Any] = {
                            **context, **heat_metrics(bars, shares_outstanding=shares),
                            "turnover_rate_basis": "Yahoo floatShares/shares proxy" if shares else None,
                        }
                        quotes[item["symbol"]] = quote
                    else:
                        errors.append(f"{item['ticker']} 報價資料不足")
                except (KeyError, TypeError, ValueError):
                    errors.append(f"{item['ticker']} 報價暫時無法取得")
        except Exception:
            errors.extend(f"{item['ticker']} 報價暫時無法取得" for item in group)
    return quotes, errors


def candidate_state_for(rows: list[dict[str, Any]], scan_state: str) -> str:
    """Describe usable candidates independently from whole-universe completion."""
    if rows:
        return "available" if scan_state == "complete" else "available_from_completed_records"
    if scan_state in {"partial", "building", "failed"}:
        return "data_gap"
    return "no_candidates"


def main() -> None:
    parser = argparse.ArgumentParser(description="Independent public value-investing research")
    parser.add_argument("--market", choices=("taiwan", "us"), required=True)
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--mops-max-refresh", type=int, default=8,
                        help="Taiwan MOPS records per run; 0 verifies the complete pool")
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
        history, history_errors = mops_pristine_history(
            [item["ticker"] for item in candidates],
            data_dir / "taiwan-mops-pristine-history.json",
            max_refresh=args.mops_max_refresh,
        )
        for ticker, values in history.items():
            fundamentals[ticker] = {**fundamentals.get(ticker, {}), **values}
        fundamental_errors.extend(history_errors)
    else:
        fundamentals, fundamental_errors = sec_fundamentals(
            [item["ticker"] for item in candidates],
            cik_overrides={item["ticker"]: item["cik"] for item in candidates if item.get("cik")},
            cache_path=os.getenv("SEC_FACTS_CACHE_PATH", str(data_dir / "sec-companyfacts-cache.json")),
        )
    # Turnover-rate is one of the six Pristine conditions for both markets.
    # Use the public float/outstanding-share proxy for US rows too; leaving it
    # null silently made every US row incomplete and guaranteed zero candidates.
    share_counts = public_share_counts(
        [item for item in candidates if args.market != "taiwan" or item["ticker"] in history]
    )
    if args.market == "us":
        # SEC CompanyFacts is the first-party fallback for share counts.  Yahoo
        # may omit floatShares during rate limiting; do not turn that omission
        # into a blanket "all US rows incomplete" result.
        for item in candidates:
            sec_shares = fundamentals.get(item["ticker"], {}).get("shares_outstanding")
            if sec_shares and item["symbol"] not in share_counts:
                share_counts[item["symbol"]] = float(sec_shares)
    quotes, quote_errors = public_quotes(candidates, args.batch_size, share_counts)
    base_rows = review_public_pool(
        candidates, fundamentals, quotes, args.market, limit=None,
        allow_missing_supplemental=args.market == "taiwan",
    )
    # Taiwan history is built incrementally.  A global ``150/150`` gate made a
    # handful of transient MOPS failures hide every already-verified company.
    # Evaluate only tickers whose own history record is complete; incomplete
    # tickers remain blocked and are disclosed in the progress fields below.
    history_complete = args.market != "taiwan" or len(history) >= len(candidates)
    if args.market == "taiwan":
        verified_tickers = set(history)
        evaluable_rows = [row for row in base_rows if str(row.get("ticker", "")) in verified_tickers]
    else:
        evaluable_rows = base_rows
    formal_rows = review_pristine_pool(evaluable_rows, args.market)
    observation_rows = review_pristine_observation_pool(evaluable_rows, args.market)
    selection_diagnostics = pristine_selection_diagnostics(evaluable_rows, args.market)
    # The user-facing shortlist is capped at five. Observation rows only fill
    # unused slots; once five formal candidates exist, do not publish a second
    # list that competes with the official shortlist.
    visible_observation_rows = [] if len(formal_rows) >= 5 else observation_rows[: max(0, 5 - len(formal_rows))]
    rows = formal_rows + visible_observation_rows

    pd.DataFrame(rows).to_csv(data_dir / f"{args.market}-value-scan.csv", index=False, encoding="utf-8-sig")
    failed_total = len(universe_errors) + len(fundamental_errors) + len(quote_errors)
    complete_records = len(evaluable_rows)
    if failed_total == 0 and (args.market != "taiwan" or history_complete):
        scan_state = "complete"
    elif complete_records > 0:
        scan_state = "partial"
    else:
        scan_state = "failed"
    candidate_state = candidate_state_for(rows, scan_state)
    summary = {
        "requested": len(candidates),
        "universe_mode": "full",
        "universe_expected": len(candidates),
        "universe_scanned": len(candidates),
        "universe_completed": complete_records,
        "universe_failed": failed_total,
        # A current TWSE snapshot is not a completed Taiwan Pristine Value
        # verification until the three-year MOPS history has been cached.
        "data_complete": len(history) if args.market == "taiwan" else len(fundamentals),
        "candidates": len(rows),
        "formal_candidates": len(formal_rows),
        "observation_candidates": len(visible_observation_rows),
        "selection_diagnostics": selection_diagnostics,
        "failed": failed_total,
        "scan_state": scan_state,
        "candidate_state": candidate_state,
        "complete_records": complete_records,
        "data_gap_counts": {
            "universe": len(universe_errors),
            "fundamentals": len(fundamental_errors),
            "quotes": len(quote_errors),
            "history": len(history_errors) if args.market == "taiwan" else 0,
        },
        "status": "可用" if failed_total == 0 else "部分缺漏",
        "universe_source": "Yuanta 0050+0051 PCF" if args.market == "taiwan" else "Nasdaq-100 + semiconductor/AI core",
        "financial_source": "TWSE OpenAPI + MOPS historical filings" if args.market == "taiwan" else "SEC EDGAR CompanyFacts",
        "sec_cache_hits": sum(1 for item in fundamentals.values() if item.get("sec_cache_used")) if args.market == "us" else 0,
        "sec_data_as_of": max((str(item.get("sec_data_fetched_at", "")) for item in fundamentals.values()), default=None) if args.market == "us" else None,
        "errors": universe_errors + fundamental_errors + quote_errors,
        "error_details": {
            "universe": universe_errors,
            "fundamentals": fundamental_errors,
            "quotes": quote_errors,
        },
        "mops_refresh_limit": args.mops_max_refresh if args.market == "taiwan" else None,
        "partial_candidates_allowed": args.market == "taiwan" and not history_complete,
        "evaluable_records": len(evaluable_rows) if args.market == "taiwan" else len(base_rows),
        "notice": "璞玉價值池獨立於技術策略；正式候選需達 5/6，觀察名單需達 3/6 或 4/6；僅提供公開財務觀察，不構成投資建議。",
    }
    if args.market == "taiwan":
        summary["history_cached"] = len(history)
        summary["history_expected"] = len(candidates)
        summary["history_progress_pct"] = round(
            (len(history) / len(candidates) * 100) if candidates else 0.0, 1
        )
        summary["history_pending"] = max(len(candidates) - len(history), 0)
        summary["history_failure_count"] = len(history_errors)
        if len(history) < len(candidates):
            summary["scan_state"] = "building"
            summary["candidate_state"] = candidate_state_for(rows, "building")
            summary["status"] = "建檔中"
            summary["notice"] = (
                f"璞玉價值歷史資料建檔中：已核對 {len(history)}／{len(candidates)} 檔；"
                "未完成六項公開資料覆核前不列入候選，並非投資結論。"
            )
            summary["blocking_reason"] = (
                "部分 MOPS 歷史資料尚未完成；未完成個股不列入，已完成個股仍可依六項規則評估。"
            )
    elif failed_total:
        # A completed US run with missing SEC/VOO/quote inputs is unavailable,
        # not an empty candidate result.  This prevents the UI from implying
        # that the strict pool was evaluated successfully.
        summary["status"] = "資料暫時無法取得"
    (data_dir / f"{args.market}-value-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
