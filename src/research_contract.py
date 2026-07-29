"""Shared, public-only fields used by every research engine.

The contract deliberately contains observations and reproducible scores only.
It must not grow into a trade-order, entry, stop-loss, or portfolio interface.
"""

from __future__ import annotations

from typing import Any

import pandas as pd


PUBLIC_CANDIDATE_FIELDS = (
    "ticker",
    "name",
    "close",
    "previous_close",
    "change_percent",
    "turnover",
    "as_of",
    "score",
    "signal_labels",
)


def latest_quote_context(df: pd.DataFrame) -> dict[str, Any] | None:
    """Return the latest completed OHLCV observation in a common shape."""
    if len(df) < 2 or not {"Close", "Volume"}.issubset(df.columns):
        return None

    current = float(df["Close"].iloc[-1])
    previous = float(df["Close"].iloc[-2])
    if current <= 0 or previous <= 0:
        return None

    observed_at = df.index[-1]
    as_of = observed_at.strftime("%Y-%m-%d") if hasattr(observed_at, "strftime") else str(observed_at)
    return {
        "close": current,
        "previous_close": previous,
        "change_percent": round((current / previous - 1) * 100, 2),
        "turnover": float(current * float(df["Volume"].iloc[-1])),
        "as_of": as_of,
    }
