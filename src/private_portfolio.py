"""Local-only portfolio risk view with an explicit privacy boundary.

The public release pipeline must never receive personal holdings.  This
adapter accepts caller-owned in-memory rows, delegates calculations to the
existing risk engine, and marks the result as ineligible for publication or
Telegram delivery.  A caller may render it locally and discard the object.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from src.portfolio_risk import portfolio_risk_snapshot


def build_private_portfolio_view(
    positions: Iterable[dict[str, Any]],
    returns: Iterable[float] | None = None,
    *,
    confidence: float = 0.95,
) -> dict[str, Any]:
    """Return a non-persistent risk view and never a public artifact."""
    result = portfolio_risk_snapshot(positions, returns, confidence=confidence)
    result.update({
        "visibility": "private_local_only",
        "public_release_eligible": False,
        "telegram_delivery_allowed": False,
        "storage": "caller_memory_only",
        "account_access": False,
        "trading_enabled": False,
    })
    return result

