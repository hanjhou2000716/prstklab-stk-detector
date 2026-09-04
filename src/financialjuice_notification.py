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
    is_valid_public_summary,
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
    if re.search(r"\bundefined\b", text, flags=re.IGNORECASE) or re.search(r"https?://|www\.", text, flags=re.IGNORECASE):
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
    text = re.sub(
        r"^(?P<entity>[A-Za-z0-9][\w.-]*)\s*將與\s*(?P<partner>[A-Za-z][\w.-]*)\s*"
        r"簽署超過\s*(?P<amount>[\d,]+)\s*億美元合約。?$",
        r"\g<entity>與\g<partner>簽約逾\g<amount>億美元。",
        text,
    )
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
        # A malformed Morning Juice envelope is metadata plus a raw URL/body,
        # not a usable event headline.  Let a richer parsed field win, or
        # suppress the item when no such field exists.
        if re.match(r"^undefined\s*[|｜]", value, flags=re.IGNORECASE):
            continue
        if field in {"brief_title", "title"}:
            value = re.sub(r"^[🟣🟡🟠🔴⚪⚫]\s*FJ\s*\d+(?:\.\d+)?\s*/\s*10\s*[｜|]\s*", "", value, flags=re.IGNORECASE)
        value = _compress_fj_sentence(value)
        if value and value.casefold() not in generic:
            return value
    return ""


def _legacy_financialjuice_notification_key(event: dict[str, Any]) -> str:
    """Return the pre-convergence key so old delivered rows remain idempotent."""
    material = "|".join(
        _text(event.get(name)).casefold()
        for name in ("event_cluster_key", "item_id", "observation_id", "source_url")
    )
    if not material:
        return ""
    return f"financialjuice:{hashlib.sha256(material.encode('utf-8')).hexdigest()[:24]}"


def financialjuice_notification_key(event: dict[str, Any]) -> str:
    """Return a stable key based on normalized facts, not ingress identity."""
    headline = _financialjuice_headline(event)
    impact = _text(event.get("possible_impact") or event.get("possible_linkage"))
    material = "|".join((headline, impact)).casefold().strip("|")
    if not material:
        material = _text(event.get("content_hash")).casefold()
    if not material:
        return ""
    return f"financialjuice:{hashlib.sha256(material.encode('utf-8')).hexdigest()[:24]}"


def financialjuice_notification_aliases(event: dict[str, Any]) -> tuple[str, ...]:
    """Return current and legacy identities for replay-safe migration."""
    current = financialjuice_notification_key(event)
    legacy = _legacy_financialjuice_notification_key(event)
    return tuple(dict.fromkeys(item for item in (current, legacy) if item))


def financialjuice_public_short_message(
    event: dict[str, Any], *, limit: int = MAX_FINANCIALJUICE_CAPTION,
) -> str:
    """Build the one canonical public FJ message used by every consumer."""
    # The priority projection's canonical ``event`` is the parsed rich
    # semantic fact.  Keep title/brief_title only as legacy fallbacks so a
    # high-importance notification does not collapse into a generic label.
    headline = _financialjuice_headline(event)
    if not headline:
        return ""
    importance = event.get("vendor_importance")
    if importance in (None, ""):
        legacy_score = re.search(
            r"FJ[^0-9]{0,40}(\d+(?:\.\d+)?)\s*/\s*10",
            _text(event.get("brief_title")), re.IGNORECASE,
        )
        if legacy_score:
            importance = legacy_score.group(1)
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
    bounded = _bounded(raw, limit)
    return bounded if is_valid_public_summary(bounded, source="financialjuice") else ""


def financialjuice_caption(event: dict[str, Any], *, limit: int = MAX_FINANCIALJUICE_CAPTION) -> str:
    """Backward-compatible alias for the canonical public FJ message."""
    return financialjuice_public_short_message(event, limit=limit)


def _history_delivered(
    history: list[dict[str, Any]], notification_keys: tuple[str, ...], recipient_hash: str,
) -> bool:
    for row in history:
        if not isinstance(row, dict):
            continue
        if _text(row.get("notification_key")) not in set(notification_keys):
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
    ledger: Any | None = None,
    slot_key: str = "",
    run_id: str = "",
) -> dict[str, Any]:
    """Deliver one eligible FJ event with recipient-level idempotency.

    The returned object is safe to persist: recipient identifiers and Telegram
    file IDs are represented only by short hashes.  A partial first attempt
    retries only recipients that did not already succeed.
    """
    notification_key = financialjuice_notification_key(event)
    notification_keys = financialjuice_notification_aliases(event)
    caption = financialjuice_caption(event, limit=MAX_FINANCIALJUICE_CAPTION)
    reasons: list[str] = []
    if _text(event.get("source_key") or event.get("source")).casefold() != "financialjuice":
        reasons.append("source_not_financialjuice")
    if _text(event.get("notification_status")) != "eligible" or event.get("vendor_priority_notification") is not True:
        reasons.append("vendor_priority_not_eligible")
    if not release_ready:
        reasons.append("release_gate_not_ready")
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

    if not is_valid_public_summary(caption, source="financialjuice"):
        return {
            "status": "blocked",
            "notification_key": notification_key,
            "reasons": ["content_incomplete"],
            "receipts": [],
            "release_id": release_id,
            "snapshot_id": snapshot_id,
        }
    if not notification_key:
        return {
            "status": "blocked",
            "notification_key": notification_key,
            "reasons": ["notification_key_missing"],
            "receipts": [],
            "release_id": release_id,
            "snapshot_id": snapshot_id,
        }

    history = delivery_history or []
    pending_ids = tuple(
        chat_id for chat_id in chat_ids
        if not _history_delivered(history, notification_keys, _recipient_hash(chat_id))
    )
    claim: dict[str, Any] | None = None
    if ledger is not None and hasattr(ledger, "claim_notification"):
        claim = ledger.claim_notification(
            notification_key,
            slot_key=slot_key,
            recipient_hashes=tuple(_recipient_hash(chat_id) for chat_id in chat_ids),
            run_id=run_id,
        )
        claim_status = str(claim.get("status") or "")
        if claim_status in {"already_delivered", "in_flight", "uncertain"}:
            return {
                "status": "already_delivered" if claim_status == "already_delivered" else "blocked",
                "notification_key": notification_key,
                "reasons": [claim_status],
                "receipts": [],
                "release_id": release_id,
                "snapshot_id": snapshot_id,
            }
        allowed_hashes = set(str(item) for item in claim.get("pending_recipient_hashes") or [])
        pending_ids = tuple(chat_id for chat_id in pending_ids if _recipient_hash(chat_id) in allowed_hashes)
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
            text=caption,
            dashboard_url=mini_app_url,
            alert_id=alert_id,
            release_id=release_id,
            snapshot_id=snapshot_id,
            observation_id=observation_id,
            target_url=target_url,
            prstk_risk_level=canonical_prstk_risk_level(event),
        )
    except Exception as exc:  # transport adapters must fail closed
        if ledger is not None and hasattr(ledger, "complete_notification_claim"):
            ledger.complete_notification_claim(notification_key, uncertain=True)
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
    failure_classes = sorted({
        _text(row.get("error_class"))
        for row in receipts
        if row.get("delivery_status") != "delivered" and _text(row.get("error_class"))
    })
    status = "delivered" if failed_count == 0 and delivered_count else "partial" if delivered_count else "failed"
    if ledger is not None and hasattr(ledger, "complete_notification_claim"):
        ledger.complete_notification_claim(
            notification_key,
            delivered_recipient_hashes=tuple(
                str(row.get("recipient_hash") or "") for row in receipts
                if row.get("delivery_status") == "delivered"
            ),
            failed_recipient_hashes=tuple(
                str(row.get("recipient_hash") or "") for row in receipts
                if row.get("delivery_status") != "delivered"
            ),
        )
    return {
        "status": status,
        "notification_key": notification_key,
        "reasons": [] if status == "delivered" else ["recipient_delivery_partial" if delivered_count else "recipient_delivery_failed"],
        "failure_classes": failure_classes,
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
    "financialjuice_public_short_message",
    "financialjuice_notification_key",
    "financialjuice_notification_aliases",
]
