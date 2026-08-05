"""Filterable event timeline with event-version continuity."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def build_timeline(events: Iterable[dict[str, Any]], *, market: str | None = None, category: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
    rows = []
    for event in events:
        if market and str(event.get("market", "")).lower() != market.lower():
            continue
        if category and str(event.get("category", "")).lower() != category.lower():
            continue
        if status and str(event.get("crosscheck_status", "")).lower() != status.lower():
            continue
        rows.append(dict(event))
    return sorted(rows, key=lambda row: str(row.get("published_at") or row.get("fetched_at") or ""), reverse=True)

