"""Rolling cross-asset relationship and contagion observations."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any


def rolling_correlation(left: Sequence[float], right: Sequence[float], window: int = 20) -> float | None:
    """Return the latest Pearson correlation only when a full window exists."""
    if window < 2 or len(left) < window or len(right) < window:
        return None
    x = [float(value) for value in left[-window:]]
    y = [float(value) for value in right[-window:]]
    mx, my = sum(x) / window, sum(y) / window
    numerator = sum((a - mx) * (b - my) for a, b in zip(x, y, strict=True))
    denominator = math.sqrt(sum((a - mx) ** 2 for a in x) * sum((b - my) ** 2 for b in y))
    return None if denominator == 0 else round(numerator / denominator, 4)


def detect_contagion(observations: dict[str, dict[str, float | None]]) -> dict[str, Any]:
    """Flag synchronized stress without predicting a future price move."""
    checks: list[str] = []
    equities = observations.get("equities") or {}
    if equities.get("change_percent", 0) is not None and float(equities.get("change_percent") or 0) <= -3:
        checks.append("equities_down")
    vix = observations.get("vix") or {}
    if vix.get("change_percent", 0) is not None and float(vix.get("change_percent") or 0) >= 10:
        checks.append("vix_up")
    usd = observations.get("usd") or {}
    if usd.get("change_percent", 0) is not None and float(usd.get("change_percent") or 0) >= 1:
        checks.append("usd_up")
    return {"contagion": len(checks) >= 2, "confirmed_signals": checks, "status": "observed" if checks else "no_confirmed_sync"}
