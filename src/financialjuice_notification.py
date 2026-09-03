"""Release-gated FinancialJuice priority notification delivery.

FinancialJuice is a discovery/relay source.  A vendor score of 8/10 or more
authorizes a vendor-priority notification, but it never changes the PRStK
risk level.  This module keeps that boundary explicit and provides a
recipient-scoped, replay-safe delivery plan for the production sender.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from src.telegram_client import (
    PUBLIC_TEXT_MAX_CHARS,
    TextDeliveryReceipt,
    alert_mini_app_url,
    canonical_prstk_risk_level,
    send_text_briefs_audited,
)

MAX_FINANCIALJUICE_CAPTION = PUBLIC_TEXT_MAX_CHARS


def _text(value: Any) -> str:
    return " ".join(str(value or "").replace("\n", " ").split()).strip()


def _recipient_hash(chat_id: str) -> str:
    return hashlib.sha256(str(chat_id).encode("utf-8")).hexdigest()[:12]


def _bounded(value: str, limit: int) -> str:
    from src.telegram_client import summarize_public_message

    return summarize_public_message(value, limit=limit)


def _compress_fj_sentence(value: str) -> str:
    """Apply only factual, deterministic shortening to an FJ event sentence."""
    from src.telegram_client import _clean_public_fragment

    text = _clean_public_fragment(value)
    if not text or "…" in text or "..." in text:
        return ""
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+-\s+The Information\s*$", "", text, flags=re.IGNORECASE)
    text = re.sub(
        r"^(?P<entity>[A-Za-z][\w-]*)\s+boasts over \$100 billion in contracted revenue"
        r" after [A-Za-z][\w-]* win\.?$",
        r"\g<entity> claims $100B revenue.",
        text,
        flags=re.IGNORECASE,
    )
    text = text.replace("1,000億", "千億").replace("1,000 億", "千億")
    # Preserve the reported claim while dropping nonessential industry
    # framing and repeated Chinese function words.
    text = re.sub(r"^AI雲端及基礎設施公司\s*", "", text)
    text = re.sub(
        r"^(?P<entity>\S+)\s+在贏得\s+(?P<partner>[^，,]+?)\s+的合約後，\s*"
        r"宣稱其已簽約的合約營收總額已超過(?P<amount>[\d,]+億美元|千億美元)",
        r"\g<entity>稱\g<partner>合約簽約營收逾\g<amount>",
        text,
    )
    text = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[A-Za-z0-9])", "", text)
    text = re.sub(r"(?<=[A-Za-z0-9])\s+(?=[\u4e00-\u9fff])", "", text)
    text = text.replace("其已", "").replace("已超過", "逾")
    text = text.replace("合約營收總額", "合約營收")
    text = text.replace("據報導", "")
    if text and not text.endswith(("。", "！", "？", ".", "!", "?")):
        text += "。"
    return text


def _financialjuice_headline(event: dict[str, Any]) -> str:
    """Select the best parsed event fact, excluding metadata-only labels."""
    from src.telegram_client import _clean_public_fragment

    generic = {"financialjuice 公開快訊", "fj 公開快訊", "公開快訊", "資訊待核對"}
    for field in (
        "event", "chinese_translation", "title", "brief_title",
        "vendor_original_headline", "original_headline",
    ):
        value = _clean_public_fragment(event.get(field))
        value = _compress_fj_sentence(value)
        if value and value.casefold() not in generic:
            return value
    return ""


def financialjuice_notification_key(event: dict[str, Any]) -> str:
    """Return a stable opaque key for one FJ event/item."""
    material = "|".join(
        _text(event.get(name)).casefold()
        for name in ("event_cluster_key", "item_id", "observation_id", "source_url")
    )
    if not material:
        return ""
    return f"financialjuice:{hashlib.sha256(material.encode('utf-8')).hexdigest()[:24]}"


def financialjuice_caption(event: dict[str, Any], *, limit: int = MAX_FINANCIALJUICE_CAPTION) -> str:
    """Build the short caption without turning vendor importance into risk."""
    # The priority projection's canonical ``event`` is the parsed rich
    # semantic fact.  Keep title/brief_title only as legacy fallbacks so a
    # high-importance notification does not collapse into a generic label.
    headline = _financialjuice_headline(event)
    if not headline:
        return ""
    importance = event.get("vendor_importance")
    suffix = f"FJ {importance}/10" if importance is not None else "FJ 待核對"
    impact = _text(event.get("possible_impact") or event.get("possible_linkage"))
    content = f"🟣 {suffix}｜{headline}"
    if impact:
        content += f"｜{impact}"
    from src.telegram_client import canonical_short_message

    raw = canonical_short_message(
        content,
        prstk_risk_level=canonical_prstk_risk_level(event),
    )
    return _bounded(raw, limit)


def _history_delivered(
    history: list[dict[str, Any]], notification_key: str, recipient_hash: str,
) -> bool:
    for row in history:
        if not isinstance(row, dict):
            continue
        if _text(row.get("notification_key")) != notification_key:
            continue
        if _text(row.get("recipient_hash") or row.get("chat_id_hash")) != recipient_hash:
            continue
        if _text(row.get("delivery_status") or row.get("status")) == "delivered":
            return True
    return False


def deliver_financialjuice_event(
    event: dict[str, Any],
    *,
    release_id: str,
    snapshot_id: str,
    mini_app_url: str,
    release_ready: bool,
    token: str,
    chat_ids: tuple[str, ...],
    photo_path: str | Path | None = None,
    delivery_history: list[dict[str, Any]] | None = None,
    photo_sender: Callable[..., tuple[Any, ...]] | None = None,
    text_sender: Callable[..., tuple[TextDeliveryReceipt, ...]] | None = None,
) -> dict[str, Any]:
    """Deliver one eligible FJ event with recipient-level idempotency.

    The returned object is safe to persist: recipient identifiers and Telegram
    file IDs are represented only by short hashes.  A partial first attempt
    retries only recipients that did not already succeed.
    """
    notification_key = financialjuice_notification_key(event)
    reasons: list[str] = []
    if _text(event.get("source_key") or event.get("source")).casefold() != "financialjuice":
        reasons.append("source_not_financialjuice")
    if _text(event.get("notification_status")) != "eligible" or event.get("vendor_priority_notification") is not True:
        reasons.append("vendor_priority_not_eligible")
    if not release_ready:
        reasons.append("release_gate_not_ready")
    if not notification_key:
        reasons.append("notification_key_missing")
    if not token or not chat_ids:
        reasons.append("telegram_configuration_missing")
    if reasons:
        return {
            "status": "blocked",
            "notification_key": notification_key,
            "reasons": reasons,
            "receipts": [],
            "release_id": release_id,
            "snapshot_id": snapshot_id,
        }

    if not financialjuice_caption(event, limit=MAX_FINANCIALJUICE_CAPTION):
        return {
            "status": "blocked",
            "notification_key": notification_key,
            "reasons": ["content_incomplete"],
            "receipts": [],
            "release_id": release_id,
            "snapshot_id": snapshot_id,
        }

    history = delivery_history or []
    pending_ids = tuple(
        chat_id for chat_id in chat_ids
        if not _history_delivered(history, notification_key, _recipient_hash(chat_id))
    )
    if not pending_ids:
        return {
            "status": "already_delivered",
            "notification_key": notification_key,
            "reasons": ["already_delivered"],
            "receipts": [],
            "release_id": release_id,
            "snapshot_id": snapshot_id,
        }

    # notification_id is the primary immutable alert identity.  Cluster/item
    # aliases remain only for legacy rows that predate the identity contract.
    alert_id = _text(event.get("notification_id") or event.get("event_cluster_key") or event.get("item_id") or event.get("observation_id"))
    observation_id = _text(event.get("observation_id"))
    target_url = alert_mini_app_url(
        mini_app_url,
        alert_id=alert_id,
        release_id=_text(release_id),
        snapshot_id=_text(snapshot_id),
        observation_id=observation_id,
    )
    # FinancialJuice is a vendor/news lane, never the Creator attachment
    # exception.  Ignore any legacy photo callback so production FJ delivery
    # can only emit one canonical text message per recipient.
    sender = text_sender or send_text_briefs_audited
    try:
        delivered = sender(
            token=token,
            chat_ids=pending_ids,
            text=financialjuice_caption(event),
            dashboard_url=mini_app_url,
            alert_id=alert_id,
            release_id=release_id,
            snapshot_id=snapshot_id,
            observation_id=observation_id,
            target_url=target_url,
            prstk_risk_level=canonical_prstk_risk_level(event),
        )
    except Exception as exc:  # transport adapters must fail closed
        return {
            "status": "failed",
            "notification_key": notification_key,
            "reasons": [f"delivery_exception:{type(exc).__name__}"],
            "receipts": [],
            "release_id": release_id,
            "snapshot_id": snapshot_id,
            "mini_app_url": target_url,
        }

    receipts: list[dict[str, Any]] = []
    for receipt in delivered:
        receipts.append({
            "notification_key": notification_key,
            "recipient_hash": receipt.chat_id_hash,
            "delivery_status": receipt.status,
            "message_id": receipt.message_id,
            "error_class": receipt.error_class,
            "release_id": receipt.release_id,
            "snapshot_id": receipt.snapshot_id,
            "observation_id": receipt.observation_id,
            "telegram_file_id_hash": getattr(receipt, "telegram_file_id_hash", None),
        })
    delivered_count = sum(row["delivery_status"] == "delivered" for row in receipts)
    failed_count = len(receipts) - delivered_count
    status = "delivered" if failed_count == 0 and delivered_count else "partial" if delivered_count else "failed"
    return {
        "status": status,
        "notification_key": notification_key,
        "reasons": [] if status == "delivered" else ["recipient_delivery_partial" if delivered_count else "recipient_delivery_failed"],
        "receipts": receipts,
        "release_id": release_id,
        "snapshot_id": snapshot_id,
        "mini_app_url": target_url,
        "vendor_importance": event.get("vendor_importance"),
        "vendor_importance_is_not_risk": event.get("source_trace", {}).get("vendor_importance_is_not_risk") is True,
        "prstk_risk": event.get("prstk_risk"),
    }


__all__ = [
    "MAX_FINANCIALJUICE_CAPTION",
    "deliver_financialjuice_event",
    "financialjuice_caption",
    "financialjuice_notification_key",
]
