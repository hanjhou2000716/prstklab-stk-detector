"""Creator-only refresh bound to the last successful production release."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from src.creator_intelligence_pipeline import build_creator_intelligence_release


def _time(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=parsed.tzinfo or UTC).astimezone(UTC)


def _snapshot_id(artifact: dict[str, Any]) -> str:
    payload = json.dumps(artifact, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return f"creator-snapshot-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:20]}"


def refresh_creator_snapshot(
    records: list[dict[str, Any]],
    *,
    parent_release: dict[str, Any],
    refreshed_at: str | None = None,
    last_success_at: str | None = None,
    max_age_days: int = 7,
    history_store: Any | None = None,
) -> dict[str, Any]:
    """Refresh Creator data without rebuilding or mutating core market data.

    A parent release must already be ``ready``.  Otherwise the function fails
    closed.  Creator-only refreshes carry the exact parent market/research/event
    snapshot IDs and never manufacture a new core snapshot.
    """
    now = _time(refreshed_at) or datetime.now(UTC)
    if str(parent_release.get("status") or "") != "ready":
        return {
            "status": "unavailable",
            "source_state": "parent_release_unavailable",
            "refresh_mode": "creator_only",
            "parent_release_id": str(parent_release.get("release_id") or ""),
            "creator_snapshot_id": None,
            "artifact": None,
        }

    result = build_creator_intelligence_release(
        records,
        parent_manifest=parent_release,
        history_store=history_store,
    )
    artifact = result["artifact"]
    previous = _time(last_success_at)
    age = now - previous if previous else None
    stale = age is not None and age > timedelta(days=max(1, int(max_age_days)))
    source_state = "stale" if stale else "available" if result["accepted_count"] else "no_new_content"
    artifact["creator_snapshot_id"] = _snapshot_id(artifact)
    artifact["refresh_mode"] = "creator_only"
    return {
        "status": "ready" if artifact.get("status") == "ready" else "unavailable",
        "refresh_mode": "creator_only",
        "source_state": source_state,
        "freshness": "stale" if stale else "fresh" if result["accepted_count"] else "unknown",
        "refreshed_at": now.isoformat(),
        "last_success_at": last_success_at,
        "parent_release_id": str(parent_release.get("release_id") or ""),
        "market_snapshot_id": str(parent_release.get("market_snapshot_id") or ""),
        "research_snapshot_id": str(parent_release.get("research_snapshot_id") or ""),
        "event_snapshot_id": str(parent_release.get("event_snapshot_id") or ""),
        "creator_snapshot_id": artifact["creator_snapshot_id"],
        "artifact": artifact,
        "history_recorded_count": result.get("history_recorded_count", 0),
    }


__all__ = ["refresh_creator_snapshot"]
