"""Append-only, research-only paper portfolio observations.

This module records what was visible when a candidate or alert was published;
it never places orders and never accepts private account data.  Missing prices
remain explicit instead of being replaced with a synthetic fill.
"""
from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

HORIZONS = (5, 20, 60)
DISCLAIMER = "僅供公開資訊整理與教育性觀察，不構成投資建議。"


def _timestamp(value: Any = None) -> str:
    if value is None or not str(value).strip():
        return datetime.now(UTC).isoformat()
    return str(value).strip()


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def record_paper_entry(
    candidate: dict[str, Any],
    *,
    release_id: str,
    snapshot_id: str,
    observed_at: str | None = None,
    price: Any = None,
    horizons: Iterable[int] = HORIZONS,
) -> dict[str, Any]:
    """Record a public candidate as an observation, not a trade instruction."""
    if not str(release_id).strip() or not str(snapshot_id).strip():
        raise ValueError("release_id and snapshot_id are required")
    ticker = str(candidate.get("ticker") or candidate.get("symbol") or "").strip()
    if not ticker:
        raise ValueError("candidate ticker is required")
    normalized_horizons = sorted({int(day) for day in horizons if int(day) > 0})
    if not normalized_horizons:
        raise ValueError("at least one positive horizon is required")
    return {
        "paper_id": f"{release_id}:{snapshot_id}:{ticker}",
        "ticker": ticker,
        "name": str(candidate.get("name") or ticker),
        "strategy": candidate.get("strategy"),
        "strategy_version": candidate.get("strategy_version"),
        "release_id": str(release_id),
        "snapshot_id": str(snapshot_id),
        "observed_at": _timestamp(observed_at),
        "observed_price": _number(price if price is not None else candidate.get("close")),
        "horizons_days": normalized_horizons,
        "simulated_returns": {str(day): None for day in normalized_horizons},
        "status": "open",
        "invalidation_condition": candidate.get("invalidation") or candidate.get("invalidation_condition"),
        "advice_state": candidate.get("advice_gate") or "observation_only",
        "paper_only": True,
        "disclaimer": DISCLAIMER,
    }


def update_paper_entry(
    entry: dict[str, Any],
    *,
    price: Any = None,
    as_of: str | None = None,
    horizon_days: int | None = None,
    invalidated: bool = False,
    final: bool = False,
) -> dict[str, Any]:
    """Append a marked observation; do not infer a result when a price is absent."""
    updated = dict(entry)
    entry_price = _number(entry.get("observed_price"))
    mark = _number(price)
    if horizon_days is not None:
        if int(horizon_days) <= 0:
            raise ValueError("horizon_days must be positive")
        returns = dict(updated.get("simulated_returns") or {})
        simulated_return: float | None = None
        if entry_price is not None and entry_price != 0 and mark is not None:
            simulated_return = round((mark - entry_price) / entry_price, 6)
        returns[str(int(horizon_days))] = simulated_return
        updated["simulated_returns"] = returns
    updated["last_price"] = mark
    updated["last_observed_at"] = _timestamp(as_of)
    updated["status"] = "invalidated" if invalidated else ("closed" if final else "open")
    updated["paper_only"] = True
    updated["disclaimer"] = DISCLAIMER
    return updated
