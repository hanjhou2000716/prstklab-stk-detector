"""Fixed-sample, research-only walk-forward validation for PRStK strategies.

This module deliberately accepts *archived* bars, constituent snapshots and
fundamental snapshots.  It never downloads a current ETF constituent list for
an historical study: doing so would silently introduce survivorship bias.
Signals are calculated from data available at a rebalance close and enter at
the following completed bar's open.  Results are educational research output,
not trading instructions.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Callable

import numpy as np
import pandas as pd

from src.momentum_research import WEIGHTS, features
from src.price_action import PriceActionResearchScanner
from src.research_backtest import MARKET_COSTS, calculate_hypothetical_return
from src.resonance_research import score_bars
from src.resonance_smart_money import smart_money_conditions, smart_money_summary
from src.value_review import score_public_fundamentals


STRATEGIES = ("momentum", "resonance", "price_action", "value")


@dataclass(frozen=True)
class Window:
    name: str
    start: pd.Timestamp
    end: pd.Timestamp


def fixed_windows(config: dict[str, Any]) -> list[Window]:
    """Read disjoint, named fixed periods and reject ambiguous input."""
    windows: list[Window] = []
    for name in ("training", "validation", "test"):
        values = (config.get("fixed_windows") or {}).get(name)
        if not isinstance(values, list) or len(values) != 2:
            raise ValueError(f"fixed_windows.{name} must contain [start, end]")
        start, end = pd.Timestamp(values[0]).normalize(), pd.Timestamp(values[1]).normalize()
        if start >= end:
            raise ValueError(f"fixed window {name} has invalid dates")
        windows.append(Window(name, start, end))
    for previous, current in zip(windows, windows[1:]):
        if previous.end >= current.start:
            raise ValueError("fixed windows must not overlap")
    return windows


def _normalise_bars(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"Open", "High", "Low", "Close", "Volume"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"missing OHLCV columns: {', '.join(sorted(missing))}")
    result = frame.copy()
    result.index = pd.to_datetime(result.index).tz_localize(None).normalize()
    return result.sort_index().loc[:, ["Open", "High", "Low", "Close", "Volume"]].dropna()


def _snapshot_for(snapshots: list[dict[str, Any]], as_of: pd.Timestamp, market: str) -> dict[str, Any] | None:
    eligible = []
    for snapshot in snapshots:
        if snapshot.get("market") != market:
            continue
        try:
            snapshot_date = pd.Timestamp(snapshot["as_of"]).normalize()
        except (KeyError, TypeError, ValueError):
            continue
        if snapshot_date <= as_of:
            eligible.append((snapshot_date, snapshot))
    return max(eligible, key=lambda item: item[0])[1] if eligible else None


def _fundamental_for(snapshots: list[dict[str, Any]], ticker: str, as_of: pd.Timestamp, market: str) -> dict[str, Any] | None:
    eligible = []
    for snapshot in snapshots:
        if snapshot.get("market") != market or str(snapshot.get("ticker")) != ticker:
            continue
        try:
            snapshot_date = pd.Timestamp(snapshot["as_of"]).normalize()
        except (KeyError, TypeError, ValueError):
            continue
        if snapshot_date <= as_of and snapshot.get("point_in_time") is True:
            eligible.append((snapshot_date, snapshot))
    return max(eligible, key=lambda item: item[0])[1] if eligible else None


def survivorship_audit(
    snapshots: list[dict[str, Any]], *, market: str, require_point_in_time: bool = True,
) -> dict[str, Any]:
    """Expose whether the supplied constituent archive is safe for history."""
    relevant = [item for item in snapshots if item.get("market") == market]
    reasons: list[str] = []
    if not relevant:
        reasons.append("no universe snapshots supplied")
    for item in relevant:
        if require_point_in_time and item.get("point_in_time") is not True:
            reasons.append(f"{item.get('as_of', 'unknown')}: not marked point_in_time")
        source = str(item.get("source", "")).lower()
        if "current" in source:
            reasons.append(f"{item.get('as_of', 'unknown')}: current-constituent source is forbidden")
        if not isinstance(item.get("tickers"), list) or not item["tickers"]:
            reasons.append(f"{item.get('as_of', 'unknown')}: ticker membership is missing")
    dates = sorted({str(item.get("as_of")) for item in relevant})
    return {
        "status": "pass" if not reasons else "failed",
        "market": market,
        "snapshot_count": len(relevant),
        "snapshot_dates": dates,
        "reasons": reasons,
        "current_constituents_rejected": True,
        "delisted_symbols_required_when_known": True,
    }


def _monthly_signal_dates(anchor: pd.DataFrame, window: Window) -> list[pd.Timestamp]:
    eligible = anchor.loc[(anchor.index >= window.start) & (anchor.index <= window.end)]
    if eligible.empty:
        return []
    periods = eligible.index.to_period("M")
    return list(eligible.groupby(periods).tail(1).index)


def _momentum_rows(histories: dict[str, pd.DataFrame], tickers: list[str], market: str) -> list[dict[str, Any]]:
    rows = []
    threshold = 30_000_000 if market == "taiwan" else 5_000_000
    for ticker in tickers:
        bars = histories.get(ticker)
        if bars is None:
            continue
        result = features(bars)
        if result and result["above_ma5"] and float(result.get("turnover") or 0) >= threshold:
            rows.append({"ticker": ticker, **result})
    if not rows:
        return []
    frame = pd.DataFrame(rows)
    frame["score"] = sum(frame[key].rank(pct=True) * weight for key, weight in WEIGHTS.items()) / sum(WEIGHTS.values()) * 100
    return frame.sort_values("score", ascending=False).to_dict("records")


def _resonance_rows(histories: dict[str, pd.DataFrame], tickers: list[str], benchmark: pd.DataFrame | None, market: str) -> list[dict[str, Any]]:
    rows = []
    threshold = 30_000_000 if market == "taiwan" else 5_000_000
    for ticker in tickers:
        bars = histories.get(ticker)
        if bars is None or len(bars) < 150:
            continue
        fgi = score_bars(bars)
        conditions = smart_money_conditions(bars, benchmark)
        summary = smart_money_summary(conditions)
        turnover = float(bars.iloc[-1]["Close"] * bars.iloc[-1]["Volume"])
        if fgi is not None and fgi < 56 and summary["count"] >= 3 and turnover >= threshold:
            # Four confirmed conditions always rank ahead of a three-condition fallback.
            rows.append({"ticker": ticker, "score": summary["score"], "fgi": fgi, "condition_count": summary["count"], "conditions": summary["matched_labels"]})
    return sorted(rows, key=lambda item: (item["condition_count"], item["score"]), reverse=True)


def _price_action_rows(histories: dict[str, pd.DataFrame], tickers: list[str]) -> list[dict[str, Any]]:
    scanner = PriceActionResearchScanner()
    rows = []
    for ticker in tickers:
        bars = histories.get(ticker)
        if bars is None:
            continue
        result = scanner.scan_daily(bars)
        if result:
            rows.append({"ticker": ticker, "score": result["score"], "structures": result["funnel_labels"]})
    return sorted(rows, key=lambda item: item["score"], reverse=True)


def _value_rows(fundamentals: list[dict[str, Any]], tickers: list[str], as_of: pd.Timestamp, market: str) -> tuple[list[dict[str, Any]], list[str]]:
    rows, missing = [], []
    for ticker in tickers:
        snapshot = _fundamental_for(fundamentals, ticker, as_of, market)
        if snapshot is None:
            missing.append(ticker)
            continue
        score, checks = score_public_fundamentals(snapshot, market)
        rows.append({"ticker": ticker, "score": score, "checks": checks})
    return sorted(rows, key=lambda item: item["score"], reverse=True), missing


def _strategy_candidates(
    strategy: str, histories: dict[str, pd.DataFrame], tickers: list[str], benchmark: pd.DataFrame | None,
    fundamentals: list[dict[str, Any]], as_of: pd.Timestamp, market: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    if strategy == "momentum":
        return _momentum_rows(histories, tickers, market), []
    if strategy == "resonance":
        return _resonance_rows(histories, tickers, benchmark, market), []
    if strategy == "price_action":
        return _price_action_rows(histories, tickers), []
    if strategy == "value":
        return _value_rows(fundamentals, tickers, as_of, market)
    raise ValueError(f"unknown strategy: {strategy}")


def _summary(trades: list[dict[str, Any]]) -> dict[str, Any]:
    if not trades:
        return {"trade_count": 0, "average_net_return_percent": None, "win_rate_percent": None, "cost_drag_percent": None}
    returns = np.array([trade["net_return_percent"] for trade in trades], dtype=float)
    cumulative = np.cumprod(1 + returns / 100)
    peak = np.maximum.accumulate(cumulative)
    drawdown = (cumulative / peak - 1) * 100
    return {
        "trade_count": len(trades),
        "average_net_return_percent": round(float(returns.mean()), 4),
        "win_rate_percent": round(float((returns > 0).mean() * 100), 2),
        "total_cost_drag_percent": round(float(sum(trade["cost_drag_percent"] for trade in trades)), 4),
        "max_drawdown_percent": round(float(drawdown.min()), 4),
    }


def run_walk_forward(
    bars_by_ticker: dict[str, pd.DataFrame], universe_snapshots: list[dict[str, Any]], *, market: str,
    config: dict[str, Any], benchmark_bars: pd.DataFrame | None = None,
    fundamental_snapshots: list[dict[str, Any]] | None = None,
    strategies: tuple[str, ...] = STRATEGIES,
) -> dict[str, Any]:
    """Run every signal only with information that existed on its signal day."""
    if market not in MARKET_COSTS:
        raise ValueError("market must be taiwan or us")
    if not bars_by_ticker:
        raise ValueError("bars_by_ticker is empty")
    unknown = set(strategies) - set(STRATEGIES)
    if unknown:
        raise ValueError(f"unsupported strategies: {sorted(unknown)}")
    normalised = {ticker: _normalise_bars(frame) for ticker, frame in bars_by_ticker.items()}
    anchor = next(iter(normalised.values()))
    benchmark = _normalise_bars(benchmark_bars) if isinstance(benchmark_bars, pd.DataFrame) else None
    fundamentals = fundamental_snapshots or []
    audit = survivorship_audit(universe_snapshots, market=market, require_point_in_time=bool((config.get("survivorship_policy") or {}).get("require_point_in_time_universe", True)))
    results: dict[str, Any] = {strategy: {"windows": {}, "data_gaps": []} for strategy in strategies}
    top_n = int(config.get("top_n", 5))
    holding_days = int(config.get("holding_days", 20))
    minimum_history = int(config.get("minimum_history_days", 150))
    costs = (config.get("costs") or {}).get(market, MARKET_COSTS[market])

    for window in fixed_windows(config):
        for strategy in strategies:
            results[strategy]["windows"][window.name] = []
        for signal_date in _monthly_signal_dates(anchor, window):
            snapshot = _snapshot_for(universe_snapshots, signal_date, market)
            if snapshot is None or snapshot.get("point_in_time") is not True:
                for strategy in strategies:
                    results[strategy]["data_gaps"].append({"signal_date": str(signal_date.date()), "reason": "point-in-time universe snapshot unavailable"})
                continue
            tickers = [str(item) for item in snapshot.get("tickers", []) if str(item) in normalised]
            histories = {ticker: bars.loc[:signal_date] for ticker, bars in normalised.items() if ticker in tickers and len(bars.loc[:signal_date]) >= minimum_history}
            if not histories:
                continue
            benchmark_history = benchmark.loc[:signal_date] if benchmark is not None else None
            for strategy in strategies:
                candidates, missing_fundamentals = _strategy_candidates(strategy, histories, list(histories), benchmark_history, fundamentals, signal_date, market)
                if strategy == "value" and missing_fundamentals:
                    results[strategy]["data_gaps"].append({"signal_date": str(signal_date.date()), "reason": "point-in-time fundamentals unavailable", "tickers": missing_fundamentals})
                for candidate in candidates[:top_n]:
                    ticker = candidate["ticker"]
                    bars = normalised[ticker]
                    positions = np.flatnonzero(bars.index == signal_date)
                    if not len(positions) or positions[0] + holding_days >= len(bars):
                        continue
                    entry_row, exit_row = positions[0] + 1, positions[0] + holding_days
                    entry_price, exit_price = float(bars.iloc[entry_row]["Open"]), float(bars.iloc[exit_row]["Close"])
                    if entry_price <= 0 or exit_price <= 0:
                        continue
                    trade = calculate_hypothetical_return(entry_price, exit_price, market, commission_rate=costs.get("commission_rate"), slippage_rate=costs.get("slippage_rate"))
                    results[strategy]["windows"][window.name].append({
                        "ticker": ticker, "signal_date": str(signal_date.date()), "entry_date": str(bars.index[entry_row].date()),
                        "exit_date": str(bars.index[exit_row].date()), "score": round(float(candidate["score"]), 2),
                        "entry_price": round(entry_price, 4), "exit_price": round(exit_price, 4), **trade,
                    })
    for strategy in strategies:
        results[strategy]["summary"] = {name: _summary(trades) for name, trades in results[strategy]["windows"].items()}
    return {
        "status": "complete" if audit["status"] == "pass" else "blocked_by_survivorship_audit",
        "research_only": True,
        "methodology": {
            "signal_uses_data_through_close": True, "entry": "next available open", "exit": f"close after {holding_days} completed bars",
            "costs": costs, "fixed_windows": [{"name": item.name, "start": str(item.start.date()), "end": str(item.end.date())} for item in fixed_windows(config)],
        },
        "survivorship_audit": audit,
        "strategies": results,
    }
