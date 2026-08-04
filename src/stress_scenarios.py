"""Deterministic, non-predictive market stress scenarios."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class Shock:
    asset: str
    change: float
    unit: str = "return"


@dataclass(frozen=True)
class StressResult:
    scenario: str
    shocks: tuple[Shock, ...]
    affected_markets: tuple[str, ...]
    risk_level: str
    confirmations: tuple[str, ...]
    non_predictive: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {"scenario": self.scenario,
                "shocks": [{"asset": s.asset, "change": s.change, "unit": s.unit} for s in self.shocks],
                "affected_markets": list(self.affected_markets), "risk_level": self.risk_level,
                "confirmations": list(self.confirmations), "non_predictive": self.non_predictive}


SCENARIOS: dict[str, tuple[Shock, ...]] = {
    "technology_selloff": (Shock("nasdaq", -0.10), Shock("sox", -0.15), Shock("taiwan_semiconductor", -0.12)),
    "inflation_shock": (Shock("usd_twd", 0.05), Shock("us10y_yield", 1.0, "percentage_points"), Shock("oil", 0.20)),
    "liquidity_crisis": (Shock("vix", 35.0, "index_level"), Shock("vix", 50.0, "stress_level"), Shock("taiwan_liquidity", -0.30)),
}


def evaluate_scenario(name: str, *, observed: Mapping[str, float] | None = None) -> StressResult:
    """Return scenario consequences and confirmation checks, never a forecast."""
    if name not in SCENARIOS:
        raise KeyError(name)
    shocks = SCENARIOS[name]
    affected = {"technology_selloff": ("US technology", "semiconductors", "Taiwan equities"),
                "inflation_shock": ("USD/TWD", "rates", "oil", "gold", "equities"),
                "liquidity_crisis": ("equities", "credit", "Taiwan liquidity", "crypto")}[name]
    checks = tuple(f"verify {shock.asset} observation and timestamp" for shock in shocks)
    if observed is None:
        level = "scenario_only"
    else:
        level = "stress" if any(abs(float(observed.get(shock.asset, 0))) >= abs(shock.change) for shock in shocks) else "scenario_only"
    return StressResult(name, shocks, tuple(affected), level, checks)


def available_scenarios() -> tuple[str, ...]:
    return tuple(SCENARIOS)
