"""Public, in-memory portfolio exposure diagnostics.

The module intentionally does not persist holdings or accept broker credentials.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class Position:
    symbol: str
    market_value: float
    sector: str = "unknown"
    country: str = "unknown"
    currency: str = "unknown"


def exposure_report(positions: Sequence[Position], *, total_cash: float = 0.0) -> dict[str, Any]:
    """Calculate concentration and geographic/sector exposure in memory only."""
    values = [max(0.0, float(position.market_value)) for position in positions]
    invested = sum(values)
    total = invested + max(0.0, float(total_cash))
    if total <= 0:
        return {"total_value": 0.0, "cash_weight": 0.0, "concentration": {}, "sector_weights": {}, "country_weights": {}, "currency_weights": {}, "research_only": True}
    def weights(attr: str) -> dict[str, float]:
        grouped: dict[str, float] = {}
        for position in positions:
            key = str(getattr(position, attr) or "unknown")
            grouped[key] = grouped.get(key, 0.0) + max(0.0, float(position.market_value))
        return {key: round(value / total, 6) for key, value in grouped.items()}
    return {
        "total_value": round(total, 6),
        "cash_weight": round(max(0.0, float(total_cash)) / total, 6),
        "concentration": {position.symbol: round(max(0.0, float(position.market_value)) / total, 6) for position in positions},
        "sector_weights": weights("sector"),
        "country_weights": weights("country"),
        "currency_weights": weights("currency"),
        "research_only": True,
        "not_a_trade_instruction": True,
    }


def stress_position_values(positions: Sequence[Position], shocks: Mapping[str, float]) -> dict[str, float]:
    """Apply transparent hypothetical shocks by symbol; no future return estimate."""
    return {position.symbol: round(float(position.market_value) * (1.0 + float(shocks.get(position.symbol, 0.0))), 6) for position in positions}
