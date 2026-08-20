# GENERATED FILE: do not edit manually.
# Run scripts/sync_railway_canonical_parser.py to refresh it.
# Canonical source: src/financialjuice_contract.py
# Canonical source SHA256: 1a69c42d550e28d378aa95cdd49534d4bd9618677eee2bac89b5b5073a706917

"""FinancialJuice observation contract and conservative PRStK risk mapping.

FinancialJuice is a discovery/relay source.  Its vendor importance score and
AI commentary are useful metadata, but neither is official confirmation or a
market-synchronisation proof.  This module keeps those concepts separate so a
10/10 vendor item cannot silently become an R4 alert.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

from src.external_event_risk import score_prstk_risk

VENDOR_IMPORTANCE_MAX = 10
PARSER_VERSION = "financialjuice-contract-v2"
VENDOR_PRIORITY_THRESHOLD = 8


def _text(value: Any) -> str:
    return str(value or "").strip()


def _time(value: Any) -> str | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=parsed.tzinfo or UTC).astimezone(UTC).isoformat()


def _importance(value: Any) -> int | None:
    try:
        parsed = int(str(value).split("/", 1)[0].strip())
    except (TypeError, ValueError):
        return None
    return min(VENDOR_IMPORTANCE_MAX, max(0, parsed))


def _identity(record: dict[str, Any]) -> str:
    material = "|".join(
        _text(record.get(key)).casefold()
        for key in ("original_headline", "headline", "source_url", "published_at")
    )
    return f"fj-{hashlib.sha256(material.encode('utf-8')).hexdigest()[:20]}"


def financialjuice_content_hash(record: dict[str, Any]) -> str:
    """Return a stable hash for one vendor item, excluding transport metadata."""
    material = "|".join(
        _text(record.get(key)).casefold()
        for key in (
            "original_headline", "headline", "chinese_translation", "vendor_translation",
            "ai_commentary", "vendor_analysis", "possible_impact", "vendor_possible_impact",
            "published_at", "source_url",
        )
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def financialjuice_item_id(message_id: str, index: int, content_hash: str) -> str:
    """Identify a compound item without treating the whole email as one event."""
    material = f"{message_id}|{index}|{content_hash}"
    return f"fj-item-{hashlib.sha256(material.encode('utf-8')).hexdigest()[:20]}"


def normalize_financialjuice(record: dict[str, Any]) -> dict[str, Any]:
    """Return public-safe vendor facts and a pending/confirmed risk decision."""
    source_url = _text(record.get("source_url") or record.get("url"))
    headline = _text(record.get("original_headline") or record.get("vendor_original_headline") or record.get("headline"))
    vendor_importance = _importance(record.get("importance", record.get("vendor_importance")))
    official_confirmed = bool(record.get("official_confirmed"))
    market_sync_confirmed = bool(record.get("market_sync_confirmed"))
    category = _text(record.get("event_type") or record.get("category") or "unknown").casefold()
    risk = score_prstk_risk(
        {
            "event_type": category,
            "cross_source_count": int(record.get("cross_source_count") or 0),
            "editorial_sources": [],
        },
        official_confirmed=official_confirmed,
        market_sync_confirmed=market_sync_confirmed,
        vendor_importance=vendor_importance,
    )
    pending: list[str] = []
    if not official_confirmed:
        pending.append("等待官方核對")
    if not market_sync_confirmed:
        pending.append("等待市場同步")
    return {
        "observation_id": _text(record.get("observation_id")) or _identity(record),
        "content_origin": "financialjuice",
        "source_tier": "discovery",
        "source_url": source_url,
        "source_domain": _text(record.get("source_domain")),
        "published_at": _time(record.get("published_at") or record.get("source_published_at")),
        "fetched_at": _time(record.get("fetched_at")) or datetime.now(UTC).isoformat(),
        "vendor_importance": vendor_importance,
        "vendor_importance_is_not_risk": True,
        "original_headline": headline,
        "chinese_translation": _text(record.get("chinese_translation") or record.get("vendor_translation")),
        "ai_commentary": _text(record.get("ai_commentary") or record.get("vendor_analysis")),
        "possible_impact": _text(record.get("possible_impact") or record.get("vendor_possible_impact")),
        "prstk_risk": risk,
        "pending_reasons": pending,
        "parser_version": PARSER_VERSION,
        "public_safe": True,
    }


def normalize_financialjuice_item(
    record: dict[str, Any], *, message_id: str = "", index: int = 0,
) -> dict[str, Any]:
    """Normalize one item from a compound FinancialJuice message."""
    normalized = normalize_financialjuice(record)
    content_hash = financialjuice_content_hash(record)
    normalized.update(
        {
            "item_id": financialjuice_item_id(message_id, index, content_hash),
            "content_hash": content_hash,
            "published_at": normalized["published_at"],
            "source_url": normalized["source_url"],
        }
    )
    return normalized


def financialjuice_notification_state(record: dict[str, Any]) -> dict[str, Any]:
    """Expose why a relay item is or is not eligible for notification."""
    normalized = record if isinstance(record.get("prstk_risk"), dict) else normalize_financialjuice(record)
    risk = normalized["prstk_risk"]
    eligible = bool(risk.get("notification_eligible"))
    vendor_importance = normalized.get("vendor_importance")
    vendor_priority = isinstance(vendor_importance, int) and vendor_importance >= VENDOR_PRIORITY_THRESHOLD
    return {
        "status": "eligible" if eligible else "pending_confirmation",
        "vendor_priority_notification": vendor_priority,
        "vendor_priority_reason": (
            "vendor_importance_at_or_above_8"
            if vendor_priority
            else "vendor_importance_below_8_or_missing"
        ),
        "risk_level": risk["prstk_risk_level"],
        "reasons": list(normalized["pending_reasons"]),
        "official_confirmed": risk["official_confirmed"],
        "market_sync_confirmed": risk["market_sync_confirmed"],
    }


__all__ = [
    "financialjuice_content_hash",
    "financialjuice_item_id",
    "financialjuice_notification_state",
    "normalize_financialjuice",
    "normalize_financialjuice_item",
    "VENDOR_PRIORITY_THRESHOLD",
]
