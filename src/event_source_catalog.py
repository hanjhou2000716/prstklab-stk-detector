"""Auditable registry for event sources and their alert authority."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class EventSource:
    key: str
    category: str
    url: str
    tier: str
    refresh_minutes: int
    max_age_minutes: int
    can_trigger_alone: bool
    retention: str = "metadata-only"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


EVENT_SOURCES: tuple[EventSource, ...] = (
    EventSource("fed", "central-bank", "https://www.federalreserve.gov/feeds/press_all.xml", "official", 5, 90, True),
    EventSource("bls", "macro", "https://www.bls.gov/feed/empsit.rss", "official", 15, 90, True),
    EventSource("eia", "energy", "https://www.eia.gov/rss/press_rss.xml", "official", 15, 90, True),
    EventSource("sec", "corporate", "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&output=atom", "official", 5, 90, True),
    EventSource("usgs", "disaster", "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/significant_hour.geojson", "official", 5, 90, True),
    EventSource("gdelt", "discovery", "https://api.gdeltproject.org/api/v2/doc/doc", "discovery", 15, 45, False),
    EventSource("reuters", "discovery", "https://www.reuters.com/", "discovery", 15, 45, False),
)


def source_for(key: str) -> EventSource | None:
    return next((source for source in EVENT_SOURCES if source.key == str(key).strip().lower()), None)


def catalog_health(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Join observed health to policy; missing records remain explicit gaps."""
    by_key = {str(record.get("key")): record for record in records}
    output: list[dict[str, Any]] = []
    for source in EVENT_SOURCES:
        item = source.to_dict()
        observed = by_key.get(source.key)
        item["observed_status"] = observed.get("status") if observed else "not_scanned"
        item["data_gap"] = observed.get("data_gap") if observed else "source_not_scanned"
        output.append(item)
    return output

