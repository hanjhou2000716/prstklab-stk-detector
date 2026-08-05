"""Conservative, explicit transaction-cost model for walk-forward research."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CostModel:
    market: str
    commission_bps: float
    tax_bps: float
    slippage_bps: float
    fx_bps: float = 0.0

    @classmethod
    def for_market(cls, market: str) -> CostModel:
        key = str(market).lower()
        if key == "taiwan":
            return cls(key, commission_bps=14.25, tax_bps=30.0, slippage_bps=10.0)
        if key == "us":
            return cls(key, commission_bps=0.0, tax_bps=0.0, slippage_bps=8.0, fx_bps=5.0)
        raise ValueError(f"unsupported market: {market}")

    def net_return(self, gross_return: float, *, turnover: float = 1.0) -> dict[str, Any]:
        total_bps = (self.commission_bps + self.tax_bps + self.slippage_bps + self.fx_bps) * max(0.0, turnover)
        cost = total_bps / 10_000
        return {"gross_return": gross_return, "cost_return": round(cost, 8), "net_return": round(gross_return - cost, 8), "cost_bps": total_bps}

