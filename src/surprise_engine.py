"""Transparent macro surprise calculations; never infer market direction alone."""

from __future__ import annotations

from typing import Any


def calculate_surprise(
    *, expected: float | None, actual: float | None, previous: float | None = None,
    historical_std: float | None = None,
) -> dict[str, Any]:
    """Return arithmetic surprise and a cautious interpretation."""
    result: dict[str, Any] = {"expected": expected, "actual": actual, "previous": previous, "status": "insufficient_evidence"}
    if expected is None or actual is None:
        return result
    surprise = actual - expected
    result["surprise"] = round(surprise, 6)
    result["surprise_pct_of_expected"] = None if expected == 0 else round(surprise / abs(expected) * 100, 3)
    result["surprise_z"] = None if not historical_std else round(surprise / abs(historical_std), 3)
    if previous is not None:
        result["change_from_previous"] = round(actual - previous, 6)
    result["status"] = "above_expectation" if surprise > 0 else "below_expectation" if surprise < 0 else "in_line"
    result["market_direction"] = "not_determined"
    result["note"] = "需搭配利率、匯率與相關市場同步反應，不能由 surprise 單獨推導漲跌。"
    return result

