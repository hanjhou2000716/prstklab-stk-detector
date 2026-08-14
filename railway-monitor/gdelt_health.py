"""Pure GDELT source-health projection for the Railway monitor."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def project_gdelt_health(
    *,
    fetch_state: str,
    fetch_error: str | None,
    article_count: int,
    alert_count: int,
    pending_count: int,
    pending_reasons: dict[str, int],
    market_sync_status: str,
    stale_cache_used: bool,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Create a bounded health record without changing delivery eligibility.

    A successful scan with zero qualifying articles is ``event_scan=no_event``;
    a failed provider is ``event_scan=scan_failed``.  Stale cache remains
    observable as ``fallback_active`` but is never promoted to live evidence.
    """
    safe_state = str(fetch_state or "unknown")
    timestamp = (now or datetime.now(UTC)).astimezone(UTC).isoformat()
    if safe_state in {"live", "fresh_cache"} and not stale_cache_used:
        status = "healthy"
        event_scan = "has_events" if article_count > 0 else "no_event"
    elif safe_state == "stale_cache" or stale_cache_used:
        status = "fallback_active"
        event_scan = "has_events" if article_count > 0 else "no_event"
    elif safe_state == "failed":
        status = "failed"
        event_scan = "scan_failed"
    else:
        status = "not_checked"
        event_scan = "not_checked"
    return {
        "status": status,
        "event_scan": event_scan,
        "article_count": max(0, int(article_count)),
        "alert_count": max(0, int(alert_count)),
        "pending_count": max(0, int(pending_count)),
        "pending_reasons": {
            str(key): max(0, int(value))
            for key, value in pending_reasons.items()
            if str(key).strip()
        },
        "market_sync_status": str(market_sync_status or "not_confirmed"),
        "stale_cache_used": bool(stale_cache_used),
        "error": fetch_error if status in {"failed", "fallback_active"} else None,
        "observed_at": timestamp,
    }
