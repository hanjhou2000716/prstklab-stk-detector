"""Third-stage public fundamental review for already-screened research candidates."""

from __future__ import annotations

from typing import Any


def metrics_from_info(info: dict[str, Any]) -> dict[str, float | None]:
    def number(key: str) -> float | None:
        value = info.get(key)
        return float(value) if isinstance(value, (int, float)) else None

    return {
        "net_income": number("netIncomeToCommon"),
        "market_cap": number("marketCap"),
        "roe": number("returnOnEquity"),
        "payout_ratio": number("payoutRatio"),
        "pe": number("trailingPE"),
    }


def score_metrics(metrics: dict[str, float | None]) -> int:
    """Score only reproducible public fields; business moat remains manual review."""
    return sum((
        (metrics.get("net_income") or 0) > 500_000_000,
        (metrics.get("market_cap") or 0) > 10_000_000_000,
        (metrics.get("roe") or 0) >= 0.17,
        0.20 <= (metrics.get("payout_ratio") or 0) <= 0.80,
    ))


def review_candidates(candidates: list[dict[str, str]], info_getter: Any) -> tuple[list[dict[str, Any]], list[str]]:
    """Enrich a bounded upstream candidate set without scanning every issuer's fundamentals."""
    reviewed, errors = [], []
    for item in candidates:
        try:
            metrics = metrics_from_info(info_getter(item["symbol"]))
        except Exception:
            errors.append(item["ticker"])
            continue
        reviewed.append({
            "ticker": item["ticker"], "name": item["name"], "score": score_metrics(metrics),
            "metrics_available": sum(value is not None for value in metrics.values()),
            "moat_review": "需人工檢視", **metrics,
        })
    reviewed.sort(key=lambda item: (item["score"], item["metrics_available"]), reverse=True)
    return reviewed[:5], errors
