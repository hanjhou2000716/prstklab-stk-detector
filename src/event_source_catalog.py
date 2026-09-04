"""Auditable registry for event sources and their alert authority."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from src.creator_provider_registry import creator_ids


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
    EventSource("financialjuice", "discovery", "https://www.financialjuice.com/", "discovery", 5, 45, False),
    EventSource("gmail", "transport", "https://gmail.googleapis.com/", "transport", 5, 15, False),
    *(EventSource(provider, "editorial", "https://www.youtube.com/", "editorial", 15, 180, False) for provider in creator_ids(enabled_only=True)),
)

_ALLOWED_TIERS = {"official", "public-market", "discovery", "transport", "editorial"}
_ALLOWED_STATUSES = {"healthy", "no_event", "stale", "failed", "not_scanned"}


def validate_catalog(sources: tuple[EventSource, ...] = EVENT_SOURCES) -> list[str]:
    """Validate source policy before it is used by a collector.

    A malformed source entry is a configuration error, not an empty scan.
    Keeping this check deterministic prevents a typo in an endpoint or tier
    from silently changing the alert authority of an entire source class.
    """
    errors: list[str] = []
    keys: set[str] = set()
    for source in sources:
        if source.key in keys:
            errors.append(f"duplicate source key: {source.key}")
        keys.add(source.key)
        if source.key != source.key.strip().lower() or not source.key:
            errors.append(f"source key must be normalized: {source.key!r}")
        parsed = urlparse(source.url)
        if parsed.scheme != "https" or not parsed.netloc:
            errors.append(f"source URL must be HTTPS: {source.key}")
        if source.tier not in _ALLOWED_TIERS:
            errors.append(f"unsupported source tier: {source.key}")
        if source.refresh_minutes <= 0 or source.max_age_minutes <= 0:
            errors.append(f"source intervals must be positive: {source.key}")
        if source.max_age_minutes < source.refresh_minutes:
            errors.append(f"max age must cover refresh interval: {source.key}")
        if source.tier == "discovery" and source.can_trigger_alone:
            errors.append(f"discovery source cannot trigger alone: {source.key}")
    return errors


def source_for(key: str) -> EventSource | None:
    return next((source for source in EVENT_SOURCES if source.key == str(key).strip().lower()), None)


def _parse_time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=parsed.tzinfo or UTC)


def catalog_health(records: list[dict[str, Any]], *, now: datetime | None = None) -> list[dict[str, Any]]:
    """Join observed health to policy; missing/stale records stay explicit.

    ``no_event`` is a successful scan with no matching event.  It is kept
    separate from ``failed``/``stale`` so the UI cannot misread a collector
    outage as evidence that nothing happened.
    """
    current = now or datetime.now(UTC)
    current = current.replace(tzinfo=current.tzinfo or UTC)
    by_key = {str(record.get("key")): record for record in records}
    output: list[dict[str, Any]] = []
    for source in EVENT_SOURCES:
        item = source.to_dict()
        observed = by_key.get(source.key)
        status = str(observed.get("status") or "not_scanned") if observed else "not_scanned"
        if status not in _ALLOWED_STATUSES:
            status = "failed"
        fetched_at = observed.get("fetched_at") if observed else None
        age_minutes: float | None = None
        fetched = _parse_time(fetched_at)
        if fetched:
            age_minutes = max(0.0, (current - fetched).total_seconds() / 60)
            if age_minutes > source.max_age_minutes and status in {"healthy", "no_event"}:
                status = "stale"
        item["observed_status"] = status
        item["fetched_at"] = fetched_at
        item["freshness_age_minutes"] = round(age_minutes, 2) if age_minutes is not None else None
        item["data_gap"] = (
            observed.get("data_gap") if observed and observed.get("data_gap")
            else None if status in {"healthy", "no_event"} else {
                "not_scanned": "source_not_scanned",
                "stale": "source_stale",
                "failed": "scan_failed",
            }.get(status, "source_unavailable")
        )
        output.append(item)
    return output
