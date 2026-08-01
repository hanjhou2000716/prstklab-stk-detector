"""Public-data Pristine Value screening.

The formal list follows eight independently verifiable Taiwan-Pristine-style
conditions: three quality conditions and five non-hotness conditions.  A
separate observation list contains complete records matching 6/8 or 7/8;
missing history is never converted into a pass.
"""

from __future__ import annotations

from math import sqrt
from typing import Any

import pandas as pd


TW_NET_INCOME_MINIMUM = 5_000_000_000
US_NET_INCOME_MINIMUM = 500_000_000
HEAT_METRICS = ("average_turnover", "average_volume", "turnover_rate", "return_3m", "volatility")
PRISTINE_QUALITY_FIELDS = (
    "three_year_eps_positive",
    "four_quarter_eps_positive",
    "three_year_dividend_paid",
)


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def heat_metrics(bars: pd.DataFrame, shares_outstanding: float | None = None) -> dict[str, float | None]:
    """Calculate public three-month heat observations from completed bars."""
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
                below = sum(item < value for item in available)
                tied = sum(item == value for item in available)
                row[f"{metric}_percentile"] = round((below + tied / 2) / len(available) * 100, 1)
    return output


def quality_checks(metrics: dict[str, Any], market: str) -> tuple[bool, list[str], list[str]]:
    """Legacy supplemental quality score; strict public-history disclosure."""
    minimum_income = TW_NET_INCOME_MINIMUM if market == "taiwan" else US_NET_INCOME_MINIMUM
    checks: list[str] = []
    missing: list[str] = []
    for key in PRISTINE_QUALITY_FIELDS:
        value = metrics.get(key)
        if value is True:
            checks.append(key)
        elif value is None:
            missing.append(key)
        else:
            return False, checks, missing
    net_income = _number(metrics.get("net_income"))
    if net_income is None:
        missing.append("net_income")
    elif net_income >= minimum_income:
        checks.append("net_income_minimum")
    else:
        return False, checks, missing
    roe = _number(metrics.get("roe"))
    if metrics.get("roe_stable") is True or (roe is not None and roe >= 0.17):
        checks.append("roe_17_percent")
    elif roe is None:
        missing.append("roe")
    else:
        return False, checks, missing
    return not missing, checks, missing


def pristine_score(row: dict[str, Any], market: str) -> tuple[float, list[str], list[str]]:
    """Supplemental 0-100 ranking; it does not override the 8-condition gate."""
    quality_ok, checks, missing = quality_checks(row, market)
    score = 50.0 if quality_ok else max(0.0, 10.0 * len(checks))
    pe = _number(row.get("pe"))
    if pe is not None and 0 < pe <= 25:
        score += 15
    elif pe is None:
        missing.append("pe")
    heat_ok = 0
    for metric in HEAT_METRICS:
        percentile = _number(row.get(f"{metric}_percentile"))
        if percentile is None:
            missing.append(f"{metric}_percentile")
        elif percentile < 90:
            heat_ok += 1
    score += heat_ok / len(HEAT_METRICS) * 35
    if row.get("financial_source"):
        score += 5
    return round(min(score, 100), 1), checks, list(dict.fromkeys(missing))


def pristine_conditions(row: dict[str, Any]) -> tuple[int, int, list[str], list[str]]:
    """Return matched/total and explain the eight independent conditions."""
    checks: list[str] = []
    missing: list[str] = []
    matched = 0
    for field in PRISTINE_QUALITY_FIELDS:
        value = row.get(field)
        if value is True:
            matched += 1
            checks.append(field)
        elif value is None:
            missing.append(field)
    for metric in HEAT_METRICS:
        percentile = _number(row.get(f"{metric}_percentile"))
        if percentile is None:
            missing.append(f"{metric}_percentile")
        elif percentile < 90:
            matched += 1
            checks.append(f"{metric}_below_top_decile")
    return matched, len(PRISTINE_QUALITY_FIELDS) + len(HEAT_METRICS), checks, missing


def _ranked_pristine_rows(rows: list[dict[str, Any]], market: str) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for row in heat_percentiles(rows):
        score, score_checks, score_missing = pristine_score(row, market)
        matched, total, condition_checks, condition_missing = pristine_conditions(row)
        ranked.append({
            **row,
            "score": score,
            "value_checks": list(dict.fromkeys(condition_checks + score_checks)),
            # Only the eight formal conditions gate candidate status.  PE,
            # ROE and net-income are supplemental ranking context and may be
            # unavailable without invalidating a fully verified 8/8 record.
            "verification_gaps": list(dict.fromkeys(condition_missing)),
            "supplemental_gaps": list(dict.fromkeys(score_missing)),
            "pristine_conditions_matched": matched,
            "pristine_conditions_total": total,
            "condition_count": f"{matched}/{total}",
        })
    return ranked


def review_pristine_pool(rows: list[dict[str, Any]], market: str, limit: int = 5) -> list[dict[str, Any]]:
    """Return formal candidates only when all eight conditions are verified."""
    scored = []
    for item in _ranked_pristine_rows(rows, market):
        if item["pristine_conditions_matched"] != item["pristine_conditions_total"] or item["verification_gaps"]:
            continue
        scored.append({
            **item,
            "list_type": "formal",
            "quality_verified": True,
            "heat_verified": True,
            "strategy_label": "璞玉價值",
        })
    scored.sort(key=lambda item: (item["pristine_conditions_matched"], item["score"]), reverse=True)
    return scored[:limit]


def review_pristine_observation_pool(rows: list[dict[str, Any]], market: str, limit: int = 5) -> list[dict[str, Any]]:
    """Return complete observations matching at least six but fewer than eight."""
    scored = []
    for item in _ranked_pristine_rows(rows, market):
        matched = item["pristine_conditions_matched"]
        if item["verification_gaps"] or matched < 6 or matched >= item["pristine_conditions_total"]:
            continue
        scored.append({
            **item,
            "list_type": "observation",
            "quality_verified": matched >= len(PRISTINE_QUALITY_FIELDS),
            "heat_verified": matched >= len(PRISTINE_QUALITY_FIELDS) + len(HEAT_METRICS),
            "strategy_label": "璞玉價值｜觀察名單",
        })
    scored.sort(key=lambda item: (item["pristine_conditions_matched"], item["score"]), reverse=True)
    return scored[:limit]
