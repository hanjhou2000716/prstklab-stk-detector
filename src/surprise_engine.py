"""Transparent macro surprise calculations; never infer market direction alone."""

from __future__ import annotations

from typing import Any


def calculate_surprise(
    *, expected: float | None, actual: float | None, previous: float | None = None,
    historical_std: float | None = None, revision: float | None = None,
    release_time: str | None = None, source_url: str | None = None,
) -> dict[str, Any]:
    """Return arithmetic surprise with point-in-time provenance.

    A surprise is a measurement against a reference, not a directional trading
    signal. Missing observations remain explicit so a caller cannot turn a
    partially populated macro calendar into a confident market conclusion.
    """
    result: dict[str, Any] = {
        "expected": expected, "actual": actual, "previous": previous,
        "revision": revision, "release_time": release_time,
        "source_url": source_url, "status": "insufficient_evidence",
        "market_direction": "not_determined",
    }
    if expected is None or actual is None:
        return result
    surprise = actual - expected
    result["surprise"] = round(surprise, 6)
    result["surprise_pct_of_expected"] = None if expected == 0 else round(surprise / abs(expected) * 100, 3)
    result["surprise_z"] = (
        None if historical_std is None or historical_std <= 0
        else round(surprise / historical_std, 3)
    )
    if previous is not None:
        result["change_from_previous"] = round(actual - previous, 6)
    result["status"] = "above_expectation" if surprise > 0 else "below_expectation" if surprise < 0 else "in_line"
    result["note"] = "公布值與預期的差異僅描述資料 surprise；市場方向仍需搭配價格、利率與其他來源核對。"
    return result
