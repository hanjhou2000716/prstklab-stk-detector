"""Fail-closed routing for Telegram Mini App alert deep links."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlparse

from src.release_manifest import canonical_alert_content_hash

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


def _notification_id(item: dict[str, Any]) -> str:
    return str(item.get("notification_id") or "").strip()


def _source_key(item: dict[str, Any]) -> str:
    return str(item.get("source_key") or item.get("source") or item.get("content_origin") or "").strip().casefold()


def _same_event_lineage(left: dict[str, Any], right: dict[str, Any], link: DeepLink) -> bool:
    if not _notification_id(left) or _notification_id(left) != _notification_id(right):
        return False
    if _source_key(left) != _source_key(right):
        return False
    left_snapshot = str(left.get("snapshot_id") or "").strip()
    right_snapshot = str(right.get("snapshot_id") or "").strip()
    if not left_snapshot or left_snapshot != right_snapshot:
        return False
    if link.snapshot and left_snapshot != link.snapshot:
        return False
    left_observation = str(left.get("observation_id") or "").strip()
    right_observation = str(right.get("observation_id") or "").strip()
    if not left_observation or left_observation != right_observation:
        return False
    if link.observation and left_observation != link.observation:
        return False
    return True


def _same_canonical_content(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_stored = str(left.get("canonical_content_hash") or "").strip()
    right_stored = str(right.get("canonical_content_hash") or "").strip()
    # Immutable alert artifacts carry the producer's release-bound identity.
    # Prefer it over re-running a newer summary projection on historical text.
    if left_stored and right_stored:
        return left_stored == right_stored

    def content_hash(item: dict[str, Any]) -> str:
        return canonical_alert_content_hash(
            item,
            public_short_message=str(item.get("public_short_message") or ""),
            brief_title=str(item.get("brief_title") or ""),
            title=str(item.get("title") or ""),
            event_text=str(item.get("event") or ""),
        )

    return content_hash(left) == content_hash(right)


def resolve_deep_link(
    link: DeepLink, *, manifest: dict[str, Any], alerts: list[dict[str, Any]],
    latest_alerts: list[dict[str, Any]] | None = None,
    historical_alerts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    manifest_release = str(manifest.get("release_id") or "")
    if not link.release or link.release != manifest_release:
        # A release-mismatched caller must explicitly provide the verified
        # historical collection; treating the current-release ``alerts`` list
        # as history would weaken the original fail-closed contract.
        historical_pool = historical_alerts if historical_alerts is not None else []
        historical = next((item for item in historical_pool if link.alert in _alert_identities(item)), None)
        latest = next((item for item in (latest_alerts or []) if link.alert in _alert_identities(item)), None)
        if historical and latest:
            if _same_event_lineage(historical, latest, link) and _same_canonical_content(historical, latest):
                return {
                    "status": "ok",
                    "resolution": "latest_same_event",
                    "view": link.view,
                    "alert": latest,
                    "release_id": manifest_release,
                    "original_release_id": link.release,
                    "snapshot_id": str(latest.get("snapshot_id") or link.snapshot),
                    "observation_id": link.observation,
                }
        if historical:
            return {
                "status": "archived",
                "resolution": "historical_exact",
                "view": link.view,
                "alert": historical,
                "release_id": link.release,
                "snapshot_id": link.snapshot,
                "observation_id": link.observation,
            }
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
        "resolution": "current_exact",
        "view": link.view,
        "alert": match,
        "release_id": link.release,
        "snapshot_id": link.snapshot,
        "observation_id": link.observation,
    }
