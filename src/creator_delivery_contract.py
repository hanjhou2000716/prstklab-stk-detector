"""Fail-closed Creator notification idempotency and media degradation policy."""

from __future__ import annotations

from typing import Any


def creator_notification_key(episode_key: str, notification_type: str = "initial") -> str:
    """Return the durable idempotency key for one Creator episode notification."""
    episode = str(episode_key or "").strip()
    kind = str(notification_type or "initial").strip().lower() or "initial"
    if not episode:
        raise ValueError("creator episode key is required")
    return f"creator:{episode}:{kind}"


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
    if insight.get("public_safe") is not True:
        reasons.append("creator_artifact_not_public_safe")
    if not release_ready:
        reasons.append("release_gate_not_ready")
    key = creator_notification_key(episode, notification_type) if episode else ""
    sent = any(str(row.get("notification_key") or "") == key and str(row.get("status") or "") in {"delivered", "partial"} for row in (delivery_history or []))
    if sent:
        reasons.append("already_delivered")
    return {
        "allowed": not reasons,
        "notification_key": key,
        "status": "media_ready" if media_available else "media_degraded" if not reasons else "blocked",
        "media_mode": "photo" if media_available else "text_only",
        "reasons": reasons,
    }


__all__ = ["creator_notification_key", "decide_creator_delivery"]
