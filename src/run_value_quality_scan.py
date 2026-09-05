"""Run the independent public value-investing research pool."""

from __future__ import annotations

import argparse
import json
import os
import time
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from src.batch_download import batches
from src.pristine_value import (
    heat_metrics,
    pristine_selection_diagnostics,
    review_pristine_observation_pool,
    review_pristine_pool,
)
from src.public_download import download_daily_batch
from src.research_contract import latest_quote_context
from src.research_scan_provenance import quote_cutoff_from_mapping, scan_trading_date
from src.value_fundamentals import (
    TW_VALUE_PARAMETER_HASH,
    TW_VALUE_RULE_VERSION,
    sec_fundamentals,
    twse_current_quality_snapshot,
)
from src.value_review import review_public_pool
from src.value_universe import (
    fetch_taiwan_official_share_records,
    fetch_taiwan_value_universe,
    fetch_us_value_universe,
    universe_snapshot,
)

TAIWAN_VALUE_POOL_EXPECTED = 150


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


def public_share_count_records(
    candidates: list[dict[str, str]], *, cache_path: str | Path | None = None,
    max_cache_age_days: int = 7,
) -> dict[str, dict[str, Any]]:
    """Read a bounded public share-count proxy for turnover-rate screening.

    Yahoo's public ``floatShares`` field is preferred; ``shares`` is the
    disclosed outstanding-share fallback.  The result is used only to derive
    a transparent turnover proxy when TWSE free-float data is unavailable.
    """
    cache_file = Path(cache_path) if cache_path else None
    cache: dict[str, dict[str, Any]] = {}
    if cache_file and cache_file.exists():
        try:
            loaded = json.loads(cache_file.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                cache = loaded
        except (OSError, ValueError, TypeError):
            cache = {}
    now = datetime.now(UTC)
    try:
        import yfinance as yf
    except ImportError:
        return {
            symbol: {**record, "freshness": "bounded_cache"}
            for symbol, record in cache.items()
            if isinstance(record, dict) and record.get("value")
            and _cache_is_fresh(record.get("fetched_at"), now, max_cache_age_days)
        }
    output: dict[str, dict[str, Any]] = {}
    for item in candidates:
        symbol = item["symbol"]
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info
            field_name = "floatShares" if info.get("floatShares") else "sharesOutstanding"
            shares = info.get(field_name)
            if shares is None:
                field_name = "fast_info.shares"
                shares = dict(ticker.fast_info).get("shares")
            if isinstance(shares, (int, float)) and float(shares) > 0:
                output[symbol] = {
                    "value": float(shares), "source": "Yahoo public quote metadata",
                    "source_tier": "secondary_public", "field": field_name,
                    "fetched_at": now.isoformat(), "freshness": "fresh",
                }
        except Exception:
            cached = cache.get(symbol)
            if isinstance(cached, dict) and cached.get("value"):
                try:
                    if _cache_is_fresh(cached.get("fetched_at"), now, max_cache_age_days):
                        output[symbol] = {**cached, "freshness": "bounded_cache"}
                except (TypeError, ValueError):
                    pass
    if cache_file and output:
        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass
    return output


def _cache_is_fresh(value: Any, now: datetime, max_age_days: int) -> bool:
    try:
        fetched = datetime.fromisoformat(str(value or "").replace("Z", "+00:00")).astimezone(UTC)
    except (TypeError, ValueError):
        return False
    return now - fetched <= timedelta(days=max_age_days)


def public_share_counts(candidates: list[dict[str, str]]) -> dict[str, float]:
    """Backward-compatible values-only view of audited share-count records."""
    return {symbol: float(record["value"]) for symbol, record in public_share_count_records(candidates).items()}


def public_quotes(
    candidates: list[dict[str, str]], batch_size: int = 50,
    share_counts: Mapping[str, float | dict[str, Any]] | None = None,
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
                        raw_shares = (share_counts or {}).get(item["symbol"])
                        metadata = raw_shares if isinstance(raw_shares, dict) else None
                        shares = metadata.get("value") if metadata else raw_shares
                        shares_value = float(shares) if isinstance(shares, (int, float)) else None
                        basis = metadata.get("shares_basis") if metadata else ("legacy_proxy" if shares_value else None)
                        quote: dict[str, Any] = {
                            **context, **heat_metrics(bars, shares_outstanding=shares_value),
                            "turnover_rate_basis": basis if shares_value else None,
                            "turnover_rate_provenance": metadata if metadata else ({"source": "legacy_proxy"} if shares_value else None),
                            "turnover_rate_fetched_at": metadata.get("fetched_at") if metadata else None,
                        }
                        quotes[item["symbol"]] = quote
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
    parser.add_argument("--mops-max-refresh", type=int, default=50,
                        help="Taiwan MOPS records per run; 0 verifies the complete pool (manual audit only)")
    parser.add_argument("--time-budget-seconds", type=float, default=None,
                        help="Shared inner deadline; finished work is published as building when it expires")
    parser.add_argument("--diagnostics-path", default=None,
                        help="Optional JSON path for stage timings and safe failure categories")
    parser.add_argument("--scan-trading-date", default=None,
                        help="Explicit target trading date; otherwise read the stable research slot")
    args = parser.parse_args()
    target_trading_date = scan_trading_date(args.market, args.scan_trading_date)
    data_dir = Path(args.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    started_monotonic = time.monotonic()
    deadline = started_monotonic + args.time_budget_seconds if args.time_budget_seconds else None
    diagnostics: dict[str, Any] = {"market": args.market, "started_at": datetime.now(UTC).isoformat(), "stages": []}

    def stage(name: str, started: float, *, processed: int | None = None, errors: list[str] | None = None) -> None:
        diagnostics["stages"].append({
            "name": name,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "processed": processed,
            "error_count": len(errors or []),
            "error_categories": sorted({str(item).split(":", 1)[-1].strip() for item in (errors or [])})[:8],
        })

    def expired() -> bool:
        return deadline is not None and time.monotonic() >= deadline

    def save_diagnostics() -> None:
        diagnostics["finished_at"] = datetime.now(UTC).isoformat()
        diagnostics["deadline_exceeded"] = expired()
        diagnostics["budget_seconds"] = args.time_budget_seconds
        if args.diagnostics_path:
            path = Path(args.diagnostics_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(diagnostics, ensure_ascii=False, indent=2), encoding="utf-8")

    timer = time.monotonic()
    candidates, universe_errors = (
        fetch_taiwan_value_universe() if args.market == "taiwan" else fetch_us_value_universe()
    )
    stage("universe", timer, processed=len(candidates), errors=universe_errors)
    (data_dir / f"runtime-value-{args.market}-universe.json").write_text(
        json.dumps(universe_snapshot(args.market, candidates, universe_errors), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if args.market == "taiwan":
        timer = time.monotonic()
        fundamentals, fundamental_errors, financial_diagnostics = twse_current_quality_snapshot(
            [item["ticker"] for item in candidates],
            cache_path=os.getenv("TAIWAN_OFFICIAL_FINANCIAL_CACHE_PATH", str(data_dir / "taiwan-official-financial-cache.json")),
            deadline=deadline,
        )
        stage("fundamentals", timer, processed=len(fundamentals), errors=fundamental_errors)
        # Taiwan current-quality v2 deliberately has no MOPS call.  The old
        # MOPS cache remains available to historical releases, but it must not
        # decide completeness or silently upgrade this strategy.
        financial_diagnostics["mops_calls"] = 0
        financial_diagnostics["mops_history_used"] = False
    else:
        timer = time.monotonic()
        fundamentals, fundamental_errors = sec_fundamentals(
            [item["ticker"] for item in candidates],
            cik_overrides={item["ticker"]: item["cik"] for item in candidates if item.get("cik")},
            cache_path=os.getenv("SEC_FACTS_CACHE_PATH", str(data_dir / "sec-companyfacts-cache.json")),
        )
        stage("fundamentals", timer, processed=len(fundamentals), errors=fundamental_errors)
        financial_diagnostics = {}
    # Turnover-rate is one of the six Pristine conditions for both markets.
    # Use the public float/outstanding-share proxy for US rows too; leaving it
    # null silently made every US row incomplete and guaranteed zero candidates.
    if args.market == "taiwan":
        timer = time.monotonic()
        share_counts, share_errors = fetch_taiwan_official_share_records(
            candidates,
            cache_path=os.getenv("TAIWAN_SHARE_CACHE_PATH", str(data_dir / "taiwan-issued-share-cache.json")),
        )
    else:
        timer = time.monotonic()
        share_counts = public_share_count_records(
            candidates,
            cache_path=os.getenv("PUBLIC_SHARE_CACHE_PATH", str(data_dir / "public-share-count-cache.json")),
        )
        share_errors = []
    stage("shares", timer, processed=len(share_counts), errors=share_errors)
    if args.market == "us":
        # SEC CompanyFacts is the first-party fallback for share counts.  Yahoo
        # may omit floatShares during rate limiting; do not turn that omission
        # into a blanket "all US rows incomplete" result.
        for item in candidates:
            sec_shares = fundamentals.get(item["ticker"], {}).get("shares_outstanding")
            if sec_shares and item["symbol"] not in share_counts:
                share_counts[item["symbol"]] = {
                    "value": float(sec_shares), "source": "SEC EDGAR CompanyFacts",
                    "source_tier": "primary", "fetched_at": fundamentals[item["ticker"]].get("sec_data_fetched_at"),
                    "freshness": "fresh",
                }
    timer = time.monotonic()
    quotes, quote_errors = public_quotes(candidates, args.batch_size, share_counts)
    stage("quotes", timer, processed=len(quotes), errors=quote_errors)
    quote_cutoff = quote_cutoff_from_mapping(quotes)
    diagnostics["scan_trading_date"] = target_trading_date
    diagnostics["scan_trading_date_source"] = (
        "explicit_argument" if args.scan_trading_date else "research_slot" if target_trading_date else None
    )
    diagnostics["quote_cutoff_at"] = quote_cutoff
    if expired():
        diagnostics["deadline_stop_stage"] = "quotes"
    timer = time.monotonic()
    base_rows = review_public_pool(
        candidates, fundamentals, quotes, args.market, limit=None,
        allow_missing_supplemental=False,
    )
    required_heat = ("average_turnover", "average_volume", "turnover_rate", "return_3m")
    if args.market == "taiwan":
        for row in base_rows:
            row["strategy_version"] = TW_VALUE_RULE_VERSION
            row["parameter_hash"] = TW_VALUE_PARAMETER_HASH
            row["data_version"] = str(fundamentals.get(str(row.get("ticker")), {}).get("reporting_period") or "")
        financial_valid = {
            ticker for ticker, item in fundamentals.items()
            if item.get("financial_complete") is True
            and item.get("financial_parse_version")
            and item.get("current_eps_positive") is not None
            and item.get("current_quality_pass") is not None
            and item.get("reporting_period")
        }
        evaluable_rows = [
            row for row in base_rows
            if str(row.get("ticker", "")) in financial_valid
            and all(row.get(metric) is not None for metric in required_heat)
        ]
        formal_rows = review_pristine_pool(evaluable_rows, args.market, rule_version=TW_VALUE_RULE_VERSION)
        observation_rows = review_pristine_observation_pool(evaluable_rows, args.market, rule_version=TW_VALUE_RULE_VERSION)
        selection_diagnostics = pristine_selection_diagnostics(evaluable_rows, args.market, rule_version=TW_VALUE_RULE_VERSION)
        financial_diagnostics["financial_valid_count"] = len(financial_valid)
        financial_diagnostics["financial_missing_count"] = max(0, len(candidates) - len(financial_valid))
        financial_diagnostics["financial_periods"] = sorted({str(item.get("reporting_period")) for item in fundamentals.values() if item.get("reporting_period")})
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
    stage("screening", timer, processed=len(rows), errors=[])

    timer = time.monotonic()
    pd.DataFrame(rows).to_csv(data_dir / f"{args.market}-value-scan.csv", index=False, encoding="utf-8-sig")
    if args.market == "taiwan":
        evidence_rows = []
        for candidate in candidates:
            ticker = str(candidate.get("ticker") or "")
            financial = fundamentals.get(ticker, {})
            quote = quotes.get(str(candidate.get("symbol") or ""), {})
            required_financial = ("eps_ytd", "total_net_income_ytd", "total_equity", "reporting_period")
            missing_financial = [field for field in required_financial if financial.get(field) is None]
            required_heat_fields = (*required_heat, "close", "as_of")
            missing_quote = [field for field in required_heat_fields if quote.get(field) is None]
            evidence_rows.append({
                "ticker": ticker,
                "name": candidate.get("name"),
                "pool": candidate.get("pool"),
                "symbol": candidate.get("symbol"),
                "financial": {
                    key: financial.get(key) for key in (
                        "reporting_period", "sector", "output_date", "source_url", "source_sha256",
                        "source_endpoints", "eps_ytd", "eps_field", "total_net_income_ytd",
                        "total_net_income_field", "total_equity", "total_equity_field",
                        "annualized_quality_ratio", "financial_parse_version", "last_checked_at",
                        "financial_complete", "financial_status",
                    )
                },
                "quote": quote,
                "scan_trading_date": target_trading_date,
                "quote_cutoff_at": quote_cutoff,
                "missing_financial_fields": missing_financial,
                "missing_quote_fields": missing_quote,
                "evaluable": not missing_financial and not missing_quote,
            })
        (data_dir / f"{args.market}-value-evidence.json").write_text(
            json.dumps({"schema_version": 1, "rule_version": TW_VALUE_RULE_VERSION, "records": evidence_rows}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    stage("output", timer, processed=len(rows), errors=[])
    complete_records = len(evaluable_rows)
    if args.market == "taiwan":
        # Record-level gaps, rather than endpoint call count, determine scan
        # completeness.  A bounded, validated financial cache may satisfy a
        # row while the endpoint outage remains visible in diagnostics.
        evaluable_tickers = {str(row.get("ticker")) for row in evaluable_rows}
        missing_tickers = {
            str(item["ticker"]) for item in candidates if str(item["ticker"]) not in evaluable_tickers
        }
        failed_total = len(missing_tickers) + len(universe_errors) + len(quote_errors) + len(share_errors)
        financial_errors_for_contract = [] if len(fundamentals) >= len(candidates) and financial_diagnostics.get("cache_used_count", 0) else fundamental_errors
        scan_complete = (
            len(candidates) == TAIWAN_VALUE_POOL_EXPECTED
            and not missing_tickers and not universe_errors and not expired()
            and not financial_errors_for_contract and not quote_errors and not share_errors
        )
    else:
        failed_total = len(universe_errors) + len(fundamental_errors) + len(quote_errors) + len(share_errors)
        scan_complete = failed_total == 0
    if scan_complete:
        scan_state = "complete"
    elif complete_records > 0:
        # ``partial`` is a completeness diagnostic, not a public scan state.
        # The research schema deliberately reserves ``building`` for a run
        # that has usable rows but has not covered the full pool yet.
        scan_state = "building"
    else:
        scan_state = "failed"
    if rows:
        candidate_state = "available"
    elif scan_state == "complete" and not share_errors:
        candidate_state = "no_candidates"
    elif share_errors or quote_errors or fundamental_errors or failed_total:
        candidate_state = "data_unavailable"
    else:
        candidate_state = "building" if args.market == "taiwan" else "data_unavailable"
    summary = {
        "requested": len(candidates),
        "requested_records": len(candidates),
        "universe_mode": "full",
        "universe_expected": len(candidates),
        "full_pool_expected": TAIWAN_VALUE_POOL_EXPECTED if args.market == "taiwan" else None,
        "universe_scanned": len(candidates),
        "universe_completed": complete_records,
        "universe_failed": failed_total,
        "data_complete": complete_records if args.market == "taiwan" else len(fundamentals),
        "candidates": len(rows),
        "formal_candidates": len(formal_rows),
        "observation_candidates": len(visible_observation_rows),
        "visible_candidate_count": len(rows),
        "formal_candidate_count": len(formal_rows),
        "observation_candidate_count": len(visible_observation_rows),
        "history_pending_count": 0,
        "source_failure_count": failed_total,
        "share_source_failure_count": len(share_errors),
        "official_share_coverage": len(share_counts) if args.market == "taiwan" else None,
        "official_share_missing_count": max(len(candidates) - len(share_counts), 0) if args.market == "taiwan" else None,
        "turnover_coverage": sum(1 for item in quotes.values() if item.get("turnover_rate") is not None),
        "incomplete_record_count": max(len(candidates) - complete_records, 0),
        "selection_diagnostics": selection_diagnostics,
        "failed": failed_total,
        "scan_state": scan_state,
        "scan_completeness": (
            "complete" if scan_complete
            else "partial" if complete_records > 0
            else "failed"
        ),
        "candidate_state": candidate_state,
        "complete_records": complete_records,
        "data_gap_counts": {
            "universe": len(universe_errors),
            "fundamentals": max(0, len(candidates) - (len(financial_valid) if args.market == "taiwan" else len(fundamentals))),
            "quotes": len(quote_errors),
            "shares": len(share_errors),
            "official_financial_endpoint": (
                0 if args.market == "taiwan" and len(fundamentals) >= len(candidates) and financial_diagnostics.get("cache_used_count", 0)
                else len(financial_diagnostics.get("endpoint_errors", [])) if args.market == "taiwan" else 0
            ),
        },
        "status": "可用" if failed_total == 0 else "部分缺漏",
        "universe_source": "Yuanta 0050+0051 PCF" if args.market == "taiwan" else "Nasdaq-100 + semiconductor/AI core",
        "financial_source": "TWSE official batch" if args.market == "taiwan" else "SEC EDGAR CompanyFacts",
        "sec_cache_hits": sum(1 for item in fundamentals.values() if item.get("sec_cache_used")) if args.market == "us" else 0,
        "sec_data_as_of": max((str(item.get("sec_data_fetched_at", "")) for item in fundamentals.values()), default=None) if args.market == "us" else None,
        "errors": universe_errors + fundamental_errors + quote_errors + share_errors,
        "error_details": {
            "universe": universe_errors,
            "fundamentals": fundamental_errors,
            "quotes": quote_errors,
            "shares": share_errors,
        },
        "mops_refresh_limit": None,
        "mops_calls": 0 if args.market == "taiwan" else None,
        "mops_history_used": False if args.market == "taiwan" else None,
        "rule_version": TW_VALUE_RULE_VERSION if args.market == "taiwan" else None,
        "parameter_hash": TW_VALUE_PARAMETER_HASH if args.market == "taiwan" else None,
        "scan_trading_date": target_trading_date,
        "quote_cutoff_at": quote_cutoff,
        "quote_evidence_count": len(quotes),
        "financial_diagnostics": financial_diagnostics if args.market == "taiwan" else None,
        "financial_period": (financial_diagnostics.get("financial_periods") or [None])[0] if args.market == "taiwan" else None,
        "financial_checked_at": max((str(item.get("last_checked_at", "")) for item in fundamentals.values()), default=None) if args.market == "taiwan" else None,
        "official_financial_coverage": sum(1 for item in fundamentals.values() if item.get("financial_complete") is True) if args.market == "taiwan" else None,
        "time_budget_seconds": args.time_budget_seconds,
        "deadline_exceeded": expired(),
        "stage_diagnostics": diagnostics["stages"],
        "partial_candidates_allowed": args.market == "taiwan" and complete_records < len(candidates),
        "evaluable_records": complete_records if args.market == "taiwan" else len(base_rows),
        "notice": "璞玉價值池獨立於技術策略；台股新版以 TWSE 當期批次財報核對 EPS 與年化獲利／期末權益估算，再檢查四項低熱度條件；僅提供公開財務觀察，不構成投資建議。",
    }
    if args.market == "taiwan" and complete_records < len(candidates):
        summary["candidate_state"] = "available_from_completed_records" if rows else "building"
        summary["status"] = "建檔中" if complete_records else "部分缺漏"
        summary["blocking_reason"] = "台股官方批次財報、行情或股數仍有個別資料缺漏；已核對紀錄可續用，未完成股票不列入完整排名。"
    elif args.market == "us" and failed_total:
        # A completed US run with missing SEC/VOO/quote inputs is unavailable,
        # not an empty candidate result.  This prevents the UI from implying
        # that the strict pool was evaluated successfully.
        summary["status"] = "資料暫時無法取得"
    if expired():
        summary["scan_state"] = "building" if complete_records > 0 else "failed"
        summary["candidate_state"] = "available_from_completed_records" if rows else "building"
        summary["status"] = "建檔中"
        summary["blocking_reason"] = "研究工作者內層期限已到；已保存的個股進度留待下一輪續跑。"
    save_diagnostics()
    (data_dir / f"{args.market}-value-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
