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
    """Flag synchronized stress without predicting a future price move.

    Explicitly stale, delayed, unavailable, or non-alertable quotes remain
    visible but cannot count as market-synchronisation evidence.
    """
    checks: list[str] = []
    evidence: list[dict[str, Any]] = []
    unusable_inputs: list[str] = []

    def eligible(name: str, item: dict[str, Any]) -> bool:
        freshness = str(item.get("freshness") or item.get("data_status") or "").lower()
        if freshness in {"stale", "delayed", "unavailable", "failed", "unknown"}:
            unusable_inputs.append(name)
            return False
        if item.get("quote_delayed") is True or item.get("alert_eligible") is False:
            unusable_inputs.append(name)
            return False
        return True

    def add_signal(name: str, item: dict[str, Any], label: str) -> None:
        if not eligible(name, item):
            return
        checks.append(label)
        evidence.append({
            "name": name,
            "source_url": item.get("source_url"),
            "fetched_at": item.get("fetched_at"),
            "freshness": item.get("freshness") or item.get("data_status") or "unspecified",
            "data_quality_score": item.get("data_quality_score"),
        })
    equities = observations.get("equities") or {}
    if equities.get("change_percent", 0) is not None and float(equities.get("change_percent") or 0) <= -3:
        add_signal("equities", equities, "equities_down")
    vix = observations.get("vix") or {}
    if vix.get("change_percent", 0) is not None and float(vix.get("change_percent") or 0) >= 10:
        add_signal("vix", vix, "vix_up")
    usd = observations.get("usd") or {}
    if usd.get("change_percent", 0) is not None and float(usd.get("change_percent") or 0) >= 1:
        add_signal("usd", usd, "usd_up")
    required = ("equities", "vix", "usd")
    missing_inputs = [name for name in required if name not in observations]
    usable_count = len([name for name in required if name in observations and name not in unusable_inputs])
    confirmed = len(checks) >= 2
    return {
        "contagion": confirmed,
        "confirmed_signals": checks,
        "signal_evidence": evidence,
        "status": "observed" if confirmed else "insufficient_evidence" if checks or unusable_inputs else "no_confirmed_sync",
        "missing_inputs": missing_inputs,
        "unusable_inputs": sorted(set(unusable_inputs)),
        "evidence_sufficient": confirmed,
        "data_quality_score": round(usable_count / len(required) * 100, 1),
        "non_predictive": True,
    }
