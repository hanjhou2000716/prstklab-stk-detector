"""Ephemeral, manual-input portfolio risk calculations.

This module intentionally does not read accounts, persist holdings, or place
orders. Callers must provide an in-memory position list and may discard the
result after rendering a private risk view.
"""

from __future__ import annotations

from collections import defaultdict
from statistics import mean
from typing import Any, Iterable


def _group_exposure(positions: list[dict[str, Any]], field: str, total: float) -> dict[str, float]:
    grouped: defaultdict[str, float] = defaultdict(float)
    for position in positions:
        grouped[str(position.get(field) or "未分類")] += float(position.get("value") or 0)
    return {key: round(value / total, 6) for key, value in sorted(grouped.items())} if total else {}


def portfolio_risk_snapshot(
    positions: Iterable[dict[str, Any]], returns: Iterable[float] | None = None, *, confidence: float = 0.95
) -> dict[str, Any]:
    """Calculate concentration, exposures, beta and optional historical VaR/CVaR."""
    if not 0 < confidence < 1:
        raise ValueError("confidence must be between 0 and 1")
    rows = [dict(item) for item in positions]
    if any(float(item.get("value") or 0) < 0 for item in rows):
        raise ValueError("position value cannot be negative")
    total = sum(float(item.get("value") or 0) for item in rows)
    weights = {str(item.get("ticker") or "未命名"): float(item.get("value") or 0) / total for item in rows} if total else {}
    beta = sum(weights.get(str(item.get("ticker") or "未命名"), 0) * float(item.get("beta") or 0) for item in rows)
    result: dict[str, Any] = {
        "position_count": len(rows),
        "total_value": round(total, 6),
        "weights": {key: round(value, 6) for key, value in sorted(weights.items())},
        "largest_position": max(weights.values(), default=0.0),
        "weighted_beta": round(beta, 6),
        "sector_exposure": _group_exposure(rows, "sector", total),
        "country_exposure": _group_exposure(rows, "country", total),
        "currency_exposure": _group_exposure(rows, "currency", total),
        "data_quality": "complete" if rows and all(item.get("ticker") and item.get("value") is not None for item in rows) else "partial",
        "persisted": False,
        "advice_allowed": False,
        "disclaimer": "僅供私人風險整理與教育性觀察，不構成投資建議。",
    }
    sample = sorted(float(value) for value in (returns or ()))
    if sample:
        index = max(0, min(len(sample) - 1, int((1 - confidence) * len(sample))))
        tail = sample[: index + 1]
        result.update({"return_observations": len(sample), "historical_var": round(-sample[index], 6), "historical_cvar": round(-mean(tail), 6)})
    else:
        result.update({"return_observations": 0, "historical_var": None, "historical_cvar": None})
    return result

