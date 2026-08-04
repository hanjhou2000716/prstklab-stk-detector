"""Event clustering facade combining cross-check evidence with durable keys."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Iterable
from urllib.parse import urlparse

from src.event_crosscheck import cross_check_event_records
from src.event_ledger import canonical_event_key, normalize_source_url


def _now(value: datetime | None) -> datetime:
    current = value or datetime.now(UTC)
    return current.replace(tzinfo=current.tzinfo or UTC).astimezone(UTC)


def _source_urls(record: dict[str, Any]) -> list[str]:
    values = [record.get("source_url"), record.get("url")]
    values.extend(record.get("crosscheck_sources") or [])
    values.extend(record.get("verified_sources") or [])
    return list(dict.fromkeys(item for value in values if (item := normalize_source_url(value))))


def _domains(urls: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(
        host for url in urls if (host := (urlparse(url).hostname or "").lower().removeprefix("www."))
    ))


def _event_status(record: dict[str, Any]) -> tuple[str, list[str]]:
    category = str(record.get("classification") or record.get("event_type") or "")
    status = str(record.get("crosscheck_status") or "")
    reasons: list[str] = []
    if status in {"official_confirmed", "corroborated"} or record.get("cross_checked") is True:
        status = "confirmed"
    elif status in {"pending_second_source", "unverified"}:
        status = "waiting_second_source"
        reasons.append("waiting_second_source")
    else:
        status = "waiting_second_source"
        reasons.append("waiting_second_source")
    if category in {"black_swan", "conflict", "disaster"} and record.get("market_sync_confirmed") is not True:
        reasons.append("waiting_market_sync")
        if status == "confirmed":
            status = "waiting_market_sync"
    return status, reasons


def cluster_events(records: Iterable[dict[str, Any]], *, now: datetime | None = None) -> list[dict[str, Any]]:
    """Collapse cross-source reports while retaining evidence and pending reasons."""
    current = _now(now)
    checked = cross_check_event_records(records)
    clusters: dict[str, dict[str, Any]] = {}
    for item in checked:
        if item.get("kind") == "market_signal":
            key = canonical_event_key(item)
        else:
            key = canonical_event_key(item)
        urls = _source_urls(item)
        status, reasons = _event_status(item)
        existing = clusters.get(key)
        if existing is None:
            published = item.get("published_at") or item.get("released_at") or item.get("event_time")
            first_seen = str(published or current.isoformat())
            clusters[key] = {
                **item,
                "cluster_id": key,
                "canonical_key": key,
                "first_seen": first_seen,
                "last_updated": current.isoformat(),
                "source_urls": urls,
                "source_domains": _domains(urls),
                "crosscheck_status": status,
                "pending_reasons": reasons,
                "evidence_count": 1,
            }
            continue
        merged_urls = list(dict.fromkeys([*(existing.get("source_urls") or []), *urls]))
        merged_reasons = list(dict.fromkeys([*(existing.get("pending_reasons") or []), *reasons]))
        existing["source_urls"] = merged_urls
        existing["source_domains"] = _domains(merged_urls)
        existing["evidence_count"] = int(existing.get("evidence_count") or 0) + 1
        existing["last_updated"] = current.isoformat()
        existing["pending_reasons"] = merged_reasons
        if status == "confirmed":
            existing["crosscheck_status"] = "confirmed"
        elif existing.get("crosscheck_status") not in {"confirmed", "waiting_market_sync"}:
            existing["crosscheck_status"] = status
        if item.get("market_sync_confirmed") is True:
            existing["market_sync_confirmed"] = True
            existing["pending_reasons"] = [reason for reason in merged_reasons if reason != "waiting_market_sync"]
    return list(clusters.values())


def cluster_health(clusters: Iterable[dict[str, Any]]) -> dict[str, int | str]:
    rows = list(clusters)
    confirmed = sum(item.get("crosscheck_status") == "confirmed" for item in rows)
    pending = len(rows) - confirmed
    return {"total": len(rows), "confirmed": confirmed, "pending": pending, "status": "healthy" if not pending else "pending"}