"""Versioned source-priority and cross-check policy for public market data."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from src.market_crosscheck import MARKET_SOURCE_PAIRS, compare_quotes


@dataclass(frozen=True)
class SourcePolicy:
    ticker: str
    primary: tuple[str, ...]
    secondary: tuple[str, ...]
    max_gap_minutes: int = 30
    max_gap_percent: float = 1.0
    official_required: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_OVERRIDES: dict[str, SourcePolicy] = {
    "TAIEX": SourcePolicy("TAIEX", ("TWSE",), ("TAIFEX",), 15, 0.5, True),
    "TPEx": SourcePolicy("TPEx", ("TPEx",), ("TWSE MIS",), 30, 1.0, True),
    "BTC": SourcePolicy("BTC", ("Binance",), ("CoinGecko",), 10, 1.5),
    "ETH": SourcePolicy("ETH", ("Binance",), ("CoinGecko",), 10, 1.5),
    "WTI": SourcePolicy("WTI", ("Yahoo",), ("EIA",), 120, 2.0),
    "VIX": SourcePolicy("VIX", ("Yahoo",), ("official-history",), 1440, 2.0),
}


def source_policy_for(ticker: str) -> SourcePolicy:
    """Return the policy without silently treating an unknown market as verified."""
    key = str(ticker or "").strip().upper()
    if key in _OVERRIDES:
        return _OVERRIDES[key]
    pair = MARKET_SOURCE_PAIRS.get(key)
    if pair:
        return SourcePolicy(key, (pair[0],), (pair[1],), 30, 1.0)
    return SourcePolicy(key, (), (), 30, 1.0)


def evaluate_crosscheck(
    ticker: str,
    primary: dict[str, Any] | None,
    secondary: dict[str, Any] | None,
) -> dict[str, Any]:
    """Evaluate one pair and expose the reason when it cannot be confirmed."""
    policy = source_policy_for(ticker)
    if not policy.primary or not policy.secondary:
        return {"ticker": ticker, "cross_checked": False, "status": "policy_missing", "policy": policy.to_dict()}
    result = compare_quotes(
        primary,
        secondary,
        max_age_minutes=policy.max_gap_minutes,
        max_gap_percent=policy.max_gap_percent,
    )
    result.update({"ticker": ticker, "policy": policy.to_dict()})
    if policy.official_required and not primary:
        result["status"] = "official_primary_unavailable"
    return result

