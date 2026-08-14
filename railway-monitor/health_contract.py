"""Standalone health-contract helpers for the Railway monitor.

This module deliberately has no repository ``src`` dependency.  Railway can
run with ``railway-monitor`` as its root directory, so health projection and
heartbeat calculations must remain importable from that deployment pack.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse


def non_negative_int(value: Any) -> int | None:
    """Parse a counter without accepting booleans or negative values."""
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def age_seconds(value: str | None, *, now: datetime | None = None) -> int | None:
    """Return non-negative UTC age for an ISO timestamp, if parseable."""
    if not value:
        return None
    try:
        timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)
        reference = now or datetime.now(UTC)
        if reference.tzinfo is None:
            reference = reference.replace(tzinfo=UTC)
        return max(
            0,
            int(
                (
                    reference.astimezone(UTC)
                    - timestamp.astimezone(UTC)
                ).total_seconds()
            ),
        )
    except (TypeError, ValueError, OverflowError):
        return None


def monitor_heartbeat(monitor: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    """Return bounded liveness diagnostics for the long-running poll loop."""
    reference = now or datetime.now(UTC)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=UTC)
    interval = non_negative_int(monitor.get("poll_interval_seconds")) or 120
    timeout = max(300, interval * 2 + 60)
    completed_age = age_seconds(monitor.get("last_cycle_completed_at"), now=reference)
    started_age = age_seconds(monitor.get("last_cycle_started_at"), now=reference)
    if completed_age is None:
        heartbeat_status = "starting" if started_age is None or started_age <= timeout else "stale"
    else:
        heartbeat_status = "healthy" if completed_age <= timeout else "stale"
    return {
        "heartbeat_status": heartbeat_status,
        "heartbeat_timeout_seconds": timeout,
        "last_cycle_age_seconds": completed_age,
        "current_cycle_age_seconds": started_age,
    }


def health_request_path(request_target: str) -> str:
    """Extract the route path while ignoring probe cache-busting parameters."""
    return urlparse(request_target).path or "/"


def gmail_health_fields(diagnostics: Any) -> dict[str, Any]:
    """Project Gmail diagnostics without exposing transport identifiers."""
    if not isinstance(diagnostics, dict):
        return {"watch_status": "not_checked", "observability": {}}
    watch = diagnostics.get("watch")
    if not isinstance(watch, dict):
        return {"watch_status": "not_checked", "observability": {}}
    metrics = watch.get("observability")
    return {
        "watch_status": str(watch.get("status") or "not_checked"),
        "observability": dict(metrics) if isinstance(metrics, dict) else {},
    }
