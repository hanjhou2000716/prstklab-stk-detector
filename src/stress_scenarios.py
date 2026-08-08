"""Non-predictive public-market stress scenarios for risk observation."""

from __future__ import annotations

from typing import Any

SCENARIOS: dict[str, dict[str, float]] = {
    "nasdaq_shock": {"NASDAQ": -10.0},
    "semiconductor_shock": {"SOX": -15.0, "TSM": -12.0},
    "currency_stress": {"USD/TWD": 5.0, "US10Y": 1.0},
    "energy_supply_shock": {"WTI": 20.0, "BRENT": 20.0},
    "volatility_spike": {"VIX": 35.0},
}


def run_stress_scenario(
    scenario: str, exposures: dict[str, float], *, assumptions: dict[str, float] | None = None
) -> dict[str, Any]:
    """Apply transparent shock assumptions to exposure weights.

    Values are scenario changes, not expected returns.  The output is intended
    for education and risk review only, never for an execution decision.
    """
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown stress scenario: {scenario}")
    shocks = dict(SCENARIOS[scenario])
    shocks.update(assumptions or {})
    contributions = []
    for ticker, weight in exposures.items():
        shock = float(shocks.get(ticker, 0.0))
        contributions.append({"ticker": ticker, "weight": float(weight), "shock_percent": shock, "weighted_effect": float(weight) * shock / 100})
    total_effect = round(sum(item["weighted_effect"] for item in contributions), 6)
    return {
        "scenario": scenario,
        "assumptions": shocks,
        "contributions": contributions,
        "estimated_weighted_effect": total_effect,
        "risk_level": "stress" if abs(total_effect) >= 5 else "warning" if abs(total_effect) >= 2 else "normal",
        "non_predictive": True,
        "disclaimer": "情境壓力測試僅供公開資訊教育性觀察，不構成投資建議。",
    }

