"""Filterable event timeline with version history preserved."""

from __future__ import annotations

from typing import Any, Iterable, Mapping


def filter_events(events: Iterable[Mapping[str, Any]], *, market: str | None = None, event_type: str | None = None, risk: str | None = None, confirmed: bool | None = None) -> list[dict[str, Any]]:
    result = []
    for event in events:
        if market and event.get("market") != market:
            continue
        if event_type and event.get("event_type") != event_type:
            continue
        if risk and event.get("importance") != risk:
            continue
        if confirmed is not None and bool(event.get("official_confirmed")) != confirmed:
            continue
        result.append(dict(event))
    return sorted(result, key=lambda item: str(item.get("last_updated") or item.get("published_at") or ""), reverse=True)


def group_versions(events: Iterable[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        key = str(event.get("cluster_id") or event.get("canonical_key") or event.get("id") or "unknown")
        grouped.setdefault(key, []).append(dict(event))
    return grouped
