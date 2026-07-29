"""Research-only Pristine Value (璞玉價值) screening rules.

The module separates quality from short-term heat.  It intentionally returns
coverage notes rather than inventing unavailable TWSE/MOPS or SEC fields.
"""

from __future__ import annotations

from math import sqrt
from typing import Any

import pandas as pd


TW_NET_INCOME_MINIMUM = 5_000_000_000
US_NET_INCOME_MINIMUM = 500_000_000
HEAT_METRICS = ("average_turnover", "average_volume", "turnover_rate", "return_3m", "volatility")


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def heat_metrics(bars: pd.DataFrame, shares_outstanding: float | None = None) -> dict[str, float | None]:
    """Calculate public three-month heat observations from completed daily bars."""
    if bars.empty or not {"Close", "Volume"}.issubset(bars.columns):
        return {key: None for key in HEAT_METRICS}
    frame = bars[["Close", "Volume"]].dropna().tail(63)
    if len(frame) < 40 or (frame["Close"] <= 0).any():
        return {key: None for key in HEAT_METRICS}
    returns = frame["Close"].pct_change().dropna()
    average_turnover = float((frame["Close"] * frame["Volume"]).mean())
    average_volume = float(frame["Volume"].mean())
    turnover_rate = None
    if isinstance(shares_outstanding, (int, float)) and shares_outstanding > 0:
        turnover_rate = float(frame["Volume"].mean() / shares_outstanding)
    return {
        "average_turnover": average_turnover,
        "average_volume": average_volume,
        "turnover_rate": turnover_rate,
        "return_3m": round(float(frame["Close"].iloc[-1] / frame["Close"].iloc[0] - 1), 6),
        "volatility": round(float(returns.std(ddof=0) * sqrt(252)), 6) if len(returns) >= 2 else None,
    }


def heat_percentiles(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach cross-pool percentiles; missing public fields remain explicit."""
    output = [dict(row) for row in rows]
    for metric in HEAT_METRICS:
        available = sorted(_number(row.get(metric)) for row in output if _number(row.get(metric)) is not None)
        if not available:
            continue
        for row in output:
            value = _number(row.get(metric))
            if value is None:
                row[f"{metric}_percentile"] = None
            else:
                # Mid-rank treatment prevents identical ordinary observations
                # from all being mislabelled as the market's hottest decile.
                below = sum(item < value for item in available)
                tied = sum(item == value for item in available)
                row[f"{metric}_percentile"] = round((below + tied / 2) / len(available) * 100, 1)
    return output


def quality_checks(metrics: dict[str, Any], market: str) -> tuple[bool, list[str], list[str]]:
    """Return strict verified checks plus missing-field disclosures."""
    minimum_income = TW_NET_INCOME_MINIMUM if market == "taiwan" else US_NET_INCOME_MINIMUM
    checks: list[str] = []
    missing: list[str] = []
    for key, label in (
        ("three_year_eps_positive", "近三年 EPS 均為正"),
        ("four_quarter_eps_positive", "近四季 EPS 均為正"),
        ("three_year_dividend_paid", "近三年持續配息"),
    ):
        if metrics.get(key) is True:
            checks.append(label)
        elif metrics.get(key) is None:
            missing.append(label)
        else:
            return False, checks, missing
    net_income = _number(metrics.get("net_income"))
    if net_income is None:
        missing.append("最新淨利")
    elif net_income >= minimum_income:
        checks.append("淨利規模達門檻")
    else:
        return False, checks, missing
    roe = _number(metrics.get("roe"))
    if metrics.get("roe_stable") is True:
        checks.append("三年 ROE 穩定達 17%")
    elif roe is not None and roe >= 0.17:
        checks.append("最新 ROE 達 17%")
    elif roe is None:
        missing.append("ROE")
    else:
        return False, checks, missing
    # A missing historic field does not become a false claim.  It is reported
    # as provisional and cannot receive the full quality score.
    return not missing, checks, missing


def pristine_score(row: dict[str, Any], market: str) -> tuple[float, list[str], list[str]]:
    """Score verified quality, valuation and non-heat observations on 0-100."""
    quality_ok, checks, missing = quality_checks(row, market)
    score = 0.0
    if quality_ok:
        score += 50
    else:
        score += max(0, 10 * len(checks))
    pe = _number(row.get("pe"))
    if pe is not None and 0 < pe <= 25:
        score += 15
        checks.append("本益比位於可檢視區間")
    elif pe is None:
        missing.append("本益比")
    heat_ok = 0
    for metric in HEAT_METRICS:
        percentile = _number(row.get(f"{metric}_percentile"))
        if percentile is None:
            missing.append(f"三月{metric}熱度")
        elif percentile < 90:
            heat_ok += 1
        else:
            checks.append(f"{metric} 位於市場前 10% 熱度")
    score += heat_ok / len(HEAT_METRICS) * 35
    if heat_ok == len(HEAT_METRICS):
        checks.append("未落入三月熱度前 10%")
    if row.get("financial_source"):
        score += 5
    return round(min(score, 100), 1), checks, list(dict.fromkeys(missing))


def review_pristine_pool(rows: list[dict[str, Any]], market: str, limit: int = 5) -> list[dict[str, Any]]:
    """Rank public observations and never conceal incomplete verification."""
    scored = []
    for row in heat_percentiles(rows):
        score, checks, missing = pristine_score(row, market)
        quality_ok, _, _ = quality_checks(row, market)
        hot = any((_number(row.get(f"{metric}_percentile")) or 0) >= 90 for metric in HEAT_METRICS)
        heat_complete = all(_number(row.get(f"{metric}_percentile")) is not None for metric in HEAT_METRICS)
        if not quality_ok or hot or not heat_complete:
            continue
        scored.append({
            **row,
            "score": score,
            "value_checks": checks,
            "verification_gaps": missing,
            "quality_verified": quality_ok,
            "heat_verified": True,
            "strategy_label": "璞玉價值",
        })
    scored.sort(key=lambda item: (item["quality_verified"], item["heat_verified"], item["score"]), reverse=True)
    return scored[:limit]
