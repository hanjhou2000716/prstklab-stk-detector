"""Material-change thresholds shared by price and event alert paths."""
from __future__ import annotations

THRESHOLDS = {"market_index": 0.7, "equity": 1.0, "volatility_index": 1.0, "crypto": 1.5, "commodity": 1.5}

def threshold_for(asset_class: str) -> float:
    return THRESHOLDS.get(asset_class, 1.0)

def has_material_change(*, previous_change: float | None, current_change: float | None, asset_class: str, direction_reversed: bool = False, new_evidence: bool = False, lifecycle_change: bool = False) -> bool:
    if direction_reversed or new_evidence or lifecycle_change:
        return True
    if previous_change is None or current_change is None:
        return False
    return abs(current_change - previous_change) >= threshold_for(asset_class)

def classify_price_pattern(*, daily_percent: float | None, move_15m: float | None) -> str:
    daily = float(daily_percent or 0)
    intraday = None if move_15m is None else float(move_15m)
    if daily > 3 and intraday is not None and intraday > 0.7:
        return "intraday_acceleration"
    if daily > 3 and intraday is not None and intraday < -0.3:
        return "gain_fading"
    if daily < 0 and intraday is not None and intraday > 1:
        return "fast_rebound"
    if daily < -3:
        return "sharp_drop"
    if daily > 3:
        return "daily_breakout"
    return "high_level_consolidation" if daily >= 0 else "direction_reversal" if intraday is not None and daily * intraday < 0 else "high_level_consolidation"
