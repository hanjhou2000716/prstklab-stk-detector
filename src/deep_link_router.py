"""Fail-closed routing for Telegram Mini App alert deep links."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlparse

VIEWS = {"event", "market", "briefing", "research", "resolved", "source-health"}


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
    match = next((item for item in alerts if str(item.get("alert_id") or "") == link.alert), None)
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
