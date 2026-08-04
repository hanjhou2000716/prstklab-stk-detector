"""Paper portfolio ledger for validating neutral scenario advice."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PaperPosition:
    symbol: str
    advised_at: str
    visible_price: float
    invalidation: str
    prices: list[float] = field(default_factory=list)

    def update(self, price: float) -> None:
        self.prices.append(float(price))

    def result(self) -> dict[str, Any]:
        latest = self.prices[-1] if self.prices else self.visible_price
        return {"symbol": self.symbol, "advised_at": self.advised_at, "visible_price": self.visible_price,
                "latest_price": latest, "max_favorable": round(max(self.prices, default=self.visible_price) / self.visible_price - 1, 8),
                "max_adverse": round(min(self.prices, default=self.visible_price) / self.visible_price - 1, 8),
                "invalidation": self.invalidation, "research_only": True}


class PaperPortfolio:
    def __init__(self) -> None:
        self.positions: dict[str, PaperPosition] = {}

    def add(self, position: PaperPosition) -> None:
        if position.symbol in self.positions:
            raise ValueError("symbol already tracked")
        self.positions[position.symbol] = position

    def update(self, prices: dict[str, float]) -> None:
        for symbol, price in prices.items():
            if symbol in self.positions:
                self.positions[symbol].update(price)

    def snapshot(self) -> list[dict[str, Any]]:
        return [position.result() for position in self.positions.values()]
