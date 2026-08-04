"""Explicit gross/net transaction cost model for Taiwan and US research."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CostBreakdown:
    commission: float
    tax: float
    spread: float
    slippage: float
    fx: float

    @property
    def total(self) -> float:
        return self.commission + self.tax + self.spread + self.slippage + self.fx


DEFAULTS = {
    "taiwan": {"commission": 0.001425, "tax": 0.003, "spread": 0.0005, "slippage": 0.001, "fx": 0.0},
    "us": {"commission": 0.00005, "tax": 0.0, "spread": 0.001, "slippage": 0.001, "fx": 0.001},
}


def estimate_cost(market: str, notional: float, *, side: str = "round_trip", overrides: dict[str, float] | None = None) -> CostBreakdown:
    if market not in DEFAULTS:
        raise KeyError(market)
    if notional < 0:
        raise ValueError("notional must be non-negative")
    rates = {**DEFAULTS[market], **(overrides or {})}
    multiplier = 2.0 if side == "round_trip" else 1.0
    return CostBreakdown(*(round(notional * max(0.0, float(rates[name])) * multiplier, 6)
                           for name in ("commission", "tax", "spread", "slippage", "fx")))


def net_return(gross_return: float, cost: CostBreakdown) -> float:
    return float(gross_return) - cost.total
