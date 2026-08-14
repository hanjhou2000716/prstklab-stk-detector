"""Private Creator photo delivery contract.

This module prepares a bounded, idempotent delivery plan without calling
Telegram.  The actual transport remains in :mod:`telegram_client`; keeping
the plan and receipt contract separate makes it possible to dry-run Creator
notifications and to degrade to one text notification when private media is
temporarily unavailable.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

from src.creator_delivery_contract import creator_notification_key, decide_creator_delivery

MAX_CREATOR_CAPTION_CHARS = 240


def _compact(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _bounded(value: str, limit: int) -> str:
    """Keep complete whitespace-delimited tokens where possible."""
    text = _compact(value)
    if len(text) <= limit:
        return text
    words = text.split(" ")
    result = ""
    for word in words:
        candidate = word if not result else f"{result} {word}"
        if len(candidate) > max(1, limit - 1):
            break
        result = candidate
    if result:
        return result + "…"
    return text[: max(0, limit - 1)] + "…"


def creator_caption(insight: dict[str, Any], *, limit: int = MAX_CREATOR_CAPTION_CHARS) -> str:
    """Build a compact attribution-first caption for a Creator episode."""
    creator = _compact(insight.get("creator_name") or insight.get("content_origin") or "Creator")
    title = _compact(insight.get("episode_title") or insight.get("title") or "新內容")
    takeaways = [
        _compact(item)
        for item in (insight.get("key_takeaways") or [])
        if _compact(item)
    ][:3]
    assets = [
        _compact(item)
        for item in (insight.get("tickers") or insight.get("sectors") or [])
        if _compact(item)
    ][:4]
    parts = [f"{creator}｜{title}"]
    if takeaways:
        parts.append("；".join(takeaways))
    if assets:
        parts.append("關聯：" + ", ".join(assets))
    text = "｜".join(parts)
    return _bounded(text, limit)


def creator_deep_link(
    base_url: str,
    *,
    release_id: str,
    creator: str,
    episode_key: str,
    snapshot_id: str,
) -> str:
    """Create a release-bound Mini App URL for one Creator episode."""
    if not str(base_url).startswith("https://"):
        raise ValueError("Mini App URL must use HTTPS")
    query = urlencode({
        "view": "creator",
        "creator": _compact(creator),
        "episode": _compact(episode_key),
        "release": _compact(release_id),
        "snapshot": _compact(snapshot_id),
    })
    separator = "&" if "?" in base_url else "?"
    return f"{base_url}{separator}{query}"


def recipient_hash(chat_id: str) -> str:
    """Return the only recipient identifier allowed in a receipt."""
    value = str(chat_id or "").strip()
    if not value:
        raise ValueError("chat_id is required")
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def build_creator_receipt(
    insight: dict[str, Any],
    *,
    release_id: str,
    creator_snapshot_id: str,
    chat_id: str,
    status: str,
    message_id: int | None = None,
    media_mode: str = "photo",
    media_hash: str = "",
    error_class: str | None = None,
    sent_at: str | None = None,
    notification_type: str = "initial",
) -> dict[str, Any]:
    """Build a privacy-safe, replay-auditable Creator delivery receipt."""
    allowed_status = {"delivered", "failed", "retryable", "blocked", "media_degraded"}
    if status not in allowed_status:
        raise ValueError("invalid creator delivery status")
    if media_mode not in {"photo", "text_only"}:
        raise ValueError("invalid creator media mode")
    episode_key = _compact(insight.get("episode_key"))
    if not episode_key:
        raise ValueError("episode_key is required")
    timestamp = sent_at or datetime.now(UTC).isoformat()
    return {
        "notification_key": creator_notification_key(episode_key, notification_type),
        "creator_episode_key": episode_key,
        "creator_snapshot_id": _compact(creator_snapshot_id),
        "release_id": _compact(release_id),
        "message_id": message_id,
        "delivery_status": status,
        "recipient_hash": recipient_hash(chat_id),
        "media_mode": media_mode,
        "media_hash": _compact(media_hash),
        "sent_at": timestamp,
        "error_class": _compact(error_class) or None,
    }


def plan_creator_delivery(
    insight: dict[str, Any],
    *,
    release_id: str,
    creator_snapshot_id: str,
    mini_app_url: str,
    release_ready: bool,
    media_available: bool,
    delivery_history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return a transport-neutral plan; no network or recipient is touched."""
    decision = decide_creator_delivery(
        insight,
        release_ready=release_ready,
        media_available=media_available,
        delivery_history=delivery_history,
    )
    episode_key = _compact(insight.get("episode_key"))
    creator = _compact(insight.get("creator_id") or insight.get("content_origin"))
    plan = {
        "allowed": bool(decision["allowed"]),
        "status": decision["status"],
        "notification_key": decision["notification_key"],
        "media_mode": decision["media_mode"],
        "caption": creator_caption(insight),
        "mini_app_url": creator_deep_link(
            mini_app_url,
            release_id=release_id,
            creator=creator,
            episode_key=episode_key,
            snapshot_id=creator_snapshot_id,
        ),
        "reasons": list(decision["reasons"]),
        "release_id": _compact(release_id),
        "creator_snapshot_id": _compact(creator_snapshot_id),
    }
    return plan


__all__ = [
    "MAX_CREATOR_CAPTION_CHARS",
    "build_creator_receipt",
    "creator_caption",
    "creator_deep_link",
    "plan_creator_delivery",
    "recipient_hash",
]
