"""Release-gated Creator notification orchestration.

Creator episodes use the same publication boundary as market alerts, but
their delivery policy is intentionally separate: one episode is sent once,
recipient failures are isolated, and missing private media degrades to a
bounded text notification instead of producing an empty image.

The module is transport-injectable so CI can exercise the complete decision
path without a Telegram token or a real recipient.
"""

from __future__ import annotations

import html
from collections.abc import Callable
from pathlib import Path
from typing import Any

from src.creator_photo_delivery import (
    build_creator_receipt,
    plan_creator_delivery,
)
from src.telegram_client import (
    PhotoDeliveryReceipt,
    TelegramDelivery,
    send_briefs,
    send_photo_briefs,
)

MAX_CREATOR_PHOTO_CAPTION = 40
MAX_CREATOR_TEXT_CAPTION = 30


def _clean(value: Any) -> str:
    return " ".join(str(value or "").replace("\n", " ").split()).strip()


def _bounded(text: str, limit: int) -> str:
    value = _clean(text)
    if len(value) <= limit:
        return value
    words = value.split(" ")
    kept = ""
    for word in words:
        candidate = word if not kept else f"{kept} {word}"
        if len(candidate) > max(1, limit - 1):
            break
        kept = candidate
    if kept:
        return kept + "…"
    return value[: max(1, limit - 1)] + "…"


def creator_telegram_caption(insight: dict[str, Any], *, limit: int = MAX_CREATOR_PHOTO_CAPTION) -> str:
    """Return a short, HTML-safe caption for a Creator episode."""
    creator = _clean(insight.get("creator_name") or insight.get("content_origin") or "Creator")
    title = _clean(insight.get("episode_title") or insight.get("title") or "新內容")
    takeaway = next((_clean(item) for item in (insight.get("key_takeaways") or []) if _clean(item)), "")
    text = f"🟣 {creator}｜{title}"
    if takeaway:
        text += f"｜{takeaway}"
    # sendPhoto uses HTML parse mode in the shared client.  Escaping can add
    # characters (for example ``&`` becomes ``&amp;``), therefore enforce the
    # limit after escaping rather than allowing Telegram to reject the photo.
    raw = _bounded(text, limit)
    escaped = html.escape(raw, quote=False)
    if len(escaped) <= limit:
        return escaped
    # Keep a deterministic attribution-only fallback.  It is preferable to a
    # substring of escaped markup, which could split an entity and make the
    # whole message invalid.
    fallback = html.escape(_bounded(f"🟣 {creator}", limit), quote=False)
    if len(fallback) <= limit:
        return fallback
    return fallback[: max(1, limit - 1)] + "…"


def creator_text_caption(insight: dict[str, Any]) -> str:
    """Return the legacy 30-character caption used by text-only fallback."""
    creator = _clean(insight.get("creator_name") or insight.get("content_origin") or "Creator")
    title = _clean(insight.get("episode_title") or insight.get("title") or "新內容")
    return _bounded(f"🟣 {creator}｜{title}", MAX_CREATOR_TEXT_CAPTION)


def _photo_delivered(receipts: tuple[PhotoDeliveryReceipt, ...]) -> bool:
    return any(item.status == "delivered" for item in receipts)


def _receipt_status(delivered: bool, *, blocked: bool = False) -> str:
    if delivered:
        return "delivered"
    return "blocked" if blocked else "failed"


def deliver_creator_episode(
    insight: dict[str, Any],
    *,
    release_id: str,
    creator_snapshot_id: str,
    mini_app_url: str,
    release_ready: bool,
    token: str,
    chat_ids: tuple[str, ...],
    media_path: str | Path | None = None,
    delivery_history: list[dict[str, Any]] | None = None,
    photo_sender: Callable[..., tuple[PhotoDeliveryReceipt, ...]] | None = None,
    text_sender: Callable[..., tuple[TelegramDelivery, ...]] | None = None,
) -> dict[str, Any]:
    """Deliver one episode and return privacy-safe per-recipient receipts.

    A photo is attempted only when the caller has an approved private media
    path.  If every photo attempt fails, the same episode falls back to one
    text message per recipient.  No raw Telegram identifiers are returned.
    """
    path = Path(media_path) if media_path else None
    photo_sender = photo_sender or send_photo_briefs
    text_sender = text_sender or send_briefs
    media_available = bool(path and path.is_file())
    plan = plan_creator_delivery(
        insight,
        release_id=release_id,
        creator_snapshot_id=creator_snapshot_id,
        mini_app_url=mini_app_url,
        release_ready=release_ready,
        media_available=media_available,
        delivery_history=delivery_history,
    )
    episode_key = _clean(insight.get("episode_key"))
    if not plan["allowed"]:
        return {
            "allowed": False,
            "status": "blocked",
            "notification_key": plan["notification_key"],
            "reasons": plan["reasons"],
            "receipts": [],
        }
    if not token or not chat_ids:
        return {
            "allowed": False,
            "status": "blocked",
            "notification_key": plan["notification_key"],
            "reasons": ["telegram_configuration_missing"],
            "receipts": [],
        }

    photo_receipts: tuple[PhotoDeliveryReceipt, ...] = ()
    if media_available and path is not None:
        try:
            photo_receipts = photo_sender(
                token=token,
                chat_ids=chat_ids,
                caption=creator_telegram_caption(insight),
                photo_path=path,
                mini_app_url=mini_app_url,
                alert_id=plan["notification_key"],
                release_id=release_id,
                snapshot_id=creator_snapshot_id,
                observation_id=episode_key,
            )
        except Exception:
            # A renderer/media adapter failure is a delivery degradation, not
            # a reason to crash the whole scheduled market brief.
            photo_receipts = ()
        if _photo_delivered(photo_receipts):
            receipts = [
                build_creator_receipt(
                    insight,
                    release_id=release_id,
                    creator_snapshot_id=creator_snapshot_id,
                    chat_id=chat_id,
                    status=_receipt_status(receipt.status == "delivered"),
                    message_id=receipt.message_id,
                    media_mode="photo",
                    media_hash=receipt.telegram_file_id_hash or "",
                    error_class=receipt.error_class,
                )
                for chat_id, receipt in zip(chat_ids, photo_receipts, strict=False)
            ]
            return {
                "allowed": True,
                "status": "delivered",
                "notification_key": plan["notification_key"],
                "media_mode": "photo",
                "receipts": receipts,
                "reasons": [],
            }

    # Missing media or an all-recipient renderer/API failure is explicitly
    # degraded to the existing text-only 30-character Telegram contract.
    text_receipts = text_sender(
        token=token,
        chat_ids=chat_ids,
        text=creator_text_caption(insight),
        dashboard_url=mini_app_url,
        target_url=plan["mini_app_url"],
    )
    receipts = [
        build_creator_receipt(
            insight,
            release_id=release_id,
            creator_snapshot_id=creator_snapshot_id,
            chat_id=chat_id,
            status=_receipt_status(delivery.delivered),
            message_id=delivery.result.message_id if delivery.result else None,
            media_mode="text_only",
            error_class=None if delivery.delivered else "text_delivery_failed",
        )
        for chat_id, delivery in zip(chat_ids, text_receipts, strict=False)
    ]
    return {
        "allowed": True,
        "status": "media_degraded" if not media_available or not _photo_delivered(photo_receipts) else "delivered",
        "notification_key": plan["notification_key"],
        "media_mode": "text_only",
        "receipts": receipts,
        "reasons": ["media_unavailable"] if not media_available else ["photo_delivery_failed"],
    }


__all__ = ["creator_telegram_caption", "creator_text_caption", "deliver_creator_episode"]
