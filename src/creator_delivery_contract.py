"""Fail-closed Creator notification idempotency and media degradation policy."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from src.creator_provider_registry import is_active_creator, is_known_creator


def creator_content_hash(insight: dict[str, Any]) -> str:
    """Hash reviewed Creator facts without release or transport metadata."""
    material = {
        "creator": str(insight.get("creator_id") or insight.get("content_origin") or "").strip().casefold(),
        "title": " ".join(str(insight.get("episode_title") or insight.get("title") or "").split()),
        "summary": " ".join(str(insight.get("summary") or insight.get("description") or "").split()),
        "takeaways": [" ".join(str(item).split()) for item in (insight.get("key_takeaways") or []) if str(item).strip()],
        "tickers": [str(item).strip().upper() for item in (insight.get("tickers") or []) if str(item).strip()],
        "sectors": [" ".join(str(item).split()) for item in (insight.get("sectors") or []) if str(item).strip()],
    }
    if not any(material[key] for key in ("title", "summary", "takeaways", "tickers", "sectors")):
        return ""
    encoded = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]


def creator_notification_key(
    episode_key: str,
    notification_type: str = "initial",
    *,
    content_hash: str | None = None,
) -> str:
    """Return the durable idempotency key for one Creator episode notification."""
    episode = str(episode_key or "").strip()
    kind = str(notification_type or "initial").strip().lower() or "initial"
    if not episode:
        raise ValueError("creator episode key is required")
    suffix = f":content-{str(content_hash).strip()[:24]}" if content_hash else ""
    return f"creator:{episode}:{kind}{suffix}"


def decide_creator_delivery(
    insight: dict[str, Any],
    *,
    delivery_history: list[dict[str, Any]] | None = None,
    release_ready: bool = False,
    media_available: bool = False,
) -> dict[str, Any]:
    """Decide whether a new Creator notification may be sent.

    Creator content never bypasses the release gate.  Missing media degrades
    to an explicit text-only state; it does not produce an empty/black image.
    """
    episode = str(insight.get("episode_key") or "").strip()
    notification_type = str(insight.get("notification_type") or "initial").strip().lower() or "initial"
    reasons: list[str] = []
    if not episode:
        reasons.append("episode_key_missing")
    creator = str(insight.get("creator_id") or insight.get("content_origin") or "").strip().casefold()
    if not is_active_creator(creator):
        reasons.append(
            "retired_source_suppressed"
            if is_known_creator(creator)
            else "creator_source_not_active"
        )
    if insight.get("public_safe") is not True:
        reasons.append("creator_artifact_not_public_safe")
    if not release_ready:
        reasons.append("release_gate_not_ready")
    content_hash = creator_content_hash(insight)
    key = creator_notification_key(episode, notification_type, content_hash=content_hash) if episode else ""
    legacy_key = creator_notification_key(episode, notification_type) if episode else ""
    # Historical receipts used ``status`` while the durable delivery-receipt
    # contract uses ``delivery_status``.  Read both names so a restart or a
    # schema upgrade cannot resend an episode that was already delivered.
    sent = any(
        str(row.get("notification_key") or "") in {key, legacy_key}
        and str(row.get("status") or row.get("delivery_status") or "") in {"delivered", "partial"}
        for row in (delivery_history or [])
    )
    if sent:
        reasons.append("already_delivered")
    return {
        "allowed": not reasons,
        "notification_key": key,
        "content_hash": content_hash,
        "status": "media_ready" if media_available else "media_degraded" if not reasons else "blocked",
        "media_mode": "photo" if media_available else "text_only",
        "reasons": reasons,
    }


__all__ = ["creator_content_hash", "creator_notification_key", "decide_creator_delivery"]
