"""Filterable event timeline with event-version continuity."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def build_timeline(
    events: Iterable[dict[str, Any]],
    *,
    market: str | None = None,
    category: str | None = None,
    status: str | None = None,
    risk_level: str | None = None,
    source_tier: str | None = None,
) -> list[dict[str, Any]]:
    """Return one event-version stream with conservative, exact filters.

    Filters are intentionally equality based; fuzzy matching belongs to event
    clustering, not to timeline retrieval, so a user can audit why a row was
    included.  The cluster key is preserved as the stable continuity key.
    """
    rows = []
    for event in events:
        if market and str(event.get("market", "")).lower() != market.lower():
            continue
        if category and str(event.get("category", "")).lower() != category.lower():
            continue
        if status and str(event.get("crosscheck_status", "")).lower() != status.lower():
            continue
        if risk_level and str(event.get("risk_level") or event.get("prstk_risk_level") or "").lower() != risk_level.lower():
            continue
        if source_tier and str(event.get("source_tier") or "").lower() != source_tier.lower():
            continue
        rows.append(dict(event))
    return sorted(rows, key=lambda row: str(row.get("published_at") or row.get("fetched_at") or ""), reverse=True)

