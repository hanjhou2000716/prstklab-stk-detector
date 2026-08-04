"""Explainable market-regime scoring for public risk observation."""

from __future__ import annotations

from typing import Any

REGIMES = ("Risk-on", "Neutral", "Risk-off", "Stress", "Crisis")


def classify_regime(factors: dict[str, float | int | None]) -> dict[str, Any]:
    """Score independent factors; positive is risk-seeking, negative defensive."""
    contributions: dict[str, float] = {}
    for name, value in factors.items():
        if value is not None:
            contributions[name] = round(float(value), 3)
    score = round(sum(contributions.values()), 3)
    if score >= 2.0:
        regime = "Risk-on"
    elif score >= 0.5:
        regime = "Neutral"
    elif score >= -1.5:
        regime = "Risk-off"
    elif score >= -3.0:
        regime = "Stress"
    else:
        regime = "Crisis"
    return {"regime": regime, "score": score, "factor_contributions": contributions, "evidence_sufficient": len(contributions) >= 2}

