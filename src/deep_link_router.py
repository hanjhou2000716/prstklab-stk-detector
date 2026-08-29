"""Fail-closed routing for Telegram Mini App alert deep links."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlparse

VIEWS = {"event", "market", "briefing", "research", "resolved", "source-health"}


def _alert_identities(item: dict[str, Any]) -> set[str]:
    """Return identities that delivery producers may place in ``alert=``.

    Event-cluster and notification IDs are the durable identities used by the
    release/Telegram pipeline; older artifacts may expose only ``alert_id`` or
    ``canonical_key``.  Matching these aliases is safe because resolution is
    still constrained to the supplied release and alert collection.
    """
    return {
        str(item.get(key)).strip()
        for key in (
            "alert_id",
            "event_id",
            "id",
            "canonical_key",
            "event_cluster_key",
            "event_key",
            "notification_id",
            "item_id",
            "story_id",
        )
        if item.get(key) not in (None, "")
    }


@dataclass(frozen=True)
class DeepLink:
    alert: str = ""
    release: str = ""
    view: str = "event"
    snapshot: str = ""
    observation: str = ""


def parse_deep_link(url: str) -> DeepLink:
    query = parse_qs(urlparse(url).query)
    view = (query.get("view", ["event"])[0] or "event").strip()
    if view not in VIEWS:
        view = "event"
    return DeepLink(
        query.get("alert", [""])[0],
        query.get("release", [""])[0],
        view,
        query.get("snapshot", [""])[0],
        query.get("observation", [""])[0],
    )


def resolve_deep_link(link: DeepLink, *, manifest: dict[str, Any], alerts: list[dict[str, Any]]) -> dict[str, Any]:
    if not link.release or link.release != str(manifest.get("release_id") or ""):
        return {"status": "archived", "message": "release mismatch", "view": link.view}
    known_snapshots = {
        str(manifest.get(name) or "")
        for name in ("market_snapshot_id", "research_snapshot_id", "event_snapshot_id")
        if manifest.get(name)
    }
    if link.snapshot and known_snapshots and link.snapshot not in known_snapshots:
        return {"status": "archived", "message": "snapshot does not belong to this release", "view": link.view}
    match = next((item for item in alerts if link.alert in _alert_identities(item)), None)
    if not match:
        return {"status": "missing", "message": "alert not found", "view": link.view}
    alert_snapshot = str(match.get("snapshot_id") or "")
    if link.snapshot and alert_snapshot and link.snapshot != alert_snapshot:
        return {"status": "archived", "message": "alert snapshot mismatch", "view": link.view}
    return {
        "status": "ok",
        "view": link.view,
        "alert": match,
        "release_id": link.release,
        "snapshot_id": link.snapshot,
        "observation_id": link.observation,
    }
