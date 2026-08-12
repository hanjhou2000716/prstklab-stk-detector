"""Privacy-safe Creator health aggregation for Railway and Mini App."""

from __future__ import annotations

from typing import Any

_STATES = {"healthy", "no_new_content", "stale", "parse_failed", "media_degraded", "configuration_missing", "failed"}
_SAFE_FIELDS = {
    "watch_expiration", "last_history_id", "last_notification_at", "last_parsed_at",
    "dlq_count", "last_release_at", "last_media_at", "last_receipt_at",
}


def _status(component: dict[str, Any] | None) -> str:
    if not isinstance(component, dict):
        return "configuration_missing"
    value = str(component.get("creator_health") or component.get("status") or "failed").strip()
    return value if value in _STATES else "failed"


def build_creator_health(*, config: dict[str, Any] | None = None, watch: dict[str, Any] | None = None,
                        parser: dict[str, Any] | None = None, release: dict[str, Any] | None = None,
                        media: dict[str, Any] | None = None, delivery: dict[str, Any] | None = None) -> dict[str, Any]:
    """Aggregate component health without exposing tokens, IDs or payloads."""
    components = {
        "config": config,
        "watch": watch,
        "parser": parser,
        "release": release,
        "media": media,
        "delivery": delivery,
    }
    statuses = {name: _status(value) for name, value in components.items()}
    if any(value == "failed" for value in statuses.values()):
        overall = "failed"
    elif statuses["config"] == "configuration_missing":
        overall = "configuration_missing"
    elif statuses["parser"] == "parse_failed":
        overall = "parse_failed"
    elif statuses["media"] == "media_degraded":
        overall = "media_degraded"
    elif any(value == "stale" for value in statuses.values()):
        overall = "stale"
    elif statuses["config"] == "healthy" and all(
        statuses[name] == "no_new_content" for name in ("watch", "parser", "release", "media", "delivery")
    ):
        overall = "no_new_content"
    else:
        overall = "healthy"

    timeline: dict[str, Any] = {}
    for component in components.values():
        if not isinstance(component, dict):
            continue
        for key in _SAFE_FIELDS:
            if component.get(key) not in (None, ""):
                timeline[key] = component[key]
    return {
        "creator_health": overall,
        "components": statuses,
        "timeline": timeline,
        "secret_values_exposed": False,
        "raw_content_stored": False,
    }


__all__ = ["build_creator_health"]
