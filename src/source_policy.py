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
        value = asdict(self)
        # ``asdict`` preserves tuple annotations.  Published contracts are
        # JSON-facing and must expose arrays consistently across producers.
        value["primary"] = list(self.primary)
        value["secondary"] = list(self.secondary)
        return value


_OVERRIDES: dict[str, SourcePolicy] = {
    "TAIEX": SourcePolicy("TAIEX", ("TWSE",), ("TAIFEX",), 15, 0.5, True),
    # Keys are normalized to uppercase by ``source_policy_for``.  Keep the
    # display ticker in the value while avoiding a case-sensitive lookup bug
    # for the canonical ``TPEx`` label.
    "TPEX": SourcePolicy("TPEx", ("TPEx",), ("TWSE MIS",), 30, 1.0, True),
    "BTC": SourcePolicy("BTC", ("Binance",), ("CoinGecko",), 10, 1.5),
    "ETH": SourcePolicy("ETH", ("Binance",), ("CoinGecko",), 10, 1.5),
    "WTI": SourcePolicy("WTI", ("Yahoo",), ("EIA",), 120, 2.0),
    "VIX": SourcePolicy("VIX", ("Yahoo",), ("official-history",), 1440, 2.0),
}


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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

    # TAIFEX TXF is a futures contract and its points are not the TAIEX cash
    # index.  Comparing the two prices directly can produce a false
    # discrepancy (or, worse, imply that one contract is a substitute for the
    # other).  For this pair only the independently observed direction and
    # timestamp are comparable.  The cash quote remains the displayed value.
    if str(ticker).strip().upper() == "TAIEX":
        if not primary or not secondary:
            return {
                "ticker": ticker,
                "cross_checked": False,
                "status": "secondary_unavailable",
                "comparison_basis": "direction_only",
                "price_comparable": False,
                "policy": policy.to_dict(),
            }
        first_direction = _as_float(primary.get("change_percent"))
        second_direction = _as_float(secondary.get("change_percent"))
        first_time = primary.get("quote_time") or primary.get("quote_date")
        second_time = secondary.get("quote_time") or secondary.get("quote_date")
        from src.market_crosscheck import _timestamp

        left = _timestamp(first_time)
        right = _timestamp(second_time)
        time_aligned = (
            left is not None
            and right is not None
            and abs((left - right).total_seconds()) <= policy.max_gap_minutes * 60
        )
        direction_agrees = (
            first_direction is not None
            and second_direction is not None
            and (abs(first_direction) < 0.05 or abs(second_direction) < 0.05
                 or (first_direction > 0) == (second_direction > 0))
        )
        return {
            "ticker": ticker,
            "cross_checked": bool(direction_agrees and time_aligned),
            "status": (
                "confirmed" if direction_agrees and time_aligned
                else "direction_mismatch" if not direction_agrees
                else "time_misaligned"
            ),
            "comparison_basis": "direction_only",
            "price_comparable": False,
            "direction_agrees": bool(direction_agrees),
            "time_aligned": bool(time_aligned),
            "policy": policy.to_dict(),
        }
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

