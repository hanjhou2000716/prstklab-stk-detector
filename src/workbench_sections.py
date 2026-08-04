"""Canonical Mini App home ordering."""

from __future__ import annotations

from typing import Any, Mapping, Sequence


HOME_SECTIONS = ("system_health", "market_regime", "priority_events", "watchlist_risk", "global_markets", "research_candidates", "pending_signals", "delivery_status")


def build_home_sections(data: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [{"id": section, "data": data.get(section), "available": section in data} for section in HOME_SECTIONS]
