"""Point-in-time provenance helpers shared by research scan workers.

The report assembly time is not evidence of the market session that a worker
actually scanned.  Workers therefore record the requested trading date from
the stable slot identity and derive the quote cutoff from the downloaded
bars/results themselves.
"""

from __future__ import annotations

import os
from datetime import date
from typing import Any

import pandas as pd


def _valid_date(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        return None


def scan_trading_date(market: str, explicit: str | None = None) -> str | None:
    """Resolve a worker's target trading date without guessing from a row."""
    direct = _valid_date(explicit)
    if explicit and direct is None:
        raise ValueError(f"invalid scan trading date: {explicit}")
    if direct:
        return direct
    raw_slot = os.getenv("RESEARCH_SLOT_KEY", "")
    for token in raw_slot.split(","):
        parts = token.split(":")
        if len(parts) >= 3 and parts[0] == market:
            return _valid_date(parts[1])
        if len(parts) >= 3 and parts[0] == "manual" and parts[1] == market:
            return _valid_date(parts[2])
    return None


def _timestamp_date(value: Any) -> str | None:
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(timestamp):
        return None
    return timestamp.date().isoformat()


def quote_cutoff_from_frame(frame: pd.DataFrame) -> str | None:
    """Return the newest downloaded bar date, never the run/slot date."""
    if frame.empty:
        return None
    dates = [_timestamp_date(value) for value in frame.index]
    valid = [item for item in dates if item]
    return max(valid) if valid else None


def quote_cutoff_from_records(records: list[dict[str, Any]]) -> str | None:
    """Return the newest bar date observed in worker records."""
    dates = []
    for record in records:
        bars = record.get("bars")
        if isinstance(bars, pd.DataFrame):
            cutoff = quote_cutoff_from_frame(bars)
            if cutoff:
                dates.append(cutoff)
    return max(dates) if dates else None


def quote_cutoff_from_mapping(quotes: dict[str, dict[str, Any]]) -> str | None:
    """Return the newest explicit ``as_of`` date in quote evidence."""
    dates = [_timestamp_date(item.get("as_of")) for item in quotes.values()]
    valid = [item for item in dates if item]
    return max(valid) if valid else None
