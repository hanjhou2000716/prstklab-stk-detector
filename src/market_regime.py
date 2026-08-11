"""Explainable market-regime scoring for public risk observation."""

from __future__ import annotations

from typing import Any

REGIMES = ("Risk-on", "Neutral", "Risk-off", "Stress", "Crisis")
EXPECTED_FACTORS = ("trend", "breadth", "volatility", "credit", "rates", "usd", "gold", "oil", "crypto")


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
    missing_factors = [name for name in EXPECTED_FACTORS if name not in contributions]
    evidence_sufficient = len(contributions) >= 2
    return {
        "regime": regime,
        "score": score,
        "factor_contributions": contributions,
        "missing_factors": missing_factors,
        "factor_count": len(contributions),
        "evidence_sufficient": evidence_sufficient,
        "evidence_status": "sufficient" if evidence_sufficient else "insufficient_evidence",
        "data_quality_score": round(min(100.0, len(contributions) / len(EXPECTED_FACTORS) * 100), 1),
        "non_predictive": True,
    }

