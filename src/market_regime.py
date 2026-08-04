"""Explainable market-regime classification from public risk factors."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


REGIMES = ("Risk-on", "Neutral", "Risk-off", "Stress", "Crisis")
DEFAULT_WEIGHTS = {
    "index_trend": 1.0, "breadth": 1.0, "volatility": 1.0, "credit": 1.0,
    "rates": 0.8, "usd": 0.6, "gold": 0.4, "oil": 0.4, "crypto": 0.4,
}


@dataclass(frozen=True)
class RegimeResult:
    regime: str
    score: float
    contributions: dict[str, float]
    missing_factors: tuple[str, ...]
    data_quality: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "regime": self.regime,
            "score": self.score,
            "contributions": self.contributions,
            "missing_factors": list(self.missing_factors),
            "data_quality": self.data_quality,
            "research_only": True,
        }


def classify_regime(score: float) -> str:
    if score <= -0.75:
        return "Crisis"
    if score <= -0.45:
        return "Stress"
    if score <= -0.15:
        return "Risk-off"
    if score <= 0.15:
        return "Neutral"
    return "Risk-on"


def evaluate_regime(factors: Mapping[str, Any], *, weights: Mapping[str, float] | None = None) -> RegimeResult:
    """Use supplied normalized factors in [-1, 1]; missing data is disclosed."""
    chosen = dict(weights or DEFAULT_WEIGHTS)
    contributions: dict[str, float] = {}
    missing: list[str] = []
    total_weight = 0.0
    weighted = 0.0
    for name, weight in chosen.items():
        try:
            value = float(factors[name])
        except (KeyError, TypeError, ValueError):
            missing.append(name)
            continue
        if not -1 <= value <= 1:
            raise ValueError(f"factor {name} must be between -1 and 1")
        contribution = value * float(weight)
        contributions[name] = round(contribution, 4)
        weighted += contribution
        total_weight += float(weight)
    if not total_weight:
        return RegimeResult("Neutral", 0.0, {}, tuple(missing), "failed")
    score = max(-1.0, min(1.0, weighted / total_weight))
    quality = "complete" if not missing else "partial" if contributions else "failed"
    return RegimeResult(classify_regime(score), round(score, 4), contributions, tuple(missing), quality)