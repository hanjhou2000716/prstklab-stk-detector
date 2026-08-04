"""Audited catalogue for public event and macro-information sources."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable
from urllib.parse import urlparse


@dataclass(frozen=True)
class EventSource:
    source_id: str
    name: str
    tier: str
    category: str
    endpoint: str
    update_interval_minutes: int
    can_trigger_alert: bool
    retention: str = "metadata_only"


EVENT_SOURCES: tuple[EventSource, ...] = (
    EventSource("bls", "BLS", "official", "macro", "https://www.bls.gov/feed/empsit.rss", 60, True),
    EventSource("bea", "BEA", "official", "macro", "https://apps.bea.gov/rss/rss.xml", 60, True),
    EventSource("fed", "Federal Reserve", "official", "central-bank", "https://www.federalreserve.gov/feeds/press_all.xml", 30, True),
    EventSource("ecb", "ECB", "official", "central-bank", "https://www.ecb.europa.eu/rss/press.html", 30, True),
    EventSource("sec", "SEC EDGAR", "official", "corporate", "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-k&count=100&output=atom", 15, True),
    EventSource("cisa", "CISA", "official", "cyber", "https://www.cisa.gov/cybersecurity-advisories/all.xml", 30, True),
    EventSource("who", "WHO", "official", "health", "https://www.who.int/rss-feeds/news-english.xml", 60, True),
    EventSource("gdacs", "GDACS", "official", "disaster", "https://www.gdacs.org/xml/rss.xml", 15, True),
    EventSource("usgs", "USGS", "official", "disaster", "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/significant_hour.geojson", 5, True),
    EventSource("twse", "TWSE/MOPS", "official", "taiwan", "https://mops.twse.com.tw/mops/api/t05st02", 15, True),
    EventSource("gdelt", "GDELT", "discovery", "global", "https://api.gdeltproject.org/api/v2/doc/doc", 15, False),
    EventSource("reuters", "Reuters", "discovery", "global", "https://www.reuters.com/", 15, False),
    EventSource("google-news", "Google News RSS", "discovery", "global", "https://news.google.com/rss", 15, False),
)


def source_catalog() -> list[dict[str, object]]:
    return [
        {
            "source_id": item.source_id,
            "name": item.name,
            "tier": item.tier,
            "category": item.category,
            "endpoint": item.endpoint,
            "source_domain": urlparse(item.endpoint).hostname or "",
            "update_interval_minutes": item.update_interval_minutes,
            "can_trigger_alert": item.can_trigger_alert,
            "retention": item.retention,
        }
        for item in EVENT_SOURCES
    ]


def get_source(source_id: str) -> EventSource | None:
    key = str(source_id or "").strip().casefold()
    return next((item for item in EVENT_SOURCES if item.source_id == key), None)


def sources_for_category(category: str, *, alert_only: bool = False) -> list[EventSource]:
    values = [item for item in EVENT_SOURCES if item.category == category or category == "global"]
    return [item for item in values if not alert_only or item.can_trigger_alert]


def alert_source_is_allowed(source_id: str, *, official_confirmed: bool, second_source_confirmed: bool) -> bool:
    """Discovery feeds never trigger alone; official or corroborated facts may."""
    source = get_source(source_id)
    if source is None:
        return False
    if source.tier == "official":
        return official_confirmed
    return second_source_confirmed


def validate_catalog(items: Iterable[EventSource] = EVENT_SOURCES) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item.source_id in seen:
            errors.append(f"duplicate source_id: {item.source_id}")
        seen.add(item.source_id)
        if item.tier not in {"official", "discovery"}:
            errors.append(f"invalid tier: {item.source_id}")
        if item.update_interval_minutes <= 0:
            errors.append(f"invalid interval: {item.source_id}")
        if not urlparse(item.endpoint).scheme:
            errors.append(f"invalid endpoint: {item.source_id}")
        if item.tier == "discovery" and item.can_trigger_alert:
            errors.append(f"discovery source cannot trigger alone: {item.source_id}")
    return errors